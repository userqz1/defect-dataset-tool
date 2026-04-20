"""Classification rule tests — cover the 4 built-in rules in core.ingest.rules.

Each rule's ``classify(paths)`` returns a list of ClassificationResult
preserving input order. Tests assert per-rule bucket assignment for
representative filename / directory / EXIF patterns.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from core.api import (
    ByExifDateRule,
    ByFilenamePrefixRule,
    BySubdirRule,
    ManualRule,
    INGEST_RULES,
    discover,
    preview,
)


# ---------- Registry ----------

class TestRegistry:
    def test_four_rules_registered(self):
        assert set(INGEST_RULES.keys()) == {
            "by_filename_prefix", "by_subdir", "by_exif_date", "manual",
        }

    def test_rule_names_match_registry_keys(self):
        for key, rule in INGEST_RULES.items():
            assert rule.name == key


# ---------- by_filename_prefix ----------

class TestByFilenamePrefix:
    def test_underscore_separator(self):
        rule = ByFilenamePrefixRule()
        paths = [Path("crack_001.jpg"), Path("crack_002.jpg"),
                 Path("good_001.png")]
        results = rule.classify(paths)
        assert [r.suggested_category for r in results] == ["crack", "crack", "good"]

    def test_dash_separator(self):
        rule = ByFilenamePrefixRule()
        paths = [Path("defect-a.jpg"), Path("defect-b.jpg")]
        results = rule.classify(paths)
        assert all(r.suggested_category == "defect" for r in results)

    def test_no_separator_falls_back_to_uncategorized(self):
        rule = ByFilenamePrefixRule()
        paths = [Path("loose.jpg"), Path("another.png")]
        results = rule.classify(paths)
        assert all(r.suggested_category == "未分类" for r in results)

    def test_leading_separator_falls_back(self):
        rule = ByFilenamePrefixRule()
        # "_crack_001" — separator at position 0, no prefix before it
        results = rule.classify([Path("_crack_001.jpg")])
        assert results[0].suggested_category == "未分类"

    def test_rule_name_propagates(self):
        rule = ByFilenamePrefixRule()
        results = rule.classify([Path("x_y.jpg")])
        assert results[0].rule_name == "by_filename_prefix"


# ---------- by_subdir ----------

class TestBySubdir:
    def test_uses_parent_dir_name(self):
        rule = BySubdirRule()
        paths = [Path("data/scratch/001.jpg"),
                 Path("data/oilleak/002.jpg"),
                 Path("data/scratch/003.jpg")]
        results = rule.classify(paths)
        assert [r.suggested_category for r in results] == ["scratch", "oilleak", "scratch"]

    def test_root_level_fallback(self, tmp_path):
        """Images directly in source_root should get '未分类'."""
        (tmp_path / "a.jpg").write_bytes(b"")
        rule = BySubdirRule(source_root=tmp_path)
        results = rule.classify([tmp_path / "a.jpg"])
        assert results[0].suggested_category == "未分类"


# ---------- by_exif_date ----------

class TestByExifDate:
    def test_no_exif_falls_back(self, tmp_path):
        # Vanilla PNG has no EXIF
        p = tmp_path / "no_exif.png"
        Image.new("RGB", (10, 10)).save(p)
        rule = ByExifDateRule()
        results = rule.classify([p])
        assert results[0].suggested_category == "未分类"

    def test_unreadable_file_falls_back(self, tmp_path):
        p = tmp_path / "garbage.jpg"
        p.write_bytes(b"not an image")
        rule = ByExifDateRule()
        results = rule.classify([p])
        assert results[0].suggested_category == "未分类"


# ---------- manual ----------

class TestManual:
    def test_everything_goes_to_single_bucket(self):
        rule = ManualRule()
        paths = [Path(f"img_{i}.jpg") for i in range(5)]
        results = rule.classify(paths)
        assert all(r.suggested_category == "未分类" for r in results)

    def test_custom_default_category(self):
        rule = ManualRule(default_category="pending")
        results = rule.classify([Path("x.jpg")])
        assert results[0].suggested_category == "pending"


# ---------- Integration: discover + preview ----------

class TestDiscoverPreview:
    def test_discover_skips_non_image_extensions(self, tmp_path):
        (tmp_path / "a.jpg").write_bytes(b"")
        (tmp_path / "b.png").write_bytes(b"")
        (tmp_path / "readme.txt").write_text("hi")
        (tmp_path / "metadata.json").write_text("{}")
        found = discover([tmp_path])
        stems = {p.stem for p in found}
        assert stems == {"a", "b"}

    def test_discover_recurses_by_default(self, tmp_path):
        sub = tmp_path / "sub" / "deep"
        sub.mkdir(parents=True)
        (sub / "deep.jpg").write_bytes(b"")
        (tmp_path / "top.jpg").write_bytes(b"")
        found = discover([tmp_path])
        assert len(found) == 2

    def test_discover_non_recursive_only_toplevel(self, tmp_path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "inner.jpg").write_bytes(b"")
        (tmp_path / "top.jpg").write_bytes(b"")
        found = discover([tmp_path], recursive=False)
        assert len(found) == 1
        assert found[0].name == "top.jpg"

    def test_preview_groups_by_category(self):
        paths = [Path("crack_001.jpg"), Path("crack_002.jpg"),
                 Path("good_001.png")]
        pv = preview(paths, INGEST_RULES["by_filename_prefix"])
        assert pv.total_images == 3
        assert pv.category_count == 2
        assert pv.placed_count == 3
        assert set(pv.categories.keys()) == {"crack", "good"}
        assert len(pv.categories["crack"]) == 2
        assert len(pv.categories["good"]) == 1
