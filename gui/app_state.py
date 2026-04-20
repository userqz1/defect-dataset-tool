"""Application-level shared state — dataset, project, task type,
plus session-level derived artifacts (quality issues, dedup groups, stats).

Single instance created in MainWindow, passed to views that need it.
Broadcasts changes via Qt signals so views stay in sync.

Review #7: derived artifacts used to live inside BrowserView
(``_quality_map``), which meant any other view wanting that data
(future quality-visualization, export gating by issue count, etc.)
would have to re-compute. Pulling them into AppState also ensures
they're properly cleared on dataset swap — a footgun when BrowserView
owned the state but wasn't in every view hierarchy.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal

from core.models import Dataset
from core.project import Project, create_project, load_project, save_project
from core.recent import add_recent
from core.task_types import TaskType


class AppState(QObject):
    """Shared session state across all top-level views."""

    dataset_changed = pyqtSignal(object)       # Dataset | None
    project_changed = pyqtSignal(object)       # Project | None
    # Derived artifacts (session-scoped; cleared on dataset change):
    quality_changed = pyqtSignal(object)       # list[QualityIssue] | None
    duplicates_changed = pyqtSignal(object)    # list[DuplicateGroup] | None
    ext_stats_changed = pyqtSignal(object)     # ExtendedStats | None

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._dataset: Dataset | None = None
        self._project: Project | None = None
        self._quality_issues: list[Any] | None = None   # list[QualityIssue]
        self._duplicate_groups: list[Any] | None = None  # list[DuplicateGroup]
        self._ext_stats: Any | None = None               # ExtendedStats

    # -- Properties --

    @property
    def dataset(self) -> Dataset | None:
        return self._dataset

    @property
    def project(self) -> Project | None:
        return self._project

    @property
    def task_type(self) -> TaskType | None:
        return self._project.task_type if self._project else None

    @property
    def quality_issues(self) -> list[Any] | None:
        """``list[QualityIssue]`` from the last run, or None if never run."""
        return self._quality_issues

    @property
    def quality_issue_paths(self) -> dict[str, list[str]]:
        """Convenience: path str → list of issue kinds for UI badge/filter.

        Returns an empty dict if no check has run (callers can treat it as
        "no issues to show" without None checks).
        """
        if not self._quality_issues:
            return {}
        return {str(i.image.path): list(i.kinds) for i in self._quality_issues}

    @property
    def duplicate_groups(self) -> list[Any] | None:
        return self._duplicate_groups

    @property
    def ext_stats(self) -> Any | None:
        return self._ext_stats

    # -- Actions --

    def open_dataset(self, root: Path, task_type: TaskType) -> Project:
        """Load or create a Project for *root*, update recents, emit signals."""
        self.close_dataset()

        project = load_project(root)
        if project is None:
            project = create_project(root, task_type=task_type)
        else:
            project.task_type = task_type
            save_project(project)

        add_recent(root)
        self._project = project
        self.project_changed.emit(project)
        return project

    def set_dataset(self, ds: Dataset) -> None:
        """Store scanned dataset and broadcast to all views.

        Also clears derived artifacts (quality / dedup / ext stats) —
        they are pinned to the previous scan and become meaningless on
        a fresh dataset. Callers that want to preserve them across
        rescans must re-apply via set_quality_issues / ... after the
        dataset_changed signal settles.
        """
        self._dataset = ds
        # Derived artifacts are per-scan; drop them so stale results
        # don't leak into the new dataset's UI.
        self._clear_derived(emit=True)
        self.dataset_changed.emit(ds)

    def set_quality_issues(self, issues: list[Any] | None) -> None:
        """Store the latest quality check output and notify subscribers."""
        self._quality_issues = issues
        self.quality_changed.emit(issues)

    def set_duplicate_groups(self, groups: list[Any] | None) -> None:
        self._duplicate_groups = groups
        self.duplicates_changed.emit(groups)

    def set_ext_stats(self, stats: Any | None) -> None:
        self._ext_stats = stats
        self.ext_stats_changed.emit(stats)

    def close_dataset(self) -> None:
        """Save current project (if any) and clear state."""
        if self._project:
            save_project(self._project)
        self._dataset = None
        self._project = None
        self._clear_derived(emit=False)

    # -- Internals --

    def _clear_derived(self, emit: bool) -> None:
        self._quality_issues = None
        self._duplicate_groups = None
        self._ext_stats = None
        if emit:
            self.quality_changed.emit(None)
            self.duplicates_changed.emit(None)
            self.ext_stats_changed.emit(None)
