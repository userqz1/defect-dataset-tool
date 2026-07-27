"""Tests for core/annotation_formats.py — YOLO, VOC, COCO parsers + dispatch."""
from __future__ import annotations

import json
import pytest
from pathlib import Path

from core.annotation_formats import (
    parse_annotation,
    parse_yolo,
    parse_voc,
    parse_coco,
    detect_format,
    load_yolo_classes,
)
from core.models import Shape


# ---- helpers ----

def _touch(p: Path, content: str | bytes = "") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        p.write_bytes(content)
    else:
        p.write_text(content, encoding="utf-8")
    return p


def _make_png() -> bytes:
    import struct, zlib
    sig = b"\x89PNG\r\n\x1a\n"
    def chunk(ctype, data):
        c = ctype + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", 100, 100, 8, 2, 0, 0, 0)
    raw = zlib.compress(b"\x00" + b"\xff\xff\xff" * 100)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", raw) + chunk(b"IEND", b"")


# ---- dispatch ----

class TestDispatch:
    def test_dispatch_json(self, tmp_path):
        data = {"imagePath": "x.jpg", "shapes": []}
        p = _touch(tmp_path / "a.json", json.dumps(data))
        r = parse_annotation(p)
        assert r.ok

    def test_dispatch_txt(self, tmp_path):
        p = _touch(tmp_path / "a.txt", "0 0.5 0.5 0.2 0.3")
        r = parse_annotation(p)
        assert r.ok

    def test_dispatch_xml(self, tmp_path):
        xml = """<annotation>
            <filename>x.jpg</filename>
            <object><name>cat</name>
                <bndbox><xmin>10</xmin><ymin>20</ymin><xmax>100</xmax><ymax>200</ymax></bndbox>
            </object>
        </annotation>"""
        p = _touch(tmp_path / "a.xml", xml)
        r = parse_annotation(p)
        assert r.ok

    def test_dispatch_unsupported(self, tmp_path):
        p = _touch(tmp_path / "a.csv", "data")
        r = parse_annotation(p)
        assert not r.ok


class TestDetectFormat:
    def test_json(self):
        assert detect_format(Path("x.json")) == "labelme"

    def test_txt(self):
        assert detect_format(Path("x.txt")) == "yolo"

    def test_xml(self):
        assert detect_format(Path("x.xml")) == "voc"

    def test_unknown(self):
        assert detect_format(Path("x.xyz")) == "unknown"


# ---- YOLO parser ----

class TestParseYolo:
    def test_single_box(self, tmp_path):
        p = _touch(tmp_path / "a.txt", "0 0.5 0.5 0.2 0.3\n")
        r = parse_yolo(p)
        assert r.ok
        assert len(r.annotation.shapes) == 1
        s = r.annotation.shapes[0]
        assert s.label == "0"
        assert s.shape_type == "rectangle"

    def test_with_class_names(self, tmp_path):
        p = _touch(tmp_path / "a.txt", "0 0.5 0.5 0.2 0.3\n1 0.1 0.1 0.05 0.05\n")
        r = parse_yolo(p, class_names=["cat", "dog"])
        assert r.ok
        assert r.annotation.shapes[0].label == "cat"
        assert r.annotation.shapes[1].label == "dog"

    def test_with_image_denormalize(self, tmp_path):
        img_p = _touch(tmp_path / "a.jpg", _make_png())
        p = _touch(tmp_path / "a.txt", "0 0.5 0.5 1.0 1.0\n")
        r = parse_yolo(p, image_path=img_p)
        assert r.ok
        s = r.annotation.shapes[0]
        # 100x100 image, full-size box: points should be (0,0) and (100,100)
        assert abs(s.points[0][0] - 0.0) < 1
        assert abs(s.points[1][0] - 100.0) < 1

    def test_empty_file(self, tmp_path):
        p = _touch(tmp_path / "a.txt", "")
        r = parse_yolo(p)
        assert r.ok
        assert len(r.annotation.shapes) == 0

    def test_comments_and_blank_lines(self, tmp_path):
        p = _touch(tmp_path / "a.txt", "# comment\n\n0 0.5 0.5 0.2 0.3\n")
        r = parse_yolo(p)
        assert r.ok
        assert len(r.annotation.shapes) == 1

    def test_malformed_line_skipped(self, tmp_path):
        p = _touch(tmp_path / "a.txt", "bad line\n0 0.5 0.5 0.2 0.3\n")
        r = parse_yolo(p)
        assert r.ok
        assert len(r.annotation.shapes) == 1

    def test_missing_file(self, tmp_path):
        r = parse_yolo(tmp_path / "nonexistent.txt")
        assert not r.ok

    def test_coord_space_pixel_when_image_given(self, tmp_path):
        """With image_path, coords denormalize to pixel space (review #4)."""
        img_p = _touch(tmp_path / "a.jpg", _make_png())
        p = _touch(tmp_path / "a.txt", "0 0.5 0.5 1.0 1.0\n")
        r = parse_yolo(p, image_path=img_p)
        assert r.ok
        assert r.coord_space == "pixel"

    def test_coord_space_normalized_without_image(self, tmp_path):
        """Without image_path, coords stay 0..1 and the flag flags it.

        Downstream writers must check coord_space to avoid treating 0.5 as
        "0.5 pixels" and silently writing a corrupt annotation.
        """
        p = _touch(tmp_path / "a.txt", "0 0.5 0.5 0.2 0.3\n")
        r = parse_yolo(p)
        assert r.ok
        assert r.coord_space == "normalized"
        s = r.annotation.shapes[0]
        # Points are in 0..1 space, not pixels
        for x, y in s.points:
            assert 0 <= x <= 1 and 0 <= y <= 1

    def test_yolo_obb_four_points(self, tmp_path):
        img_p = _touch(tmp_path / "a.jpg", _make_png())
        p = _touch(
            tmp_path / "a.txt",
            "0 0.10 0.20 0.80 0.10 0.90 0.70 0.20 0.80\n",
        )
        r = parse_yolo(p, image_path=img_p, class_names=["plate"])
        assert r.ok
        s = r.annotation.shapes[0]
        assert s.label == "plate"
        assert s.shape_type == "polygon"
        assert len(s.points) == 4
        assert r.coord_space == "pixel"

    def test_yolo_seg_many_points_not_misread_as_dota(self, tmp_path):
        p = _touch(
            tmp_path / "a.txt",
            "0 0.10 0.10 0.80 0.10 0.90 0.50 0.50 0.90 0.20 0.60\n",
        )
        r = parse_yolo(p, class_names=["mask"])
        assert r.ok
        s = r.annotation.shapes[0]
        assert s.label == "mask"
        assert s.shape_type == "polygon"
        assert len(s.points) == 5

    def test_dota_labeltxt_line(self, tmp_path):
        p = _touch(tmp_path / "a.txt", "10 20 80 10 90 70 20 80 plate 0\n")
        r = parse_yolo(p)
        assert r.ok
        s = r.annotation.shapes[0]
        assert s.label == "plate"
        assert s.shape_type == "polygon"
        assert len(s.points) == 4
        assert r.coord_space == "pixel"


class TestLoadYoloClasses:
    def test_from_classes_txt(self, tmp_path):
        _touch(tmp_path / "classes.txt", "cat\ndog\n")
        result = load_yolo_classes(tmp_path)
        assert result == ["cat", "dog"]

    def test_from_classes_txt_strips_bom_and_newlines(self, tmp_path):
        _touch(tmp_path / "classes.txt", "\ufefffastener_core\n\nLoose\n")
        result = load_yolo_classes(tmp_path)
        assert result == ["fastener_core", "Loose"]

    def test_from_parent_dir(self, tmp_path):
        _touch(tmp_path / "classes.txt", "a\nb\n")
        sub = tmp_path / "labels"
        sub.mkdir()
        result = load_yolo_classes(sub)
        assert result == ["a", "b"]

    def test_no_classes_file(self, tmp_path):
        result = load_yolo_classes(tmp_path)
        assert result == []


# ---- VOC parser ----

class TestParseVoc:
    def test_single_object(self, tmp_path):
        xml = """<annotation>
            <filename>test.jpg</filename>
            <object>
                <name>cat</name>
                <bndbox>
                    <xmin>10</xmin><ymin>20</ymin>
                    <xmax>100</xmax><ymax>200</ymax>
                </bndbox>
            </object>
        </annotation>"""
        p = _touch(tmp_path / "a.xml", xml)
        r = parse_voc(p)
        assert r.ok
        assert len(r.annotation.shapes) == 1
        s = r.annotation.shapes[0]
        assert s.label == "cat"
        assert s.shape_type == "rectangle"
        assert s.points == [(10.0, 20.0), (100.0, 200.0)]

    def test_multiple_objects(self, tmp_path):
        xml = """<annotation>
            <filename>test.jpg</filename>
            <object><name>cat</name>
                <bndbox><xmin>0</xmin><ymin>0</ymin><xmax>50</xmax><ymax>50</ymax></bndbox>
            </object>
            <object><name>dog</name>
                <bndbox><xmin>60</xmin><ymin>60</ymin><xmax>100</xmax><ymax>100</ymax></bndbox>
            </object>
        </annotation>"""
        p = _touch(tmp_path / "a.xml", xml)
        r = parse_voc(p)
        assert r.ok
        assert len(r.annotation.shapes) == 2

    def test_empty_annotation(self, tmp_path):
        xml = "<annotation><filename>test.jpg</filename></annotation>"
        p = _touch(tmp_path / "a.xml", xml)
        r = parse_voc(p)
        assert r.ok
        assert len(r.annotation.shapes) == 0

    def test_invalid_xml(self, tmp_path):
        p = _touch(tmp_path / "bad.xml", "not xml at all!!!")
        r = parse_voc(p)
        assert not r.ok

    def test_infers_image_path(self, tmp_path):
        xml = """<annotation><filename>my_image.jpg</filename></annotation>"""
        p = _touch(tmp_path / "a.xml", xml)
        r = parse_voc(p)
        assert r.ok
        assert r.annotation.image_path.name == "my_image.jpg"


# ---- COCO parser ----

class TestParseCoco:
    def _coco_json(self, tmp_path, *, categories=None, images=None, annotations=None):
        data = {
            "categories": categories or [{"id": 1, "name": "cat"}],
            "images": images or [{"id": 1, "file_name": "a.jpg", "width": 100, "height": 100}],
            "annotations": annotations or [
                {"id": 1, "image_id": 1, "category_id": 1, "bbox": [10, 20, 30, 40]}
            ],
        }
        p = tmp_path / "annotations.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        return p

    def test_basic(self, tmp_path):
        p = self._coco_json(tmp_path)
        idx = parse_coco(p)
        assert idx is not None
        assert "a" in idx.by_stem
        assert len(idx.by_stem["a"]) == 1
        s = idx.by_stem["a"][0]
        assert s.label == "cat"
        assert s.shape_type == "rectangle"
        # bbox [10,20,30,40] → points [(10,20),(40,60)]
        assert s.points[0] == (10.0, 20.0)
        assert s.points[1] == (40.0, 60.0)

    def test_multiple_annotations(self, tmp_path):
        p = self._coco_json(
            tmp_path,
            annotations=[
                {"id": 1, "image_id": 1, "category_id": 1, "bbox": [0, 0, 10, 10]},
                {"id": 2, "image_id": 1, "category_id": 1, "bbox": [50, 50, 20, 20]},
            ],
        )
        idx = parse_coco(p)
        assert len(idx.by_stem["a"]) == 2

    def test_not_coco(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text('{"foo": "bar"}', encoding="utf-8")
        assert parse_coco(p) is None

    def test_invalid_json(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("not json!", encoding="utf-8")
        assert parse_coco(p) is None

    def test_missing_file(self, tmp_path):
        assert parse_coco(tmp_path / "no.json") is None

    def test_categories_index(self, tmp_path):
        p = self._coco_json(
            tmp_path,
            categories=[{"id": 1, "name": "dog"}, {"id": 2, "name": "cat"}],
            annotations=[
                {"id": 1, "image_id": 1, "category_id": 2, "bbox": [0, 0, 10, 10]},
            ],
        )
        idx = parse_coco(p)
        assert idx.categories == {1: "dog", 2: "cat"}
        assert idx.by_stem["a"][0].label == "cat"

    def test_category_names_are_normalized(self, tmp_path):
        p = self._coco_json(
            tmp_path,
            categories=[{"id": 1, "name": "fastener_core\n"}],
        )
        idx = parse_coco(p)
        assert idx.categories == {1: "fastener_core"}
        assert idx.by_stem["a"][0].label == "fastener_core"
