"""Inbox — staged import area for incremental dataset building.

Images land in ``<root>/_inbox/<batch_id>/images/`` first, then get
"committed" into the real dataset layout after the user confirms
classification rules. This keeps the formal dataset directory clean
until the user is ready.

Pure Python — no PyQt.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable

from .config import image_extensions
from .workflow import IngestBatch, WorkItem, WorkStatus, _now_iso, make_id

INBOX_DIR = "_inbox"


def inbox_path(root: Path) -> Path:
    return root / INBOX_DIR


def create_batch(
    root: Path,
    source_dirs: list[Path],
    name: str = "",
    *,
    recursive: bool = True,
    progress_cb: Callable[[int, int, str], None] | None = None,
) -> tuple[IngestBatch, list[WorkItem]]:
    """Import images from *source_dirs* into ``_inbox/<batch_id>/images/``.

    Returns the IngestBatch descriptor + one WorkItem per copied file.
    Caller is responsible for persisting via workflow_store.add_batch().
    """
    batch_id = make_id()
    batch_dir = inbox_path(root) / batch_id / "images"
    batch_dir.mkdir(parents=True, exist_ok=True)

    exts = image_extensions()
    sources: list[Path] = []
    for d in source_dirs:
        d = Path(d)
        if not d.is_dir():
            continue
        walker = d.rglob("*") if recursive else d.iterdir()
        for p in walker:
            if p.is_file() and p.suffix.lower() in exts:
                sources.append(p)
    sources.sort(key=lambda p: p.name.lower())

    total = len(sources)
    items: list[WorkItem] = []
    now = _now_iso()
    seen: set[str] = set()

    for i, src in enumerate(sources):
        if progress_cb:
            progress_cb(i, total, src.name)
        dst = batch_dir / src.name
        # dedupe within batch
        if dst.name.lower() in seen:
            dst = _unique(dst)
        seen.add(dst.name.lower())
        try:
            shutil.copy2(str(src), str(dst))
        except OSError:
            continue
        rel = str(dst.relative_to(root)).replace("\\", "/")
        items.append(WorkItem(
            item_id=make_id(),
            relative_path=rel,
            batch_id=batch_id,
            status=WorkStatus.NEW,
            updated_at=now,
        ))

    if progress_cb:
        progress_cb(total, total, "")

    batch = IngestBatch(
        batch_id=batch_id,
        name=name or f"批次 {batch_id[:6]}",
        created_at=now,
        source_dirs=[str(d) for d in source_dirs],
        item_count=len(items),
    )
    return batch, items


def commit_items(
    root: Path,
    items: list[WorkItem],
    category: str,
    *,
    progress_cb: Callable[[int, int, str], None] | None = None,
) -> list[WorkItem]:
    """Move items from _inbox into ``<root>/<category>/images/``.

    Updates each item's ``relative_path`` and ``category_hint`` in place.
    Returns the list of successfully committed items.
    """
    target = root / category / "images"
    target.mkdir(parents=True, exist_ok=True)
    (root / category / "labels").mkdir(parents=True, exist_ok=True)

    committed: list[WorkItem] = []
    total = len(items)
    now = _now_iso()

    for i, item in enumerate(items):
        if progress_cb:
            progress_cb(i, total, Path(item.relative_path).name)
        src = root / item.relative_path
        if not src.is_file():
            continue
        dst = target / src.name
        if dst.exists():
            dst = _unique(dst)
        try:
            shutil.move(str(src), str(dst))
        except OSError:
            continue
        item.relative_path = str(dst.relative_to(root)).replace("\\", "/")
        item.category_hint = category
        item.status = WorkStatus.ANNOTATING
        item.updated_at = now
        committed.append(item)

    if progress_cb:
        progress_cb(total, total, "")
    return committed


def batch_status_counts(
    state: "WorkflowState",
    batch_id: str,
) -> dict[str, int]:
    """Count items per WorkStatus for a single batch.

    Returns e.g. ``{"new": 12, "ready": 3, "annotating": 5}``.
    Only keys with count > 0 are included.
    """
    counts: dict[str, int] = {}
    for item in state.items:
        if item.batch_id == batch_id:
            key = item.status.value
            counts[key] = counts.get(key, 0) + 1
    return counts


def all_batch_summaries(
    state: "WorkflowState",
) -> list[dict]:
    """Return a list of per-batch summary dicts for UI display.

    Each dict contains the IngestBatch fields plus a ``status_counts``
    breakdown and an ``inbox_count`` (items still in _inbox).
    """
    # Pre-compute per-batch item counts by status
    batch_items: dict[str, dict[str, int]] = {}
    batch_inbox: dict[str, int] = {}
    for item in state.items:
        bid = item.batch_id
        if not bid:
            continue
        if bid not in batch_items:
            batch_items[bid] = {}
            batch_inbox[bid] = 0
        key = item.status.value
        batch_items[bid][key] = batch_items[bid].get(key, 0) + 1
        if "_inbox/" in item.relative_path:
            batch_inbox[bid] += 1

    result = []
    for batch in state.batches:
        result.append({
            "batch_id": batch.batch_id,
            "name": batch.name,
            "created_at": batch.created_at,
            "source_dirs": batch.source_dirs,
            "item_count": batch.item_count,
            "status_counts": batch_items.get(batch.batch_id, {}),
            "inbox_count": batch_inbox.get(batch.batch_id, 0),
        })
    return result


def _unique(path: Path) -> Path:
    i = 1
    while True:
        cand = path.with_name(f"{path.stem}_{i}{path.suffix}")
        if not cand.exists():
            return cand
        i += 1
