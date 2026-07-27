"""Regression tests for per-shape-type geometry conventions.

Two models describe the same shape differently and MUST be translated per
type, never guessed from whichever geometry field happens to be set:

    core (``Region``)          viewer / LabelMe (``Shape``)
    ----------------------     ----------------------------
    circle    -> bbox          circle    -> [centre, edge]
    point     -> keypoints     point     -> [(x, y)]           (exactly 1 pt)
    ellipse   -> bbox          ellipse   -> [tl, br]           (its bbox)
    rectangle -> bbox          rectangle -> [tl, br]

Shipped bugs these lock down:
  * The GUI bridge had no ``circle`` branch, so a circle loaded from disk was
    rendered at its bbox top-left with radius = half-diagonal (≈2.8× too big).
    Touching it then saved that wrong geometry back.
  * ``point`` matched the bbox branch before the keypoint branch and came
    back as two duplicated points.
  * The directory category (incl. the synthetic "(未分类)") was injected as an
    image label on region-bearing samples, adding a phantom class to the
    export class registry and shifting every real class id.

The bridge functions are pure (dataclasses in, dataclasses out) — they need
no display, so they are unit-testable despite living under ``gui/``.
"""
from __future__ import annotations

import json
import math
import os

import pytest

from core.unified import BBox, Region

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6", reason="bridge lives in a PyQt module")

from gui.views.detail_view import (  # noqa: E402
    _region_to_shape,
    _shape_to_region,
)


def _circle_of(shape):
    """Read (centre, radius) back out of a viewer Shape's [centre, edge]."""
    (cx, cy), (ex, ey) = shape.points[0], shape.points[1]
    return (cx, cy), math.hypot(ex - cx, ey - cy)


class TestCircleConvention:
    def test_region_to_shape_preserves_centre_and_radius(self):
        # core stores a circle as its bounding box
        r = Region(label="hole", shape_type="circle", bbox=BBox(350, 250, 450, 350))
        (cx, cy), rad = _circle_of(_region_to_shape(r))
        assert (cx, cy) == (400.0, 300.0)
        assert rad == pytest.approx(50.0)

    def test_shape_to_region_rebuilds_the_circle_bbox(self):
        from core.models import Shape
        s = Shape(label="hole", shape_type="circle", points=[(400, 300), (450, 300)])
        bb = _shape_to_region(s).bbox
        assert (bb.x1, bb.y1, bb.x2, bb.y2) == (350.0, 250.0, 450.0, 350.0)

    def test_round_trip_is_stable_over_repeated_open_save(self):
        """Open→save→open… must not drift: the old bridge moved the centre
        and grew the radius on the very first load."""
        r = Region(label="hole", shape_type="circle", bbox=BBox(350, 250, 450, 350))
        for _ in range(5):
            shape = _region_to_shape(r)
            (cx, cy), rad = _circle_of(shape)
            assert (cx, cy) == (400.0, 300.0)
            assert rad == pytest.approx(50.0)
            r = _shape_to_region(shape)
            assert (r.bbox.x1, r.bbox.y1, r.bbox.x2, r.bbox.y2) == \
                (350.0, 250.0, 450.0, 350.0)


class TestPointConvention:
    def test_point_stays_a_single_coordinate(self):
        r = Region(label="tip", shape_type="point",
                   keypoints=[(30.0, 40.0, 2)], bbox=BBox(30, 40, 30, 40))
        s = _region_to_shape(r)
        assert s.points == [(30.0, 40.0)], "a point must not become 2 points"

    def test_point_round_trip(self):
        r = Region(label="tip", shape_type="point",
                   keypoints=[(30.0, 40.0, 2)], bbox=BBox(30, 40, 30, 40))
        back = _shape_to_region(_region_to_shape(r))
        assert back.keypoints == [(30.0, 40.0, 2)]


class TestEllipseAndRectConvention:
    @pytest.mark.parametrize("st", ["rectangle", "ellipse"])
    def test_bbox_shapes_round_trip_exactly(self, st):
        r = Region(label="x", shape_type=st, bbox=BBox(20, 150, 90, 190))
        s = _region_to_shape(r)
        assert s.points == [(20.0, 150.0), (90.0, 190.0)]
        bb = _shape_to_region(s).bbox
        assert (bb.x1, bb.y1, bb.x2, bb.y2) == (20.0, 150.0, 90.0, 190.0)


class TestNoPhantomClassFromDirectory:
    """The folder name must never enter the export class registry for
    region-bearing (detection/segmentation) samples."""

    def _dataset_with_regions(self, tmp_path, category_dirname):
        from PIL import Image
        from core.dataset import scan_dataset

        root = tmp_path / "ds"
        if category_dirname is None:          # root_pair -> "(未分类)"
            img_dir, lbl_dir = root / "images", root / "labels"
        else:                                  # standard -> real category
            img_dir = root / category_dirname / "images"
            lbl_dir = root / category_dirname / "labels"
        img_dir.mkdir(parents=True)
        lbl_dir.mkdir(parents=True)
        Image.new("RGB", (100, 100), (5, 5, 5)).save(img_dir / "a.png")
        (lbl_dir / "a.json").write_text(json.dumps({
            "shapes": [{"label": "defect", "points": [[10, 10], [50, 50]],
                        "shape_type": "rectangle", "flags": {}}],
            "imagePath": "a.png", "imageWidth": 100, "imageHeight": 100,
        }), encoding="utf-8")
        return scan_dataset(root)

    def test_uncategorized_placeholder_is_not_a_class(self, tmp_path):
        from core.format_in import load_samples
        ss = load_samples(self._dataset_with_regions(tmp_path, None))
        assert ss.class_names == ["defect"], ss.class_names
        assert ss.class_to_index["defect"] == 0, "real class must own id 0"

    def test_real_category_dir_is_not_a_class_for_detection(self, tmp_path):
        from core.format_in import load_samples
        ss = load_samples(self._dataset_with_regions(tmp_path, "cracks"))
        assert "cracks" not in ss.class_names, (
            "a detection sample's folder name must not become a class")
        assert ss.class_names == ["defect"]

    def test_classification_sample_still_gets_its_category(self, tmp_path):
        """The category→image_label derivation must survive for genuinely
        image-level (no-region) samples — that's what it exists for."""
        from PIL import Image
        from core.dataset import scan_dataset
        from core.format_in import load_samples

        root = tmp_path / "cls"
        for cat in ("cat", "dog"):
            d = root / cat
            d.mkdir(parents=True)
            Image.new("RGB", (40, 40), (7, 7, 7)).save(d / f"{cat}.png")
        ss = load_samples(scan_dataset(root))
        assert sorted(ss.class_names) == ["cat", "dog"]
