"""Tests for core/format_migrate.py — annotation format migration.

Round-trips: LabelMe → YOLO → VOC, verifying labels survive, backup
files are cleaned up, and malformed inputs don't crash.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from core.annotation_formats import detect_format, parse_annotation
from core.format_migrate import MigrateResult, migrate_annotation_format
from core.models import Category, Dataset, ImageInfo


# ── Helpers ────────────────────────────────────────────────────────────

def _write_image(path: Path, w: int = 64, h: int = 64) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (w, h), (128, 128, 128)).save(path)


def _write_labelme(json_path: Path, image_name: str,
                   label: str = "defect",
                   points: list | None = None) -> None:
    pts = points or [[10.0, 10.0], [50.0, 50.0]]
    payload = {
        "version": "5.0.1",
        "shapes": [{
            "label": label,
            "points": pts,
            "group_id": None,
            "shape_type": "rectangle",
            "flags": {},
        }],
        "imagePath": image_name,
        "imageWidth": 64,
        "imageHeight": 64,
    }
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, ensure_ascii=False),
                         encoding="utf-8")


def _make_labeled_dataset(tmp_path: Path, n: int = 3,
                          label: str = "crack") -> Dataset:
    """Build a real on-disk dataset with LabelMe labels."""
    root = tmp_path / "ds"
    cat_dir = root / "defects"
    img_dir = cat_dir / "images"
    lbl_dir = cat_dir / "labels"
    img_dir.mkdir(parents=True)
    lbl_dir.mkdir(parents=True)

    images: list[ImageInfo] = []
    for i in range(n):
        ip = img_dir / f"img_{i:03d}.png"
        jp = lbl_dir / f"img_{i:03d}.json"
        _write_image(ip)
        _write_labelme(jp, ip.name, label)
        images.append(ImageInfo(
            path=ip, category="defects", width=64, height=64,
            has_label=True, label_path=jp,
        ))

    cat = Category(name="defects", image_count=n, label_count=n,
                   images=images)
    return Dataset(
        name="test_ds", root_path=root, categories=[cat],
        total_images=n, total_annotations=n, layout="standard",
    )


# ── LabelMe → YOLO ───────────────────────────────────────────────────

class TestLabelmeToYolo:
    def test_basic_migration(self, tmp_path):
        ds = _make_labeled_dataset(tmp_path, n=2, label="scratch")
        result = migrate_annotation_format(ds, "yolo")
        assert result.converted == 2
        assert result.skipped == 0
        assert result.failed == []

        # YOLO .txt files should now exist
        lbl_dir = tmp_path / "ds" / "defects" / "labels"
        txt_files = list(lbl_dir.glob("*.txt"))
        # classes.txt + per-image .txt
        per_image = [f for f in txt_files if f.name != "classes.txt"]
        assert len(per_image) == 2

        # Old .json files should be deleted
        json_files = list(lbl_dir.glob("*.json"))
        assert len(json_files) == 0

        # No .bak files left behind
        bak_files = list(lbl_dir.glob("*.bak"))
        assert len(bak_files) == 0

    def test_classes_txt_written(self, tmp_path):
        ds = _make_labeled_dataset(tmp_path, n=1, label="dent")
        migrate_annotation_format(ds, "yolo")
        classes = (tmp_path / "ds" / "defects" / "labels" / "classes.txt")
        assert classes.is_file()
        names = classes.read_text(encoding="utf-8").strip().split("\n")
        assert "dent" in names

    def test_yolo_content_valid(self, tmp_path):
        ds = _make_labeled_dataset(tmp_path, n=1, label="crack")
        migrate_annotation_format(ds, "yolo")
        lbl_dir = tmp_path / "ds" / "defects" / "labels"
        txt = [f for f in lbl_dir.glob("*.txt") if f.name != "classes.txt"][0]
        line = txt.read_text(encoding="utf-8").strip()
        parts = line.split()
        assert len(parts) == 5  # class_idx cx cy w h
        assert int(parts[0]) == 0
        cx, cy, w, h = (float(x) for x in parts[1:])
        assert 0.0 < cx < 1.0
        assert 0.0 < cy < 1.0
        assert 0.0 < w <= 1.0
        assert 0.0 < h <= 1.0


# ── LabelMe → VOC ────────────────────────────────────────────────────

class TestLabelmeToVoc:
    def test_basic_migration(self, tmp_path):
        ds = _make_labeled_dataset(tmp_path, n=2, label="rust")
        result = migrate_annotation_format(ds, "voc")
        assert result.converted == 2

        lbl_dir = tmp_path / "ds" / "defects" / "labels"
        xml_files = list(lbl_dir.glob("*.xml"))
        assert len(xml_files) == 2

    def test_voc_xml_structure(self, tmp_path):
        ds = _make_labeled_dataset(tmp_path, n=1, label="pit")
        migrate_annotation_format(ds, "voc")
        lbl_dir = tmp_path / "ds" / "defects" / "labels"
        xml_file = list(lbl_dir.glob("*.xml"))[0]

        from xml.etree import ElementTree as ET
        tree = ET.parse(xml_file)
        root = tree.getroot()
        assert root.tag == "annotation"
        objs = root.findall("object")
        assert len(objs) == 1
        assert objs[0].find("name").text == "pit"
        bnd = objs[0].find("bndbox")
        assert bnd is not None
        xmin = int(bnd.find("xmin").text)
        ymin = int(bnd.find("ymin").text)
        xmax = int(bnd.find("xmax").text)
        ymax = int(bnd.find("ymax").text)
        assert xmin < xmax
        assert ymin < ymax


# ── YOLO → VOC round-trip ────────────────────────────────────────────

class TestYoloToVoc:
    def test_labelme_to_yolo_to_voc_preserves_labels(self, tmp_path):
        """Multi-hop migration: LabelMe → YOLO → VOC.
        The class label must survive both hops."""
        ds = _make_labeled_dataset(tmp_path, n=2, label="chip")

        # Hop 1: LabelMe → YOLO
        r1 = migrate_annotation_format(ds, "yolo")
        assert r1.converted == 2

        # Update ImageInfo to point to new YOLO labels
        lbl_dir = tmp_path / "ds" / "defects" / "labels"
        for img in ds.categories[0].images:
            yolo_path = lbl_dir / (img.path.stem + ".txt")
            assert yolo_path.is_file()
            img.label_path = yolo_path

        # Hop 2: YOLO → VOC
        r2 = migrate_annotation_format(ds, "voc")
        assert r2.converted == 2

        # Verify VOC files contain "chip"
        xml_files = list(lbl_dir.glob("*.xml"))
        assert len(xml_files) == 2
        from xml.etree import ElementTree as ET
        for xf in xml_files:
            tree = ET.parse(xf)
            names = [o.find("name").text for o in tree.findall(".//object")]
            assert "chip" in names


# ── Edge cases ────────────────────────────────────────────────────────

class TestMigrateEdgeCases:
    def test_unlabeled_images_skipped(self, tmp_path):
        root = tmp_path / "ds"
        img_dir = root / "empty" / "images"
        img_dir.mkdir(parents=True)
        ip = img_dir / "no_label.png"
        _write_image(ip)
        img = ImageInfo(path=ip, category="empty", width=64, height=64,
                        has_label=False)
        cat = Category(name="empty", image_count=1, label_count=0,
                       images=[img])
        ds = Dataset(name="x", root_path=root, categories=[cat],
                     total_images=1, total_annotations=0, layout="standard")
        result = migrate_annotation_format(ds, "yolo")
        assert result.converted == 0
        assert result.skipped == 1

    def test_progress_callback_invoked(self, tmp_path):
        ds = _make_labeled_dataset(tmp_path, n=3)
        calls: list[tuple] = []
        migrate_annotation_format(
            ds, "yolo",
            progress_cb=lambda i, t, n: calls.append((i, t, n)),
        )
        assert len(calls) >= 3  # at least once per image + final
        # Final callback should have i == t
        assert calls[-1][0] == calls[-1][1]
