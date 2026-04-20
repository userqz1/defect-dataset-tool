"""Schema validator tests — cover each of the 10 registered schemas.

Each Schema exposes ``slots`` + ``validator`` per slot; calling
``schema.validate(dataset)`` returns a ComplianceReport. These tests
assert specific slots pass / fail against representative datasets so a
future regression in a validator (e.g. accidentally always returning OK)
surfaces immediately.
"""
from __future__ import annotations

import pytest

from core.api import all_schemas, get_schema, TaskType


# ---------- Registry-level ----------

class TestRegistry:
    def test_ten_schemas_registered(self):
        keys = {s.key for s in all_schemas()}
        assert keys == {
            "YOLO", "COCO", "VOC", "ImageFolder", "MVTec",
            "CSV", "JSONL", "ShareGPT", "LLaVA", "Swift",
        }

    def test_every_schema_has_required_attributes(self):
        for s in all_schemas():
            assert s.key
            assert s.display_name
            assert s.slots, f"{s.key} has no slots"
            assert callable(s.writer), f"{s.key} writer not callable"
            assert s.options_class is not None
            assert s.task_types, f"{s.key} declares no task_types"

    def test_get_schema_unknown_returns_none(self):
        assert get_schema("BogusFormat") is None

    def test_detection_schemas_include_mainline(self):
        from core.api import schemas_for_task
        det = {s.key for s in schemas_for_task(TaskType.DETECTION)}
        # The v0.1 §14.3 mainline must be available for DETECTION
        assert {"YOLO", "COCO", "VOC"} <= det

    def test_classification_includes_imagefolder(self):
        from core.api import schemas_for_task
        cls = {s.key for s in schemas_for_task(TaskType.CLASSIFICATION)}
        assert "ImageFolder" in cls

    def test_anomaly_includes_mvtec(self):
        from core.api import schemas_for_task
        ano = {s.key for s in schemas_for_task(TaskType.ANOMALY)}
        assert "MVTec" in ano


# ---------- Per-schema slot semantics ----------

class TestYoloValidator:
    def test_empty_dataset_not_ready(self, empty_dataset):
        rep = get_schema("YOLO").validate(empty_dataset)
        assert not rep.ready
        # All 6 slots failing
        assert rep.required_filled == 0

    def test_fully_annotated_detection_ready_except_split(self, synthetic_dataset):
        # synthetic_dataset has 6 imgs + 6 labels + 2 cats.
        # YOLO wants split, which is always "decided at export time"; so
        # ready=False but everything except split passes.
        rep = get_schema("YOLO").validate(synthetic_dataset)
        missing_keys = {s.key for s in rep.missing()}
        assert missing_keys == {"split"}, f"unexpected missing: {missing_keys}"

    def test_unlabeled_fails_labels_slot(self, unlabeled_dataset):
        rep = get_schema("YOLO").validate(unlabeled_dataset)
        # both labels and split should be missing
        missing_keys = {s.key for s in rep.missing()}
        assert "labels" in missing_keys
        assert "split" in missing_keys


class TestImageFolderValidator:
    def test_requires_two_classes(self, empty_dataset):
        rep = get_schema("ImageFolder").validate(empty_dataset)
        # Neither images nor 2-class minimum met
        missing_keys = {s.key for s in rep.missing()}
        assert {"images", "classes", "split"} <= missing_keys

    def test_two_classes_passes_classes_slot(self, synthetic_dataset):
        rep = get_schema("ImageFolder").validate(synthetic_dataset)
        # 2 classes — classes slot should pass
        status_by_key = {s.key: st for s, st in rep.results}
        assert status_by_key["classes"].ok, "classes slot should pass with 2 cats"


class TestMvtecValidator:
    def test_missing_good_fails(self, synthetic_dataset):
        # synthetic has "cat" and "dog", no "good"
        rep = get_schema("MVTec").validate(synthetic_dataset)
        status_by_key = {s.key: st for s, st in rep.results}
        assert not status_by_key["good"].ok
        assert "good" in status_by_key["good"].action_text or \
               "good" in status_by_key["good"].current_text

    def test_good_class_present_passes(self, tmp_path):
        from core.models import Category, Dataset, ImageInfo
        good = Category(name="good", image_count=5, label_count=0,
                        images=[ImageInfo(path=tmp_path / f"{i}.jpg",
                                           category="good") for i in range(5)])
        ds = Dataset(name="mv", root_path=tmp_path, categories=[good],
                      total_images=5, total_annotations=0)
        rep = get_schema("MVTec").validate(ds)
        status_by_key = {s.key: st for s, st in rep.results}
        assert status_by_key["good"].ok


class TestCsvValidator:
    def test_csv_labels_always_optional(self, unlabeled_dataset):
        """CSV is annotation-tolerant — unlabeled rows are still valid CSV."""
        rep = get_schema("CSV").validate(unlabeled_dataset)
        status_by_key = {s.key: st for s, st in rep.results}
        assert status_by_key["labels"].ok  # optional, so always ok


class TestShareGptValidator:
    def test_shapes_50_percent_threshold(self, synthetic_dataset):
        # 6 imgs, 6 labels (100% coverage) → shapes slot ok
        rep = get_schema("ShareGPT").validate(synthetic_dataset)
        status_by_key = {s.key: st for s, st in rep.results}
        assert status_by_key["shapes"].ok

    def test_below_50_percent_fails(self, tmp_path):
        from core.models import Category, Dataset, ImageInfo
        # 10 imgs, 3 labels = 30% — below 50%
        imgs = [ImageInfo(path=tmp_path / f"{i}.jpg", category="x",
                           has_label=i < 3) for i in range(10)]
        cat = Category(name="x", image_count=10, label_count=3, images=imgs)
        ds = Dataset(name="t", root_path=tmp_path, categories=[cat],
                      total_images=10, total_annotations=3)
        rep = get_schema("ShareGPT").validate(ds)
        status_by_key = {s.key: st for s, st in rep.results}
        assert not status_by_key["shapes"].ok


# ---------- ComplianceReport helpers ----------

class TestComplianceReport:
    def test_missing_returns_only_required_failures(self, synthetic_dataset):
        rep = get_schema("YOLO").validate(synthetic_dataset)
        for slot in rep.missing():
            assert slot.required, \
                f"missing() returned non-required slot {slot.key}"

    def test_progress_text_format(self, synthetic_dataset):
        rep = get_schema("YOLO").validate(synthetic_dataset)
        # "5/6" format — two ints joined by slash
        a, b = rep.progress_text.split("/")
        assert a.isdigit() and b.isdigit()

    def test_ready_requires_all_required_ok(self, synthetic_dataset):
        rep = get_schema("YOLO").validate(synthetic_dataset)
        if rep.required_filled == rep.required_count:
            assert rep.ready
        else:
            assert not rep.ready
