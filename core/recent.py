"""Recent dataset list. JSON file under ~/.dataforge/recent.json."""
from __future__ import annotations

import json
from pathlib import Path

RECENT_PATH = Path.home() / ".dataforge" / "recent.json"
MAX_RECENT = 10


def load_recent() -> list[str]:
    try:
        data = json.loads(RECENT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [str(p) for p in data if isinstance(p, str)]


def add_recent(path: Path) -> list[str]:
    items = load_recent()
    s = str(path)
    items = [x for x in items if x != s]
    items.insert(0, s)
    items = items[:MAX_RECENT]
    try:
        RECENT_PATH.parent.mkdir(parents=True, exist_ok=True)
        RECENT_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
    return items


def clear_recent() -> None:
    try:
        RECENT_PATH.unlink()
    except OSError:
        pass


def relocate(old_path: str, new_path: str) -> list[str]:
    """Replace ``old_path`` with ``new_path`` in the recent list.

    Review #17: users who external-renamed the dataset root (or had a NAS
    disconnect and come back with a different mount point) can now point
    the entry at the real location instead of losing it.

    Preserves the entry's position in the list. If ``new_path`` already
    appeared elsewhere, removes the duplicate so the relocated entry wins.
    """
    items = load_recent()
    if old_path not in items:
        return items
    old_idx = items.index(old_path)
    items = [p for p in items if p != old_path and p != new_path]
    items.insert(old_idx, new_path)
    items = items[:MAX_RECENT]
    try:
        RECENT_PATH.parent.mkdir(parents=True, exist_ok=True)
        RECENT_PATH.write_text(
            json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
    return items
