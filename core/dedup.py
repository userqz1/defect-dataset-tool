"""Perceptual-hash based image deduplication."""
from __future__ import annotations

from collections import defaultdict
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


def find_duplicates(
    images: list[ImageInfo],
    threshold: int = 5,
    progress_cb=None,
) -> list[DuplicateGroup]:
    """Find duplicate images using perceptual hash (pHash).

    `threshold` is the max Hamming distance considered duplicate (0 = identical,
    5 = visually nearly identical).
    """
    hashes: list[tuple[ImageInfo, imagehash.ImageHash]] = []
    total = len(images)
    for i, img in enumerate(images):
        if progress_cb:
            progress_cb(i, total, img.path.name)
        try:
            with Image.open(img.path) as im:
                h = imagehash.phash(im)
            hashes.append((img, h))
        except Exception:
            continue
    if progress_cb:
        progress_cb(total, total, "")

    # 简单 O(n²) 分组；对中等数据集足够；超大集需要 BK-tree
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
