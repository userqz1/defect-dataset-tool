"""Remember where the user left off in each dataset.

Annotation is a long job spread over many sittings. Reopening a dataset
and having to recall "I got to somewhere around the two hundredth image"
is a real cost, and scrolling to find the first unlabelled one is not the
same thing — people stop mid-run for all sorts of reasons.

Stored **by image path, never by index**. Between sessions images get
added, deleted, renamed and re-sorted; an index would then designate a
different image, and silently resuming at the wrong place is worse than
not resuming at all. A path that no longer exists simply means "no
position", which the caller can handle honestly.

Keyed by dataset root, so several datasets keep independent positions.
Lives in ``~/.dataforge/last_position.json`` next to the other app state.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

POSITIONS_PATH = Path.home() / ".dataforge" / "last_position.json"

# Keep the file small and bounded. Datasets are opened, finished and
# abandoned; without a cap this grows forever with entries nobody will
# ever resume. Oldest-first eviction, so the datasets in active rotation
# survive.
MAX_ENTRIES = 50


@dataclass(frozen=True)
class LastPosition:
    """Where a dataset was left, as recorded at ``saved_at``."""

    image: Path
    saved_at: str = ""


def _key(root: Path) -> str:
    """Normalised map key for a dataset root.

    ``resolve()`` so ``D:\\data`` and ``D:/data/.`` are one entry, and
    casefold because Windows paths are case-insensitive — two entries for
    the same dataset would each hold half the history.
    """
    try:
        return str(root.resolve()).casefold()
    except OSError:
        return str(root).casefold()


def _load_raw() -> dict:
    try:
        raw = json.loads(POSITIONS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _write_raw(data: dict) -> None:
    try:
        POSITIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        POSITIONS_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        # Losing a resume marker must never take the annotation session
        # with it — a read-only home dir or a full disk is annoying, not
        # fatal. The caller carries on at whatever image it is showing.
        pass


def remember(root: Path, image: Path, *, now: datetime | None = None) -> None:
    """Record *image* as the last place visited in *root*."""
    data = _load_raw()
    stamp = (now or datetime.now()).isoformat(timespec="seconds")
    data[_key(root)] = {"image": str(image), "at": stamp}
    if len(data) > MAX_ENTRIES:
        # Entries without a timestamp sort first and get evicted first;
        # they are pre-timestamp leftovers with nothing to lose.
        ordered = sorted(
            data.items(),
            key=lambda kv: (kv[1] or {}).get("at", "") if isinstance(kv[1], dict) else "",
        )
        data = dict(ordered[-MAX_ENTRIES:])
    _write_raw(data)


def recall(root: Path) -> LastPosition | None:
    """The last image visited in *root*, or None.

    Returns None when the recorded image no longer exists on disk: a
    resume entry pointing at a deleted file would either dead-end or,
    worse, be "fixed up" to a neighbouring image the user never asked
    for.
    """
    entry = _load_raw().get(_key(root))
    if not isinstance(entry, dict):
        return None
    raw_image = entry.get("image")
    if not isinstance(raw_image, str) or not raw_image:
        return None
    image = Path(raw_image)
    try:
        if not image.is_file():
            return None
    except OSError:
        return None
    at = entry.get("at")
    return LastPosition(image=image, saved_at=at if isinstance(at, str) else "")


def forget(root: Path) -> None:
    """Drop the stored position for *root* (no-op when there isn't one)."""
    data = _load_raw()
    if data.pop(_key(root), None) is not None:
        _write_raw(data)
