"""Application-level shared state — dataset, project, task type.

Single instance created in MainWindow, passed to views that need it.
Broadcasts changes via Qt signals so views stay in sync.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal

from core.models import Dataset
from core.project import Project, create_project, load_project, save_project
from core.recent import add_recent
from core.task_types import TaskType


class AppState(QObject):
    """Shared session state across all top-level views."""

    dataset_changed = pyqtSignal(object)   # Dataset | None
    project_changed = pyqtSignal(object)   # Project | None

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._dataset: Dataset | None = None
        self._project: Project | None = None

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
        """Store scanned dataset and broadcast to all views."""
        self._dataset = ds
        self.dataset_changed.emit(ds)

    def close_dataset(self) -> None:
        """Save current project (if any) and clear state."""
        if self._project:
            save_project(self._project)
        self._dataset = None
        self._project = None
