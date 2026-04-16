"""Tests for core/history.py — append/read round-trip + tolerance."""
from __future__ import annotations

import json
from pathlib import Path

from core.history import (
    HistoryEntry,
    MAX_ENTRIES,
    _history_path,
    append,
    clear,
    read_recent,
)


class TestAppendRead:
    def test_round_trip(self, tmp_path):
        e = HistoryEntry.now(
            action="rename-category",
            params={"old": "A", "new": "B"},
            summary="重命名 A → B",
        )
        append(tmp_path, e)
        got = read_recent(tmp_path)
        assert len(got) == 1
        assert got[0].action == "rename-category"
        assert got[0].params == {"old": "A", "new": "B"}
        assert got[0].summary == "重命名 A → B"
        assert got[0].ok is True

    def test_read_order_newest_first(self, tmp_path):
        for i in range(3):
            append(tmp_path, HistoryEntry.now(
                action=f"op-{i}", params={}, summary=str(i)))
        got = read_recent(tmp_path)
        assert [e.summary for e in got] == ["2", "1", "0"]

    def test_empty_before_any_write(self, tmp_path):
        assert read_recent(tmp_path) == []

    def test_limit_applied_at_read(self, tmp_path):
        for i in range(10):
            append(tmp_path, HistoryEntry.now(
                action="op", params={}, summary=str(i)))
        got = read_recent(tmp_path, limit=3)
        assert len(got) == 3
        assert [e.summary for e in got] == ["9", "8", "7"]


class TestRobustness:
    def test_malformed_lines_skipped(self, tmp_path):
        """A corrupted line must not kill reading of good lines."""
        path = _history_path(tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        good = json.dumps({
            "timestamp": "2026-04-16T00:00:00+00:00",
            "action": "move-to-category",
            "params": {"to": "X"},
            "ok": True,
            "summary": "移动 3 张",
        }, ensure_ascii=False)
        path.write_text(good + "\n{not json}\n" + good + "\n", encoding="utf-8")
        entries = read_recent(tmp_path)
        # Two valid, one skipped
        assert len(entries) == 2
        assert all(e.action == "move-to-category" for e in entries)

    def test_unicode_params(self, tmp_path):
        append(tmp_path, HistoryEntry.now(
            action="rename-category",
            params={"old": "猫猫", "new": "犬🐕"},
            summary="重命名 猫猫 → 犬🐕",
        ))
        got = read_recent(tmp_path)[0]
        assert got.params["old"] == "猫猫"
        assert got.params["new"] == "犬🐕"

    def test_clear_removes_file(self, tmp_path):
        append(tmp_path, HistoryEntry.now(action="op", params={}, summary="x"))
        assert _history_path(tmp_path).exists()
        clear(tmp_path)
        assert not _history_path(tmp_path).exists()
        # No error clearing twice
        clear(tmp_path)

    def test_failed_op_logged(self, tmp_path):
        """ok=False still appends — record of attempts matters."""
        append(tmp_path, HistoryEntry.now(
            action="merge-categories", params={},
            ok=False, summary="失败：目标类别被占用"))
        got = read_recent(tmp_path)[0]
        assert got.ok is False
        assert "失败" in got.summary
