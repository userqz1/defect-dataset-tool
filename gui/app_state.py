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

import enum
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal

from core.models import Dataset
from core.project import Project, create_project, load_project, save_project
from core.recent import add_recent
from core.task_types import TaskType
from core.workflow import WorkflowState, WorkflowSummary
from core import workflow_store


class SampleSetStatus(enum.Enum):
    """Lifecycle state of the cached SampleSet.

    - ``READY``       — SampleSet was built from the current Dataset
                        and can be used as the authoritative data source.
    - ``STALE``       — SampleSet exists but the underlying data has changed
                        (e.g. a mutating tool ran). UI may display it with a
                        warning; export should refuse or re-build first.
    - ``UNAVAILABLE`` — No SampleSet (build failed or never ran).
                        Consumers must fall back to disk-based parsing.
    """
    READY = "ready"
    STALE = "stale"
    UNAVAILABLE = "unavailable"


class AppState(QObject):
    """Shared session state across all top-level views."""

    dataset_changed = pyqtSignal(object)       # Dataset | None
    project_changed = pyqtSignal(object)       # Project | None
    # Workflow:
    workflow_changed = pyqtSignal(object)      # WorkflowState | None
    workflow_summary_changed = pyqtSignal(object)  # WorkflowSummary | None
    # Unified model — lifecycle-managed; see SampleSetStatus:
    sample_set_changed = pyqtSignal(object)    # SampleSet | None
    sample_set_status_changed = pyqtSignal(str)  # SampleSetStatus.value
    # Derived artifacts (session-scoped; cleared on dataset change):
    quality_changed = pyqtSignal(object)       # list[QualityIssue] | None
    duplicates_changed = pyqtSignal(object)    # list[DuplicateGroup] | None
    ext_stats_changed = pyqtSignal(object)     # ExtendedStats | None
    readiness_changed = pyqtSignal(object)     # TaskReadinessReport | None
    # Scan lifecycle — gates write operations during scan/rescan windows:
    scan_active_changed = pyqtSignal(bool)     # True while a scan worker runs

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._dataset: Dataset | None = None
        self._project: Project | None = None
        self._workflow: WorkflowState | None = None
        self._workflow_summary: WorkflowSummary | None = None
        self._sample_set: Any | None = None                 # SampleSet
        self._ss_status = SampleSetStatus.UNAVAILABLE
        self._task_readiness: Any | None = None          # TaskReadinessReport
        self._quality_issues: list[Any] | None = None   # list[QualityIssue]
        self._duplicate_groups: list[Any] | None = None  # list[DuplicateGroup]
        self._ext_stats: Any | None = None               # ExtendedStats
        self._scan_active: bool = False

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
    def sample_set(self) -> Any | None:
        """``SampleSet`` from the last full scan, or None."""
        return self._sample_set

    @property
    def sample_set_status(self) -> SampleSetStatus:
        """Current lifecycle state of the cached SampleSet."""
        return self._ss_status

    @property
    def sample_set_ready(self) -> bool:
        """Convenience: True only when SampleSet is READY (authoritative)."""
        return self._ss_status is SampleSetStatus.READY

    @property
    def task_readiness(self) -> Any | None:
        """``TaskReadinessReport`` — recomputed on dataset/sample_set change."""
        return self._task_readiness

    @property
    def ext_stats(self) -> Any | None:
        return self._ext_stats

    @property
    def workflow(self) -> WorkflowState | None:
        return self._workflow

    @property
    def workflow_summary(self) -> WorkflowSummary | None:
        return self._workflow_summary

    @property
    def scan_active(self) -> bool:
        """True while a scan worker (scan/rescan) is active.

        Mutation entry points (DetailView save, tool sidebar, category
        rename, etc.) should refuse or defer when this is True — the
        worker is holding the disk and the SampleSet is not yet
        authoritative.
        """
        return self._scan_active

    @property
    def can_write(self) -> bool:
        """True when mutating operations are safe to run.

        Composite of ``not scan_active`` and "a dataset is loaded".
        Views can bind their enabled-state to this.
        """
        return (not self._scan_active) and self._dataset is not None

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
        self.load_workflow()
        return project

    def set_dataset(self, ds: Dataset) -> None:
        """Store scanned dataset and broadcast to all views.

        Also clears derived artifacts (quality / dedup / ext stats) **and
        the SampleSet** — they are pinned to the previous scan and become
        meaningless on a fresh dataset.  The caller is expected to call
        ``set_sample_set()`` immediately after to transition from
        UNAVAILABLE to READY (or leave it UNAVAILABLE if build failed).

        Signal batching (review #5): derived-cleared signals are
        *suppressed* here — subscribers re-render anyway via
        ``dataset_changed``.  ``sample_set_changed`` *is* emitted
        (clearing DetailView's index is safety-critical to prevent
        stale annotation data surviving a rescan).
        """
        self._dataset = ds
        # Drop stale derived state without emitting — dataset_changed
        # below carries the "everything has changed" message by itself.
        self._clear_derived(emit=False)
        # Hard-clear SampleSet — old SS must NOT survive into the new
        # Dataset.  Emit so DetailView drops its index immediately.
        self._sample_set = None
        self._ss_status = SampleSetStatus.UNAVAILABLE
        self.sample_set_changed.emit(None)
        self.sample_set_status_changed.emit(self._ss_status.value)
        self.dataset_changed.emit(ds)

    def set_quality_issues(self, issues: list[Any] | None) -> None:
        """Store the latest quality check output and notify subscribers."""
        self._quality_issues = issues
        self.quality_changed.emit(issues)

    def set_duplicate_groups(self, groups: list[Any] | None) -> None:
        self._duplicate_groups = groups
        self.duplicates_changed.emit(groups)

    def set_sample_set(self, ss: Any | None) -> None:
        """Store a freshly loaded SampleSet and broadcast.

        Transitions status to READY when *ss* is not None, or
        UNAVAILABLE when None (build failed).  Also syncs workflow
        status onto each Sample and recomputes task readiness so the
        readiness bar updates automatically.
        """
        self._sample_set = ss
        self._ss_status = (
            SampleSetStatus.READY if ss is not None
            else SampleSetStatus.UNAVAILABLE
        )
        if ss is not None:
            self._sync_workflow_to_samples()
        self.sample_set_changed.emit(ss)
        self.sample_set_status_changed.emit(self._ss_status.value)
        self._recompute_readiness()

    def patch_sample(self, image_path, **fields) -> bool:
        """Update a single Sample in-place and emit ``sample_set_changed``.

        Use this for lightweight, local mutations (caption save, single-
        image workflow status flip, category reassignment in memory) that
        do NOT require a full rescan.  The SampleSet status stays READY.

        Returns True if the sample was found and updated.
        """
        ss = self._sample_set
        if ss is None:
            return False
        ok = ss.update_sample(image_path, **fields)
        if ok:
            self.sample_set_changed.emit(ss)
        return ok

    def remove_samples(self, paths: set[str]) -> int:
        """Bulk-remove samples from the in-memory SampleSet.

        Use after deleting images from disk when you want to keep the
        SampleSet READY (avoiding a full rescan).  Returns the count of
        samples removed.  Also removes corresponding WorkItems.
        """
        ss = self._sample_set
        if ss is None:
            return 0
        removed = ss.remove_by_paths(paths)
        if removed:
            self.sample_set_changed.emit(ss)
            self._recompute_readiness()
        return removed

    def notify_dataset_mutated(self) -> None:
        """Re-broadcast ``dataset_changed`` for the current (in-place mutated) dataset.

        Use after an incremental edit that changed the already-held
        ``Dataset`` object (e.g. ``ds.remove_images``, adding a new
        ImageInfo in place).  Prefer ``set_dataset`` when you have a
        freshly-built Dataset — that clears derived artifacts.
        """
        self.dataset_changed.emit(self._dataset)

    def notify_sample_set_mutated(self) -> None:
        """Re-broadcast ``sample_set_changed`` + recompute task readiness.

        Use after an in-place mutation of the held SampleSet (e.g.
        patching a sample's path/category, bulk ``remove_by_paths``).
        Does NOT change ``sample_set_status`` — callers that need to
        move from READY to STALE should use ``mark_sample_set_stale``
        explicitly.
        """
        self.sample_set_changed.emit(self._sample_set)
        self._recompute_readiness()

    def notify_project_mutated(self) -> None:
        """Re-broadcast ``project_changed`` for the current project.

        Use after in-place edits (e.g. ``project.annotation_format = 'yolo'``
        following a format migration).  Persistence is the caller's
        responsibility — AppState doesn't decide when to save.
        """
        self.project_changed.emit(self._project)

    def set_scan_active(self, active: bool) -> None:
        """Flip the scan gate and broadcast.

        Session controller calls ``set_scan_active(True)`` when it
        launches a ScanWorker and ``set_scan_active(False)`` from every
        terminal handler (finished_ok / failed / canceled).  Views bind
        their write-enabled UI to ``can_write`` / ``scan_active_changed``.
        """
        if self._scan_active == active:
            return
        self._scan_active = active
        self.scan_active_changed.emit(active)

    def mark_sample_set_stale(self) -> None:
        """Mark the current SampleSet as STALE.

        Call this before launching a rescan after a mutating operation
        (delete, move, augment, predict, etc.).  The SampleSet object
        remains accessible for read-only display, but consumers that
        require authoritative data (export, save-back) should refuse
        or wait for the rescan to complete.

        If no SampleSet exists, transitions to UNAVAILABLE instead.
        """
        if self._sample_set is not None:
            self._ss_status = SampleSetStatus.STALE
        else:
            self._ss_status = SampleSetStatus.UNAVAILABLE
        self.sample_set_status_changed.emit(self._ss_status.value)

    def set_ext_stats(self, stats: Any | None) -> None:
        self._ext_stats = stats
        self.ext_stats_changed.emit(stats)

    def open_project(self, root: Path, name: str,
                     task_type: TaskType) -> Project:
        """Create a brand-new empty project (no scan, no dataset).

        Used for the "新建空项目" flow — the directory may contain no
        images yet.  A subsequent scan/import will populate it.
        """
        self.close_dataset()
        root.mkdir(parents=True, exist_ok=True)
        project = create_project(root, name=name, task_type=task_type)
        add_recent(root)
        self._project = project
        self.project_changed.emit(project)
        self.load_workflow()
        return project

    def load_workflow(self) -> None:
        """Load workflow state from disk for the current project."""
        if self._project is None:
            return
        state = workflow_store.load(self._project.root_path)
        self._workflow = state
        self.workflow_changed.emit(state)
        self._workflow_summary = WorkflowSummary.from_state(state)
        self.workflow_summary_changed.emit(self._workflow_summary)

    def set_workflow(self, state: WorkflowState) -> None:
        """Store workflow state, persist to disk, and broadcast.

        When a READY SampleSet exists, re-syncs ``Sample.work_status``
        from the updated workflow so the browser's work-queue filters
        and the dataset bar's production stats reflect the change
        immediately.
        """
        if self._project is not None:
            workflow_store.save(self._project.root_path, state)
        self._workflow = state
        self.workflow_changed.emit(state)
        self._workflow_summary = WorkflowSummary.from_state(state)
        self.workflow_summary_changed.emit(self._workflow_summary)
        # Re-stamp Sample.work_status when SS is live
        if self._sample_set is not None and self._ss_status is SampleSetStatus.READY:
            self._sync_workflow_to_samples()
            self.sample_set_changed.emit(self._sample_set)

    def refresh_workflow_summary(self) -> None:
        """Re-derive summary from current workflow state and broadcast."""
        if self._workflow is None:
            self._workflow_summary = None
        else:
            self._workflow_summary = WorkflowSummary.from_state(self._workflow)
        self.workflow_summary_changed.emit(self._workflow_summary)

    def close_dataset(self) -> None:
        """Save current project (if any) and clear state."""
        if self._project:
            save_project(self._project)
        self._dataset = None
        self._project = None
        self._workflow = None
        self._workflow_summary = None
        self._sample_set = None
        self._ss_status = SampleSetStatus.UNAVAILABLE
        self._clear_derived(emit=False)

    # -- Internals --

    def _sync_workflow_to_samples(self) -> None:
        """Stamp ``Sample.work_status`` from the current WorkflowState.

        Calls ``core.workflow.sync_samples`` which also auto-creates
        WorkItem entries for images that appear in the SampleSet but
        are not yet tracked by the workflow.  After sync, derives the
        workflow summary from the SampleSet (more accurate — only counts
        images that actually exist on disk).
        """
        wf = self._workflow
        ss = self._sample_set
        if wf is None or ss is None or self._project is None:
            return
        from core.workflow import sync_samples
        mutated = sync_samples(wf, ss, self._project.root_path)
        if mutated:
            workflow_store.save(self._project.root_path, wf)
        # Re-derive summary from SampleSet (authoritative — excludes
        # dead WorkItems for files that no longer exist on disk).
        self._workflow_summary = WorkflowSummary.from_sample_set(
            ss, batch_count=len(wf.batches),
        )
        self.workflow_summary_changed.emit(self._workflow_summary)

    def _recompute_readiness(self) -> None:
        """Recompute task readiness from current dataset + sample_set."""
        ds = self._dataset
        if ds is None:
            self._task_readiness = None
            self.readiness_changed.emit(None)
            return
        tt = self.task_type
        if tt is None:
            self._task_readiness = None
            self.readiness_changed.emit(None)
            return
        from core.task_readiness import check_task_readiness
        report = check_task_readiness(
            ds, tt,
            sample_set=self._sample_set if self.sample_set_ready else None,
        )
        self._task_readiness = report
        self.readiness_changed.emit(report)

    def _clear_derived(self, emit: bool) -> None:
        self._quality_issues = None
        self._duplicate_groups = None
        self._ext_stats = None
        self._task_readiness = None
        if emit:
            self.quality_changed.emit(None)
            self.duplicates_changed.emit(None)
            self.ext_stats_changed.emit(None)
