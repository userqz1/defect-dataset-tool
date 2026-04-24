"""Workflow controller — inbox import, commit, and status transitions.

Owns the business logic for the inbox-based ingest pipeline.
UI views call these methods; the controller updates AppState which
broadcasts changes via signals.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from core import workflow_store
from core.inbox import commit_items, create_batch
from core.workflow import WorkItem, WorkStatus

if TYPE_CHECKING:
    from gui.app_state import AppState

logger = logging.getLogger(__name__)


class WorkflowController:
    """Manages inbox import, commit, and work-status transitions."""

    def __init__(self, state: AppState) -> None:
        self._state = state

    # -- Inbox import --

    def import_to_inbox(
        self,
        source_dirs: list[Path],
        name: str = "",
        *,
        recursive: bool = True,
        progress_cb=None,
    ) -> int:
        """Copy images from *source_dirs* into ``_inbox/<batch>/images/``.

        Returns the number of items created.  Caller should wrap this
        in a ``BatchWorker`` for background execution.
        """
        project = self._state.project
        if project is None:
            return 0
        root = project.root_path
        batch, items = create_batch(
            root, source_dirs, name=name,
            recursive=recursive, progress_cb=progress_cb,
        )
        state = workflow_store.add_batch(root, batch, items)
        self._state.set_workflow(state)
        return len(items)

    # -- Commit --

    def commit_batch_items(
        self,
        item_ids: list[str],
        category: str,
        *,
        progress_cb=None,
    ) -> int:
        """Move selected inbox items into ``<root>/<category>/images/``.

        Returns the number of successfully committed items.
        """
        project = self._state.project
        if project is None:
            return 0
        root = project.root_path
        wf = self._state.workflow
        if wf is None:
            return 0

        # Resolve WorkItem objects from IDs
        id_set = set(item_ids)
        items = [i for i in wf.items if i.item_id in id_set]
        if not items:
            return 0

        committed = commit_items(root, items, category,
                                 progress_cb=progress_cb)
        # Persist updated paths/status
        workflow_store.save(root, wf)
        self._state.set_workflow(wf)
        return len(committed)

    # -- Status transitions --

    def update_status(self, item_ids: list[str],
                      new_status: WorkStatus) -> None:
        """Batch-update status for a set of items."""
        project = self._state.project
        if project is None:
            return
        state = workflow_store.update_status(
            project.root_path, item_ids, new_status,
        )
        self._state.set_workflow(state)

    def remove_items(self, item_ids: list[str]) -> None:
        """Remove items from workflow tracking (e.g. after deletion)."""
        project = self._state.project
        if project is None:
            return
        state = workflow_store.remove_items(project.root_path, item_ids)
        self._state.set_workflow(state)
