"""Dedup tests — perceptual hash threshold boundaries.

The pHash-based dedup in core.dedup groups images by Hamming distance
on their 64-bit hashes. These tests verify:
  - Identical images are always grouped (distance == 0).
  - Threshold 0 only groups exact pHash matches.
  - Threshold 20 (max sane bound) groups aggressively.
  - Distinct images (random noise) are not grouped at moderate thresholds.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from core.api import DuplicateGroup, ImageInfo, find_duplicates


def _make_image(path: Path, color: tuple[int, int, int] = (100, 150, 200)) -> None:
    Image.new("RGB", (64, 64), color).save(path)


def _make_patterned_image(path: Path, color: tuple[int, int, int]) -> None:
    """Image with a color + gradient so pHash is distinct from solid colors.

    pHash operates on the DCT of a grayscale image; pure solid colors all
    share the same pHash regardless of color, so tests that want distinct
    hashes must add spatial variation.
    """
    from PIL import ImageDraw
    im = Image.new("RGB", (64, 64), (255, 255, 255))
    draw = ImageDraw.Draw(im)
    # Draw 4 concentric rectangles of the target color shade
    for i in range(4):
        pad = i * 8
        draw.rectangle([pad, pad, 63 - pad, 63 - pad], outline=color, width=2)
    im.save(path)


def _make_random_image(path: Path, seed: int) -> None:
    """Noisy image — pHash should be distinct from solid colors."""
    import random as _random
    rng = _random.Random(seed)
    im = Image.new("RGB", (64, 64))
    px = im.load()
    for y in range(64):
        for x in range(64):
            px[x, y] = (rng.randint(0, 255),
                         rng.randint(0, 255),
                         rng.randint(0, 255))
    im.save(path)


def _copy_file(src: Path, dst: Path) -> None:
    import shutil
    shutil.copyfile(src, dst)


@pytest.fixture
def three_copies(tmp_path):
    """3 byte-identical images (true duplicates) + 1 distinct random-noise image."""
    # A random-noise image produces a high-entropy pHash. Binary-copying it
    # to two more files guarantees identical pHash; the 4th (distinct seed)
    # has a clearly different pHash no matter how DCT hashes collapse.
    _make_random_image(tmp_path / "green_0.png", seed=11)
    _copy_file(tmp_path / "green_0.png", tmp_path / "green_1.png")
    _copy_file(tmp_path / "green_0.png", tmp_path / "green_2.png")
    _make_random_image(tmp_path / "distinct.png", seed=9999)
    return [
        ImageInfo(path=tmp_path / f"green_{i}.png", category="green")
        for i in range(3)
    ] + [ImageInfo(path=tmp_path / "distinct.png", category="red")]


class TestExactDuplicates:
    def test_three_identical_grouped(self, three_copies):
        groups = find_duplicates(three_copies, threshold=0)
        # find_duplicates only returns groups with size >= 2, so we expect
        # exactly one group (the 3 identical greens).
        assert len(groups) == 1
        assert groups[0].size == 3

    def test_returns_duplicate_group_objects(self, three_copies):
        groups = find_duplicates(three_copies, threshold=0)
        assert all(isinstance(g, DuplicateGroup) for g in groups)
        for g in groups:
            assert g.hash_value  # hex string
            assert all(isinstance(img, ImageInfo) for img in g.images)


class TestThresholdEffect:
    def test_stricter_threshold_fewer_dupes(self, tmp_path):
        # Slightly varied images at the pixel level
        imgs = []
        for i in range(3):
            p = tmp_path / f"gr_{i}.png"
            _make_image(p, (50, 200 + i, 50))  # each 1 unit brighter
            imgs.append(ImageInfo(path=p, category="x"))
        strict = find_duplicates(imgs, threshold=0)
        loose = find_duplicates(imgs, threshold=20)
        # Loose should group >= as many as strict
        strict_groups = sum(1 for g in strict if g.size >= 2)
        loose_groups = sum(1 for g in loose if g.size >= 2)
        assert loose_groups >= strict_groups


class TestDistinctImages:
    def test_random_noise_not_grouped_moderate_threshold(self, tmp_path):
        imgs = []
        for i in range(3):
            p = tmp_path / f"rand_{i}.png"
            _make_random_image(p, seed=i * 97 + 13)
            imgs.append(ImageInfo(path=p, category="x"))
        groups = find_duplicates(imgs, threshold=5)
        # At threshold 5 and truly random content, distinct images should
        # not be in a 2+ group. (Singleton groups of size 1 are allowed —
        # find_duplicates returns them too, just not as "duplicates".)
        paired = [g for g in groups if g.size >= 2]
        assert paired == [], f"unexpected pairing: {[g.hash_value for g in paired]}"


class TestErrorResilience:
    def test_unreadable_image_skipped(self, tmp_path):
        # Two identical + one corrupt — dedup should survive the corrupt one
        # and still group the identical pair.
        p1 = tmp_path / "good_1.png"
        p2 = tmp_path / "good_2.png"
        _make_patterned_image(p1, (80, 80, 200))
        _make_patterned_image(p2, (80, 80, 200))
        bad = tmp_path / "bad.png"
        bad.write_bytes(b"not an image")
        imgs = [ImageInfo(path=p1, category="x"),
                ImageInfo(path=bad, category="x"),
                ImageInfo(path=p2, category="x")]
        groups = find_duplicates(imgs, threshold=0)
        all_paths = [img.path for g in groups for img in g.images]
        # Corrupt one never appears
        assert bad not in all_paths
        # The two good ones ended up grouped
        assert p1 in all_paths and p2 in all_paths


class TestEmptyInput:
    def test_empty_returns_empty_groups(self):
        groups = find_duplicates([], threshold=5)
        assert groups == []
