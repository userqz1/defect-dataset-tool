"""Tests for core/annotation.py and core/annotation_formats.py — parsing edge cases."""
from __future__ import annotations

import json
import pytest
from pathlib import Path

from core.annotation import ParseResult, parse_labelme
from core.models import Annotation


class TestParseResult:
    def test_ok_with_annotation(self):
        r = ParseResult(annotation=Annotation(image_path=Path("x.jpg"), shapes=[]))
        assert r.ok

    def test_not_ok_with_error(self):
        r = ParseResult(annotation=Annotation(image_path=Path("x.jpg")), error="bad")
        assert not r.ok  # annotation exists but error is set → not ok

    def test_not_ok_with_none(self):
        r = ParseResult(annotation=None, error="missing")
        assert not r.ok


class TestParseLabelme:
    def test_valid_json(self, tmp_path):
        data = {
            "imagePath": "test.jpg",
            "imageWidth": 640,
            "imageHeight": 480,
            "shapes": [
                {"label": "cat", "shape_type": "rectangle",
                 "points": [[10, 20], [100, 200]]},
            ],
        }
        p = tmp_path / "test.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        result = parse_labelme(p)
        assert result.ok
        assert len(result.annotation.shapes) == 1
        assert result.annotation.shapes[0].label == "cat"

    def test_utf8_bom_and_trailing_label_newline(self, tmp_path):
        data = {
            "imagePath": "test.jpg",
            "imageWidth": 640,
            "imageHeight": 480,
            "shapes": [
                {"label": "fastener_core\n", "shape_type": "rectangle",
                 "points": [[10, 20], [100, 200]]},
            ],
        }
        p = tmp_path / "test.json"
        p.write_text("\ufeff" + json.dumps(data), encoding="utf-8")

        result = parse_labelme(p)

        assert result.ok
        assert result.annotation.shapes[0].label == "fastener_core"

    def test_empty_shapes(self, tmp_path):
        data = {"imagePath": "x.jpg", "shapes": []}
        p = tmp_path / "empty.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        result = parse_labelme(p)
        assert result.ok
        assert len(result.annotation.shapes) == 0

    def test_invalid_json(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{not valid json!!!", encoding="utf-8")
        result = parse_labelme(p)
        assert not result.ok
        assert result.error is not None

    def test_missing_file(self, tmp_path):
        result = parse_labelme(tmp_path / "nonexistent.json")
        assert not result.ok

    def test_malformed_shape_tolerant(self, tmp_path):
        """Parser should be tolerant of shapes with missing fields."""
        data = {
            "imagePath": "x.jpg",
            "shapes": [
                {"label": "ok", "shape_type": "rectangle",
                 "points": [[0, 0], [10, 10]]},
                {"label": "bad"},  # missing shape_type and points
            ],
        }
        p = tmp_path / "partial.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        result = parse_labelme(p)
        # Should parse successfully, tolerating the bad shape
        assert result.annotation is not None
