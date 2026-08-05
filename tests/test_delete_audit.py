"""Permanent deletes must leave a record of what they destroyed.

Deleting unlinks files — no recycle bin, no undo. The history entry is
the only thing that survives, so it has to carry the actual paths and it
has to be written even when the op partly failed. Moving files was
already audited; destroying them was not.

Covers the core contract (history round-trip with the delete actions) and
the shape the GUI writes, without driving the batch workers.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import history as _hist
from core.history import HistoryEntry, append, find_last_undoable, read_recent

DELETE_ACTIONS = ["delete-images", "delete-issue-images", "delete-duplicates"]


def _entry(action: str, paths: list[str], failed: int = 0) -> HistoryEntry:
    return HistoryEntry.now(
        action=action,
        params={
            "deleted_count": len(paths),
            "failed_count": failed,
            "deleted_paths": paths,
        },
        ok=failed == 0,
        summary=f"永久删除 {len(paths)} 张图片",
    )


@pytest.mark.parametrize("action", DELETE_ACTIONS)
def test_deleted_paths_survive_a_roundtrip(tmp_path, action):
    paths = [f"C:/ds/cat/images/img_{i}.png" for i in range(3)]
    append(tmp_path, _entry(action, paths))
    back = read_recent(tmp_path, limit=10)
    assert len(back) == 1
    assert back[0].action == action
    assert back[0].params["deleted_paths"] == paths


@pytest.mark.parametrize("action", DELETE_ACTIONS)
def test_a_delete_is_never_offered_for_undo(tmp_path, action):
    """The files are gone; offering 撤销 would be a lie."""
    append(tmp_path, _entry(action, ["C:/ds/a.png"]))
    assert find_last_undoable(tmp_path) is None


def test_undo_still_finds_a_move_recorded_before_a_delete(tmp_path):
    """Adding delete records must not shadow the real undoable op."""
    append(tmp_path, HistoryEntry.now(
        action="move-to-category",
        params={"target": "b", "original_categories": {"C:/ds/a.png": "a"}},
        ok=True, summary="移动 1 张到 b", undoable=True,
    ))
    append(tmp_path, _entry("delete-images", ["C:/ds/z.png"]))
    found = find_last_undoable(tmp_path)
    assert found is not None
    assert found.action == "move-to-category"


def test_partial_failure_is_still_recorded(tmp_path):
    """A half-failed delete is exactly when the record matters most."""
    append(tmp_path, _entry("delete-images", ["C:/ds/a.png"], failed=2))
    e = read_recent(tmp_path, limit=1)[0]
    assert e.ok is False
    assert e.params["failed_count"] == 2
    assert e.params["deleted_paths"] == ["C:/ds/a.png"]


def test_record_is_plain_json_lines(tmp_path):
    """Readable without the app — the point of an audit trail."""
    append(tmp_path, _entry("delete-images", ["C:/ds/a.png"]))
    line = (tmp_path / ".dataforge" / "history.jsonl").read_text(
        encoding="utf-8").strip()
    obj = json.loads(line)
    assert obj["action"] == "delete-images"
    assert obj["params"]["deleted_paths"] == ["C:/ds/a.png"]


def test_non_ascii_paths_are_not_escaped(tmp_path):
    """Chinese dataset paths must stay readable in the log."""
    append(tmp_path, _entry("delete-images", ["C:/数据集/图片/一.png"]))
    raw = (tmp_path / ".dataforge" / "history.jsonl").read_text(
        encoding="utf-8")
    assert "数据集" in raw


def test_recorder_logs_the_outcome_not_the_request(qapp, tmp_path):
    """params are built before the op runs, so a path list written then
    is only what was *asked for*. The recorder must overwrite it with
    what actually succeeded, or the log names files that still exist.

    Takes the session-scoped ``qapp`` fixture rather than building a
    QApplication here — a per-test one gets collected and takes
    qfluentwidgets' global qconfig down with it (see conftest).
    """
    from core.models import Dataset
    from gui.app_state import AppState
    from gui.views.browser_view import BrowserView

    state = AppState()
    state.set_dataset(Dataset(name="ds", root_path=tmp_path, categories=[],
                              total_images=0, total_annotations=0,
                              layout="standard"))
    view = BrowserView(state)
    view._pending_history = {
        "action": "delete-images",
        "params": {"requested_count": 3, "labeled_count": 0},
        "summary": "永久删除 3 张图片",
    }
    # Asked for three, only two went.
    gone = [Path("C:/ds/a.png"), Path("C:/ds/b.png")]
    view._record_history(ok=False, ok_count=2, fail_count=1, succeeded=gone)
    entry = read_recent(tmp_path, limit=1)[0]
    assert entry.params["requested_count"] == 3
    # str(Path(...)) so the comparison holds on either separator style.
    assert entry.params["deleted_paths"] == [str(p) for p in gone]
    assert entry.undoable is False


def test_history_dialog_labels_every_delete_action():
    """Otherwise the history list shows a raw kebab-case slug."""
    from gui.dialogs.history_dialog import _ACTION_LABELS
    for action in DELETE_ACTIONS:
        assert action in _ACTION_LABELS
        assert "删除" in _ACTION_LABELS[action]


def test_append_failure_does_not_raise(tmp_path, monkeypatch):
    """The delete already happened; a lost log line must not blow up."""
    def boom(*_a, **_k):
        raise OSError("disk full")
    monkeypatch.setattr(_hist.Path, "open", boom, raising=False)
    append(tmp_path, _entry("delete-images", ["C:/ds/a.png"]))
