"""Perceptual-hash based image deduplication.

Two entry points:
  - ``find_duplicates(images)`` — legacy, iterates ``ImageInfo`` objects.
  - ``find_duplicates_from_samples(sample_set)`` — preferred when a
    SampleSet is available. Builds the ``ImageInfo`` list from Samples
    so all analysis reads from the same unified source.

Optimized: parallel hash computation via ThreadPoolExecutor,
images resized to 128x128 before hashing to reduce I/O.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import imagehash
from PIL import Image

from .models import ImageInfo

if TYPE_CHECKING:
    from .unified import SampleSet


@dataclass
class DuplicateGroup:
    hash_value: str
    images: list[ImageInfo] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.images)


def _hash_one(img: ImageInfo) -> tuple[ImageInfo, imagehash.ImageHash | None]:
    """Compute pHash for a single image (resize first for speed)."""
    try:
        with Image.open(img.path) as im:
            im = im.convert("RGB").resize((128, 128), Image.Resampling.LANCZOS)
            return img, imagehash.phash(im)
    except Exception:
        return img, None


def find_duplicates(
    images,
    threshold: int = 5,
    progress_cb=None,
    total: int | None = None,
) -> list[DuplicateGroup]:
    """Find duplicate images using perceptual hash (pHash).

    Uses ThreadPoolExecutor for parallel I/O. Images resized to 128x128
    before hashing (pHash only needs ~32x32, so this is plenty).

    Accepts any ``Iterable[ImageInfo]``. If ``total`` is omitted, falls
    back to ``len(images)``; for generators pass ``total`` explicitly or
    the function materializes the iterable.
    """
    if total is None:
        try:
            total = len(images)  # type: ignore[arg-type]
        except TypeError:
            images = list(images)
            total = len(images)
    hashes: list[tuple[ImageInfo, imagehash.ImageHash]] = []

    # Parallel hash computation (I/O bound → threads)
    workers = min(8, max(1, total // 10))
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_hash_one, img): img for img in images}
        for fut in as_completed(futures):
            done += 1
            img, h = fut.result()
            if h is not None:
                hashes.append((img, h))
            if progress_cb and done % 20 == 0:
                progress_cb(done, total, img.path.name)

    if progress_cb:
        progress_cb(total, total, "")

    # Stable sort so "representative image" (group[0]) is deterministic
    hashes.sort(key=lambda x: str(x[0].path))

    return _group_by_hamming(hashes, threshold)


def _as_int(h: imagehash.ImageHash) -> int:
    """Pack an ImageHash's 8×8 bool grid into a 64-bit int (MSB first)."""
    n = 0
    for b in h.hash.flatten():
        n = (n << 1) | int(bool(b))
    return n


def _group_by_hamming(
    hashes: list[tuple[ImageInfo, imagehash.ImageHash]],
    threshold: int,
) -> list[DuplicateGroup]:
    """Group hashes within ``threshold`` Hamming distance.

    Uses multi-index hashing (review #7) — split each 64-bit hash into
    ``threshold + 1`` segments; by the pigeonhole principle, any two
    hashes within ``threshold`` bits of each other must share at least
    one exact-match segment, so we only do precise Hamming checks
    inside shared-segment buckets. Drops the old O(n²) scan to ~O(n)
    on well-distributed pHashes, ~O(n·k) in the worst case where k is
    the largest bucket size.
    """
    if not hashes:
        return []

    n_seg = max(1, threshold + 1)
    seg_bits = 64 // n_seg  # 64 bits / 6 segments = 10-11 bits each
    mask = (1 << seg_bits) - 1

    # Precompute each hash's 64-bit int + per-segment keys
    packed: list[int] = []
    keys_per_hash: list[list[tuple[int, int]]] = []  # [(seg_idx, seg_val)]
    for _, h in hashes:
        v = _as_int(h)
        packed.append(v)
        keys = [
            (i, (v >> (64 - seg_bits * (i + 1))) & mask)
            for i in range(n_seg)
        ]
        keys_per_hash.append(keys)

    # Inverted index: (seg_idx, seg_val) → list of hash indices
    from collections import defaultdict
    buckets: dict[tuple[int, int], list[int]] = defaultdict(list)
    for idx, keys in enumerate(keys_per_hash):
        for k in keys:
            buckets[k].append(idx)

    # Union-find over near-duplicate edges
    parent = list(range(len(hashes)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]  # path compression
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    # For each bucket, verify candidate pairs via popcount; small buckets
    # stay linear, large buckets still do k² but on a much smaller k.
    for members in buckets.values():
        if len(members) < 2:
            continue
        for i in range(len(members)):
            a = members[i]
            for j in range(i + 1, len(members)):
                b = members[j]
                if find(a) == find(b):
                    continue  # already grouped via another segment
                if bin(packed[a] ^ packed[b]).count("1") <= threshold:
                    union(a, b)

    # Materialize groups from union-find
    root_to_members: dict[int, list[int]] = defaultdict(list)
    for idx in range(len(hashes)):
        root_to_members[find(idx)].append(idx)

    groups: list[DuplicateGroup] = []
    for root, members in root_to_members.items():
        if len(members) < 2:
            continue
        members.sort()  # deterministic order within group
        groups.append(DuplicateGroup(
            hash_value=str(hashes[root][1]),
            images=[hashes[m][0] for m in members],
        ))
    return groups


# ---------- SampleSet entry point ----------

def find_duplicates_from_samples(
    sample_set: SampleSet,
    threshold: int = 5,
    progress_cb=None,
) -> list[DuplicateGroup]:
    """Preferred dedup entry when SampleSet is available.

    Builds ``ImageInfo`` objects from the unified model so the entire
    analysis chain reads from one source. The returned ``DuplicateGroup``
    items contain the same ``ImageInfo`` objects as the legacy path.
    """
    from .unified import SampleSet as _SS  # noqa: F811

    images = [
        ImageInfo(
            path=Path(s.image_path),
            category=s.category,
            has_label=s.has_label,
            label_path=s.label_path,
        )
        for s in sample_set.samples
    ]
    return find_duplicates(
        images, threshold=threshold,
        progress_cb=progress_cb, total=len(images),
    )
