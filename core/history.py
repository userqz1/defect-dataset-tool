"""Append-only operation history for a dataset project.

Every metadata-changing operation (rename/merge/split category, batch
rename, move-to-category, delete-duplicates) appends one JSON line to
``<root>/.dataforge/history.jsonl``. Each entry captures *enough* before-
and-after state that a future Undo phase can roll forward from here.

This module intentionally does NOT implement undo — reviewer's note was
"不需要一上来做完整 undo,但至少应该给 ... 这类'元数据'操作留一个
history.json,记录每次改动的前后快照。" That is what this does.

Pure Python — no PyQt. Reads are cheap (small file, line-by-line)
because writes are append-only and a cap of MAX_ENTRIES trims the head.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROJECT_DIR = ".dataforge"
HISTORY_FILE = "history.jsonl"
MAX_ENTRIES = 500


@dataclass
class HistoryEntry:
    """One logged operation.

    ``action`` is a short kebab-case id (rename-category, merge-categories,
    split-category, move-to-category, batch-rename, delete-duplicates).
    ``params`` carries the inputs the caller would need to replay the op;
    ``summary`` is the one-line Chinese description shown in the UI.
    """
    timestamp: str
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    ok: bool = True
    summary: str = ""

    @classmethod
    def now(cls, action: str, params: dict[str, Any],
            ok: bool = True, summary: str = "") -> "HistoryEntry":
        return cls(
            timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            action=action,
            params=params,
            ok=ok,
            summary=summary,
        )


def _history_path(root: Path) -> Path:
    return Path(root) / PROJECT_DIR / HISTORY_FILE


def append(root: Path, entry: HistoryEntry) -> None:
    """Append *entry* to the project's history file.

    Failures here are non-fatal — the actual dataset op already happened;
    losing a log line must never roll that back. Errors are logged.
    """
    path = _history_path(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("history append failed at %s", path)
        return

    # Opportunistic trim: if the file gets huge, keep only the tail
    try:
        size = path.stat().st_size
    except OSError:
        return
    if size > 512_000:  # ~500 KB is a lot of lines
        _trim(path, MAX_ENTRIES)


def _trim(path: Path, keep: int) -> None:
    """Rewrite the file keeping only the last *keep* lines."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) <= keep:
            return
        tail = lines[-keep:]
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text("\n".join(tail) + "\n", encoding="utf-8")
        tmp.replace(path)
    except OSError:
        logger.exception("history trim failed at %s", path)


def read_recent(root: Path, limit: int = 100) -> list[HistoryEntry]:
    """Return the most recent *limit* entries, newest first.

    Tolerant of malformed lines — they're skipped with a log warning so
    a single bad line can't render the whole history unreadable.
    """
    path = _history_path(root)
    if not path.is_file():
        return []
    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        logger.exception("history read failed at %s", path)
        return []

    entries: list[HistoryEntry] = []
    for line in raw_lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("skipping malformed history line in %s", path)
            continue
        entries.append(HistoryEntry(
            timestamp=str(obj.get("timestamp", "")),
            action=str(obj.get("action", "unknown")),
            params=obj.get("params") or {},
            ok=bool(obj.get("ok", True)),
            summary=str(obj.get("summary", "")),
        ))
    entries.reverse()  # newest first
    return entries


def clear(root: Path) -> None:
    """Remove the history file. Used by settings/maintenance UI."""
    path = _history_path(root)
    try:
        if path.exists():
            path.unlink()
    except OSError:
        logger.exception("history clear failed at %s", path)
