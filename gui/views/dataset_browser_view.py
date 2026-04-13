"""Top-level dataset browser — standalone view, no pipeline dependency.

Extracted from pipeline_view._make_datasource_ws(). Wraps BrowserView +
DetailView + ThumbnailWorker + ScanWorker into a self-contained top-level
widget for MainWindow navigation.
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

        tbar_lay.addStretch()
        lay.addWidget(toolbar)

        # -- Browser + Detail stack --
        self._browser_stack = QStackedWidget()
        self._browser = BrowserView()
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
        self._thumb.requestInterruption()
        self._thumb.wait(3000)

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
            self._stats_label.setText(
                f"{ds.total_images} 图片 · {len(ds.categories)} 类"
            )
            self._browser.load_dataset(ds)
            self._export_btn.setEnabled(True)
            # Broadcast to all views via AppState
            self._state.set_dataset(ds)

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
            self._browser.load_dataset(ds)
            self._stats_label.setText(
                f"{ds.total_images} 图片 · {len(ds.categories)} 类"
            )
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
        from core.splitter import SplitOptions, split_dataset

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
            if fmt == "YOLO":
                from core.exporter.yolo import YoloExportOptions, export_yolo
                return export_yolo(split, YoloExportOptions(out_dir=out_dir, copy_images=copy_images), progress_cb)
            elif fmt == "COCO":
                from core.exporter.coco import CocoExportOptions, export_coco
                return export_coco(split, CocoExportOptions(out_dir=out_dir), progress_cb)
            elif fmt == "Pascal VOC":
                from core.exporter.voc import VocExportOptions, export_voc
                return export_voc(split, VocExportOptions(out_dir=out_dir), progress_cb)
            elif fmt == "JSON Lines":
                from core.exporter.jsonl import JsonlExportOptions, export_jsonl
                return export_jsonl(split, JsonlExportOptions(out_dir=out_dir, copy_images=copy_images), progress_cb)
            elif fmt == "ShareGPT":
                from core.exporter.sharegpt import ShareGptExportOptions, export_sharegpt
                return export_sharegpt(split, ShareGptExportOptions(out_dir=out_dir), progress_cb)
            elif fmt == "ms-swift":
                from core.exporter.swift import SwiftExportOptions, export_swift
                return export_swift(split, SwiftExportOptions(out_dir=out_dir), progress_cb)
            elif fmt == "LLaVA":
                from core.exporter.llava import LlavaExportOptions, export_llava
                return export_llava(split, LlavaExportOptions(out_dir=out_dir, copy_images=copy_images), progress_cb)
            elif fmt == "CSV":
                from core.exporter.csv_export import export_csv_dataset
                return export_csv_dataset(split, out_dir, progress_cb)
            else:
                raise ValueError(f"不支持的导出格式: {fmt}")

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

    def _on_dataset_changed(self, ds) -> None:
        """Receive dataset update from AppState (e.g. from pipeline rescan)."""
        if ds is None:
            self._path_label.setText("未选择目录")
            self._stats_label.setText("")
            return
        # Avoid re-loading if we are the source of this signal
        if ds is self._state.dataset:
            self._path_label.setText(str(ds.root_path))
            self._stats_label.setText(
                f"{ds.total_images} 图片 · {len(ds.categories)} 类"
            )
            # Only reload browser if it doesn't already have this dataset
            if getattr(self._browser, '_dataset', None) is not ds:
                self._browser.load_dataset(ds)
