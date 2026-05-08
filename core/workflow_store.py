"""Workflow store — read/write .dataforge/workflow.json.

JSON-based for now; interface is narrow enough to swap to SQLite later
without touching callers.

Pure Python — no PyQt.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from .project import PROJECT_DIR
from .workflow import (
    IngestBatch,
    WorkItem,
    WorkStatus,
    WorkflowState,
    WorkflowSummary,
    _now_iso,
)

logger = logging.getLogger(__name__)

WORKFLOW_FILE = "workflow.json"
_LOCK = threading.Lock()


def _path(root: Path) -> Path:
    return root / PROJECT_DIR / WORKFLOW_FILE


# -- Read / write --

def load(root: Path) -> WorkflowState:
    """Load workflow state. Returns empty state if file is missing."""
    path = _path(root)
    if not path.is_file():
        return WorkflowState()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return WorkflowState.from_dict(raw)
    except (OSError, json.JSONDecodeError, KeyError):
        logger.exception("workflow load failed at %s", path)
        return WorkflowState()


def save(root: Path, state: WorkflowState) -> None:
    """Persist workflow state to disk (thread-safe)."""
    with _LOCK:
        _save_unlocked(root, state)


def _save_unlocked(root: Path, state: WorkflowState) -> None:
    """Write state to disk without acquiring the lock.

    Internal helper for mutation functions that already hold ``_LOCK``.
    """
    path = _path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def summarize(root: Path) -> WorkflowSummary:
    """Quick summary without loading items into caller memory."""
    return WorkflowSummary.from_state(load(root))


# -- Mutations --

def add_batch(root: Path, batch: IngestBatch,
              items: list[WorkItem]) -> WorkflowState:
    """Register a new ingest batch + its items. Returns updated state."""
    with _LOCK:
        state = load(root)
        state.batches.append(batch)
        state.items.extend(items)
        state.active_batch_id = batch.batch_id
        _save_unlocked(root, state)
    return state


def update_status(root: Path, item_ids: list[str],
                  new_status: WorkStatus) -> WorkflowState:
    """Batch-update status for a set of items. Returns updated state."""
    id_set = set(item_ids)
    now = _now_iso()
    with _LOCK:
        state = load(root)
        for item in state.items:
            if item.item_id in id_set:
                item.status = new_status
                item.updated_at = now
        _save_unlocked(root, state)
    return state


def remove_items(root: Path, item_ids: list[str]) -> WorkflowState:
    """Remove items by id (e.g. after permanent delete)."""
    id_set = set(item_ids)
    with _LOCK:
        state = load(root)
        state.items = [i for i in state.items if i.item_id not in id_set]
        _save_unlocked(root, state)
    return state


def reconcile(root: Path, valid_relative_paths: set[str]) -> int:
    """Drop workflow items whose ``relative_path`` no longer exists.

    Called after a fresh dataset scan finishes so stats derived from
    workflow state (home launchpad cards, DatasetBar production strip,
    ReviewHub summary) reflect actual disk state — without this,
    deleting images via the workbench leaves orphan items pointing at
    paths that are gone, and counts stay inflated.

    Returns the number of items removed. ``0`` when the workflow file
    is missing or every item is still valid; nothing is written in
    that case.
    """
    with _LOCK:
        state = load(root)
        before = len(state.items)
        if before == 0:
            return 0
        state.items = [
            i for i in state.items
            if i.relative_path in valid_relative_paths
        ]
        removed = before - len(state.items)
        if removed:
            _save_unlocked(root, state)
        return removed


def items_by_status(root: Path, status: WorkStatus) -> list[WorkItem]:
    """Return items matching a given status."""
    state = load(root)
    return [i for i in state.items if i.status == status]


def item_by_path(state: WorkflowState,
                 relative_path: str) -> WorkItem | None:
    """Lookup a single item by relative path (O(n), fine for JSON store)."""
    for item in state.items:
        if item.relative_path == relative_path:
            return item
    return None
