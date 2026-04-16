"""Tests for core/splitter.py — split ratios, stratification, edge cases."""
from __future__ import annotations

import pytest

from core.models import Category, Dataset, ImageInfo
from core.splitter import SplitMode, SplitOptions, SplitResult, split_dataset
from pathlib import Path


def _dataset(cats: dict[str, int]) -> Dataset:
    """Create a Dataset with given category→image_count mapping."""
    categories = []
    for name, n in cats.items():
        imgs = [ImageInfo(path=Path(f"{name}/{i}.jpg"), category=name)
                for i in range(n)]
        categories.append(Category(name=name, image_count=n, images=imgs))
    total = sum(cats.values())
    return Dataset(name="test", root_path=Path("."), categories=categories,
                   total_images=total)


class TestSplitRatio:
    def test_basic_ratio(self):
        ds = _dataset({"cat": 100})
        result = split_dataset(ds, SplitOptions(train=0.8, val=0.1, test=0.1))
        total = len(result.train) + len(result.val) + len(result.test)
        assert total == 100
        assert len(result.train) == 80
        assert len(result.val) == 10
        assert len(result.test) == 10

    def test_all_train(self):
        ds = _dataset({"cat": 50})
        result = split_dataset(ds, SplitOptions(train=1.0, val=0.0, test=0.0))
        assert len(result.train) == 50
        assert len(result.val) == 0
        assert len(result.test) == 0

    def test_single_image(self):
        ds = _dataset({"cat": 1})
        result = split_dataset(ds, SplitOptions(train=0.8, val=0.1, test=0.1))
        total = len(result.train) + len(result.val) + len(result.test)
        assert total == 1


class TestStratified:
    def test_stratified_preserves_proportions(self):
        ds = _dataset({"dog": 80, "cat": 20})
        result = split_dataset(ds, SplitOptions(
            train=0.8, val=0.1, test=0.1, stratified=True))
        # Train should have ~64 dog, ~16 cat
        train_cats = {}
        for img in result.train:
            train_cats[img.category] = train_cats.get(img.category, 0) + 1
        assert "dog" in train_cats
        assert "cat" in train_cats
        # Allow ±2 for rounding
        assert abs(train_cats["dog"] - 64) <= 2
        assert abs(train_cats["cat"] - 16) <= 2

    def test_empty_dataset(self):
        ds = _dataset({})
        result = split_dataset(ds)
        assert len(result.train) == 0
        assert len(result.val) == 0
        assert len(result.test) == 0


class TestSplitResult:
    def test_counts_property(self):
        sr = SplitResult(train=[1, 2, 3], val=[4], test=[5, 6])
        assert sr.counts == (3, 1, 2)


class TestSplitMode:
    """Enum round-tripping + legacy string compatibility."""

    def test_enum_equivalent_to_string(self):
        """Old SplitOptions(mode='ratio') should behave identical to new
        SplitOptions(mode=SplitMode.RATIO)."""
        ds = _dataset({"cat": 100})
        r_str = split_dataset(ds, SplitOptions(mode="ratio", train=0.8,
                                               val=0.1, test=0.1))
        r_enum = split_dataset(ds, SplitOptions(mode=SplitMode.RATIO, train=0.8,
                                                val=0.1, test=0.1))
        assert r_str.counts == r_enum.counts

    def test_manual_returns_empty(self):
        """Manual mode: splitter defers to caller, returns empty result."""
        ds = _dataset({"cat": 50})
        result = split_dataset(ds, SplitOptions(mode=SplitMode.MANUAL))
        assert result.counts == (0, 0, 0)

    def test_enum_values(self):
        assert SplitMode.RATIO.value == "ratio"
        assert SplitMode.COUNT.value == "count"
        assert SplitMode.MANUAL.value == "manual"
