"""Tests for core/project.py — persistence + backward compatibility."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.project import (
    BrowseState,
    Project,
    create_project,
    load_project,
    save_project,
)
from core.task_types import TaskType


class TestRoundTrip:
    def test_save_load_round_trip(self, tmp_path):
        p = create_project(tmp_path, name="demo", task_type=TaskType.DETECTION)
        p.browse_state.filter = "labeled"
        save_project(p)
        loaded = load_project(tmp_path)
        assert loaded is not None
        assert loaded.name == "demo"
        assert loaded.task_type is TaskType.DETECTION
        assert loaded.browse_state.filter == "labeled"

    def test_missing_returns_none(self, tmp_path):
        assert load_project(tmp_path) is None

    def test_malformed_json_returns_none(self, tmp_path):
        pdir = tmp_path / ".dataforge"
        pdir.mkdir()
        (pdir / "project.json").write_text("{not json", encoding="utf-8")
        assert load_project(tmp_path) is None

    def test_bom_project_json_normalizes_class_names(self, tmp_path):
        pdir = tmp_path / ".dataforge"
        pdir.mkdir()
        payload = {
            "name": "demo",
            "task_type": "object_detection",
            "class_names": ["\ufefffastener_core\n", "fastener_core"],
            "browse_state": {},
            "split_state": {},
            "export_config": {},
            "review_progress": {},
        }
        (pdir / "project.json").write_text(
            "\ufeff" + json.dumps(payload), encoding="utf-8")

        loaded = load_project(tmp_path)

        assert loaded is not None
        assert loaded.class_names == ["fastener_core"]


class TestBackwardCompat:
    """Reviewer's note: ``data_standard`` was a never-used placeholder.
    Removing it must not break loading old project.json files that
    still carry the key."""

    def test_legacy_data_standard_field_ignored(self, tmp_path):
        pdir = tmp_path / ".dataforge"
        pdir.mkdir()
        legacy_payload = {
            "name": "legacy",
            "task_type": "object_detection",
            "target_format": "",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "notes": "",
            "browse_state": {"category": "", "filter": "all", "search": "", "page": 0},
            "split_state": {"mode": "ratio", "train": 0.8, "val": 0.1, "test": 0.1,
                           "stratified": True, "manual_train": [], "manual_val": [],
                           "manual_test": []},
            "export_config": {"format": "YOLO", "copy_images": True},
            "review_progress": {"reviewed": [], "flagged": []},
            # The legacy key — may be present in older project.json files
            "data_standard": None,
        }
        (pdir / "project.json").write_text(
            json.dumps(legacy_payload), encoding="utf-8")
        loaded = load_project(tmp_path)
        assert loaded is not None
        assert loaded.name == "legacy"
        # Field must not exist on the new dataclass (reviewer wanted it gone)
        assert not hasattr(loaded, "data_standard")

    def test_legacy_with_dict_data_standard(self, tmp_path):
        """Some early projects stored an actual dict in data_standard.
        Loading must still succeed — the dict is silently dropped."""
        pdir = tmp_path / ".dataforge"
        pdir.mkdir()
        payload = {
            "name": "x",
            "task_type": "object_detection",
            "browse_state": {},
            "split_state": {},
            "export_config": {},
            "review_progress": {},
            "data_standard": {"categories": ["a", "b"], "notes": "甲方规范"},
        }
        (pdir / "project.json").write_text(
            json.dumps(payload), encoding="utf-8")
        loaded = load_project(tmp_path)
        assert loaded is not None
        assert not hasattr(loaded, "data_standard")

    def test_save_does_not_write_data_standard(self, tmp_path):
        """After removing the field, the on-disk JSON must not carry it
        back — otherwise old loaders would see stale data."""
        p = create_project(tmp_path, name="x", task_type=TaskType.DETECTION)
        save_project(p)
        raw = json.loads((tmp_path / ".dataforge" / "project.json")
                         .read_text(encoding="utf-8"))
        assert "data_standard" not in raw
