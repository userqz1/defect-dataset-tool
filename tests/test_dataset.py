"""Tests for core/dataset.py — layout detection and scan phases.

Each of the 5 layouts (standard, flat, single, recursive, empty)
gets at least 2 fixture directories.
"""
from __future__ import annotations

import pytest
from pathlib import Path

from core.dataset import _detect_layout, scan_dataset, count_annotations


# ---- helpers ----

IMG_EXTS = {".jpg", ".png"}


def _touch(p: Path, content: bytes = b"\x00") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    return p


# ---- _detect_layout ----

class TestDetectLayout:
    """5 layouts × 2 fixtures each."""

    # -- standard --

    def test_standard_basic(self, tmp_path):
        _touch(tmp_path / "cats" / "images" / "a.jpg")
        assert _detect_layout(tmp_path, IMG_EXTS) == "standard"

    def test_standard_with_labels(self, tmp_path):
        _touch(tmp_path / "dogs" / "images" / "d.jpg")
        _touch(tmp_path / "dogs" / "labels" / "d.json")
        assert _detect_layout(tmp_path, IMG_EXTS) == "standard"

    # -- flat --

    def test_flat_basic(self, tmp_path):
        _touch(tmp_path / "cats" / "a.jpg")
        assert _detect_layout(tmp_path, IMG_EXTS) == "flat"

    def test_flat_multiple_categories(self, tmp_path):
        _touch(tmp_path / "cats" / "a.jpg")
        _touch(tmp_path / "dogs" / "b.png")
        assert _detect_layout(tmp_path, IMG_EXTS) == "flat"

    # -- single --

    def test_single_basic(self, tmp_path):
        _touch(tmp_path / "a.jpg")
        assert _detect_layout(tmp_path, IMG_EXTS) == "single"

    def test_single_multiple_images(self, tmp_path):
        _touch(tmp_path / "a.jpg")
        _touch(tmp_path / "b.png")
        _touch(tmp_path / "a.json")
        assert _detect_layout(tmp_path, IMG_EXTS) == "single"

    # -- recursive --

    def test_recursive_nested(self, tmp_path):
        _touch(tmp_path / "level1" / "level2" / "a.jpg")
        assert _detect_layout(tmp_path, IMG_EXTS) == "recursive"

    def test_recursive_mixed_depths(self, tmp_path):
        _touch(tmp_path / "a" / "b" / "c.jpg")
        _touch(tmp_path / "x" / "y" / "z" / "d.png")
        assert _detect_layout(tmp_path, IMG_EXTS) == "recursive"

    # -- empty --

    def test_empty_no_files(self, tmp_path):
        assert _detect_layout(tmp_path, IMG_EXTS) == "empty"

    def test_empty_only_non_image_files(self, tmp_path):
        _touch(tmp_path / "readme.txt")
        _touch(tmp_path / "data.csv")
        assert _detect_layout(tmp_path, IMG_EXTS) == "empty"

    # -- priority: standard > single (review #8) --

    def test_standard_beats_single(self, tmp_path):
        """A stray cover.jpg / README.png in the root must not demote the
        whole tree to "single" when there's a real <cat>/images/ structure."""
        _touch(tmp_path / "root.jpg")
        _touch(tmp_path / "cat" / "images" / "a.jpg")
        assert _detect_layout(tmp_path, IMG_EXTS) == "standard"

    def test_single_when_no_categorized_subdir(self, tmp_path):
        """No <cat>/images/ → root images do drive a "single" layout."""
        _touch(tmp_path / "a.jpg")
        _touch(tmp_path / "subdir" / "readme.txt")
        assert _detect_layout(tmp_path, IMG_EXTS) == "single"


# ---- scan_dataset ----

class TestScanDataset:
    def test_scan_standard(self, tmp_path):
        # minimal 1×1 white PNG
        import struct, zlib
        png = _make_png()
        _touch(tmp_path / "cat" / "images" / "a.jpg", png)
        ds = scan_dataset(tmp_path)
        assert ds.layout == "standard"
        assert ds.total_images == 1
        assert len(ds.categories) == 1
        assert ds.categories[0].name == "cat"

    def test_scan_flat(self, tmp_path):
        png = _make_png()
        _touch(tmp_path / "cat" / "a.jpg", png)
        _touch(tmp_path / "cat" / "b.jpg", png)
        ds = scan_dataset(tmp_path)
        assert ds.layout == "flat"
        assert ds.total_images == 2

    def test_scan_single(self, tmp_path):
        png = _make_png()
        _touch(tmp_path / "img1.jpg", png)
        _touch(tmp_path / "img2.jpg", png)
        ds = scan_dataset(tmp_path)
        assert ds.layout == "single"
        assert ds.total_images == 2
        assert ds.categories[0].name == "(未分类)"

    def test_scan_empty(self, tmp_path):
        ds = scan_dataset(tmp_path)
        assert ds.layout == "empty"
        assert ds.total_images == 0

    def test_scan_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            scan_dataset(tmp_path / "nonexistent")

    def test_scan_with_labels(self, tmp_path):
        import json
        png = _make_png()
        _touch(tmp_path / "cat" / "images" / "a.jpg", png)
        label = {"imagePath": "a.jpg", "shapes": [
            {"label": "defect", "shape_type": "rectangle",
             "points": [[0, 0], [10, 10]]}
        ]}
        _touch(tmp_path / "cat" / "labels" / "a.json",
               json.dumps(label).encode())
        ds = scan_dataset(tmp_path)
        assert ds.categories[0].label_count == 1

    def test_scan_recursive_finds_sibling_labels(self, tmp_path):
        """Review #1: when recursive walk hits ``<cat>/images/``, labels
        should come from the sibling ``<cat>/labels/`` dir — the old
        behavior used the image dir as its own label root and dropped
        every .json."""
        import json
        png = _make_png()
        # Put a non-image file at root so _detect_layout falls through
        # to "recursive" (otherwise this would be a plain standard scan).
        _touch(tmp_path / "README.md", b"")
        _touch(tmp_path / "nested" / "cat" / "images" / "a.jpg", png)
        _touch(tmp_path / "nested" / "cat" / "labels" / "a.json",
               json.dumps({"imagePath": "a.jpg", "shapes": []}).encode())
        ds = scan_dataset(tmp_path)
        # Bucket is named after the category parent, not "images"
        assert any(c.name == "cat" for c in ds.categories), \
            [c.name for c in ds.categories]
        cat = next(c for c in ds.categories if c.name == "cat")
        assert cat.label_count == 1, f"expected 1 label, got {cat.label_count}"
        assert ds.categories[0].images[0].has_label


# ---- count_annotations ----

class TestCountAnnotations:
    def test_count_basic(self, tmp_path):
        import json
        png = _make_png()
        _touch(tmp_path / "c" / "images" / "a.jpg", png)
        label = {"imagePath": "a.jpg", "shapes": [
            {"label": "x", "shape_type": "rectangle",
             "points": [[0, 0], [10, 10]]},
            {"label": "y", "shape_type": "rectangle",
             "points": [[5, 5], [15, 15]]},
        ]}
        _touch(tmp_path / "c" / "labels" / "a.json",
               json.dumps(label).encode())
        ds = scan_dataset(tmp_path)
        total = count_annotations(ds)
        assert total == 2
        assert ds.total_annotations == 2

    def test_count_no_labels(self, tmp_path):
        png = _make_png()
        _touch(tmp_path / "c" / "images" / "a.jpg", png)
        ds = scan_dataset(tmp_path)
        total = count_annotations(ds)
        assert total == 0


class TestCocoLayout:
    """COCO: single dataset-level JSON referencing images in the same root
    or in ``images/``. Reviewer's bug: scanner treated .json per-image and
    reported 0 annotations for valid COCO datasets."""

    def _coco_payload(self) -> bytes:
        import json as _json
        payload = {
            "images": [
                {"id": 1, "file_name": "a.jpg", "width": 64, "height": 64},
                {"id": 2, "file_name": "b.jpg", "width": 64, "height": 64},
            ],
            "annotations": [
                {"id": 1, "image_id": 1, "category_id": 1, "bbox": [0, 0, 20, 20]},
                {"id": 2, "image_id": 1, "category_id": 2, "bbox": [20, 20, 10, 10]},
                {"id": 3, "image_id": 2, "category_id": 1, "bbox": [5, 5, 30, 30]},
            ],
            "categories": [
                {"id": 1, "name": "cat"},
                {"id": 2, "name": "dog"},
            ],
        }
        return _json.dumps(payload).encode()

    def test_detect_coco_root_level(self, tmp_path):
        _touch(tmp_path / "annotations.json", self._coco_payload())
        _touch(tmp_path / "a.jpg", _make_png())
        _touch(tmp_path / "b.jpg", _make_png())
        assert _detect_layout(tmp_path, IMG_EXTS) == "coco"

    def test_detect_coco_annotations_subdir(self, tmp_path):
        _touch(tmp_path / "annotations" / "instances_train.json",
               self._coco_payload())
        _touch(tmp_path / "images" / "a.jpg", _make_png())
        _touch(tmp_path / "images" / "b.jpg", _make_png())
        assert _detect_layout(tmp_path, IMG_EXTS) == "coco"

    def test_scan_counts_annotations(self, tmp_path):
        """Reviewer's exact scenario: open a COCO dataset → get actual counts,
        not 0."""
        _touch(tmp_path / "annotations.json", self._coco_payload())
        _touch(tmp_path / "a.jpg", _make_png())
        _touch(tmp_path / "b.jpg", _make_png())
        ds = scan_dataset(tmp_path)
        assert ds.layout == "coco"
        assert ds.total_images == 2
        # cat/dog categories should show up (not the filesystem-named "(未分类)")
        cat_names = {c.name for c in ds.categories}
        assert "cat" in cat_names
        # count_annotations must see all 3 shapes
        total = count_annotations(ds)
        assert total == 3
        assert ds.total_annotations == 3

    def test_labelme_json_not_misdetected_as_coco(self, tmp_path):
        """Per-image LabelMe JSONs (no images/annotations/categories keys)
        must still go down the per-image LabelMe path, not COCO."""
        import json as _json
        _touch(tmp_path / "c" / "images" / "a.jpg", _make_png())
        labelme = {"shapes": [{"label": "x", "shape_type": "rectangle",
                               "points": [[1, 1], [5, 5]]}],
                   "imagePath": "a.jpg"}
        _touch(tmp_path / "c" / "labels" / "a.json",
               _json.dumps(labelme).encode())
        assert _detect_layout(tmp_path, IMG_EXTS) == "standard"


# ---- PNG helper ----

def _make_png() -> bytes:
    """Create a minimal valid 1×1 white PNG."""
    import struct, zlib
    sig = b"\x89PNG\r\n\x1a\n"

    def chunk(ctype, data):
        c = ctype + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    raw = zlib.compress(b"\x00\xff\xff\xff")
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", raw) + chunk(b"IEND", b"")
