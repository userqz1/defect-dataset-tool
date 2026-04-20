"""Top-level dataset browser — standalone view.

Wraps BrowserView + DetailView + ThumbnailWorker + ScanWorker into a
self-contained top-level widget for MainWindow navigation. Also hosts
the toolbar (export / quality check / dedup / augment / stats) that
operates on the currently-loaded dataset.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CaptionLabel,
    FluentIcon as FIF,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    PushButton,
)

from gui.app_state import AppState
from gui.theme import T
from gui.views.browser_view import BrowserView
from gui.views.detail_view import DetailView
from gui.workers.thumbnail_worker import ThumbnailWorker


class DatasetBrowserView(QWidget):
    """Top-level browser: directory picker + scan + browse + detail."""

    def __init__(self, app_state: AppState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("datasetBrowserView")
        self._state = app_state
        self._scan_worker = None
        self._export_worker = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # -- Top bar: path + stats + open button --
        topbar = QFrame()
        topbar.setObjectName("detailTopBar")
        topbar.setFixedHeight(44)
        tb_lay = QHBoxLayout(topbar)
        tb_lay.setContentsMargins(T.PAD_LG, 0, T.PAD_LG, 0)
        tb_lay.setSpacing(T.GAP)

        self._path_label = CaptionLabel("未选择目录")
        tb_lay.addWidget(self._path_label, 1)

        self._stats_label = CaptionLabel("")
        tb_lay.addWidget(self._stats_label)

        open_btn = PrimaryPushButton("选择目录")
        open_btn.setIcon(FIF.FOLDER)
        open_btn.setFixedWidth(120)
        open_btn.clicked.connect(self._on_open_dir)
        tb_lay.addWidget(open_btn)
        self._open_btn = open_btn

        lay.addWidget(topbar)

        # -- Toolbar: quick-access tools --
        toolbar = QFrame()
        toolbar.setObjectName("detailTopBar")
        toolbar.setFixedHeight(38)
        tbar_lay = QHBoxLayout(toolbar)
        tbar_lay.setContentsMargins(T.PAD_LG, 0, T.PAD_LG, 0)
        tbar_lay.setSpacing(T.GAP)

        self._refresh_btn = PushButton("刷新")
        self._refresh_btn.setIcon(FIF.SYNC)
        self._refresh_btn.setFixedWidth(80)
        self._refresh_btn.setEnabled(False)
        self._refresh_btn.clicked.connect(self._on_refresh)
        tbar_lay.addWidget(self._refresh_btn)

        self._export_btn = PushButton("导出")
        self._export_btn.setIcon(FIF.SHARE)
        self._export_btn.setFixedWidth(80)
        self._export_btn.setEnabled(False)
        self._export_btn.clicked.connect(self._on_export)
        tbar_lay.addWidget(self._export_btn)

        self._quality_btn = PushButton("质检")
        self._quality_btn.setIcon(FIF.SEARCH)
        self._quality_btn.setFixedWidth(80)
        self._quality_btn.setEnabled(False)
        self._quality_btn.clicked.connect(self._on_quality_check)
        tbar_lay.addWidget(self._quality_btn)

        self._dedup_btn = PushButton("去重")
        self._dedup_btn.setIcon(FIF.COPY)
        self._dedup_btn.setFixedWidth(80)
        self._dedup_btn.setEnabled(False)
        self._dedup_btn.clicked.connect(self._on_dedup)
        tbar_lay.addWidget(self._dedup_btn)

        tbar_lay.addStretch()

        self._history_btn = PushButton("历史")
        self._history_btn.setIcon(FIF.HISTORY)
        self._history_btn.setFixedWidth(80)
        self._history_btn.setEnabled(False)
        self._history_btn.clicked.connect(self._on_history)
        tbar_lay.addWidget(self._history_btn)

        self._stats_btn = PushButton("统计")
        self._stats_btn.setIcon(FIF.PIE_SINGLE)
        self._stats_btn.setFixedWidth(80)
        self._stats_btn.setEnabled(False)
        self._stats_btn.clicked.connect(self._on_stats)
        tbar_lay.addWidget(self._stats_btn)

        lay.addWidget(toolbar)

        # -- Browser + Detail stack --
        self._browser_stack = QStackedWidget()
        # BrowserView reads dataset/task_type via AppState — single truth.
        self._browser = BrowserView(app_state=self._state)
        self._detail = DetailView()

        self._thumb = ThumbnailWorker(size=170, parent=self)
        self._thumb.start()
        self._browser.thumb_request.connect(self._thumb.request)
        self._browser.clear_thumb_queue.connect(self._thumb.clear_queue)
        self._thumb.thumb_ready.connect(self._browser.on_thumb_ready)

        self._browser.image_activated.connect(
            lambda img, imgs: (
                self._detail.show_image(img, imgs),
                self._browser_stack.setCurrentWidget(self._detail),
            )
        )
        self._detail.back_requested.connect(
            lambda: self._browser_stack.setCurrentWidget(self._browser)
        )

        self._browser_stack.addWidget(self._browser)
        self._browser_stack.addWidget(self._detail)
        lay.addWidget(self._browser_stack, 1)

        # Re-scan when browser reports file-system changes (delete / move /
        # category ops). force=True so fingerprint-based cache-hit doesn't
        # serve stale data — the user just intentionally modified files.
        self._browser.dataset_changed.connect(
            lambda: self._rescan(force=True)
        )

        # Listen to AppState for dataset changes from other sources
        self._state.dataset_changed.connect(self._on_dataset_changed)

    # -- Public API --

    def open_directory(self, root: Path) -> None:
        """Programmatic entry — called by MainWindow after welcome page action."""
        self._scan_dir(root)

    def cleanup(self) -> None:
        """Stop workers. Called from MainWindow.closeEvent."""
        if self._scan_worker is not None:
            self._scan_worker.quit()
            self._scan_worker.wait(3000)
        # stop() wakes the queue + closes diskcache; requestInterruption
        # alone would leave the worker blocked on queue.get().
        self._thumb.stop()

    # -- Private --

    def _on_open_dir(self) -> None:
        from PyQt6.QtWidgets import QFileDialog
        d = QFileDialog.getExistingDirectory(self, "选择数据集目录", str(Path.home()))
        if not d:
            return
        root = Path(d)
        # Check for existing project (has saved task type)
        from core.project import load_project
        project = load_project(root)
        if project:
            task_type = project.task_type
        else:
            from gui.dialogs.task_type_dialog import TaskTypeDialog
            dlg = TaskTypeDialog(self.window())
            if not dlg.exec():
                return
            task_type = dlg.selected_task_type()
            if task_type is None:
                return
        self._state.open_dataset(root, task_type)
        self._scan_dir(root)

    def _scan_dir(self, root: Path, force: bool = False) -> None:
        """Scan a directory and load into browser.

        ``force=True`` skips the SQLite index cache and re-walks the
        filesystem — used by the manual "刷新" button.
        """
        if self._scan_worker is not None and self._scan_worker.isRunning():
            return
        self._path_label.setText(str(root))
        self._open_btn.setEnabled(False)
        self._stats_label.setText("扫描中…")

        from gui.dialogs.op_dialogs import ProgressDialog
        progress = ProgressDialog("扫描数据集", parent=self.window())
        progress.show()

        from gui.workers.scan_worker import ScanWorker
        worker = ScanWorker(root, parent=self, force_rescan=force)
        self._scan_worker = worker

        # Show which phase is running so 5k-image scans don't look like
        # they're looping — ScanWorker emits "scan" → "annotate" → "analyze".
        _PHASE_TITLES = {
            "scan": "扫描文件系统",
            "annotate": "解析标注",
            "analyze": "统计类别分布",
        }

        def on_phase(p: str) -> None:
            progress.titleLabel.setText(_PHASE_TITLES.get(p, "扫描数据集"))

        def on_progress(done, total, name):
            progress.set_progress(done, total, name)

        def on_done(result):
            self._scan_worker = None
            progress.accept()
            self._open_btn.setEnabled(True)

            from gui.workers.scan_worker import ScanResult
            ds = result.dataset if isinstance(result, ScanResult) else result
            # Single write: AppState → dataset_changed signal →
            # _on_dataset_changed updates the topbar + browser. No dual
            # writes to both self._browser and self._state.
            self._state.set_dataset(ds)
            if ds.total_images == 0:
                InfoBar.warning(
                    "目录中未找到图片",
                    "期望布局：<根>/<类别>/images/*.jpg 或扁平 <根>/*.jpg。"
                    "请确认子目录或扩展名（jpg/png/bmp/tif/webp）。",
                    parent=self.window(), duration=8000,
                    position=InfoBarPosition.TOP,
                )

        def on_fail(msg):
            self._scan_worker = None
            progress.accept()
            self._open_btn.setEnabled(True)
            self._stats_label.setText(f"失败: {msg}")

        worker.phase.connect(on_phase)
        worker.progress.connect(on_progress)
        worker.finished_ok.connect(on_done)
        worker.failed.connect(on_fail)
        worker.start()

    def _on_refresh(self) -> None:
        """Manual refresh — re-scan the current dataset on demand.

        v1.2 UX note: "实时更新数据集状况" — whenever outside processes
        (other tools, file-system changes) touch the dataset, user can
        hit this to re-index without reopening. Goes through _scan_dir so
        the user gets the same phase-labeled ProgressDialog as initial open.
        """
        if self._scan_worker is not None and self._scan_worker.isRunning():
            InfoBar.info("", "正在扫描，请稍候…",
                         parent=self.window(), duration=1800,
                         position=InfoBarPosition.TOP)
            return
        ds = self._state.dataset
        if ds is None:
            return
        self._scan_dir(ds.root_path, force=True)

    def _rescan(self, force: bool = False) -> None:
        """Re-scan after file ops (delete/rename/move) or manual refresh.

        ``force=True`` bypasses the SQLite index cache — used by the manual
        refresh button. Non-forced rescans (after delete/rename/move) still
        trust the fingerprint check because those ops update parent mtime.
        """
        if self._scan_worker is not None and self._scan_worker.isRunning():
            return
        ds = self._state.dataset
        if ds is None:
            return
        root = ds.root_path

        from gui.workers.scan_worker import ScanWorker
        worker = ScanWorker(root, parent=self, force_rescan=force)
        self._scan_worker = worker

        def _done(result):
            self._scan_worker = None
            from gui.workers.scan_worker import ScanResult
            ds = result.dataset if isinstance(result, ScanResult) else result
            # Same single-write pattern as the initial scan — the
            # dataset_changed handler re-renders everything.
            self._state.set_dataset(ds)

        def _fail(msg):
            self._scan_worker = None

        worker.finished_ok.connect(_done)
        worker.failed.connect(_fail)
        worker.start()

    def _on_export(self) -> None:
        """Open export wizard dialog and run export."""
        ds = self._state.dataset
        if ds is None:
            return
        task_type = self._state.task_type

        from gui.dialogs.export_wizard import ExportWizardDialog
        dlg = ExportWizardDialog(ds, task_type, parent=self.window())
        if not dlg.exec():
            return
        opts = dlg.export_options()
        if opts["out_dir"] is None:
            return

        self._run_export(ds, opts)

    def _run_export(self, dataset, opts: dict) -> None:
        """Execute export in a BatchWorker — Schema.writer-driven (v1.2 §5.5)."""
        if self._export_worker is not None and self._export_worker.isRunning():
            return
        from core.schema import get as get_schema
        from core.splitter import SplitOptions, split_dataset

        schema = get_schema(opts["format"])
        if schema is None:
            InfoBar.error(
                "导出失败", f"未注册的格式:{opts['format']}",
                parent=self.window(), duration=4000,
                position=InfoBarPosition.TOP,
            )
            return

        split_opts = SplitOptions(
            train=opts["train_ratio"],
            val=opts["val_ratio"],
            test=opts["test_ratio"],
        )
        split = split_dataset(dataset, split_opts)
        out_dir = opts["out_dir"]
        copy_images = opts["copy_images"]

        # Build options from the schema's declared options_class.
        # Only pass copy_images if the dataclass supports it (ShareGPT does,
        # some future schemas might not).
        opt_fields = schema.options_class.__dataclass_fields__
        kwargs: dict = {"out_dir": out_dir}
        if "copy_images" in opt_fields:
            kwargs["copy_images"] = copy_images
        options = schema.options_class(**kwargs)

        def task(progress_cb):
            return schema.writer(split, options, progress_cb=progress_cb)

        from gui.dialogs.op_dialogs import ProgressDialog
        from gui.workers.batch_worker import BatchWorker

        progress = ProgressDialog("导出数据集", parent=self.window())
        progress.show()

        worker = BatchWorker(task)

        def on_progress(done, total, name):
            progress.set_progress(done, total, name)

        def on_done(result):
            progress.accept()
            count = getattr(result, "written_images", 0)
            InfoBar.success(
                "导出完成",
                f"{count} 张图片已导出到 {out_dir}",
                parent=self.window(), duration=5000,
                position=InfoBarPosition.TOP,
            )

        def on_fail(msg):
            progress.accept()
            InfoBar.error(
                "导出失败", msg,
                parent=self.window(), duration=5000,
                position=InfoBarPosition.TOP,
            )

        worker.progress.connect(on_progress)
        worker.finished_ok.connect(on_done)
        worker.failed.connect(on_fail)
        worker.start()
        self._export_worker = worker

    def _set_tools_enabled(self, enabled: bool) -> None:
        """Enable/disable all toolbar buttons."""
        for btn in (self._refresh_btn, self._export_btn, self._quality_btn,
                    self._dedup_btn, self._history_btn, self._stats_btn):
            btn.setEnabled(enabled)

    def _on_history(self) -> None:
        """Show the operation history for the current dataset."""
        ds = self._state.dataset
        if ds is None:
            return
        from gui.dialogs.history_dialog import HistoryDialog
        HistoryDialog(ds.root_path, parent=self.window()).exec()

    def _all_images(self) -> list:
        """Collect all images from current dataset."""
        ds = self._state.dataset
        if ds is None:
            return []
        return [img for cat in ds.categories for img in cat.images]

    def _on_dataset_changed(self, ds) -> None:
        """Single rendering path for dataset changes.

        AppState is the truth; this handler is the one place that
        reacts to changes and rebuilds the browser + topbar. Having it
        the only write path removes the stale-guard hack that used to
        read BrowserView._dataset (now deleted).
        """
        if ds is None:
            self._path_label.setText("未选择目录")
            self._stats_label.setText("")
            self._set_tools_enabled(False)
            return
        self._path_label.setText(str(ds.root_path))
        self._stats_label.setText(
            f"{ds.total_images} 图片 · {len(ds.categories)} 类"
        )
        # Tools only useful when we actually have images
        self._set_tools_enabled(ds.total_images > 0)
        self._browser.load_dataset(ds)

    # -- Tool handlers --

    def _on_quality_check(self) -> None:
        """Run quality check on all images."""
        images = self._all_images()
        if not images:
            return

        from gui.dialogs.tool_dialogs import QualityCheckDialog
        dlg = QualityCheckDialog(parent=self.window())
        if not dlg.exec():
            return

        from core.quality import QualityOptions, check_images
        from gui.workers.batch_runner import BatchRunner
        opts = QualityOptions(blur_threshold=dlg.blur_threshold())

        def handle(issues):
            if not issues:
                self._browser.set_quality_issues({})
                InfoBar.success("质量检查完成", "未发现问题图片",
                                parent=self.window(), duration=3000,
                                position=InfoBarPosition.TOP)
                return
            issues_map = {str(i.image.path): i.kinds for i in issues}
            self._browser.set_quality_issues(issues_map)
            from collections import Counter
            kind_counts: Counter = Counter()
            for issue in issues:
                for k in issue.kinds:
                    kind_counts[k] += 1
            kind_names = {"blur": "模糊", "blank": "空白",
                          "over": "过曝", "under": "欠曝", "corrupt": "损坏"}
            parts = [f"{c} {kind_names.get(k, k)}"
                     for k, c in kind_counts.most_common()]
            InfoBar.warning(
                f"发现 {len(issues)} 张问题图片",
                " · ".join(parts) + " · 缩略图已标红角，可用 \"有问题\" 筛选",
                parent=self.window(), duration=8000,
                position=InfoBarPosition.TOP,
            )

        BatchRunner(self, "质量检查").run(
            task=lambda cb: check_images(images, opts, progress_cb=cb),
            on_done=handle,
        )

    def _on_dedup(self) -> None:
        """Run duplicate detection."""
        images = self._all_images()
        if not images:
            return

        from gui.dialogs.tool_dialogs import DedupDialog
        dlg = DedupDialog(parent=self.window())
        if not dlg.exec():
            return
        threshold = dlg.threshold()

        from core.dedup import find_duplicates
        from gui.workers.batch_runner import BatchRunner

        def handle(groups):
            if not groups:
                InfoBar.success("重复检测完成", "未发现重复图片",
                                parent=self.window(), duration=3000,
                                position=InfoBarPosition.TOP)
                return
            from gui.dialogs.tool_dialogs import DedupResultDialog
            result_dlg = DedupResultDialog(groups, parent=self.window())
            if result_dlg.exec():
                self._delete_duplicates(result_dlg.groups)

        BatchRunner(self, "重复检测").run(
            task=lambda cb: find_duplicates(images, threshold=threshold,
                                            progress_cb=cb),
            on_done=handle,
        )

    def _delete_duplicates(self, groups) -> None:
        """Delete duplicate images (keep first in each group).

        Records the action to history.jsonl so a future undo phase can
        locate the trashed files — send2trash is recoverable from the
        OS recycle bin but not always from inside the app.
        """
        import logging
        from send2trash import send2trash
        log = logging.getLogger(__name__)
        deleted = 0
        failed = 0
        trashed_paths: list[str] = []
        for g in groups:
            for img in g.images[1:]:
                try:
                    send2trash(str(img.path))
                    if img.label_path and img.label_path.exists():
                        send2trash(str(img.label_path))
                    deleted += 1
                    trashed_paths.append(str(img.path))
                except Exception:
                    log.exception("send2trash failed for %s", img.path)
                    failed += 1
        # Record to history (best-effort — doesn't block rescan on failure)
        ds = self._state.dataset
        if ds is not None:
            try:
                from core import history as _hist
                _hist.append(
                    ds.root_path,
                    _hist.HistoryEntry.now(
                        action="delete-duplicates",
                        params={
                            "group_count": len(groups),
                            "deleted": deleted,
                            "failed": failed,
                            "trashed": trashed_paths,
                        },
                        ok=failed == 0,
                        summary=f"删除重复图片 {deleted} 张到回收站"
                                + (f"（{failed} 失败）" if failed else ""),
                    ),
                )
            except Exception:
                log.exception("history append failed after delete-duplicates")
        if failed:
            InfoBar.warning(
                "部分删除失败",
                f"成功 {deleted} 张，{failed} 张失败（查看日志）",
                parent=self.window(), duration=6000,
                position=InfoBarPosition.TOP,
            )
        else:
            InfoBar.success("删除完成", f"已移除 {deleted} 张重复图片到回收站",
                            parent=self.window(), duration=5000,
                            position=InfoBarPosition.TOP)
        self._rescan()

    def _on_stats(self) -> None:
        """Compute and show dataset statistics."""
        ds = self._state.dataset
        if ds is None:
            return

        from core.stats import compute_extended_stats, compute_stats
        from gui.workers.batch_runner import BatchRunner
        stats = compute_stats(ds)  # fast, no worker

        def show_dialog(extended):
            from gui.dialogs.tool_dialogs import StatsResultDialog
            StatsResultDialog(stats, extended, parent=self.window()).exec()

        BatchRunner(self, "计算详细统计").run(
            task=lambda cb: compute_extended_stats(ds, progress_cb=cb),
            on_done=show_dialog,
            # Extended stats is best-effort — on failure still show basic
            on_fail=lambda _msg: show_dialog(None),
        )
