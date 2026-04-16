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

        self._export_btn = PushButton("导出")
        self._export_btn.setIcon(FIF.SHARE)
        self._export_btn.setFixedWidth(80)
        self._export_btn.setEnabled(False)
        self._export_btn.clicked.connect(self._on_export)
        tbar_lay.addWidget(self._export_btn)

        self._quality_btn = PushButton("质量检查")
        self._quality_btn.setIcon(FIF.SEARCH)
        self._quality_btn.setFixedWidth(100)
        self._quality_btn.setEnabled(False)
        self._quality_btn.clicked.connect(self._on_quality_check)
        tbar_lay.addWidget(self._quality_btn)

        self._dedup_btn = PushButton("去重")
        self._dedup_btn.setIcon(FIF.COPY)
        self._dedup_btn.setFixedWidth(80)
        self._dedup_btn.setEnabled(False)
        self._dedup_btn.clicked.connect(self._on_dedup)
        tbar_lay.addWidget(self._dedup_btn)

        self._augment_btn = PushButton("增强")
        self._augment_btn.setIcon(FIF.ADD)
        self._augment_btn.setFixedWidth(80)
        self._augment_btn.setEnabled(False)
        self._augment_btn.clicked.connect(self._on_augment)
        tbar_lay.addWidget(self._augment_btn)

        tbar_lay.addStretch()

        self._stats_btn = PushButton("统计")
        self._stats_btn.setIcon(FIF.HISTORY)
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

        # Re-scan when browser reports category changes
        self._browser.dataset_changed.connect(self._rescan)

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

    def _scan_dir(self, root: Path) -> None:
        """Scan a directory and load into browser."""
        if self._scan_worker is not None and self._scan_worker.isRunning():
            return
        self._path_label.setText(str(root))
        self._open_btn.setEnabled(False)
        self._stats_label.setText("扫描中…")

        from gui.dialogs.op_dialogs import ProgressDialog
        progress = ProgressDialog("扫描数据集", parent=self.window())
        progress.show()

        from gui.workers.scan_worker import ScanWorker
        worker = ScanWorker(root, parent=self)
        self._scan_worker = worker

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

        worker.progress.connect(on_progress)
        worker.finished_ok.connect(on_done)
        worker.failed.connect(on_fail)
        worker.start()

    def _rescan(self) -> None:
        """Re-scan after file ops (delete/rename/move)."""
        if self._scan_worker is not None and self._scan_worker.isRunning():
            return
        ds = self._state.dataset
        if ds is None:
            return
        root = ds.root_path

        from gui.workers.scan_worker import ScanWorker
        worker = ScanWorker(root, parent=self)
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
        """Execute export in a BatchWorker."""
        if self._export_worker is not None and self._export_worker.isRunning():
            return
        from core.splitter import SplitOptions, split_dataset
        from core.exporter.registry import run_export

        split_opts = SplitOptions(
            train=opts["train_ratio"],
            val=opts["val_ratio"],
            test=opts["test_ratio"],
        )
        split = split_dataset(dataset, split_opts)
        out_dir = opts["out_dir"]
        fmt = opts["format"]
        copy_images = opts["copy_images"]

        def task(progress_cb):
            return run_export(fmt, split, out_dir, copy_images=copy_images,
                              progress_cb=progress_cb)

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
        for btn in (self._export_btn, self._quality_btn, self._dedup_btn,
                    self._augment_btn, self._stats_btn):
            btn.setEnabled(enabled)

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
        opts = QualityOptions(blur_threshold=dlg.blur_threshold())

        from gui.dialogs.op_dialogs import ProgressDialog
        from gui.workers.batch_worker import BatchWorker

        progress = ProgressDialog("质量检查", parent=self.window())
        progress.show()

        def task(progress_cb):
            return check_images(images, opts, progress_cb=progress_cb)

        worker = BatchWorker(task)
        worker.progress.connect(
            lambda d, t, n: progress.set_progress(d, t, n))

        def on_done(issues):
            progress.accept()
            if not issues:
                # Clear any prior quality state
                self._browser.set_quality_issues({})
                InfoBar.success("质量检查完成", "未发现问题图片",
                                parent=self.window(), duration=3000,
                                position=InfoBarPosition.TOP)
                return
            # Push results into the browser so the grid shows red badges
            # and the "有问题" filter chip becomes enabled.
            issues_map = {str(issue.image.path): issue.kinds for issue in issues}
            self._browser.set_quality_issues(issues_map)
            # Summarize by kind
            from collections import Counter
            kind_counts = Counter()
            for issue in issues:
                for k in issue.kinds:
                    kind_counts[k] += 1
            parts = []
            kind_names = {"blur": "模糊", "blank": "空白",
                          "over": "过曝", "under": "欠曝", "corrupt": "损坏"}
            for k, c in kind_counts.most_common():
                parts.append(f"{c} {kind_names.get(k, k)}")
            InfoBar.warning(
                f"发现 {len(issues)} 张问题图片",
                " · ".join(parts) + " · 缩略图已标红角，可用 \"有问题\" 筛选",
                parent=self.window(), duration=8000,
                position=InfoBarPosition.TOP,
            )

        def on_fail(msg):
            progress.accept()
            InfoBar.error("质量检查失败", msg,
                          parent=self.window(), duration=5000,
                          position=InfoBarPosition.TOP)

        worker.finished_ok.connect(on_done)
        worker.failed.connect(on_fail)
        worker.start()
        self._quality_worker = worker

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
        from gui.dialogs.op_dialogs import ProgressDialog
        from gui.workers.batch_worker import BatchWorker

        progress = ProgressDialog("重复检测", parent=self.window())
        progress.show()

        def task(progress_cb):
            return find_duplicates(images, threshold=threshold,
                                   progress_cb=progress_cb)

        worker = BatchWorker(task)
        worker.progress.connect(
            lambda d, t, n: progress.set_progress(d, t, n))

        def on_done(groups):
            progress.accept()
            if not groups:
                InfoBar.success("重复检测完成", "未发现重复图片",
                                parent=self.window(), duration=3000,
                                position=InfoBarPosition.TOP)
                return
            from gui.dialogs.tool_dialogs import DedupResultDialog
            result_dlg = DedupResultDialog(groups, parent=self.window())
            if result_dlg.exec():
                self._delete_duplicates(result_dlg.groups)

        def on_fail(msg):
            progress.accept()
            InfoBar.error("重复检测失败", msg,
                          parent=self.window(), duration=5000,
                          position=InfoBarPosition.TOP)

        worker.finished_ok.connect(on_done)
        worker.failed.connect(on_fail)
        worker.start()
        self._dedup_worker = worker

    def _delete_duplicates(self, groups) -> None:
        """Delete duplicate images (keep first in each group)."""
        import logging
        from send2trash import send2trash
        log = logging.getLogger(__name__)
        deleted = 0
        failed = 0
        for g in groups:
            for img in g.images[1:]:
                try:
                    send2trash(str(img.path))
                    if img.label_path and img.label_path.exists():
                        send2trash(str(img.label_path))
                    deleted += 1
                except Exception:
                    log.exception("send2trash failed for %s", img.path)
                    failed += 1
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

    def _on_augment(self) -> None:
        """Run data augmentation."""
        images = self._all_images()
        if not images:
            return

        # Look at current selection so the dialog can offer "仅已选中"
        selected = self._browser.get_selected_images()

        from gui.dialogs.tool_dialogs import AugmentDialog
        dlg = AugmentDialog(parent=self.window(),
                            selected_count=len(selected))
        if not dlg.exec():
            return
        aug_opts = dlg.options()
        if aug_opts["out_dir"] is None:
            return

        # Honor source choice
        source_imgs = (selected if aug_opts.get("source") == "selected"
                       else images)
        if not source_imgs:
            InfoBar.warning("没有可用图片", "请先选中图片或切换到\"全部\"",
                            parent=self.window(), duration=4000,
                            position=InfoBarPosition.TOP)
            return

        from core.augment import augment_batch
        from gui.dialogs.op_dialogs import ProgressDialog
        from gui.workers.batch_worker import BatchWorker

        image_paths = [img.path for img in source_imgs]
        out_dir = aug_opts["out_dir"]
        opts = aug_opts["opts"]

        progress = ProgressDialog("数据增强", parent=self.window())
        progress.show()

        def task(progress_cb):
            return augment_batch(image_paths, out_dir, opts,
                                 progress_cb=progress_cb)

        worker = BatchWorker(task)
        worker.progress.connect(
            lambda d, t, n: progress.set_progress(d, t, n))

        def on_done(result):
            progress.accept()
            InfoBar.success(
                "增强完成",
                f"生成 {result.count} 张增强图片到 {out_dir}",
                parent=self.window(), duration=5000,
                position=InfoBarPosition.TOP,
            )

        def on_fail(msg):
            progress.accept()
            InfoBar.error("增强失败", msg,
                          parent=self.window(), duration=5000,
                          position=InfoBarPosition.TOP)

        worker.finished_ok.connect(on_done)
        worker.failed.connect(on_fail)
        worker.start()
        self._augment_worker = worker

    def _on_stats(self) -> None:
        """Compute and show dataset statistics."""
        ds = self._state.dataset
        if ds is None:
            return

        from core.stats import compute_extended_stats, compute_stats
        from gui.dialogs.op_dialogs import ProgressDialog
        from gui.workers.batch_worker import BatchWorker

        stats = compute_stats(ds)  # fast, no worker needed

        progress = ProgressDialog("计算详细统计", parent=self.window())
        progress.show()

        def task(progress_cb):
            return compute_extended_stats(ds, progress_cb=progress_cb)

        worker = BatchWorker(task)
        worker.progress.connect(
            lambda d, t, n: progress.set_progress(d, t, n))

        def on_done(extended):
            progress.accept()
            from gui.dialogs.tool_dialogs import StatsResultDialog
            dlg = StatsResultDialog(stats, extended, parent=self.window())
            dlg.exec()

        def on_fail(msg):
            progress.accept()
            # Show basic stats even if extended fails
            from gui.dialogs.tool_dialogs import StatsResultDialog
            dlg = StatsResultDialog(stats, None, parent=self.window())
            dlg.exec()

        worker.finished_ok.connect(on_done)
        worker.failed.connect(on_fail)
        worker.start()
        self._stats_worker = worker
