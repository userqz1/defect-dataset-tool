"""Tests for grounding (region-text) round-trip: write → read → Sample → export.

Covers: sidecar .grounding.json persistence, Region.text field,
Shape.text bridge, format_in grounding import, and export through
LLaVA / ShareGPT with grounding entries.
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from core.annotation_writer import (
    grounding_sidecar_path,
    read_grounding,
    write_grounding,
)
from core.format_out import ExportOptions, export_samples
from core.models import Shape
from core.unified import BBox, Region, Sample, SampleSet


# ── Helpers ────────────────────────────────────────────────────────────

def _make_image(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 64), (100, 150, 200)).save(path)


_GROUNDING_ENTRIES = [
    {"label": "crack", "bbox": [10, 20, 100, 200], "text": "A hairline crack"},
    {"label": "scratch", "bbox": [50, 60, 150, 250], "text": "Light surface scratch"},
]


def _grounded_sample_set(
    tmp_path: Path,
    regions_per_sample: list[list[Region]],
    split: str = "train",
) -> SampleSet:
    """Build SampleSet with images on disk and region text fields."""
    samples = []
    for i, regions in enumerate(regions_per_sample):
        ip = tmp_path / "images" / f"img_{i:03d}.png"
        _make_image(ip)
        s = Sample(
            image_path=ip,
            image_width=64, image_height=64,
            category="test",
            regions=regions,
            has_label=True,
            split=split,
        )
        samples.append(s)
    return SampleSet(samples=samples)


# ── Sidecar write / read ─────────────────────────────────────────────

class TestGroundingSidecar:
    def test_sidecar_path(self, tmp_path):
        img = tmp_path / "photo.jpg"
        p = grounding_sidecar_path(img)
        assert p.name == "photo.grounding.json"
        assert p.parent == tmp_path

    def test_write_creates_json(self, tmp_path):
        img = tmp_path / "photo.jpg"
        _make_image(img)
        p = write_grounding(img, _GROUNDING_ENTRIES)
        assert p.exists()
        assert p.suffix == ".json"
        data = json.loads(p.read_text(encoding="utf-8"))
        assert len(data) == 2
        assert data[0]["label"] == "crack"
        assert data[0]["text"] == "A hairline crack"
        assert data[1]["bbox"] == [50, 60, 150, 250]

    def test_read_roundtrip(self, tmp_path):
        img = tmp_path / "photo.jpg"
        _make_image(img)
        write_grounding(img, _GROUNDING_ENTRIES)
        result = read_grounding(img)
        assert len(result) == 2
        assert result[0]["text"] == "A hairline crack"
        assert result[1]["label"] == "scratch"

    def test_read_nonexistent(self, tmp_path):
        assert read_grounding(tmp_path / "missing.jpg") == []

    def test_read_malformed_json(self, tmp_path):
        img = tmp_path / "bad.jpg"
        sidecar = grounding_sidecar_path(img)
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        sidecar.write_text("{not a list}", encoding="utf-8")
        assert read_grounding(img) == []

    def test_read_filters_invalid_entries(self, tmp_path):
        img = tmp_path / "partial.jpg"
        sidecar = grounding_sidecar_path(img)
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        data = [
            {"label": "a", "text": "ok"},
            {"unrelated": "garbage"},  # no label or text
            "not a dict",
            {"text": "text-only entry"},  # valid — has text
        ]
        sidecar.write_text(json.dumps(data), encoding="utf-8")
        result = read_grounding(img)
        assert len(result) == 2
        assert result[0]["label"] == "a"
        assert result[1]["text"] == "text-only entry"

    def test_write_unicode(self, tmp_path):
        img = tmp_path / "img.png"
        _make_image(img)
        entries = [{"label": "defect", "text": "表面有一条划痕"}]
        write_grounding(img, entries)
        result = read_grounding(img)
        assert result[0]["text"] == "表面有一条划痕"

    def test_overwrite(self, tmp_path):
        img = tmp_path / "img.png"
        _make_image(img)
        write_grounding(img, _GROUNDING_ENTRIES)
        assert len(read_grounding(img)) == 2
        write_grounding(img, [{"label": "x", "text": "y"}])
        assert len(read_grounding(img)) == 1

    def test_empty_grounding(self, tmp_path):
        img = tmp_path / "img.png"
        _make_image(img)
        write_grounding(img, [])
        assert read_grounding(img) == []


# ── Region.text field ─────────────────────────────────────────────────

class TestRegionText:
    def test_region_text_default_empty(self):
        r = Region(label="crack")
        assert r.text == ""

    def test_region_text_set(self):
        r = Region(label="crack", text="A hairline crack on the surface")
        assert r.text == "A hairline crack on the surface"

    def test_shape_text_default_empty(self):
        s = Shape(label="crack", shape_type="rectangle", points=[(0, 0), (1, 1)])
        assert s.text == ""

    def test_shape_text_set(self):
        s = Shape(label="crack", shape_type="rectangle",
                  points=[(0, 0), (1, 1)], text="some text")
        assert s.text == "some text"


# ── Bridge functions ──────────────────────────────────────────────────

class TestBridgeFunctions:
    """Verify text survives Region ↔ Shape conversion."""

    def test_region_to_shape_carries_text(self):
        from gui.views.detail_view import _region_to_shape
        r = Region(label="crack", bbox=BBox(10, 20, 100, 200),
                   shape_type="rectangle", text="crack description")
        s = _region_to_shape(r)
        assert s.text == "crack description"
        assert s.label == "crack"

    def test_shape_to_region_carries_text(self):
        from gui.views.detail_view import _shape_to_region
        s = Shape(label="scratch", shape_type="rectangle",
                  points=[(10, 20), (100, 200)], text="scratch text")
        r = _shape_to_region(s)
        assert r.text == "scratch text"
        assert r.label == "scratch"

    def test_round_trip_preserves_text(self):
        from gui.views.detail_view import _region_to_shape, _shape_to_region
        original = Region(
            label="defect",
            bbox=BBox(5, 10, 50, 60),
            shape_type="rectangle",
            text="Important grounding text",
        )
        shape = _region_to_shape(original)
        restored = _shape_to_region(shape)
        assert restored.text == "Important grounding text"
        assert restored.label == "defect"


# ── Export with grounding ─────────────────────────────────────────────

class TestGroundingExport:
    def test_llava_includes_grounding(self, tmp_path):
        regions = [
            Region(label="crack", bbox=BBox(10, 20, 100, 200),
                   shape_type="rectangle", text="A crack"),
            Region(label="ok", bbox=BBox(0, 0, 50, 50),
                   shape_type="rectangle"),  # no text
        ]
        ss = _grounded_sample_set(tmp_path, [regions])
        out = tmp_path / "export"
        opts = ExportOptions(out_dir=out, copy_images=False,
                             question="Describe defects.")
        export_samples(ss, "llava", opts)
        jsonl = out / "llava_train.jsonl"
        assert jsonl.exists()
        record = json.loads(jsonl.read_text(encoding="utf-8").strip())
        assert "grounding" in record
        assert len(record["grounding"]) == 1  # only the one with text
        assert record["grounding"][0]["label"] == "crack"
        assert record["grounding"][0]["text"] == "A crack"
        assert record["grounding"][0]["bbox"] == [10, 20, 100, 200]

    def test_sharegpt_includes_grounding(self, tmp_path):
        regions = [
            Region(label="scratch", bbox=BBox(5, 5, 60, 60),
                   shape_type="rectangle", text="Light scratch"),
        ]
        ss = _grounded_sample_set(tmp_path, [regions])
        out = tmp_path / "export"
        opts = ExportOptions(out_dir=out, copy_images=False, question="")
        export_samples(ss, "sharegpt", opts)
        jsonf = out / "sharegpt_train.json"
        data = json.loads(jsonf.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert "grounding" in data[0]
        assert data[0]["grounding"][0]["text"] == "Light scratch"

    def test_no_grounding_when_no_text(self, tmp_path):
        regions = [
            Region(label="defect", bbox=BBox(0, 0, 10, 10),
                   shape_type="rectangle"),  # no text
        ]
        ss = _grounded_sample_set(tmp_path, [regions])
        out = tmp_path / "export"
        opts = ExportOptions(out_dir=out, copy_images=False, question="Q")
        export_samples(ss, "llava", opts)
        jsonl = out / "llava_train.jsonl"
        record = json.loads(jsonl.read_text(encoding="utf-8").strip())
        assert "grounding" not in record


# ── Format_in grounding import ───────────────────────────────────────

class TestGroundingImport:
    def test_vlm_jsonl_grounding_carries_text(self, tmp_path):
        """Verify that importing VLM JSONL with grounding data populates
        Region.text on the created regions."""
        img = tmp_path / "images" / "test.png"
        _make_image(img)
        jsonl = tmp_path / "data.jsonl"
        record = {
            "image": "images/test.png",
            "conversations": [
                {"from": "human", "value": "<image>\nDescribe"},
                {"from": "gpt", "value": "A surface with defects"},
            ],
            "grounding": [
                {"label": "crack", "bbox": [10, 20, 50, 60],
                 "text": "hairline crack"},
            ],
        }
        jsonl.write_text(json.dumps(record), encoding="utf-8")
        from core.format_in import load_vlm_jsonl
        ss = load_vlm_jsonl(jsonl, tmp_path)
        assert len(ss.samples) == 1
        s = ss.samples[0]
        # Regions created from grounding should have text
        grounded = [r for r in s.regions if r.text]
        assert len(grounded) == 1
        assert grounded[0].text == "hairline crack"
        assert grounded[0].label == "crack"


# ── Disk sidecar → Sample round-trip ─────────────────────────────────

class TestSidecarToSampleRoundtrip:
    def test_full_round_trip(self, tmp_path):
        """Write grounding sidecar, read back, attach to Sample, export."""
        img = tmp_path / "photo.png"
        _make_image(img)

        # 1. Write to disk
        write_grounding(img, _GROUNDING_ENTRIES)

        # 2. Read back
        disk = read_grounding(img)
        assert len(disk) == 2

        # 3. Build regions with text
        regions = []
        for g in disk:
            bb = g.get("bbox")
            r = Region(
                label=g.get("label", ""),
                text=g.get("text", ""),
                shape_type="rectangle",
            )
            if bb and len(bb) >= 4:
                r.bbox = BBox(*bb[:4])
            regions.append(r)

        # 4. Export
        s = Sample(
            image_path=img,
            image_width=64, image_height=64,
            category="test",
            regions=regions,
            split="train",
        )
        ss = SampleSet(samples=[s])
        out = tmp_path / "export"
        opts = ExportOptions(out_dir=out, copy_images=False, question="Q")
        export_samples(ss, "llava", opts)

        jsonl = out / "llava_train.jsonl"
        record = json.loads(jsonl.read_text(encoding="utf-8").strip())
        assert len(record["grounding"]) == 2
        assert record["grounding"][0]["text"] == "A hairline crack"
        assert record["grounding"][1]["label"] == "scratch"
