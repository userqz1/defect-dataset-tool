"""Append-only audit log for dataset metadata operations.

Every metadata-changing operation (rename/merge/split category, batch
rename, move-to-category, delete-duplicates) appends one JSON line to
``<root>/.dataforge/history.jsonl``. This is an **audit log**, not an
undo primitive — review point #6:

- Entries capture the operation's declared parameters, not full
  file-system snapshots. ``move-to-category`` records source paths at
  call time, which may no longer exist by the time you'd try to undo.
- ``delete-duplicates`` records permanently deleted paths as plain strings;
  deleted files cannot be reconstructed from the audit log.
- ``rename-category`` only records old/new names; a reverse play relies
  on filesystem state being identical to when it ran.

Use this for debugging / audit / diff viewing, not for programmatic undo.
If undo becomes necessary, we'd design a proper BeforeState/AfterState
model rather than extending this.

Pure Python — no PyQt. Reads are cheap (small file, line-by-line)
because writes are append-only and a cap of MAX_ENTRIES trims the head.
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_HISTORY_LOCK = threading.Lock()

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
    ``undoable`` flags whether ``try_undo_last`` knows how to reverse this
    entry — today only ``move-to-category`` and ``rename-category``. Ops
    that permanently delete files (delete-duplicates) or lose source→target
    grouping (merge-categories) stay ``False`` until a proper snapshot
    model exists.
    """
    timestamp: str
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    ok: bool = True
    summary: str = ""
    undoable: bool = False

    @classmethod
    def now(cls, action: str, params: dict[str, Any],
            ok: bool = True, summary: str = "",
            undoable: bool = False) -> "HistoryEntry":
        return cls(
            timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            action=action,
            params=params,
            ok=ok,
            summary=summary,
            undoable=undoable,
        )


def _history_path(root: Path) -> Path:
    return Path(root) / PROJECT_DIR / HISTORY_FILE


def append(root: Path, entry: HistoryEntry) -> None:
    """Append *entry* to the project's history file.

    Failures here are non-fatal — the actual dataset op already happened;
    losing a log line must never roll that back. Errors are logged.
    """
    path = _history_path(root)
    with _HISTORY_LOCK:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
        except OSError:
            logger.exception("history append failed at %s", path)
            return

        try:
            size = path.stat().st_size
        except OSError:
            return
        if size > 512_000:
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
            undoable=bool(obj.get("undoable", False)),
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


# ---------- Undo MVP (single-step, reversible ops only) ----------
#
# This is intentionally NOT a full undo stack. It finds the most recent
# ``undoable=True`` entry and tries to reverse just that one op. If the
# user has moved on to other ops since, those other ops aren't rolled
# back — the undo targets the last reversible thing.
#
# Supported ops today:
#   - ``move-to-category`` — reads ``original_categories`` map (path →
#     source category) and moves each image back. Requires the caller
#     to populate that map at record time.
#   - ``rename-category`` — swaps old/new name, pure filesystem rename.
#
# Not yet supported (stay ``undoable=False``):
#   - ``delete-duplicates`` (files are permanently deleted)
#   - ``merge-categories`` (source→target grouping isn't captured)
#   - ``split-category`` (same)
# These will be added when we design a proper BeforeState snapshot model.


def find_last_undoable(root: Path) -> "HistoryEntry | None":
    """Most recent successful, undoable entry that hasn't already been undone.

    An undo writes a companion ``undo-<action>`` entry carrying the
    ``undone_timestamp`` of the entry it reversed; those reversed entries
    are skipped here so clicking 撤销 twice doesn't ping-pong.
    """
    entries = read_recent(root, limit=100)
    consumed: set[str] = set()
    for e in entries:
        if e.action.startswith("undo-"):
            ts = e.params.get("undone_timestamp")
            if ts:
                consumed.add(str(ts))
    for e in entries:
        if e.ok and e.undoable and e.timestamp not in consumed:
            return e
    return None


def try_undo_last(root: Path) -> tuple[bool, str]:
    """Reverse the last undoable op. Returns ``(ok, message)``.

    The undo itself is logged as a new entry with ``undoable=False`` so
    re-clicking the button doesn't ping-pong between op and anti-op.
    """
    entry = find_last_undoable(root)
    if entry is None:
        return False, "没有可撤销的操作"

    root = Path(root)
    if entry.action == "move-to-category":
        return _undo_move_to_category(root, entry)
    if entry.action == "rename-category":
        return _undo_rename_category(root, entry)
    return False, f"不支持撤销 {entry.action}"


def _undo_move_to_category(root: Path, entry: HistoryEntry) -> tuple[bool, str]:
    # Delayed import to keep core.history GUI-free and fileops import cheap.
    from .fileops import label_path_for_image
    import shutil

    target = entry.params.get("target", "")
    original = entry.params.get("original_categories") or {}
    # review #11: fileops.move_to_category writes a source→landed map into
    # OpResult.moves to record _ensure_unique renames. Use it when present;
    # fall back to "<target>/images/<original_filename>" only for legacy
    # history entries that predate the moves field.
    moves = entry.params.get("moves") or {}
    if not target or not original:
        return False, "撤销所需数据不完整(缺 original_categories)"

    moved_back = 0
    failed: list[tuple[str, str]] = []
    for src_str, orig_cat in original.items():
        landed_str = moves.get(src_str)
        if landed_str:
            current = Path(landed_str)
        else:
            # Legacy entries (pre-moves-field) only stored the original
            # filename. Try the literal location first; if missing, probe
            # ``foo_1.jpg / foo_2.jpg / ...`` up to _3 to cover the case
            # where move_to_category's ``_ensure_unique`` appended a suffix.
            # If none match, refuse the row rather than misidentify a
            # same-named file that happened to land there later (review #6).
            candidate = root / target / "images" / Path(src_str).name
            if candidate.exists():
                current = candidate
            else:
                current = None
                p = Path(src_str)
                for i in range(1, 4):
                    guess = (root / target / "images"
                             / f"{p.stem}_{i}{p.suffix}")
                    if guess.exists():
                        current = guess
                        break
                if current is None:
                    failed.append((src_str,
                                   "当前位置找不到文件(legacy 记录缺 moves 字段)"))
                    continue
        filename = current.name
        if not current.exists():
            failed.append((src_str, "当前位置找不到文件"))
            continue
        dst_dir = root / orig_cat / "images"
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / filename
        try:
            shutil.move(str(current), str(dst))
            # Move the label too if one exists
            label_src = label_path_for_image(current)
            if label_src and label_src.is_file():
                label_dst_dir = root / orig_cat / "labels"
                label_dst_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(label_src), str(label_dst_dir / label_src.name))
            moved_back += 1
        except (OSError, shutil.Error) as e:
            failed.append((src_str, str(e)))

    # Record the undo itself (undoable=False so we don't bounce).
    # ``undone_timestamp`` points back at the entry we reversed so
    # find_last_undoable can skip it on the next click.
    append(root, HistoryEntry.now(
        action="undo-move-to-category",
        params={
            "undone_timestamp": entry.timestamp,
            "restored": moved_back,
            "failed": len(failed),
            "original_target": target,
        },
        ok=not failed,
        summary=f"撤销: 将 {moved_back} 张图片移回原类别"
                + (f"（{len(failed)} 失败）" if failed else ""),
        undoable=False,
    ))
    if failed:
        return False, f"已恢复 {moved_back} 张,但 {len(failed)} 张失败"
    return True, f"已撤销移动,{moved_back} 张图片回到原类别"


def _undo_rename_category(root: Path, entry: HistoryEntry) -> tuple[bool, str]:
    old = entry.params.get("old")
    new = entry.params.get("new")
    if not old or not new:
        return False, "撤销所需数据不完整(缺 old/new)"

    src = root / new
    dst = root / old
    if not src.is_dir():
        return False, f"找不到类别目录 {new}"
    if dst.exists():
        return False, f"原名称 {old} 已被其他类别占用"
    try:
        src.rename(dst)
    except OSError as e:
        return False, f"重命名失败: {e}"

    append(root, HistoryEntry.now(
        action="undo-rename-category",
        params={
            "undone_timestamp": entry.timestamp,
            "restored_from": new,
            "restored_to": old,
        },
        ok=True,
        summary=f"撤销: 类别 {new} → {old}",
        undoable=False,
    ))
    return True, f"已撤销: 类别 {new} 改回 {old}"


