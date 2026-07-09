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
from core.format_out import ExportOptions, export_samples
from core.splitter import SplitOptions, split_dataset

# ``synthetic_dataset`` fixture now lives in tests/conftest.py so it's
# reused by test_schema / test_ingest_rules / test_pipeline / test_dedup.


@pytest.fixture
def split(synthetic_dataset):
    return split_dataset(
        synthetic_dataset,
        SplitOptions(train=0.5, val=0.5, test=0.0, stratified=True, seed=42),
    )


def _one_region_set(tmp_path, w, h, region):
    """A 1-image train-split SampleSet carrying a single region."""
    from core.unified import Sample, SampleSet
    img = tmp_path / "s.png"
    Image.new("RGB", (w, h), (10, 20, 30)).save(img)
    s = Sample(image_path=img, image_width=w, image_height=h,
               split="train", regions=[region])
    return SampleSet(samples=[s])


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

    def test_data_yaml_omits_missing_val(self, synthetic_dataset, tmp_path):
        """data.yaml must not point val: at a non-existent images/val when
        there's no val split (Ultralytics errors on the missing dir)."""
        ss = split_dataset(
            synthetic_dataset,
            SplitOptions(train=1.0, val=0.0, test=0.0, seed=1),
        )
        out = tmp_path / "out_yolo_noval"
        run_export("YOLO", ss, out, copy_images=True)
        yaml = (out / "data.yaml").read_text(encoding="utf-8")
        assert "train: images/train" in yaml
        assert "val:" not in yaml, yaml
        assert not (out / "images" / "val").exists()

    def test_clamps_out_of_bounds_box(self, tmp_path):
        """An OOB box must export with coords in [0,1] (Ultralytics rejects
        out-of-bounds); corners are clamped to the image."""
        from core.unified import BBox, Region
        region = Region(label="x", bbox=BBox(80, 80, 150, 150),
                        shape_type="rectangle")
        ss = _one_region_set(tmp_path, 100, 100, region)
        out = tmp_path / "out_yolo_oob"
        export_samples(ss, "yolo", ExportOptions(out_dir=out, copy_images=False))
        line = next((out / "labels" / "train").glob("*.txt")).read_text().strip()
        for v in line.split()[1:]:
            assert 0.0 <= float(v) <= 1.0, line


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

    def test_categories_consistent_across_splits(self, split, tmp_path):
        """Same category_id must mean the same class in every split file —
        otherwise a COCO consumer that reads the label map from one file
        mislabels the others."""
        out = tmp_path / "out_coco_cats"
        run_export("COCO", split, out, copy_images=True)
        files = sorted((out / "annotations").glob("instances_*.json"))
        cats = [json.loads(f.read_text(encoding="utf-8"))["categories"]
                for f in files]
        assert len(cats) >= 2, "need >=2 split files to compare"
        for c in cats[1:]:
            assert c == cats[0], "COCO categories differ across split files"
        # 1-indexed, contiguous
        ids = [c["id"] for c in cats[0]]
        assert ids == list(range(1, len(ids) + 1)), ids


class TestLabelMe:
    def test_image_path_resolves(self, split, tmp_path):
        """imagePath must resolve to the copied image from the JSON's dir —
        a bare filename makes labelme look in labels/ and fail to load."""
        out = tmp_path / "out_lme"
        run_export("LabelMe JSON", split, out, copy_images=True)
        jsons = list((out / "labels").rglob("*.json"))
        assert jsons, "no LabelMe json produced"
        for jf in jsons:
            data = json.loads(jf.read_text(encoding="utf-8"))
            ip = data["imagePath"]
            assert ip.startswith("../../images/"), ip
            assert (jf.parent / ip).resolve().exists(), (
                f"{ip} does not resolve from {jf}")

    def test_circle_and_point_geometry(self, tmp_path):
        """circle → exactly [center, edge]; point → exactly 1 pt. LabelMe
        rejects a 4-corner polygon carrying shape_type circle/point."""
        from core.format_out import _region_points
        from core.unified import BBox, Region
        # circle centered at (50,50), radius 10 → square bbox (40,40,60,60)
        circle = Region(label="c", bbox=BBox(40, 40, 60, 60),
                        shape_type="circle")
        pts = _region_points(circle)
        assert len(pts) == 2, pts
        (cx, cy), (ex, ey) = pts
        assert (cx, cy) == (50.0, 50.0)
        r = ((ex - cx) ** 2 + (ey - cy) ** 2) ** 0.5
        assert abs(r - 10.0) < 1e-6, r
        # point → single coordinate
        point = Region(label="p", keypoints=[(30.0, 40.0, 2)],
                       bbox=BBox(30, 40, 30, 40), shape_type="point")
        assert _region_points(point) == [(30.0, 40.0)]


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


class TestSegmentationExport:
    """Polygon regions must keep their mask geometry, not silently flatten
    to boxes, in COCO + YOLO-seg."""

    def _seg_set(self, tmp_path):
        from core.unified import BBox, Region
        poly = [(10.0, 10.0), (90.0, 10.0), (50.0, 90.0)]  # triangle
        region = Region(label="crack", polygon=poly,
                        bbox=BBox.from_points(poly), shape_type="polygon")
        return _one_region_set(tmp_path, 100, 100, region)

    def test_coco_keeps_segmentation(self, tmp_path):
        out = tmp_path / "seg_coco"
        export_samples(self._seg_set(tmp_path), "coco",
                       ExportOptions(out_dir=out, copy_images=False))
        data = json.loads(
            (out / "annotations" / "instances_train.json").read_text(
                encoding="utf-8"))
        assert data["annotations"], "no annotations written"
        ann = data["annotations"][0]
        assert ann.get("segmentation"), "segmentation dropped"
        assert len(ann["segmentation"][0]) == 6, ann["segmentation"]  # 3 pts
        assert len(ann["bbox"]) == 4  # bbox still present

    def test_yolo_writes_polygon_lines(self, tmp_path):
        out = tmp_path / "seg_yolo"
        export_samples(self._seg_set(tmp_path), "yolo",
                       ExportOptions(out_dir=out, copy_images=False))
        txt = next((out / "labels" / "train").glob("*.txt")).read_text().strip()
        parts = txt.split()
        # class id + 3 (x,y) pairs = 7 tokens, all normalized to [0,1]
        assert len(parts) == 7, parts
        assert parts[0].isdigit()
        for v in parts[1:]:
            assert 0.0 <= float(v) <= 1.0


class TestEllipse:
    """Ellipse is stored by bbox (shape_type='ellipse'); it reads back with a
    bbox and exports as an oval polygon to LabelMe, a bbox to YOLO/COCO."""

    def _ellipse_set(self, tmp_path):
        from core.unified import BBox, Region
        # bbox (20,30)-(80,70) → centre (50,50), rx=30, ry=20
        region = Region(label="oval", bbox=BBox(20, 30, 80, 70),
                        shape_type="ellipse")
        return _one_region_set(tmp_path, 100, 100, region)

    def test_format_in_reads_ellipse(self, tmp_path):
        from core.format_in import load_sample
        from core.models import ImageInfo
        img = tmp_path / "e.png"
        Image.new("RGB", (100, 100), (0, 0, 0)).save(img)
        jf = tmp_path / "e.json"
        jf.write_text(json.dumps({
            "shapes": [{"label": "oval", "points": [[20, 30], [80, 70]],
                        "shape_type": "ellipse", "flags": {}}],
            "imagePath": "e.png", "imageWidth": 100, "imageHeight": 100,
        }), encoding="utf-8")
        sample = load_sample(
            ImageInfo(path=img, category="", has_label=True, label_path=jf),
            "labelme")
        assert len(sample.regions) == 1
        r = sample.regions[0]
        assert r.shape_type == "ellipse" and r.bbox is not None
        assert (r.bbox.x1, r.bbox.y1, r.bbox.x2, r.bbox.y2) == (20, 30, 80, 70)

    def test_labelme_ellipse_becomes_oval_polygon(self, tmp_path):
        out = tmp_path / "el_lme"
        export_samples(self._ellipse_set(tmp_path), "labelme",
                       ExportOptions(out_dir=out, copy_images=False))
        jf = next((out / "labels").rglob("*.json"))
        shp = json.loads(jf.read_text(encoding="utf-8"))["shapes"][0]
        assert shp["shape_type"] == "polygon", shp["shape_type"]  # not "ellipse"
        assert len(shp["points"]) >= 8
        # every sampled point lies on the ellipse
        cx, cy, rx, ry = 50, 50, 30, 20
        for x, y in shp["points"]:
            assert abs(((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 - 1.0) < 1e-6

    def test_yolo_ellipse_uses_bbox(self, tmp_path):
        out = tmp_path / "el_yolo"
        export_samples(self._ellipse_set(tmp_path), "yolo",
                       ExportOptions(out_dir=out, copy_images=False))
        parts = next((out / "labels" / "train").glob("*.txt")
                     ).read_text().strip().split()
        assert len(parts) == 5, parts   # bbox line, not a polygon
        assert abs(float(parts[1]) - 0.5) < 1e-6   # cx
        assert abs(float(parts[3]) - 0.6) < 1e-6   # w = 60/100


class TestUnknownFormat:
    def test_raises_value_error(self, split, tmp_path):
        with pytest.raises(ValueError, match="未知导出格式"):
            run_export("Bogus", split, tmp_path / "out_x")
