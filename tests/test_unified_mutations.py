"""Tests for incremental SampleSet + Dataset mutations.

Covers: SampleSet.find, .remove_by_path, .remove_by_paths,
.update_sample, and Dataset.remove_images — the building blocks
for avoiding full rescan after delete/move operations.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.models import Category, Dataset, ImageInfo
from core.unified import BBox, Region, Sample, SampleSet


# ── SampleSet mutations ──────────────────────────────────────────────

class TestSampleSetFind:
    def test_find_existing(self):
        p = Path("a/b/img.png")
        s = Sample(image_path=p)
        ss = SampleSet(samples=[s])
        assert ss.find(str(p)) is s

    def test_find_by_path_object(self):
        s = Sample(image_path=Path("x.png"))
        ss = SampleSet(samples=[s])
        assert ss.find(Path("x.png")) is s

    def test_find_missing_returns_none(self):
        ss = SampleSet(samples=[Sample(image_path=Path("a.png"))])
        assert ss.find("nope.png") is None


class TestSampleSetRemove:
    def test_remove_by_path_single(self):
        s1 = Sample(image_path=Path("a.png"))
        s2 = Sample(image_path=Path("b.png"))
        ss = SampleSet(samples=[s1, s2])
        assert ss.remove_by_path("a.png") is True
        assert len(ss.samples) == 1
        assert ss.samples[0] is s2

    def test_remove_by_path_missing(self):
        ss = SampleSet(samples=[Sample(image_path=Path("x.png"))])
        assert ss.remove_by_path("nope.png") is False
        assert len(ss.samples) == 1

    def test_remove_by_paths_bulk(self):
        ss = SampleSet(samples=[
            Sample(image_path=Path("a.png")),
            Sample(image_path=Path("b.png")),
            Sample(image_path=Path("c.png")),
            Sample(image_path=Path("d.png")),
        ])
        removed = ss.remove_by_paths({"a.png", "c.png"})
        assert removed == 2
        assert len(ss.samples) == 2
        names = {str(s.image_path) for s in ss.samples}
        assert names == {"b.png", "d.png"}

    def test_remove_by_paths_empty_set(self):
        ss = SampleSet(samples=[Sample(image_path=Path("x.png"))])
        assert ss.remove_by_paths(set()) == 0
        assert len(ss.samples) == 1


class TestSampleSetUpdate:
    def test_update_existing_field(self):
        s = Sample(image_path=Path("img.png"), category="old", caption="")
        ss = SampleSet(samples=[s])
        ok = ss.update_sample("img.png", category="new", caption="hello")
        assert ok
        assert s.category == "new"
        assert s.caption == "hello"

    def test_update_missing_returns_false(self):
        ss = SampleSet(samples=[Sample(image_path=Path("x.png"))])
        assert ss.update_sample("nope.png", category="z") is False

    def test_update_ignores_unknown_fields(self):
        s = Sample(image_path=Path("a.png"))
        ss = SampleSet(samples=[s])
        ok = ss.update_sample("a.png", nonexistent_field="value")
        assert ok  # no crash, field silently ignored

    def test_update_work_status(self):
        s = Sample(image_path=Path("a.png"), work_status="new")
        ss = SampleSet(samples=[s])
        ss.update_sample("a.png", work_status="ready")
        assert s.work_status == "ready"


# ── Dataset.remove_images ────────────────────────────────────────────

def _make_dataset() -> Dataset:
    """3 images across 2 categories."""
    imgs_a = [
        ImageInfo(path=Path("root/cat_a/images/a1.png"), category="cat_a",
                  has_label=True, label_path=Path("root/cat_a/labels/a1.json")),
        ImageInfo(path=Path("root/cat_a/images/a2.png"), category="cat_a",
                  has_label=False),
    ]
    imgs_b = [
        ImageInfo(path=Path("root/cat_b/images/b1.png"), category="cat_b",
                  has_label=True, label_path=Path("root/cat_b/labels/b1.json")),
    ]
    return Dataset(
        name="test",
        root_path=Path("root"),
        categories=[
            Category(name="cat_a", image_count=2, label_count=1, images=imgs_a),
            Category(name="cat_b", image_count=1, label_count=1, images=imgs_b),
        ],
        total_images=3,
        total_annotations=2,
    )


class TestDatasetRemoveImages:
    def test_remove_single(self):
        ds = _make_dataset()
        removed = ds.remove_images({str(Path("root/cat_a/images/a1.png"))})
        assert removed == 1
        assert ds.total_images == 2
        assert ds.categories[0].image_count == 1

    def test_remove_updates_label_count(self):
        ds = _make_dataset()
        # Remove the labeled image from cat_a
        ds.remove_images({str(Path("root/cat_a/images/a1.png"))})
        assert ds.categories[0].label_count == 0
        # total_annotations is the SampleSet region count — without
        # regions_by_path passed in, remove_images must NOT touch it
        # (the semantic changed in Phase 2: it's no longer the
        # labeled-image count).
        assert ds.total_annotations == 2

    def test_remove_subtracts_region_count_when_provided(self):
        ds = _make_dataset()
        # Caller (browser_tool_controller._incremental_remove) passes
        # SampleSet-derived region counts so total_annotations stays in
        # sync with the in-memory model.
        a1 = str(Path("root/cat_a/images/a1.png"))
        regions = {a1: 1}  # a1 had 1 region total
        ds.remove_images({a1}, regions_by_path=regions)
        assert ds.total_annotations == 1  # 2 - 1

    def test_remove_region_count_clamps_at_zero(self):
        ds = _make_dataset()
        a1 = str(Path("root/cat_a/images/a1.png"))
        # Provide a regions count bigger than total_annotations — the
        # subtraction must floor at 0, not go negative.
        ds.remove_images({a1}, regions_by_path={a1: 99})
        assert ds.total_annotations == 0

    def test_remove_from_multiple_categories(self):
        ds = _make_dataset()
        paths = {
            str(Path("root/cat_a/images/a1.png")),
            str(Path("root/cat_b/images/b1.png")),
        }
        removed = ds.remove_images(paths)
        assert removed == 2
        assert ds.total_images == 1
        assert ds.categories[1].image_count == 0

    def test_remove_nonexistent_paths(self):
        ds = _make_dataset()
        removed = ds.remove_images({"nonexistent.png"})
        assert removed == 0
        assert ds.total_images == 3

    def test_category_by_name_works_after_remove(self):
        ds = _make_dataset()
        ds.remove_images({str(Path("root/cat_a/images/a1.png"))})
        cat = ds.category_by_name("cat_a")
        assert cat is not None
        assert cat.image_count == 1

    def test_remove_all_from_category(self):
        ds = _make_dataset()
        paths = {
            str(Path("root/cat_a/images/a1.png")),
            str(Path("root/cat_a/images/a2.png")),
        }
        removed = ds.remove_images(paths)
        assert removed == 2
        assert ds.categories[0].image_count == 0
        assert ds.total_images == 1
