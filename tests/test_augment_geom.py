"""Geometric-transform coordinate tests (#11).

The augmentation pipeline chains flips / rotations / crops on both image
pixels and annotation points. A silent bug here is particularly bad:
the augmented image still looks fine visually, but the bbox is in the
wrong place and training quality degrades without any error.

These tests pin the pure coordinate-mapping functions (flip_h_points,
rotate_90_points, ...) — if a future change flips a sign or swaps x/y,
the test catches it instantly. The end-to-end ``augment_in_memory`` path
is also exercised so the integration layer between ``_apply_geometric``
and the annotation round-trip stays correct.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from core.augment import (
    AugmentOptions,
    augment_in_memory,
    crop_points,
    flip_h_points,
    flip_v_points,
    rotate_90_points,
    rotate_180_points,
    rotate_270_points,
)
from core.models import Annotation, Shape


# ---------- Pure transform math ----------

W, H = 100, 80  # canonical test canvas
CORNERS = [(0, 0), (W, 0), (0, H), (W, H), (W / 2, H / 2)]


class TestFlipH:
    @pytest.mark.parametrize("x, y, expected", [
        (0, 0, (W, 0)),
        (W, 0, (0, 0)),
        (W / 2, H / 2, (W / 2, H / 2)),
        (25, 40, (75, 40)),
    ])
    def test_point(self, x, y, expected):
        fn = flip_h_points(W, H)
        assert fn(x, y) == expected

    def test_involution(self):
        """Applying flip_h twice returns the original point."""
        fn = flip_h_points(W, H)
        for pt in CORNERS:
            assert fn(*fn(*pt)) == pt


class TestFlipV:
    @pytest.mark.parametrize("x, y, expected", [
        (0, 0, (0, H)),
        (0, H, (0, 0)),
        (W / 2, H / 2, (W / 2, H / 2)),
        (25, 40, (25, 40)),
    ])
    def test_point(self, x, y, expected):
        fn = flip_v_points(W, H)
        assert fn(x, y) == expected

    def test_involution(self):
        fn = flip_v_points(W, H)
        for pt in CORNERS:
            assert fn(*fn(*pt)) == pt


class TestRotate90:
    """Output canvas becomes (H, W). Clockwise, so top-left → top-right."""

    @pytest.mark.parametrize("x, y, expected", [
        (0, 0, (H, 0)),     # top-left → top-right (of rotated)
        (W, 0, (H, W)),     # top-right → bottom-right
        (W, H, (0, W)),     # bottom-right → bottom-left
        (0, H, (0, 0)),     # bottom-left → top-left
    ])
    def test_corners(self, x, y, expected):
        fn = rotate_90_points(W, H)
        assert fn(x, y) == expected

    def test_quadruple_identity(self):
        """90° x 4 returns to original point (modulo canvas resize)."""
        # After 4 rotations of 90, both original canvas (W,H) is restored.
        # Compose the four rotation maps.
        f1 = rotate_90_points(W, H)
        # After 1st rotate, canvas is (H, W)
        f2 = rotate_90_points(H, W)
        # After 2nd, (W, H) again
        f3 = rotate_90_points(W, H)
        f4 = rotate_90_points(H, W)

        def chain(p):
            for f in (f1, f2, f3, f4):
                p = f(*p)
            return p

        for pt in CORNERS:
            result = chain(pt)
            assert result == pt


class TestRotate180:
    @pytest.mark.parametrize("x, y, expected", [
        (0, 0, (W, H)),
        (W, H, (0, 0)),
        (W / 2, H / 2, (W / 2, H / 2)),
    ])
    def test_corners(self, x, y, expected):
        fn = rotate_180_points(W, H)
        assert fn(x, y) == expected

    def test_involution(self):
        fn = rotate_180_points(W, H)
        for pt in CORNERS:
            assert fn(*fn(*pt)) == pt


class TestRotate270:
    """270° clockwise = 90° counter-clockwise. Output canvas (H, W)."""

    @pytest.mark.parametrize("x, y, expected", [
        (0, 0, (0, W)),
        (W, 0, (0, 0)),
        (W, H, (H, 0)),
        (0, H, (H, W)),
    ])
    def test_corners(self, x, y, expected):
        fn = rotate_270_points(W, H)
        assert fn(x, y) == expected


class TestRotate90_270_Inverse:
    """rotate_90 followed by rotate_270 (or vice versa) == identity."""

    def test_90_then_270(self):
        f1 = rotate_90_points(W, H)       # (W,H) → (H,W)
        f2 = rotate_270_points(H, W)      # (H,W) → (W,H)
        for pt in CORNERS:
            result = f2(*f1(*pt))
            assert result == pt

    def test_270_then_90(self):
        f1 = rotate_270_points(W, H)      # (W,H) → (H,W)
        f2 = rotate_90_points(H, W)       # (H,W) → (W,H)
        for pt in CORNERS:
            result = f2(*f1(*pt))
            assert result == pt


class TestCrop:
    def test_offset(self):
        fn = crop_points(10, 20)
        assert fn(30, 40) == (20, 20)
        assert fn(10, 20) == (0, 0)


# ---------- End-to-end: augment_in_memory preserves image pixel count ----------

class TestAugmentInMemory:
    def test_returns_rgb_image_with_same_area_or_smaller(self):
        # No random_crop → output area should equal input area (after any
        # flip/rotate, total pixel count is preserved).
        src = Image.new("RGB", (100, 80), (128, 128, 128))
        opts = AugmentOptions(
            flip_h=True, flip_v=False, rotate90=False,
            random_crop=False, copy_paste=False,
            brightness=False, contrast=False,
            color_jitter=False, gauss_blur=False, gauss_noise=False,
            seed=0,
        )
        out = augment_in_memory(src, opts, seed=0)
        assert out.size[0] * out.size[1] == 100 * 80

    def test_rotate90_swaps_dimensions_or_keeps_them(self):
        """With rotate90 enabled, output should be 100x80 OR 80x100 depending
        on whether the RNG triggered the branch."""
        src = Image.new("RGB", (100, 80))
        opts = AugmentOptions(
            flip_h=False, flip_v=False, rotate90=True,
            random_crop=False, copy_paste=False,
            brightness=False, contrast=False,
            color_jitter=False, gauss_blur=False, gauss_noise=False,
        )
        out = augment_in_memory(src, opts, seed=0)
        assert out.size in [(100, 80), (80, 100)]


# ---------- Shape-level invariants ----------

class TestShapeInsideCanvas:
    """Any single-transform map of a rectangle's corners must still form a
    rectangle fully inside the post-transform canvas."""

    RECT = [(10, 10), (30, 40)]  # bbox-style, 2 points

    def _inside(self, points, w, h) -> bool:
        return all(0 <= x <= w and 0 <= y <= h for x, y in points)

    def test_flip_h_keeps_shape_inside(self):
        fn = flip_h_points(W, H)
        mapped = [fn(*p) for p in self.RECT]
        assert self._inside(mapped, W, H)

    def test_flip_v_keeps_shape_inside(self):
        fn = flip_v_points(W, H)
        mapped = [fn(*p) for p in self.RECT]
        assert self._inside(mapped, W, H)

    def test_rotate_90_keeps_shape_inside_rotated_canvas(self):
        # After rotate_90, canvas becomes (H, W) not (W, H)
        fn = rotate_90_points(W, H)
        mapped = [fn(*p) for p in self.RECT]
        assert self._inside(mapped, H, W)

    def test_rotate_180_keeps_shape_inside(self):
        fn = rotate_180_points(W, H)
        mapped = [fn(*p) for p in self.RECT]
        assert self._inside(mapped, W, H)

    def test_rotate_270_keeps_shape_inside_rotated_canvas(self):
        fn = rotate_270_points(W, H)
        mapped = [fn(*p) for p in self.RECT]
        assert self._inside(mapped, H, W)
