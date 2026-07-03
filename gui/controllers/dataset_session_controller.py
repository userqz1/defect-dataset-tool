"""Dataset session controller — scan, refresh, worker lifecycle.

Extracted from DatasetBrowserView to separate scan/session orchestration
from layout and widget assembly.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject
from qfluentwidgets import InfoBar, InfoBarPosition

if TYPE_CHECKING:
    from gui.controllers.browser_runtime import BrowserRuntime

logger = logging.getLogger(__name__)


class DatasetSessionController(QObject):
    """Owns scan workers and dataset lifecycle on behalf of the browser shell."""

    def __init__(self, rt: BrowserRuntime, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._rt = rt
        self._scan_worker = None

    # -- Public API --

    def open_directory(self, root: Path) -> None:
        self.scan(root, show_progress=False)

    def choose_and_open_directory(self) -> None:
        from PyQt6.QtWidgets import QFileDialog

        d = QFileDialog.getExistingDirectory(
            self._rt.shell, "选择数据集目录", str(Path.home()))
        if not d:
            return
        root = Path(d)
        from core.project import infer_preset_for_root, load_project

        project = load_project(root)
        if project:
            task_type = project.task_type
            preset_id = project.preset_id
        else:
            task_type, preset_id = infer_preset_for_root(root)
        self._rt.state.open_dataset(root, task_type, preset_id=preset_id)
        self.scan(root, show_progress=False)

    def scan(
        self, root: Path, force: bool = False, show_progress: bool = False
    ) -> None:
        if self._scan_worker is not None and self._scan_worker.isRunning():
            return
        self._rt.dataset_bar.set_open_enabled(False)
        # Keep every dataset-wide action surface disabled for the full
        # scan lifecycle (Phase 1 + Phase 2 + Phase 3).  Quick-open
        # renders the grid the moment scan_finished fires, but mutating
        # tools must NOT race with the worker still reading disk for
        # load_samples / compute_stats — re-enable only at finished_ok
        # / failed / canceled.
        self._set_tools_enabled(False)
        # Flip the global scan-active gate BEFORE any signal emission
        # happens — DetailView and other mutation entry points bind
        # their enabled state to ``state.can_write`` and must see the
        # gate closed as soon as the worker starts, not after Phase 1.
        self._rt.state.set_scan_active(True)

        progress = None
        if show_progress:
            from gui.dialogs.op_dialogs import ProgressDialog

            progress = ProgressDialog(
                "扫描数据集", parent=self._window(), cancelable=True)
            progress.show()

        from gui.workers.scan_worker import ScanWorker

        # Intentionally do NOT pass project.annotation_format as a hint
        # here — that field defaults to "labelme" at project-create time
        # and only changes after an explicit format-migration, so
        # trusting it on first-open of a YOLO/VOC dataset would parse
        # every .txt/.xml as LabelMe and produce an empty SampleSet.
        # load_samples() infers the format from the scanned label
        # suffixes itself (with a COCO-vs-LabelMe peek when suffixes
        # are all .json).
        #
        # Phase 3 (ExtendedStats) is *always* skipped here.  The only
        # consumer is the Stats tool, which on-demand recomputes from
        # the live SampleSet when ``state.ext_stats`` is unset
        # (``browser_tool_controller._run_stats``).  Running it as part
        # of the scan worker just extends the "模型加载中" window on
        # every open for a payload the user may never ask to see.
        worker = ScanWorker(
            root, parent=self._rt.shell,
            force_rescan=force, skip_analyze=True)
        self._scan_worker = worker
        if progress is not None:
            progress.canceled.connect(worker.cancel)

        _PHASE_TITLES = {
            "scan": "扫描文件系统",
            "unify": "加载标注模型",
            "annotate": "解析标注",     # fallback only
            # "analyze" phase is always skipped on first-open
            # (see skip_analyze=True below); stats are computed
            # on-demand when the user opens the Stats dialog.
        }

        def on_phase(p: str) -> None:
            if progress is not None:
                progress.titleLabel.setText(
                    _PHASE_TITLES.get(p, "扫描数据集"))

        def on_progress(done, total, name):
            if progress is not None:
                progress.set_progress(done, total, name)

        def on_scan_finished(ds):
            # Phase 1 complete — render the grid/catalogue NOW.  Phase 2+3
            # continue in background; sample_set_changed fires later and
            # tools that need the unified model already guard on
            # ``sample_set_ready`` (falling back to disk until it's READY).
            self._rt.state.set_dataset(ds)
            # Reconcile workflow.json against the freshly-scanned
            # filesystem.  Without this, deletions made in the
            # workbench leave orphan workflow items behind and the
            # home-launchpad cards / DatasetBar / ReviewHub summary
            # keep showing pre-deletion counts.  Cheap: a single read,
            # set comparison, and conditional save.
            project = self._rt.state.project
            if project is not None and ds.total_images > 0:
                from core import workflow_store
                valid: set[str] = set()
                for cat in ds.categories:
                    for img in cat.images:
                        try:
                            valid.add(img.path.relative_to(
                                project.root_path).as_posix())
                        except ValueError:
                            # Image path landed outside the project
                            # root (rare; symlinks). Skip — we can't
                            # safely match against workflow items.
                            pass
                try:
                    removed = workflow_store.reconcile(
                        project.root_path, valid)
                except Exception:
                    logger.exception("workflow reconcile failed")
                    removed = 0
                if removed:
                    # Re-broadcast so every open view (DatasetBar
                    # production strip, ReviewHub summary, etc.)
                    # repaints from the cleaned counts immediately.
                    self._rt.state.load_workflow()
            if progress is not None and progress.isVisible():
                progress.accept()
            if ds.total_images == 0:
                InfoBar.warning(
                    "目录中未找到图片",
                    "期望布局：<根>/<类别>/images/*.jpg 或扁平 <根>/*.jpg。"
                    "请确认子目录或扩展名（jpg/png/bmp/tif/webp）。",
                    parent=self._window(), duration=8000,
                    position=InfoBarPosition.TOP,
                )

        def on_done(result):
            self._scan_worker = None
            # Progress dialog already closed in on_scan_finished; defensive
            # re-close in case scan_finished was skipped (shouldn't happen).
            if progress is not None and progress.isVisible():
                progress.accept()
            self._rt.dataset_bar.set_open_enabled(True)

            from gui.workers.scan_worker import ScanResult

            if isinstance(result, ScanResult):
                ext, ss = result.ext_stats, result.sample_set
            else:
                ext, ss = None, None
            # Dataset is already set by on_scan_finished; just publish
            # the SampleSet + ext_stats.  None means "build failed,
            # status → UNAVAILABLE" which is better than leaving a
            # stale SampleSet from the previous scan.
            # Align the project's write-back format with what we just
            # imported.  Scenario: first-open of a YOLO/VOC dataset
            # creates a Project with ``annotation_format="labelme"``
            # (the dataclass default); without this sync DetailView
            # would happily save LabelMe JSON next to the original
            # .txt/.xml files and corrupt the dataset's format.
            if ss is not None:
                ss = self._prepare_sample_set_for_project(ss)
                self._sync_project_format_from_samples(ss)
            self._rt.state.set_sample_set(ss)
            if ext is not None:
                self._rt.state.set_ext_stats(ext)
            self._rt.state.set_scan_active(False)
            self._enable_tools_if_loaded()

        def on_fail(msg):
            self._scan_worker = None
            if progress is not None and progress.isVisible():
                progress.accept()
            self._rt.dataset_bar.set_open_enabled(True)
            self._rt.state.set_scan_active(False)
            self._enable_tools_if_loaded()
            InfoBar.error(
                "扫描失败", msg,
                parent=self._window(), duration=5000,
                position=InfoBarPosition.TOP)

        def on_canceled():
            self._scan_worker = None
            if progress is not None and progress.isVisible():
                progress.accept()
            self._rt.dataset_bar.set_open_enabled(True)
            self._rt.state.set_scan_active(False)
            self._enable_tools_if_loaded()
            InfoBar.info(
                "", "扫描已取消",
                parent=self._window(), duration=3000,
                position=InfoBarPosition.TOP)

        worker.phase.connect(on_phase)
        worker.progress.connect(on_progress)
        worker.scan_finished.connect(on_scan_finished)
        worker.finished_ok.connect(on_done)
        worker.failed.connect(on_fail)
        worker.canceled.connect(on_canceled)
        worker.start()

    def refresh(self) -> None:
        if self._scan_worker is not None and self._scan_worker.isRunning():
            InfoBar.info(
                "", "正在扫描，请稍候…",
                parent=self._window(), duration=1800,
                position=InfoBarPosition.TOP)
            return
        ds = self._rt.state.dataset
        if ds is None:
            return
        self.scan(ds.root_path, force=True, show_progress=True)

    def rescan(self, force: bool = False) -> None:
        if self._scan_worker is not None and self._scan_worker.isRunning():
            return
        ds = self._rt.state.dataset
        if ds is None:
            return

        # Mark current SampleSet stale immediately — the underlying data
        # has changed (delete/move/augment/…) and the in-memory model may
        # no longer match disk.  Consumers that check `sample_set_ready`
        # will fall back to disk until the rescan finishes.
        self._rt.state.mark_sample_set_stale()
        # Same rule as scan() — disable tools for the full worker
        # lifecycle so the in-flight unify/analyze passes don't race
        # with user mutations.  Re-enabled from the terminal handlers.
        self._set_tools_enabled(False)
        # Close the write gate for every mutation entry point while the
        # worker is live.
        self._rt.state.set_scan_active(True)

        from gui.workers.scan_worker import ScanWorker

        # See scan() — don't trust project.annotation_format as a read
        # hint; load_samples() infers from label suffixes.
        worker = ScanWorker(
            ds.root_path, parent=self._rt.shell,
            force_rescan=force, skip_analyze=True)
        self._scan_worker = worker

        def _scan_done(ds_new):
            # Publish the fresh Dataset as soon as Phase 1 finishes so the
            # grid updates even when Phase 2 is slow.
            self._rt.state.set_dataset(ds_new)

        def _done(result):
            self._scan_worker = None
            from gui.workers.scan_worker import ScanResult

            if isinstance(result, ScanResult):
                ext, ss = result.ext_stats, result.sample_set
            else:
                ext, ss = None, None
            # Dataset already set by _scan_done — just publish the
            # SampleSet / ext_stats.
            if ss is not None:
                ss = self._prepare_sample_set_for_project(ss)
                self._sync_project_format_from_samples(ss)
            self._rt.state.set_sample_set(ss)
            if ext is not None:
                self._rt.state.set_ext_stats(ext)
            self._rt.state.set_scan_active(False)
            self._enable_tools_if_loaded()

        def _fail(msg):
            self._scan_worker = None
            self._rt.state.set_scan_active(False)
            self._enable_tools_if_loaded()

        def _canceled():
            self._scan_worker = None
            self._rt.state.set_scan_active(False)
            self._enable_tools_if_loaded()

        worker.scan_finished.connect(_scan_done)
        worker.finished_ok.connect(_done)
        worker.failed.connect(_fail)
        worker.canceled.connect(_canceled)
        worker.start()

    def handle_dataset_changed(self, ds) -> None:
        if ds is None:
            self._rt.dataset_bar.clear()
            self._rt.catalog.clear()
            self._set_tools_enabled(False)
            return
        flagged = len(self._rt.state.quality_issues or [])
        self._rt.dataset_bar.set_dataset(ds, flagged_count=flagged)
        self._rt.dataset_bar.set_workflow_summary(
            self._rt.state.workflow_summary)

        # Preserve the user's category selection across rescans.
        # Snapshot the previously-active category, validate it against
        # the new dataset, and thread the surviving name through both
        # the catalog tree (visual selection) and the browser (filter
        # state).  Falls back to "All" only when the category was
        # itself removed by the just-finished mutation (e.g. delete
        # cleaned up the last image of "Loose").
        prev_category = self._rt.browser._current_category
        valid_names = {c.name for c in ds.categories}
        surviving_category = (
            prev_category if prev_category in valid_names else ""
        )

        self._rt.catalog.set_dataset(
            ds, select_category=surviving_category or None)
        # Tool enablement is owned by scan()/rescan() terminal handlers
        # — do NOT enable here, or quick-open would unlock mutating
        # tools while Phase 2/3 are still reading disk.  We still want
        # the undo button to reflect the freshly loaded dataset, so
        # refresh_undo_state runs independently.
        self.refresh_undo_state()
        self._rt.browser.load_dataset(ds)

    def cleanup_workers(self) -> None:
        if self._scan_worker is not None:
            # ScanWorker overrides run() — quit() only stops an event
            # loop and does nothing here.  cancel() sets the flag that
            # the progress callback checks, causing _ScanCancelled.
            self._scan_worker.cancel()
            if not self._scan_worker.wait(5000):
                logger.warning("ScanWorker did not stop within 5 s — "
                               "terminating thread")
                self._scan_worker.terminate()
                self._scan_worker.wait(2000)
        self._rt.thumb_worker.stop()

    # -- Private --

    def _window(self):
        return self._rt.shell.window()

    def _prepare_sample_set_for_project(self, ss):
        """Apply task-specific SampleSet normalization before publishing."""
        project = self._rt.state.project
        if project is None:
            return ss
        try:
            from core.task_types import TaskType
            if project.task_type is TaskType.IMAGE_PAIR:
                from core.pairing import infer_pairs
                return infer_pairs(ss)
        except Exception:
            logger.exception("image-pair inference failed")
        return ss

    def _set_tools_enabled(self, enabled: bool) -> None:
        """Gate every dataset-wide action surface.

        After the IA v3 split, "tools" is spread across three widgets:
          - DatasetBar refresh button (global refresh)
          - DeliveryHub action buttons (copy conversion / export / VLM export)
          - ReviewHub action buttons (quality / dedup / stats)

        Undo state is refreshed independently from the history log —
        enable/disable alone doesn't say whether an op is undoable.
        """
        self._rt.dataset_bar.set_refresh_enabled(enabled)
        self._rt.delivery_hub.set_actions_enabled(enabled)
        self._rt.review_hub.set_actions_enabled(enabled)
        self.refresh_undo_state()

    def _enable_tools_if_loaded(self) -> None:
        """Re-enable every action surface iff a non-empty dataset is loaded.

        Called from every scan/rescan terminal path (finished_ok /
        failed / canceled) so the hubs unlock exactly once the worker
        thread has stopped touching disk.  Safe to call when no dataset
        is loaded — it'll keep the surfaces disabled.
        """
        ds = self._rt.state.dataset
        self._set_tools_enabled(ds is not None and ds.total_images > 0)

    def _sync_project_format_from_samples(self, ss) -> None:
        """Align ``project.annotation_format`` with the scanned data.

        Scenario: first-open of a YOLO/VOC dataset.  ``load_project``
        finds no ``.dataforge/project.json`` so ``create_project``
        stamps ``annotation_format="labelme"`` (the dataclass default).
        If we leave it there, ``DetailView._on_save`` will write
        LabelMe JSON alongside the dataset's real ``.txt``/``.xml``
        files and quietly corrupt the layout.

        Rule: only flip the field when **all** labeled samples agree on
        a single source format that is writeback-capable (labelme /
        yolo / voc; COCO is excluded because ``Project.annotation_format``
        must be per-image-writable).  Persists via ``save_project`` and
        broadcasts through ``notify_project_mutated`` so DetailView and
        DatasetBar re-read the format.
        """
        project = self._rt.state.project
        if project is None:
            return
        fmts: set[str] = set()
        for s in ss.samples:
            sf = getattr(s, "source_format", "")
            if sf:
                fmts.add(sf)
        if len(fmts) != 1:
            return
        detected = fmts.pop()
        from core.project import WRITEBACK_FORMATS, save_project
        if detected not in WRITEBACK_FORMATS:
            return
        if project.annotation_format == detected:
            return
        project.annotation_format = detected
        try:
            save_project(project)
        except Exception:
            logger.exception("save_project failed after format auto-sync")
        self._rt.state.notify_project_mutated()

    def refresh_undo_state(self) -> None:
        # DetailView's local shape-undo stack takes precedence while
        # the user is on the detail page — that's the only way the
        # button can revert a shape delete.  The bar tooltip
        # ("撤销: <op>") tracks whichever stack is currently authoritative.
        rt = self._rt
        on_detail = (rt.browser_stack is not None
                     and rt.browser_stack.currentWidget() is rt.detail)
        if on_detail and rt.detail.can_undo():
            rt.dataset_bar.set_undo_enabled(True)
            rt.dataset_bar.set_undo_tooltip(
                f"撤销: {rt.detail.last_undo_label()}")
            return

        ds = rt.state.dataset
        if ds is None:
            rt.dataset_bar.set_undo_enabled(False)
            return
        from core.history import find_last_undoable

        try:
            entry = find_last_undoable(ds.root_path)
        except Exception:
            logger.exception("find_last_undoable failed")
            entry = None
        rt.dataset_bar.set_undo_enabled(entry is not None)
        if entry is not None:
            rt.dataset_bar.set_undo_tooltip(f"撤销: {entry.summary}")
        else:
            from gui import i18n
            rt.dataset_bar.set_undo_tooltip(i18n.t("tools.undo.none"))
