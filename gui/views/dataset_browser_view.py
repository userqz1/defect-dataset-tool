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

        # Undo MVP: reverses only the most recent reversible op
        # (move-to-category / rename-category). Other ops stay as audit log.
        self._undo_btn = PushButton("撤销")
        self._undo_btn.setIcon(FIF.CANCEL)
        self._undo_btn.setFixedWidth(80)
        self._undo_btn.setEnabled(False)
        self._undo_btn.clicked.connect(self._on_undo)
        tbar_lay.addWidget(self._undo_btn)

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

        # "处理" dropdown — transform / convert / augment / predict.
        # All core modules (transform / convert / augment / predictor)
        # had no GUI entry point before this; review stage 2.
        self._process_btn = PushButton("处理")
        self._process_btn.setIcon(FIF.DEVELOPER_TOOLS)
        self._process_btn.setFixedWidth(90)
        self._process_btn.setEnabled(False)
        self._process_btn.clicked.connect(self._show_process_menu)
        tbar_lay.addWidget(self._process_btn)

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
        # In-detail "改分类" (review #21) — DetailView emits, outer view
        # performs fileops.move_to_category and triggers force rescan.
        self._detail.change_category_requested.connect(self._on_change_category)

        self._browser_stack.addWidget(self._browser)
        self._browser_stack.addWidget(self._detail)
        lay.addWidget(self._browser_stack, 1)

        # Re-scan when browser reports file-system changes (delete / move /
        # category ops). force=True so fingerprint-based cache-hit doesn't
        # serve stale data — the user just intentionally modified files.
        self._browser.dataset_changed.connect(
            lambda: self._rescan(force=True)
        )

        # "加入手动划分 → Train/Val/Test" was emitting into the void before
        # (review #9). Hook it to SplitState so the selection actually
        # persists across sessions.
        self._browser.add_to_split.connect(self._on_add_to_split)

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
            if isinstance(result, ScanResult):
                ds, ext = result.dataset, result.ext_stats
            else:
                ds, ext = result, None
            # Single write: AppState → dataset_changed signal →
            # _on_dataset_changed updates the topbar + browser. No dual
            # writes to both self._browser and self._state.
            self._state.set_dataset(ds)
            # set_dataset cleared derived artifacts; push the fresh
            # ExtendedStats back so downstream views (future stats panel)
            # get it without waiting for another scan.
            if ext is not None:
                self._state.set_ext_stats(ext)
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
            if isinstance(result, ScanResult):
                ds, ext = result.dataset, result.ext_stats
            else:
                ds, ext = result, None
            # Same single-write pattern as the initial scan — the
            # dataset_changed handler re-renders everything.
            self._state.set_dataset(ds)
            if ext is not None:
                self._state.set_ext_stats(ext)

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
        """Execute export as a Pipeline (v1.2 §4.3 + §5.5).

        Runs ``Pipeline([SplitStep, ExportStep])`` so the Pipeline
        abstraction has a real GUI consumer — previously the wizard
        hand-rolled schema.writer, leaving core/pipeline/ unused.
        Adding QualityStep/DedupStep here in v0.2 just means appending
        to the steps list.
        """
        if self._export_worker is not None and self._export_worker.isRunning():
            return
        from core.schema import get as get_schema
        from core.pipeline import (
            ExportStep, Pipeline, PipelineContext, SplitStep,
        )

        schema = get_schema(opts["format"])
        if schema is None:
            InfoBar.error(
                "导出失败", f"未注册的格式:{opts['format']}",
                parent=self.window(), duration=4000,
                position=InfoBarPosition.TOP,
            )
            return

        out_dir = opts["out_dir"]
        pipe = Pipeline(
            name=f"{schema.display_name} 导出",
            steps=[
                SplitStep(
                    train=opts["train_ratio"],
                    val=opts["val_ratio"],
                    test=opts["test_ratio"],
                ),
                ExportStep(
                    schema_key=opts["format"],
                    out_dir=out_dir,
                    copy_images=opts["copy_images"],
                ),
            ],
        )
        ctx = PipelineContext(dataset=dataset)

        def task(progress_cb):
            return pipe.run(ctx, progress_cb=progress_cb)

        from gui.dialogs.op_dialogs import ProgressDialog
        from gui.workers.batch_worker import BatchWorker

        progress = ProgressDialog("导出数据集", parent=self.window())
        progress.show()

        worker = BatchWorker(task)

        def on_progress(done, total, name):
            progress.set_progress(done, total, name)

        def on_done(result):
            # ``result`` is PipelineResult now; drill in to the per-step
            # ExportReport for the image count.
            progress.accept()
            if not result.ok:
                msg = " | ".join(f"{name}: {err}" for name, err in result.errors)
                InfoBar.error(
                    "导出失败", msg or "未知错误",
                    parent=self.window(), duration=6000,
                    position=InfoBarPosition.TOP,
                )
                return
            reports = result.context.export_reports
            count = getattr(reports[0], "written_images", 0) if reports else 0
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
                    self._dedup_btn, self._process_btn,
                    self._history_btn, self._stats_btn):
            btn.setEnabled(enabled)
        # Undo button is independent — gated on whether a reversible op
        # exists in history, not just on dataset presence.
        self._refresh_undo_enabled()

    def _refresh_undo_enabled(self) -> None:
        """Poll history for a reversible entry; called after dataset_changed."""
        ds = self._state.dataset
        if ds is None:
            self._undo_btn.setEnabled(False)
            return
        from core.history import find_last_undoable
        try:
            entry = find_last_undoable(ds.root_path)
        except Exception:
            logger.exception("find_last_undoable failed")
            entry = None
        self._undo_btn.setEnabled(entry is not None)
        if entry is not None:
            self._undo_btn.setToolTip(f"撤销: {entry.summary}")
        else:
            self._undo_btn.setToolTip("没有可撤销的操作")

    def _on_undo(self) -> None:
        """Reverse the last undoable op via core.history.try_undo_last."""
        ds = self._state.dataset
        if ds is None:
            return
        from core.history import try_undo_last
        try:
            ok, msg = try_undo_last(ds.root_path)
        except Exception as e:
            logger.exception("try_undo_last raised")
            InfoBar.error("撤销失败", str(e),
                          parent=self.window(), duration=5000,
                          position=InfoBarPosition.TOP)
            return
        if ok:
            InfoBar.success("撤销成功", msg,
                            parent=self.window(), duration=4000,
                            position=InfoBarPosition.TOP)
            # Force rescan — disk changed, index cache is now stale
            self._rescan(force=True)
        else:
            InfoBar.warning("撤销失败", msg,
                            parent=self.window(), duration=4000,
                            position=InfoBarPosition.TOP)

    # -- 处理 (transform / convert / augment / predict) ----------------

    def _show_process_menu(self) -> None:
        """Open the 处理 dropdown menu anchored under the button."""
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)

        transform_menu = menu.addMenu("变换")
        transform_menu.addAction("缩放…", self._on_resize)
        transform_menu.addAction("裁剪…", self._on_crop)
        transform_menu.addAction("旋转…", self._on_rotate)
        transform_menu.addAction("翻转…", self._on_flip)
        menu.addAction("格式转换…", self._on_convert)
        menu.addAction("数据增强…", self._on_augment)
        menu.addAction("AI 预标注…", self._on_predict)

        # Anchor below the button
        pos = self._process_btn.mapToGlobal(
            self._process_btn.rect().bottomLeft())
        menu.exec(pos)

    def _run_transform(self, dlg_cls, op_fn, dlg_title_for_runner: str) -> None:
        """Shared plumbing for 4 transforms — dialog → BatchRunner."""
        n = self._image_count()
        if n == 0:
            return
        dlg = dlg_cls(n, parent=self.window())
        if not dlg.exec():
            return
        opts = dlg.options()
        paths = [img.path for img in self._all_images()]
        from core.transform import batch_apply
        from gui.workers.batch_runner import BatchRunner

        def handle(result):
            ok = len(getattr(result, "succeeded", []))
            fail = len(getattr(result, "failed", []))
            if fail:
                InfoBar.warning(
                    dlg_title_for_runner + "完成",
                    f"成功 {ok} · 失败 {fail} · 可能需刷新",
                    parent=self.window(), duration=5000,
                    position=InfoBarPosition.TOP,
                )
            else:
                InfoBar.success(
                    dlg_title_for_runner + "完成",
                    f"处理 {ok} 张 · 点刷新查看",
                    parent=self.window(), duration=4000,
                    position=InfoBarPosition.TOP,
                )

        BatchRunner(self, dlg_title_for_runner).run(
            task=lambda cb: batch_apply(paths, op_fn, opts, progress_cb=cb),
            on_done=handle,
        )

    def _on_resize(self) -> None:
        from core.transform import resize_one
        from gui.dialogs.batch_ops import ResizeDialog
        self._run_transform(ResizeDialog, resize_one, "批量缩放")

    def _on_crop(self) -> None:
        from core.transform import crop_one
        from gui.dialogs.batch_ops import CropDialog
        self._run_transform(CropDialog, crop_one, "批量裁剪")

    def _on_rotate(self) -> None:
        from core.transform import rotate_one
        from gui.dialogs.batch_ops import RotateDialog
        self._run_transform(RotateDialog, rotate_one, "批量旋转")

    def _on_flip(self) -> None:
        from core.transform import flip_one
        from gui.dialogs.batch_ops import FlipDialog
        self._run_transform(FlipDialog, flip_one, "批量翻转")

    def _on_convert(self) -> None:
        n = self._image_count()
        if n == 0:
            return
        from gui.dialogs.batch_ops import ConvertDialog
        dlg = ConvertDialog(n, parent=self.window())
        if not dlg.exec():
            return
        opts = dlg.options()
        paths = [img.path for img in self._all_images()]

        from core.convert import convert_batch
        from gui.workers.batch_runner import BatchRunner

        def handle(result):
            ok = len(getattr(result, "succeeded", []))
            fail = len(getattr(result, "failed", []))
            msg = f"成功 {ok} · 失败 {fail}" if fail else f"转换 {ok} 张 · 点刷新查看"
            (InfoBar.warning if fail else InfoBar.success)(
                "格式转换完成", msg,
                parent=self.window(), duration=4000,
                position=InfoBarPosition.TOP,
            )

        BatchRunner(self, "格式转换").run(
            task=lambda cb: convert_batch(paths, opts, progress_cb=cb),
            on_done=handle,
        )

    def _on_augment(self) -> None:
        n = self._image_count()
        if n == 0:
            return
        from gui.dialogs.batch_ops import AugmentDialog
        dlg = AugmentDialog(n, parent=self.window())
        if not dlg.exec():
            return
        cfg = dlg.options()
        out_dir = cfg["out_dir"]
        aug_opts = cfg["opts"]
        paths = [img.path for img in self._all_images()]

        from core.augment import augment_batch
        from gui.workers.batch_runner import BatchRunner

        def handle(result):
            InfoBar.success(
                "数据增强完成",
                f"生成 {result.count} 张增强图片到 "
                f"{out_dir.name if out_dir else ''}",
                parent=self.window(), duration=5000,
                position=InfoBarPosition.TOP,
            )

        BatchRunner(self, "数据增强").run(
            task=lambda cb: augment_batch(paths, out_dir, aug_opts, progress_cb=cb),
            on_done=handle,
        )

    def _on_predict(self) -> None:
        n_all = self._image_count()
        if n_all == 0:
            return
        # Count un-labeled to set dialog header
        all_imgs = list(self._all_images())
        unlabeled = [img for img in all_imgs if not img.has_label]
        from gui.dialogs.batch_ops import PredictDialog
        dlg = PredictDialog(len(unlabeled), parent=self.window())
        if not dlg.exec():
            return
        cfg = dlg.options()

        from core.predictor import YoloPredictor, predict_batch
        from gui.workers.batch_runner import BatchRunner

        predictor = YoloPredictor(
            model_name=cfg["model_name"], conf=cfg["conf"])
        if not predictor.is_available():
            InfoBar.error(
                "AI 预标注失败",
                "ultralytics 未安装,请 pip install ultralytics 后重试",
                parent=self.window(), duration=6000,
                position=InfoBarPosition.TOP,
            )
            return

        # Scope: unlabeled only unless overwrite checked
        target_paths = ([img.path for img in all_imgs]
                        if cfg["overwrite"]
                        else [img.path for img in unlabeled])
        if not target_paths:
            InfoBar.info("", "没有待处理的图片(全部已标注)",
                         parent=self.window(), duration=3000,
                         position=InfoBarPosition.TOP)
            return

        def handle(result):
            msg = (f"成功 {len(result.written)} · "
                   f"跳过 {len(result.skipped)} · "
                   f"失败 {len(result.failed)}")
            (InfoBar.warning if result.failed else InfoBar.success)(
                "AI 预标注完成", msg + " · 点刷新查看",
                parent=self.window(), duration=5000,
                position=InfoBarPosition.TOP,
            )

        BatchRunner(self, "AI 预标注").run(
            task=lambda cb: predict_batch(
                target_paths, predictor,
                overwrite=cfg["overwrite"], progress_cb=cb),
            on_done=handle,
        )

    def _on_history(self) -> None:
        """Show the operation history for the current dataset."""
        ds = self._state.dataset
        if ds is None:
            return
        from gui.dialogs.history_dialog import HistoryDialog
        HistoryDialog(ds.root_path, parent=self.window()).exec()

    def _on_change_category(self, image, target: str) -> None:
        """Move the current image to `target` category + rescan (review #21).

        Invoked from DetailView's "改分类" button. One-image move via
        fileops.move_to_category; rescan is forced since mtime-based
        fingerprint checks might not catch single-file moves.
        """
        ds = self._state.dataset
        if ds is None or not target:
            return
        from core import fileops
        try:
            fileops.move_to_category([image], ds.root_path, target)
        except Exception as e:
            logger.exception("move_to_category failed in DetailView")
            InfoBar.error(
                "改分类失败", str(e),
                parent=self.window(), duration=5000,
                position=InfoBarPosition.TOP,
            )
            return
        InfoBar.success(
            "",
            f"已把 {image.path.name} 移到 {target}",
            parent=self.window(), duration=3000,
            position=InfoBarPosition.TOP,
        )
        # Send back to browser to re-render after rescan settles
        self._browser_stack.setCurrentWidget(self._browser)
        self._rescan(force=True)

    def _on_add_to_split(self, bucket: str, images: list) -> None:
        """Right-click → "加入手动划分 → Train/Val/Test" handler (review #9).

        Writes image paths into Project.split_state.manual_<bucket> and
        saves the project. Duplicates are de-duped; images already in
        other buckets get moved (a path can only live in one bucket at a
        time or SplitOptions(mode=manual) would double-count it).
        """
        project = self._state.project
        if project is None:
            return
        if bucket not in ("train", "val", "test"):
            return
        ss = project.split_state
        lists = {
            "train": ss.manual_train,
            "val": ss.manual_val,
            "test": ss.manual_test,
        }
        target = lists[bucket]
        # Strip from other buckets first — a given path belongs to exactly one.
        new_paths = [str(i.path) for i in images]
        for key, lst in lists.items():
            if key == bucket:
                continue
            lst[:] = [p for p in lst if p not in new_paths]
        # Dedupe + append to target bucket, preserving insertion order.
        seen = set(target)
        for p in new_paths:
            if p not in seen:
                target.append(p)
                seen.add(p)

        from core.project import save_project
        try:
            save_project(project)
        except Exception:
            logger.exception("save_project failed after add_to_split")

        bucket_cn = {"train": "训练集", "val": "验证集", "test": "测试集"}[bucket]
        InfoBar.success(
            "",
            f"已加入 {bucket_cn}:{len(new_paths)} 张 "
            f"(当前合计 {len(target)} 张)",
            parent=self.window(), duration=3500,
            position=InfoBarPosition.TOP,
        )

    def _all_images(self):
        """Iterate over all images in the current dataset.

        Returns an ``itertools.chain`` — no intermediate list copy, which
        matters for 50k+ datasets. Use ``_image_count()`` alongside if
        you need a length (core.quality / core.dedup need it for progress).
        """
        from itertools import chain
        ds = self._state.dataset
        if ds is None:
            return iter([])
        return chain.from_iterable(cat.images for cat in ds.categories)

    def _image_count(self) -> int:
        ds = self._state.dataset
        return ds.total_images if ds else 0

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
        n_images = self._image_count()
        if n_images == 0:
            return

        from gui.dialogs.tool_dialogs import QualityCheckDialog
        dlg = QualityCheckDialog(parent=self.window())
        if not dlg.exec():
            return

        from core.quality import QualityOptions, check_images
        from gui.workers.batch_runner import BatchRunner
        opts = QualityOptions(blur_threshold=dlg.blur_threshold())

        def handle(issues):
            # Push results to AppState — all views subscribe via
            # quality_changed signal; BrowserView auto-refreshes its grid.
            self._state.set_quality_issues(issues or None)
            if not issues:
                InfoBar.success("质量检查完成", "未发现问题图片",
                                parent=self.window(), duration=3000,
                                position=InfoBarPosition.TOP)
                return
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
            task=lambda cb: check_images(self._all_images(), opts,
                                          progress_cb=cb, total=n_images),
            on_done=handle,
        )

    def _on_dedup(self) -> None:
        """Run duplicate detection."""
        n_images = self._image_count()
        if n_images == 0:
            return

        from gui.dialogs.tool_dialogs import DedupDialog
        dlg = DedupDialog(parent=self.window())
        if not dlg.exec():
            return
        threshold = dlg.threshold()

        from core.dedup import find_duplicates
        from gui.workers.batch_runner import BatchRunner

        def handle(groups):
            # Store in AppState so future views (a dedicated dedup viz,
            # batch-delete panel, etc.) can read without re-running.
            self._state.set_duplicate_groups(groups or None)
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
            task=lambda cb: find_duplicates(
                self._all_images(), threshold=threshold,
                progress_cb=cb, total=n_images),
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
