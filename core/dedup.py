"""Perceptual-hash based image deduplication.

Optimized: parallel hash computation via ThreadPoolExecutor,
images resized to 128x128 before hashing to reduce I/O.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

import imagehash
from PIL import Image

from .models import ImageInfo


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
    images: list[ImageInfo],
    threshold: int = 5,
    progress_cb=None,
) -> list[DuplicateGroup]:
    """Find duplicate images using perceptual hash (pHash).

    Uses ThreadPoolExecutor for parallel I/O. Images resized to 128x128
    before hashing (pHash only needs ~32x32, so this is plenty).
    """
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

    # Group by hamming distance (O(n²) but fast for <10k hashed images)
    groups: list[DuplicateGroup] = []
    visited = [False] * len(hashes)
    for i in range(len(hashes)):
        if visited[i]:
            continue
        visited[i] = True
        group = DuplicateGroup(hash_value=str(hashes[i][1]), images=[hashes[i][0]])
        for j in range(i + 1, len(hashes)):
            if visited[j]:
                continue
            if hashes[i][1] - hashes[j][1] <= threshold:
                visited[j] = True
                group.images.append(hashes[j][0])
        if group.size > 1:
            groups.append(group)
    return groups
