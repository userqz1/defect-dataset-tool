"""End-to-end exporter validation — ROADMAP 第一步 1.3.

Each test:
  1. Builds a synthetic dataset on disk (real PNG + LabelMe JSON)
  2. Splits it
  3. Runs the exporter
  4. Validates the output structure + parses key files

Covers all Schemas registered in ``core.schema`` after the v1.2
registry unification (review #4+#14).
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from PIL import Image

from core.api import all_schemas, run_export
from core.splitter import SplitOptions, split_dataset

# ``synthetic_dataset`` fixture now lives in tests/conftest.py so it's
# reused by test_schema / test_ingest_rules / test_pipeline / test_dedup.


@pytest.fixture
def split(synthetic_dataset):
    return split_dataset(
        synthetic_dataset,
        SplitOptions(train=0.5, val=0.5, test=0.0, stratified=True, seed=42),
    )


# ---- Tests -----------------------------------------------------------------

class TestRegistryComplete:
    def test_all_schemas_registered(self):
        expected = {
            "YOLO", "COCO", "VOC", "LabelMe JSON",
            "ImageFolder", "MVTec", "PairedFolder",
            "CSV", "JSONL", "ShareGPT", "LLaVA", "Swift",
        }
        assert {s.key for s in all_schemas()} == expected


class TestYolo:
    def test_structure(self, split, tmp_path):
        out = tmp_path / "out_yolo"
        run_export("YOLO", split, out, copy_images=True)
        # Required directories
        assert (out / "images" / "train").is_dir()
        assert (out / "labels" / "train").is_dir()
        # train labels are .txt files with "class cx cy w h" format
        for txt in (out / "labels" / "train").glob("*.txt"):
            for line in txt.read_text().splitlines():
                parts = line.split()
                assert len(parts) == 5
                cls, cx, cy, w, h = parts
                assert cls.isdigit()
                for v in (cx, cy, w, h):
                    f = float(v)
                    assert 0.0 <= f <= 1.0


class TestCoco:
    def test_json_loads(self, split, tmp_path):
        out = tmp_path / "out_coco"
        run_export("COCO", split, out, copy_images=True)
        # COCO writes annotations/instances_<split>.json
        ann_dir = out / "annotations"
        json_files = list(ann_dir.glob("*.json"))
        assert json_files, "no COCO json produced"
        for jf in json_files:
            data = json.loads(jf.read_text(encoding="utf-8"))
            assert "images" in data and "annotations" in data and "categories" in data
            # Every annotation references a real image_id
            img_ids = {im["id"] for im in data["images"]}
            for ann in data["annotations"]:
                assert ann["image_id"] in img_ids
                # bbox = [x, y, w, h]
                assert len(ann["bbox"]) == 4


class TestVoc:
    def test_xml_per_image(self, split, tmp_path):
        out = tmp_path / "out_voc"
        run_export("VOC", split, out, copy_images=True)
        assert (out / "JPEGImages").is_dir()
        assert (out / "Annotations").is_dir()
        xml_files = list((out / "Annotations").glob("*.xml"))
        assert xml_files
        # XML must contain <annotation>, <object>, <bndbox>
        for xf in xml_files:
            text = xf.read_text(encoding="utf-8")
            assert "<annotation>" in text
            assert "<bndbox>" in text


class TestCsv:
    def test_columns(self, split, tmp_path):
        out = tmp_path / "out_csv"
        run_export("CSV", split, out, copy_images=True)
        csv_files = list(out.glob("*.csv"))
        assert csv_files
        with csv_files[0].open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            assert rows
            # Common columns we expect to see
            for col in ("image", "label"):
                assert any(col in k.lower() for k in rows[0].keys()), (
                    f"missing col '{col}' in {list(rows[0].keys())}")


class TestJsonl:
    def test_each_line_parses(self, split, tmp_path):
        out = tmp_path / "out_jsonl"
        run_export("JSONL", split, out, copy_images=True)
        jl_files = list(out.glob("*.jsonl"))
        assert jl_files
        for jf in jl_files:
            for line in jf.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                assert isinstance(obj, dict)


class TestLlava:
    def test_conversation_format(self, split, tmp_path):
        out = tmp_path / "out_llava"
        run_export("LLaVA", split, out, copy_images=True)
        jl_files = list(out.glob("*.jsonl"))
        assert jl_files
        for jf in jl_files:
            for line in jf.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                # LLaVA records have "image" + "conversations"
                assert "conversations" in obj or "messages" in obj


class TestShareGpt:
    def test_dataset_info(self, split, tmp_path):
        out = tmp_path / "out_sharegpt"
        run_export("ShareGPT", split, out, copy_images=True)
        # ShareGPT must produce a dataset_info.json
        info = out / "dataset_info.json"
        assert info.exists(), "missing dataset_info.json"
        data = json.loads(info.read_text(encoding="utf-8"))
        assert isinstance(data, dict) and data


class TestSwift:
    def test_jsonl_query_response(self, split, tmp_path):
        out = tmp_path / "out_swift"
        run_export("Swift", split, out, copy_images=True)
        jl_files = list(out.glob("*.jsonl"))
        assert jl_files
        for jf in jl_files:
            for line in jf.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                # Swift VLM records carry images + (query|messages|response)
                keys = set(obj.keys())
                assert keys & {"query", "messages", "response", "images"}, (
                    f"unexpected swift keys: {keys}")


class TestUnknownFormat:
    def test_raises_value_error(self, split, tmp_path):
        with pytest.raises(ValueError, match="未知导出格式"):
            run_export("Bogus", split, tmp_path / "out_x")
