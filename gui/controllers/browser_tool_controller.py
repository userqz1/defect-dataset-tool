"""Browser tool controller — tool action dispatch and execution.

Extracted from DatasetBrowserView to separate tool/op logic from
layout and widget assembly.
"""
from __future__ import annotations

import json
import logging
from itertools import chain
from typing import TYPE_CHECKING

from qfluentwidgets import InfoBar, InfoBarPosition

if TYPE_CHECKING:
    from gui.controllers.browser_runtime import BrowserRuntime
    from gui.controllers.dataset_session_controller import DatasetSessionController

logger = logging.getLogger(__name__)


class BrowserToolController:
    """Executes dataset-wide operations triggered by the stage hubs.

    Hubs (``ProjectHub`` / ``ReviewHub``) and the ``DatasetBar`` emit
    zero-arg "requested" signals; the shell wires each to a ``run_*``
    wrapper here.  There is no string-keyed dispatch anymore — every
    entry point is a typed method so callers get compile-time
    verification that the handler exists.
    """

    def __init__(
        self,
        rt: BrowserRuntime,
        session: DatasetSessionController,
    ) -> None:
        self._rt = rt
        self._session = session
        self._export_worker = None

    # -- Public API --

    def refresh_undo_state(self) -> None:
        self._session.refresh_undo_state()

    def change_category(self, image, target: str) -> None:
        self._on_change_category(image, target)

    def add_to_split(self, bucket: str, images: list) -> None:
        self._on_add_to_split(bucket, images)

    def cleanup_workers(self) -> None:
        if self._export_worker is not None:
            self._export_worker.quit()
            self._export_worker.wait(3000)

    # -- Run handlers (called by DatasetBar / stage hubs) --

    # DatasetBar — global toolbar actions
    def run_refresh(self) -> None:
        self._session.refresh()

    def run_undo(self) -> None:
        self._on_undo()

    # ProjectHub — format center
    def run_import_annot(self) -> None:
        self._on_import_annot()

    def run_convert_annot(self) -> None:
        self._on_convert_annot()

    def run_migrate_format(self) -> None:
        self._on_migrate_format()

    # ProjectHub — processing (batch image ops on the loaded dataset)
    def run_resize(self) -> None:
        self._on_resize()

    def run_crop(self) -> None:
        self._on_crop()

    def run_rotate(self) -> None:
        self._on_rotate()

    def run_flip(self) -> None:
        self._on_flip()

    def run_convert(self) -> None:
        self._on_convert()

    def run_augment(self) -> None:
        self._on_augment()

    def run_predict(self) -> None:
        self._on_predict()

    # ProjectHub — output & records
    def run_export(self, initial_fmt: str = "") -> None:
        """Open the export wizard.

        ``initial_fmt`` (optional) preselects a format card — used when
        the trigger is the LlmDataCard which already asked the user to
        pick LLaVA / ShareGPT / Swift / Caption JSONL.  Empty string
        falls back to "first visible card for the current task type".
        """
        self._on_export(initial_fmt)

    def run_history(self) -> None:
        self._on_history()

    # ReviewHub
    def run_quality(self) -> None:
        self._on_quality_check()

    def run_dedup(self) -> None:
        self._on_dedup()

    def run_stats(self) -> None:
        self._on_stats()

    # -- Helpers --

    def _window(self):
        return self._rt.shell.window()

    def _all_images(self):
        ds = self._rt.state.dataset
        if ds is None:
            return iter([])
        return chain.from_iterable(cat.images for cat in ds.categories)

    def _image_count(self) -> int:
        ds = self._rt.state.dataset
        return ds.total_images if ds else 0

    # -- Tool handlers --

    def _on_export(self, initial_fmt: str = "") -> None:
        ds = self._rt.state.dataset
        if ds is None:
            return
        task_type = self._rt.state.task_type

        project = self._rt.state.project
        if project is not None:
            ss = project.split_state
            manual_counts = (len(ss.manual_train), len(ss.manual_val),
                             len(ss.manual_test))
        else:
            manual_counts = (0, 0, 0)

        # Workflow counts for scope selector
        wf_summary = self._rt.state.workflow_summary
        wf_ready = wf_total = 0
        if wf_summary is not None:
            wf_ready = wf_summary.ready + wf_summary.exported
            wf_total = wf_summary.total

        # Carry the catalog tree's current category through as the
        # default scope so users coming from "I'm working on Loose"
        # don't have to reselect Loose from a 12-checkbox grid.
        try:
            initial_category = self._rt.browser.active_category()
        except AttributeError:
            initial_category = ""

        from gui.dialogs.export_wizard import ExportWizardDialog
        dlg = ExportWizardDialog(ds, task_type,
                                  manual_counts=manual_counts,
                                  wf_ready_count=wf_ready,
                                  wf_total_count=wf_total,
                                  initial_fmt=initial_fmt,
                                  initial_category=initial_category,
                                  parent=self._window())
        if not dlg.exec():
            return
        opts = dlg.export_options()
        if opts["out_dir"] is None:
            return
        # Reject "all categories unchecked" before any worker spins up.
        # ``categories=None`` means the wizard didn't show the row
        # (single-category dataset) — that's fine.  ``[]`` means the
        # user actively unchecked everything — refuse.
        if opts.get("categories") == []:
            InfoBar.warning(
                "未选类目", "请至少勾选一个类目",
                parent=self._window(), duration=3000,
                position=InfoBarPosition.TOP,
            )
            return
        self._run_export(ds, opts)

    def _run_export(self, dataset, opts: dict) -> None:
        # Guard: a previous worker may have completed and had its
        # underlying QObject destroyed by Qt (deleteLater) while the
        # Python ``self._export_worker`` reference still points at the
        # dead wrapper.  Calling ``isRunning()`` on a deleted wrapper
        # raises ``RuntimeError: wrapped C/C++ object ... has been
        # deleted``.  Treat any RuntimeError there as "no live
        # worker" and clear the stale ref so the new run can start.
        if self._export_worker is not None:
            try:
                if self._export_worker.isRunning():
                    return
            except RuntimeError:
                self._export_worker = None

        # --- Category filter (applies to BOTH paths) ---
        # When a non-None list is given, restrict the dataset (and the
        # SampleSet, downstream) to only those categories.  Done HERE,
        # before path selection, so the unified and pipeline branches
        # see consistent input.  ``None`` short-circuits — single-
        # category datasets never see the row in the wizard.
        cat_filter = opts.get("categories")
        if cat_filter is not None:
            dataset = self._filter_dataset_by_categories(dataset, cat_filter)

        # Unified model path: only when SampleSet is READY (authoritative).
        # STALE or UNAVAILABLE → fall back to pipeline (re-parse from disk).
        from gui.app_state import SampleSetStatus
        ss = self._rt.state.sample_set
        if ss is not None and self._rt.state.sample_set_ready:
            if cat_filter is not None:
                ss = self._filter_sampleset_by_categories(ss, cat_filter)
            self._run_export_unified(dataset, ss, opts)
            return
        self._run_export_pipeline(dataset, opts)

    @staticmethod
    def _filter_dataset_by_categories(dataset, names: list[str]):
        """Return a shallow-filtered Dataset containing only the named
        categories.  Counts are recomputed from kept categories so the
        downstream splitter / preview / pipeline see a self-consistent
        snapshot.  The original Dataset is never mutated.
        """
        from core.models import Dataset
        keep = set(names)
        kept_cats = [c for c in dataset.categories if c.name in keep]
        return Dataset(
            name=dataset.name,
            root_path=dataset.root_path,
            categories=kept_cats,
            total_images=sum(c.image_count for c in kept_cats),
            total_annotations=sum(c.label_count for c in kept_cats),
            layout=dataset.layout,
            fingerprint="",  # filtered view — invalidate fingerprint
        )

    @staticmethod
    def _filter_sampleset_by_categories(sample_set, names: list[str]):
        """Return a SampleSet containing only samples whose ``category``
        is in *names*.  Original is not mutated."""
        from core.unified import SampleSet
        keep = set(names)
        return SampleSet(samples=[s for s in sample_set.samples
                                  if s.category in keep])

    @staticmethod
    def _wrap_export_out_dir(picked_dir, fmt: str):
        """Wrap the user-picked directory in a self-contained subfolder.

        Why: format writers spray ``<out>/images/...`` AND
        ``<out>/swift_train.jsonl`` (etc.) into ``out``.  When the user
        picked their Desktop, the JSONLs ended up loose next to .lnk
        files and the images folder ended up alongside.  Forcing a
        subfolder named ``<format>_<timestamp>`` keeps every artifact
        of one export in one bag the user can move / delete / archive
        atomically.
        """
        import datetime
        from pathlib import Path
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = (fmt or "export").lower().replace(" ", "_")
        target = Path(picked_dir) / f"{slug}_{ts}"
        target.mkdir(parents=True, exist_ok=True)
        return target

    def _run_export_unified(self, dataset, sample_set, opts: dict) -> None:
        """Export via format_out (unified SampleSet path)."""
        from pathlib import Path as _P
        from core.format_out import ExportOptions, export_samples
        from core.splitter import SplitOptions, split_dataset
        from core.unified import SampleSet as _SS

        out_dir = self._wrap_export_out_dir(opts["out_dir"], opts["format"])
        fmt = opts["format"]
        extra = {}
        q = opts.get("question") or ""
        if q:
            extra["question"] = q

        # --- Workflow scope: filter to ready-only if requested ---
        export_scope = opts.get("export_scope", "all")
        if export_scope == "ready_only":
            ready_samples = [s for s in sample_set.samples
                             if s.work_status in ("ready", "exported")]
            sample_set = _SS(samples=ready_samples)

        # --- Assign split labels to SampleSet samples ---
        split_mode = opts.get("split_mode", "ratio")
        if split_mode == "manual":
            project = self._rt.state.project
            ps = project.split_state if project else None
            path_to_split: dict[str, str] = {}
            if ps:
                for p in ps.manual_train:
                    path_to_split[p] = "train"
                for p in ps.manual_val:
                    path_to_split[p] = "val"
                for p in ps.manual_test:
                    path_to_split[p] = "test"
            for s in sample_set.samples:
                s.split = path_to_split.get(str(s.image_path), "train")
        else:
            split_opts = SplitOptions(
                train=opts["train_ratio"],
                val=opts["val_ratio"],
                test=opts["test_ratio"],
                stratified=opts.get("stratified", True),
                seed=opts.get("seed", 42),
            )
            split_result = split_dataset(dataset, split_opts)
            # Map ImageInfo paths → split labels onto SampleSet
            path_to_split = {}
            for img in split_result.train:
                path_to_split[str(img.path)] = "train"
            for img in split_result.val:
                path_to_split[str(img.path)] = "val"
            for img in split_result.test:
                path_to_split[str(img.path)] = "test"
            for s in sample_set.samples:
                s.split = path_to_split.get(str(s.image_path), "train")

        export_opts = ExportOptions(
            out_dir=_P(out_dir) if not isinstance(out_dir, _P) else out_dir,
            copy_images=opts["copy_images"],
            question=q or "请描述这张图片中的内容。",
        )

        def task(progress_cb):
            return export_samples(sample_set, fmt, export_opts,
                                  progress_cb=progress_cb)

        from gui.dialogs.op_dialogs import ProgressDialog
        from gui.workers.batch_worker import BatchWorker

        progress = ProgressDialog("导出数据集", parent=self._window())
        progress.show()

        worker = BatchWorker(task)

        def on_progress(done, total, name):
            progress.set_progress(done, total, name)

        def on_done(result):
            progress.accept()
            count = getattr(result, "written_images", 0)
            # Mark exported samples in the workflow
            self._mark_exported(sample_set)
            InfoBar.success(
                "导出完成",
                f"{count} 张图片已导出到 {out_dir}",
                parent=self._window(), duration=5000,
                position=InfoBarPosition.TOP,
            )

        def on_fail(msg):
            progress.accept()
            InfoBar.error(
                "导出失败", msg,
                parent=self._window(), duration=5000,
                position=InfoBarPosition.TOP,
            )

        worker.progress.connect(on_progress)
        worker.finished_ok.connect(on_done)
        worker.failed.connect(on_fail)
        worker.start()
        self._export_worker = worker

    def _run_export_pipeline(self, dataset, opts: dict) -> None:
        """Legacy export via Pipeline (fallback when SampleSet is unavailable)."""
        from core.pipeline import (
            ExportStep, Pipeline, PipelineContext, SplitStep,
        )
        from core.schema import get as get_schema

        schema = get_schema(opts["format"])
        if schema is None:
            InfoBar.error(
                "导出失败", f"未注册的格式:{opts['format']}",
                parent=self._window(), duration=4000,
                position=InfoBarPosition.TOP,
            )
            return

        out_dir = self._wrap_export_out_dir(opts["out_dir"], opts["format"])
        extra = {}
        q = opts.get("question") or ""
        if q:
            extra["question"] = q

        split_mode = opts.get("split_mode", "ratio")
        if split_mode == "manual":
            project = self._rt.state.project
            ss = project.split_state if project else None
            split_step = SplitStep(
                mode="manual",
                manual_train=tuple(ss.manual_train) if ss else (),
                manual_val=tuple(ss.manual_val) if ss else (),
                manual_test=tuple(ss.manual_test) if ss else (),
            )
        else:
            split_step = SplitStep(
                train=opts["train_ratio"],
                val=opts["val_ratio"],
                test=opts["test_ratio"],
                stratified=opts.get("stratified", True),
                seed=opts.get("seed"),
            )

        pipe = Pipeline(
            name=f"{schema.display_name} 导出",
            steps=[
                split_step,
                ExportStep(
                    schema_key=opts["format"],
                    out_dir=out_dir,
                    copy_images=opts["copy_images"],
                    extra_options=extra,
                ),
            ],
        )
        ctx = PipelineContext(dataset=dataset)

        def task(progress_cb):
            return pipe.run(ctx, progress_cb=progress_cb)

        from gui.dialogs.op_dialogs import ProgressDialog
        from gui.workers.batch_worker import BatchWorker

        progress = ProgressDialog("导出数据集", parent=self._window())
        progress.show()

        worker = BatchWorker(task)

        def on_progress(done, total, name):
            progress.set_progress(done, total, name)

        def on_done(result):
            progress.accept()
            if not result.ok:
                msg = " | ".join(f"{name}: {err}" for name, err in result.errors)
                InfoBar.error(
                    "导出失败", msg or "未知错误",
                    parent=self._window(), duration=6000,
                    position=InfoBarPosition.TOP,
                )
                return
            reports = result.context.export_reports
            count = getattr(reports[0], "written_images", 0) if reports else 0
            InfoBar.success(
                "导出完成",
                f"{count} 张图片已导出到 {out_dir}",
                parent=self._window(), duration=5000,
                position=InfoBarPosition.TOP,
            )

        def on_fail(msg):
            progress.accept()
            InfoBar.error(
                "导出失败", msg,
                parent=self._window(), duration=5000,
                position=InfoBarPosition.TOP,
            )

        worker.progress.connect(on_progress)
        worker.finished_ok.connect(on_done)
        worker.failed.connect(on_fail)
        worker.start()
        self._export_worker = worker

    def _on_undo(self) -> None:
        # While the user is on DetailView, the local shape-edit stack
        # takes priority over the dataset-level history. This is the
        # only path that can revert a shape delete — history.jsonl
        # only knows about file-level metadata ops.
        rt = self._rt
        if (rt.browser_stack is not None
                and rt.browser_stack.currentWidget() is rt.detail
                and rt.detail.can_undo()):
            label = rt.detail.undo()
            if label:
                InfoBar.success(
                    "撤销成功", label,
                    parent=self._window(), duration=2500,
                    position=InfoBarPosition.TOP,
                )
            self._session.refresh_undo_state()
            return

        ds = self._rt.state.dataset
        if ds is None:
            return
        from core.history import try_undo_last
        try:
            ok, msg = try_undo_last(ds.root_path)
        except Exception as e:
            logger.exception("try_undo_last raised")
            InfoBar.error("撤销失败", str(e),
                          parent=self._window(), duration=5000,
                          position=InfoBarPosition.TOP)
            return
        if ok:
            InfoBar.success("撤销成功", msg,
                            parent=self._window(), duration=4000,
                            position=InfoBarPosition.TOP)
            self._session.rescan(force=True)
        else:
            InfoBar.warning("撤销失败", msg,
                            parent=self._window(), duration=4000,
                            position=InfoBarPosition.TOP)

    def _run_transform(self, dlg_cls, op_fn, title: str) -> None:
        n = self._image_count()
        if n == 0:
            return
        dlg = dlg_cls(n, parent=self._window())
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
                    title + "完成",
                    f"成功 {ok} · 失败 {fail}",
                    parent=self._window(), duration=5000,
                    position=InfoBarPosition.TOP,
                )
            else:
                InfoBar.success(
                    title + "完成", f"处理 {ok} 张",
                    parent=self._window(), duration=4000,
                    position=InfoBarPosition.TOP,
                )
            self._session.rescan(force=True)

        BatchRunner(self._rt.shell, title).run(
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
        dlg = ConvertDialog(n, parent=self._window())
        if not dlg.exec():
            return
        opts = dlg.options()
        paths = [img.path for img in self._all_images()]

        from core.convert import convert_batch
        from gui.workers.batch_runner import BatchRunner

        def handle(result):
            ok = len(getattr(result, "succeeded", []))
            fail = len(getattr(result, "failed", []))
            msg = f"成功 {ok} · 失败 {fail}" if fail else f"转换 {ok} 张"
            (InfoBar.warning if fail else InfoBar.success)(
                "格式转换完成", msg,
                parent=self._window(), duration=4000,
                position=InfoBarPosition.TOP,
            )
            self._session.rescan(force=True)

        BatchRunner(self._rt.shell, "格式转换").run(
            task=lambda cb: convert_batch(paths, opts, progress_cb=cb),
            on_done=handle,
        )

    def _on_augment(self) -> None:
        n = self._image_count()
        if n == 0:
            return
        from gui.dialogs.batch_ops import AugmentDialog
        dlg = AugmentDialog(n, parent=self._window())
        if not dlg.exec():
            return
        cfg = dlg.options()
        out_dir = cfg["out_dir"]
        aug_opts = cfg["opts"]
        paths = [img.path for img in self._all_images()]

        from core.augment import augment_batch
        from gui.workers.batch_runner import BatchRunner

        ds_root = self._rt.state.dataset.root_path if self._rt.state.dataset else None

        def _output_inside_dataset() -> bool:
            """True when augmented images land inside the current dataset."""
            if not ds_root or not out_dir:
                return False
            from pathlib import Path as _P
            resolved = _P(out_dir).resolve()
            root_resolved = _P(ds_root).resolve()
            return resolved == root_resolved or root_resolved in resolved.parents

        def handle(result):
            InfoBar.success(
                "数据增强完成",
                f"生成 {result.count} 张增强图片到 "
                f"{out_dir.name if out_dir else ''}",
                parent=self._window(), duration=5000,
                position=InfoBarPosition.TOP,
            )
            # Auto-rescan when output lands inside the dataset root —
            # new images are now part of the dataset.
            if _output_inside_dataset():
                self._session.rescan(force=True)

        BatchRunner(self._rt.shell, "数据增强").run(
            task=lambda cb: augment_batch(paths, out_dir, aug_opts, progress_cb=cb),
            on_done=handle,
        )

    def _on_predict(self) -> None:
        n_all = self._image_count()
        if n_all == 0:
            return
        all_imgs = list(self._all_images())
        unlabeled = [img for img in all_imgs if not img.has_label]
        from gui.dialogs.batch_ops import PredictDialog
        dlg = PredictDialog(len(unlabeled), parent=self._window())
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
                parent=self._window(), duration=6000,
                position=InfoBarPosition.TOP,
            )
            return

        target_paths = ([img.path for img in all_imgs]
                        if cfg["overwrite"]
                        else [img.path for img in unlabeled])
        if not target_paths:
            InfoBar.info("", "没有待处理的图片(全部已标注)",
                         parent=self._window(), duration=3000,
                         position=InfoBarPosition.TOP)
            return

        def handle(result):
            msg = (f"成功 {len(result.written)} · "
                   f"跳过 {len(result.skipped)} · "
                   f"失败 {len(result.failed)}")
            (InfoBar.warning if result.failed else InfoBar.success)(
                "AI 预标注完成", msg,
                parent=self._window(), duration=5000,
                position=InfoBarPosition.TOP,
            )
            self._session.rescan(force=True)

        BatchRunner(self._rt.shell, "AI 预标注").run(
            task=lambda cb: predict_batch(
                target_paths, predictor,
                overwrite=cfg["overwrite"], progress_cb=cb),
            on_done=handle,
        )

    def _on_history(self) -> None:
        ds = self._rt.state.dataset
        if ds is None:
            return
        from gui.dialogs.history_dialog import HistoryDialog
        HistoryDialog(ds.root_path, parent=self._window()).exec()

    def _on_change_category(self, image, target: str) -> None:
        ds = self._rt.state.dataset
        if ds is None or not target:
            return
        from core import fileops, history as _hist
        from gui.workers.batch_runner import BatchRunner

        original_category = image.category
        original_path = str(image.path)

        def task(cb):
            return fileops.move_to_category([image], ds.root_path, target,
                                              progress_cb=cb)

        def handle(result):
            if result.fail_count:
                _, err = result.failed[0]
                InfoBar.error(
                    "改分类失败", err,
                    parent=self._window(), duration=5000,
                    position=InfoBarPosition.TOP,
                )
                return
            try:
                _hist.append(
                    ds.root_path,
                    _hist.HistoryEntry.now(
                        action="move-to-category",
                        params={
                            "target": target,
                            "image_count": 1,
                            "images": [original_path],
                            "original_categories": {original_path: original_category},
                            "moves": dict(getattr(result, "moves", {}) or {}),
                        },
                        ok=True,
                        summary=f"移动 1 张到 {target}",
                        undoable=True,
                    ),
                )
            except Exception:
                logger.exception("history append failed for single-image move")
            InfoBar.success(
                "",
                f"已把 {image.path.name} 移到 {target}",
                parent=self._window(), duration=3000,
                position=InfoBarPosition.TOP,
            )
            self._rt.browser_stack.setCurrentWidget(self._rt.browser)
            # Incremental: single-image move has known old→new path mapping.
            # Update both Dataset and SampleSet in memory instead of rescanning.
            moved = getattr(result, "moves", {}) or {}
            if original_path in moved:
                self._incremental_move_single(
                    original_path, moved[original_path],
                    original_category, target)
            else:
                self._session.rescan(force=True)

        BatchRunner(self._rt.shell, "改分类").run(task=task, on_done=handle)

    def _delete_issue_images(self, images: list) -> None:
        if not images:
            return
        from core import fileops
        from gui.workers.batch_runner import BatchRunner

        def task(cb):
            return fileops.delete_pairs(images, to_trash=True, progress_cb=cb)

        def handle(result):
            n_ok = len(getattr(result, "succeeded", []))
            InfoBar.success(
                "问题图片已删除",
                f"{n_ok} 张已移至回收站",
                parent=self._window(), duration=4000,
                position=InfoBarPosition.TOP,
            )
            self._rt.state.set_quality_issues(None)
            # Incremental: remove deleted paths from Dataset + SampleSet
            # instead of a full filesystem rescan.
            deleted_paths = {str(p) for p in result.succeeded}
            if deleted_paths:
                self._incremental_remove(deleted_paths)

        BatchRunner(self._rt.shell, "删除问题图片").run(task=task, on_done=handle)

    def _move_issue_images_to_bucket(self, images: list) -> None:
        if not images:
            return
        ds = self._rt.state.dataset
        if ds is None:
            return
        from core import fileops
        from gui.workers.batch_runner import BatchRunner

        target = "质量问题"

        def task(cb):
            return fileops.move_to_category(images, ds.root_path, target,
                                             progress_cb=cb)

        def handle(result):
            n_ok = len(getattr(result, "succeeded", []))
            InfoBar.success(
                f"已移到 {target}",
                f"{n_ok} 张图片和标注已归档到 {target} 类别",
                parent=self._window(), duration=4000,
                position=InfoBarPosition.TOP,
            )
            self._rt.state.set_quality_issues(None)
            self._session.rescan(force=True)

        BatchRunner(self._rt.shell, f"移动到 {target}").run(
            task=task, on_done=handle)

    def _on_add_to_split(self, bucket: str, images: list) -> None:
        project = self._rt.state.project
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
        new_paths = [str(i.path) for i in images]
        for key, lst in lists.items():
            if key == bucket:
                continue
            lst[:] = [p for p in lst if p not in new_paths]
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
            parent=self._window(), duration=3500,
            position=InfoBarPosition.TOP,
        )

    def _on_quality_check(self) -> None:
        n_images = self._image_count()
        if n_images == 0:
            return

        from gui.dialogs.tool_dialogs import QualityCheckDialog
        dlg = QualityCheckDialog(parent=self._window())
        if not dlg.exec():
            return

        from core.quality import QualityOptions, check_images
        from gui.workers.batch_runner import BatchRunner
        opts = QualityOptions(blur_threshold=dlg.blur_threshold())

        def handle(pixel_issues):
            # Merge pixel-level issues with annotation-level issues
            # when SampleSet is READY (in-memory, instant).
            issues = list(pixel_issues or [])
            ss = self._rt.state.sample_set
            if ss is not None and self._rt.state.sample_set_ready:
                from core.quality import check_annotations
                ann_issues = check_annotations(ss)
                # Merge: if same image has both pixel + annotation issues,
                # combine into one QualityIssue entry.
                existing = {str(qi.image.path): qi for qi in issues}
                for ai in ann_issues:
                    key = str(ai.image.path)
                    if key in existing:
                        existing[key].kinds.extend(ai.kinds)
                        existing[key].metrics.update(ai.metrics)
                    else:
                        issues.append(ai)

            self._rt.state.set_quality_issues(issues or None)
            # Workflow: mark issue images as needs_fix
            self._mark_issues_needs_fix(issues)
            if not issues:
                InfoBar.success("质量检查完成", "未发现问题图片",
                                parent=self._window(), duration=3000,
                                position=InfoBarPosition.TOP)
                return
            from gui.dialogs.tool_dialogs import QualityReviewDialog
            review = QualityReviewDialog(issues, parent=self._window())
            if not review.exec():
                return
            action = review.chosen_action()
            imgs = review.issue_images()
            if action == QualityReviewDialog.ACTION_DELETE:
                self._delete_issue_images(imgs)
            elif action == QualityReviewDialog.ACTION_MOVE:
                self._move_issue_images_to_bucket(imgs)
            if action == QualityReviewDialog.ACTION_NONE:
                InfoBar.info(
                    "已标记问题图片",
                    f"{len(issues)} 张已标红角,点 \"有问题\" 筛选查看",
                    parent=self._window(), duration=5000,
                    position=InfoBarPosition.TOP,
                )

        BatchRunner(self._rt.shell, "质量检查").run(
            task=lambda cb: check_images(self._all_images(), opts,
                                          progress_cb=cb, total=n_images),
            on_done=handle,
        )

    def _on_dedup(self) -> None:
        n_images = self._image_count()
        if n_images == 0:
            return

        from gui.dialogs.tool_dialogs import DedupDialog
        dlg = DedupDialog(parent=self._window())
        if not dlg.exec():
            return
        threshold = dlg.threshold()

        from gui.workers.batch_runner import BatchRunner

        # Prefer SampleSet path — all analysis reads from one source.
        ss = self._rt.state.sample_set
        if ss is not None and self._rt.state.sample_set_ready:
            from core.dedup import find_duplicates_from_samples
            task_fn = lambda cb: find_duplicates_from_samples(
                ss, threshold=threshold, progress_cb=cb)
        else:
            from core.dedup import find_duplicates
            task_fn = lambda cb: find_duplicates(
                self._all_images(), threshold=threshold,
                progress_cb=cb, total=n_images)

        def handle(groups):
            self._rt.state.set_duplicate_groups(groups or None)
            if not groups:
                InfoBar.success("重复检测完成", "未发现重复图片",
                                parent=self._window(), duration=3000,
                                position=InfoBarPosition.TOP)
                return
            from gui.dialogs.tool_dialogs import DedupResultDialog
            result_dlg = DedupResultDialog(groups, parent=self._window())
            if result_dlg.exec():
                self._delete_duplicates(result_dlg.groups)

        BatchRunner(self._rt.shell, "重复检测").run(
            task=task_fn, on_done=handle,
        )

    def _delete_duplicates(self, groups) -> None:
        from send2trash import send2trash
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
                    logger.exception("send2trash failed for %s", img.path)
                    failed += 1
        ds = self._rt.state.dataset
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
                logger.exception("history append failed after delete-duplicates")
        if failed:
            InfoBar.warning(
                "部分删除失败",
                f"成功 {deleted} 张，{failed} 张失败（查看日志）",
                parent=self._window(), duration=6000,
                position=InfoBarPosition.TOP,
            )
        else:
            InfoBar.success("删除完成", f"已移除 {deleted} 张重复图片到回收站",
                            parent=self._window(), duration=5000,
                            position=InfoBarPosition.TOP)
        # Incremental: remove deleted paths from Dataset + SampleSet
        if trashed_paths:
            self._incremental_remove(set(trashed_paths))

    def _on_stats(self) -> None:
        ds = self._rt.state.dataset
        if ds is None:
            return

        from core.stats import compute_extended_stats, compute_stats
        from gui.dialogs.tool_dialogs import StatsResultDialog
        stats = compute_stats(ds)

        cached = self._rt.state.ext_stats
        if cached is not None:
            StatsResultDialog(stats, cached, parent=self._window()).exec()
            return

        # Prefer SampleSet path: in-memory, no disk I/O, instant.
        # Only when READY — stale data would produce misleading stats.
        ss = self._rt.state.sample_set
        if ss is not None and self._rt.state.sample_set_ready:
            from core.stats import compute_extended_stats_from_samples
            extended = compute_extended_stats_from_samples(ss)
            self._rt.state.set_ext_stats(extended)
            StatsResultDialog(stats, extended, parent=self._window()).exec()
            return

        # Fallback: parse from disk on background thread.
        from gui.workers.batch_runner import BatchRunner

        def show_dialog(extended):
            if extended is not None:
                self._rt.state.set_ext_stats(extended)
            StatsResultDialog(stats, extended, parent=self._window()).exec()

        BatchRunner(self._rt.shell, "计算详细统计").run(
            task=lambda cb: compute_extended_stats(ds, progress_cb=cb),
            on_done=show_dialog,
            on_fail=lambda _msg: show_dialog(None),
        )

    # -- Workflow helpers --

    def _mark_issues_needs_fix(self, issues) -> None:
        """Mark issue images as needs_fix in the workflow."""
        if not issues:
            return
        wf = self._rt.state.workflow
        project = self._rt.state.project
        ss = self._rt.state.sample_set
        if wf is None or project is None:
            return
        root = project.root_path
        # Build path → WorkItem lookup
        path_to_item = {item.relative_path: item for item in wf.items}
        from core.workflow import WorkStatus, _now_iso
        now = _now_iso()
        mutated = False
        for qi in issues:
            try:
                rel = qi.image.path.relative_to(root).as_posix()
            except (ValueError, AttributeError):
                continue
            wi = path_to_item.get(rel)
            if wi is not None and wi.status not in (
                    WorkStatus.NEEDS_FIX, WorkStatus.READY, WorkStatus.EXPORTED):
                wi.status = WorkStatus.NEEDS_FIX
                wi.updated_at = now
                mutated = True
                # Sync to SampleSet if available
                if ss is not None:
                    for s in ss.samples:
                        try:
                            if s.image_path.relative_to(root).as_posix() == rel:
                                s.work_status = "needs_fix"
                                break
                        except (ValueError, TypeError):
                            continue
        if mutated:
            from core import workflow_store
            workflow_store.save(root, wf)
            self._rt.state.refresh_workflow_summary()

    def _mark_exported(self, sample_set) -> None:
        """Mark all exported samples as exported in the workflow."""
        wf = self._rt.state.workflow
        project = self._rt.state.project
        if wf is None or project is None:
            return
        root = project.root_path
        path_to_item = {item.relative_path: item for item in wf.items}
        from core.workflow import WorkStatus, _now_iso
        now = _now_iso()
        mutated = False
        for s in sample_set.samples:
            try:
                rel = s.image_path.relative_to(root).as_posix()
            except (ValueError, TypeError):
                continue
            wi = path_to_item.get(rel)
            if wi is not None and wi.status in (
                    WorkStatus.READY, WorkStatus.EXPORTED):
                wi.status = WorkStatus.EXPORTED
                wi.updated_at = now
                s.work_status = "exported"
                mutated = True
        if mutated:
            from core import workflow_store
            workflow_store.save(root, wf)
            self._rt.state.refresh_workflow_summary()

    # -- Bulk workflow status transitions --

    def batch_set_status(self, images: list, new_status_str: str) -> int:
        """Transition *images* to *new_status_str* in the workflow.

        Returns the count of items actually mutated. Called from the
        browser view's context menu / bulk action bar.
        """
        from core.workflow import WorkStatus, _now_iso

        wf = self._rt.state.workflow
        project = self._rt.state.project
        ss = self._rt.state.sample_set
        if wf is None or project is None:
            return 0
        try:
            target = WorkStatus(new_status_str)
        except ValueError:
            return 0

        root = project.root_path
        path_to_item = {item.relative_path: item for item in wf.items}
        now = _now_iso()
        mutated = 0

        for img in images:
            try:
                rel = img.path.relative_to(root).as_posix()
            except (ValueError, AttributeError):
                continue
            wi = path_to_item.get(rel)
            if wi is None or wi.status == target:
                continue
            wi.status = target
            wi.updated_at = now
            mutated += 1
            # Sync to SampleSet
            if ss is not None:
                for s in ss.samples:
                    try:
                        if s.image_path.relative_to(root).as_posix() == rel:
                            s.work_status = new_status_str
                            break
                    except (ValueError, TypeError):
                        continue

        if mutated:
            from core import workflow_store
            workflow_store.save(root, wf)
            self._rt.state.refresh_workflow_summary()

        return mutated

    # -- Import annotation handler --

    def _on_import_annot(self) -> None:
        ds = self._rt.state.dataset
        if ds is None:
            return

        from gui.dialogs.import_annot_dialog import ImportAnnotDialog
        dlg = ImportAnnotDialog(parent=self._window())
        if not dlg.exec():
            return
        opts = dlg.import_options()
        source = opts["source_path"]
        fmt = opts["format"]
        overwrite = opts["overwrite"]
        if source is None:
            return

        from gui.workers.batch_runner import BatchRunner

        def task(progress_cb):
            return self._execute_import_annot(
                ds, source, fmt, overwrite, progress_cb)

        def handle(result):
            imported, skipped = result
            msg = f"{imported} 个标注已导入"
            if skipped:
                msg += f" · {skipped} 跳过"
            InfoBar.success(
                "导入完成", msg,
                parent=self._window(), duration=5000,
                position=InfoBarPosition.TOP,
            )
            self._session.rescan(force=True)

        BatchRunner(self._rt.shell, "导入标注").run(
            task=task, on_done=handle)

    def _execute_import_annot(self, dataset, source, fmt, overwrite,
                              progress_cb) -> tuple[int, int]:
        """Run annotation import on worker thread."""
        from pathlib import Path as _P
        imported = 0
        skipped = 0

        if fmt == "vlm_jsonl":
            # VLM JSONL: read into SampleSet, match by filename, mutate
            # the live SampleSet IN-MEMORY *and* write sidecars to disk
            # so the import survives an app restart.
            from core.format_in import load_vlm_jsonl
            from core.annotation_writer import (
                write_caption, write_conversations, write_grounding,
            )
            ss = load_vlm_jsonl(_P(source), progress_cb=progress_cb)
            current_ss = self._rt.state.sample_set
            if current_ss is not None:
                stem_idx = {s.image_path.stem: s for s in current_ss.samples}
                for new_s in ss.samples:
                    existing = stem_idx.get(new_s.image_path.stem)
                    if existing is None:
                        skipped += 1
                        continue
                    if not overwrite and (
                        existing.caption or existing.conversations
                        or existing.grounding
                    ):
                        skipped += 1
                        continue
                    # In-memory update
                    existing.caption = new_s.caption
                    existing.conversations = new_s.conversations
                    existing.grounding = new_s.grounding
                    # Disk write (best-effort — partial failure doesn't
                    # abort the batch; the next save attempt resyncs).
                    try:
                        if existing.caption:
                            write_caption(existing.image_path, existing.caption)
                        if existing.conversations:
                            write_conversations(
                                existing.image_path, existing.conversations)
                        if existing.grounding:
                            write_grounding(
                                existing.image_path, existing.grounding)
                    except OSError:
                        logger.exception(
                            "VLM sidecar write failed for %s",
                            existing.image_path)
                    imported += 1
            # Re-broadcast SampleSet so LlmDataCard counts refresh
            # immediately after import without needing a rescan.
            self._rt.state.notify_sample_set_mutated()
            return (imported, skipped)

        if fmt in ("caption_sidecar", "conversations_sidecar",
                   "image_labels_sidecar"):
            # Folder-of-sidecars import: read each <stem>.<ext> in the
            # source dir, match by stem to existing samples, update
            # in-memory + persist via the sidecar writer (idempotent).
            from core.annotation_writer import (
                read_caption, read_conversations, read_image_labels,
                write_caption, write_conversations, write_image_labels,
            )
            current_ss = self._rt.state.sample_set
            if current_ss is None:
                return (0, 0)
            stem_idx = {s.image_path.stem: s for s in current_ss.samples}
            source_dir = _P(source)
            if fmt == "caption_sidecar":
                ext = ".txt"
                read_fn = read_caption
                attr = "caption"
                write_fn = write_caption
            elif fmt == "conversations_sidecar":
                ext = ".conversations.json"
                read_fn = read_conversations
                attr = "conversations"
                write_fn = write_conversations
            else:
                ext = ".labels.json"
                read_fn = read_image_labels
                attr = "image_labels"
                write_fn = write_image_labels
            files = [p for p in source_dir.iterdir() if p.is_file()
                     and p.name.lower().endswith(ext)]
            total = len(files)
            for i, src_file in enumerate(files):
                if progress_cb:
                    progress_cb(i, total, src_file.name)
                # Strip the multi-suffix (e.g. .conversations.json → stem)
                stem = src_file.name[: -len(ext)]
                target = stem_idx.get(stem)
                if target is None:
                    skipped += 1
                    continue
                existing_value = getattr(target, attr, None)
                if not overwrite and existing_value:
                    skipped += 1
                    continue
                # Read via the sidecar reader (which already handles the
                # source-file path layout) — but here we want to read
                # from THIS source_dir, not next to the image.  Read raw
                # and parse manually to keep things simple.
                try:
                    if fmt == "caption_sidecar":
                        new_value = src_file.read_text(encoding="utf-8").strip()
                    else:
                        import json as _json
                        raw = _json.loads(src_file.read_text(encoding="utf-8"))
                        if fmt == "conversations_sidecar" and isinstance(raw, list):
                            new_value = [
                                d for d in raw
                                if isinstance(d, dict) and "from" in d and "value" in d
                            ]
                        elif fmt == "image_labels_sidecar" and isinstance(raw, dict):
                            lst = raw.get("labels", [])
                            new_value = [str(s) for s in lst
                                         if isinstance(s, (str, int))]
                        else:
                            skipped += 1
                            continue
                except (OSError, json.JSONDecodeError):
                    skipped += 1
                    continue
                if not new_value:
                    skipped += 1
                    continue
                # In-memory + disk
                setattr(target, attr, new_value)
                try:
                    write_fn(target.image_path, new_value)
                except OSError:
                    logger.exception(
                        "sidecar write failed for %s", target.image_path)
                imported += 1
            if progress_cb:
                progress_cb(total, total, "")
            self._rt.state.notify_sample_set_mutated()
            return (imported, skipped)

        if fmt == "coco":
            # COCO: dataset-level file → match by image name
            from core.format_in import _build_coco_index, _read_coco_sample
            from core.unified import Sample
            idx = _build_coco_index(_P(source))
            if idx is None:
                return (0, 0)
            all_images = []
            for cat in dataset.categories:
                all_images.extend(cat.images)
            total = len(all_images)
            for i, img in enumerate(all_images):
                if progress_cb:
                    progress_cb(i, total, img.path.name)
                if not overwrite and img.has_label:
                    skipped += 1
                    continue
                s = Sample(image_path=img.path,
                           image_width=0, image_height=0)
                _read_coco_sample(s, idx)
                if s.regions:
                    # Write as labelme (default)
                    from core.annotation_writer import write_annotation_as
                    from core.models import Annotation, Shape
                    ann = Annotation(
                        image_path=img.path,
                        shapes=[Shape(
                            label=r.label,
                            shape_type=r.shape_type,
                            points=([(r.bbox.x1, r.bbox.y1), (r.bbox.x2, r.bbox.y2)]
                                    if r.bbox else []),
                        ) for r in s.regions],
                    )
                    project = self._rt.state.project
                    ann_fmt = (project.annotation_format
                               if project else "labelme")
                    write_annotation_as(ann, img.path, ann_fmt)
                    imported += 1
                else:
                    skipped += 1
            if progress_cb:
                progress_cb(total, total, "")
            return (imported, skipped)

        # Per-file formats: labelme / yolo / voc
        # Read source labels → unified model → write in project format.
        # This guarantees on-disk files always match annotation_format.
        ext_map = {"labelme": ".json", "yolo": ".txt", "voc": ".xml"}
        ext = ext_map.get(fmt, ".json")
        source_dir = _P(source)

        project = self._rt.state.project
        target_fmt = (project.annotation_format if project else fmt)

        all_images = []
        for cat in dataset.categories:
            all_images.extend(cat.images)
        total = len(all_images)

        # Index source files by stem
        src_files: dict[str, _P] = {}
        if source_dir.is_dir():
            for f in source_dir.rglob(f"*{ext}"):
                src_files[f.stem] = f

        for i, img in enumerate(all_images):
            if progress_cb:
                progress_cb(i, total, img.path.name)
            src_lbl = src_files.get(img.path.stem)
            if src_lbl is None:
                skipped += 1
                continue
            if not overwrite and img.has_label:
                skipped += 1
                continue

            if fmt == target_fmt:
                # Same format: direct copy
                import shutil
                from core.annotation_writer import label_path_for_format
                dst_lbl = label_path_for_format(img.path, fmt)
                dst_lbl.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src_lbl), str(dst_lbl))
                imported += 1
            else:
                # Different format: read → convert → write in project format
                from core.format_in import load_sample as _load
                from core.models import Annotation as _A, Shape as _S
                from core.annotation_writer import write_annotation_as
                from core.unified import Region as _R
                try:
                    fake_img = type(img)(
                        path=img.path, category=img.category,
                        has_label=True, label_path=src_lbl)
                    sample = _load(fake_img, format_hint=fmt)
                    if not sample.regions:
                        skipped += 1
                        continue
                    shapes = []
                    for r in sample.regions:
                        pts = []
                        if r.polygon:
                            pts = list(r.polygon)
                        elif r.bbox:
                            if r.shape_type == "rectangle":
                                pts = [(r.bbox.x1, r.bbox.y1),
                                       (r.bbox.x2, r.bbox.y2)]
                            else:
                                pts = [(r.bbox.x1, r.bbox.y1),
                                       (r.bbox.x2, r.bbox.y1),
                                       (r.bbox.x2, r.bbox.y2),
                                       (r.bbox.x1, r.bbox.y2)]
                        if pts:
                            shapes.append(_S(label=r.label,
                                             shape_type=r.shape_type,
                                             points=pts))
                    ann = _A(image_path=img.path, shapes=shapes)
                    write_annotation_as(ann, img.path, target_fmt)
                    imported += 1
                except Exception:
                    skipped += 1

        if progress_cb:
            progress_cb(total, total, "")
        return (imported, skipped)

    # -- Annotation conversion handler --

    def _on_convert_annot(self) -> None:
        ds = self._rt.state.dataset
        if ds is None:
            return

        project = self._rt.state.project
        current_fmt = (project.annotation_format
                       if project else "")

        from gui.dialogs.convert_annot_dialog import ConvertAnnotDialog
        dlg = ConvertAnnotDialog(
            current_format=current_fmt, parent=self._window())
        if not dlg.exec():
            return
        opts = dlg.convert_options()
        out_dir = opts["out_dir"]
        if out_dir is None:
            return

        from gui.workers.batch_runner import BatchRunner

        # Use SampleSet when ready
        ss = self._rt.state.sample_set
        if ss is None or not self._rt.state.sample_set_ready:
            InfoBar.warning(
                "", "SampleSet 未就绪，请先刷新数据集",
                parent=self._window(), duration=3000,
                position=InfoBarPosition.TOP)
            return

        def task(progress_cb):
            return self._execute_convert(ss, opts, progress_cb)

        def handle(result):
            export_result, rt_result = result
            written = getattr(export_result, "written_labels", 0)
            msg = f"{written} 个标注已转换"
            if rt_result is not None:
                if rt_result.ok:
                    msg += " · round-trip OK"
                else:
                    n_diff = len(rt_result.diffs)
                    msg += f" · round-trip {n_diff} 差异"
            InfoBar.success(
                "转换完成", msg,
                parent=self._window(), duration=6000,
                position=InfoBarPosition.TOP,
            )

        BatchRunner(self._rt.shell, "标注转换").run(
            task=task, on_done=handle)

    def _execute_convert(self, sample_set, opts, progress_cb):
        """Run format conversion on worker thread."""
        from pathlib import Path as _P
        from core.format_out import ExportOptions, export_samples

        dst_fmt = opts["dst_format"]
        out_dir = _P(opts["out_dir"])
        export_opts = ExportOptions(
            out_dir=out_dir,
            copy_images=opts["copy_images"],
        )
        export_result = export_samples(
            sample_set, dst_fmt, export_opts, progress_cb=progress_cb)

        rt_result = None
        if opts.get("validate"):
            from core.format_rt import validate_roundtrip
            rt_result = validate_roundtrip(sample_set, dst_fmt)

        return (export_result, rt_result)

    # -- Migrate project annotation format --

    def _on_migrate_format(self) -> None:
        ds = self._rt.state.dataset
        project = self._rt.state.project
        if ds is None or project is None:
            InfoBar.warning(
                "", "需要项目才能切换主格式",
                parent=self._window(), duration=3000,
                position=InfoBarPosition.TOP)
            return

        n_labeled = sum(
            1 for cat in ds.categories
            for img in cat.images if img.has_label
        )
        from gui.dialogs.migrate_format_dialog import MigrateFormatDialog
        dlg = MigrateFormatDialog(
            project.annotation_format, n_labeled,
            parent=self._window())
        if not dlg.exec():
            return
        opts = dlg.migrate_options()
        self._run_migrate(
            ds, project, opts["target_format"], validate=opts["validate"])

    def _run_migrate(self, ds, project, target_fmt: str,
                     *, validate: bool = False) -> None:
        """Shared migration runner used by both the dialog flow and the
        settings popup shortcut."""
        from gui.workers.batch_runner import BatchRunner

        def task(progress_cb):
            from core.format_migrate import migrate_annotation_format
            result = migrate_annotation_format(
                ds, target_fmt, progress_cb=progress_cb)

            rt_result = None
            if validate and result.converted > 0:
                ss = self._rt.state.sample_set
                if ss is not None:
                    from core.format_rt import validate_roundtrip
                    rt_result = validate_roundtrip(ss, target_fmt)

            return (result, rt_result)

        def handle(result_pair):
            migrate_result, rt_result = result_pair
            n_ok = migrate_result.converted
            n_fail = len(migrate_result.failed)

            # Update project config on success
            if n_ok > 0 and n_fail == 0:
                project.annotation_format = target_fmt
                from core.project import save_project
                save_project(project)
                # Push new format to DetailView + DatasetBar + Settings
                self._rt.state.notify_project_mutated()

            msg = f"{n_ok:,} 个标注已迁移到 {target_fmt.upper()}"
            if n_fail:
                msg += f" · {n_fail} 失败"
            if rt_result is not None:
                if rt_result.ok:
                    msg += " · round-trip OK"
                else:
                    msg += f" · round-trip {len(rt_result.diffs)} 差异"

            (InfoBar.success if n_fail == 0 else InfoBar.warning)(
                "格式迁移完成", msg,
                parent=self._window(), duration=6000,
                position=InfoBarPosition.TOP,
            )
            self._session.rescan(force=True)

        BatchRunner(self._rt.shell, "格式迁移").run(
            task=task, on_done=handle)

    def commit_batch(self, batch_id: str) -> None:
        """Commit inbox batch items into a category chosen by the user."""
        wf = self._rt.state.workflow
        project = self._rt.state.project
        if wf is None or project is None:
            return

        # Collect items still in _inbox for this batch
        items = [i for i in wf.items
                 if i.batch_id == batch_id
                 and "_inbox/" in i.relative_path]
        if not items:
            from gui import i18n
            InfoBar.info("", "该批次没有待提交的图片",
                         parent=self._window(), duration=3000,
                         position=InfoBarPosition.TOP)
            return

        # Pick target category
        from gui.dialogs.op_dialogs import MoveToCategoryDialog
        ds = self._rt.state.dataset
        cats = [c.name for c in ds.categories] if ds else []
        dlg = MoveToCategoryDialog(cats, parent=self._window())
        if not dlg.exec():
            return
        target = dlg.chosen_category()
        if not target:
            return

        root = project.root_path
        item_ids = [i.item_id for i in items]

        from gui.workers.batch_runner import BatchRunner

        def task(progress_cb):
            from gui.controllers.workflow_controller import WorkflowController
            wf_ctrl = WorkflowController(self._rt.state)
            return wf_ctrl.commit_batch_items(
                item_ids, target, progress_cb=progress_cb)

        def handle(count):
            from gui import i18n
            InfoBar.success(
                "", f"{count} 张已提交到 {target}",
                parent=self._window(), duration=4000,
                position=InfoBarPosition.TOP,
            )
            self._session.rescan(force=True)
            # Refresh the batch list
            chrome = getattr(self._rt.shell, "_chrome", None)
            if chrome is not None:
                chrome.refresh_batch_list()

        BatchRunner(self._rt.shell, "提交新数据").run(
            task=task, on_done=handle)

    # -- Incremental SampleSet/Dataset update --

    def _incremental_remove(self, deleted_paths: set[str]) -> None:
        """Remove *deleted_paths* from both Dataset and SampleSet in memory.

        Avoids a full filesystem rescan for pure-delete operations (quality
        delete, dedup delete).  Emits ``dataset_changed`` and
        ``sample_set_changed`` so the UI refreshes immediately.

        Feeds the live SampleSet's per-image region counts into
        ``Dataset.remove_images`` so ``total_annotations`` stays an
        accurate region count (not a labeled-image count).
        """
        state = self._rt.state
        ss = state.sample_set
        regions_by_path: dict[str, int] | None = None
        if ss is not None:
            regions_by_path = {}
            for s in ss.samples:
                key = str(s.image_path)
                if key in deleted_paths:
                    regions_by_path[key] = s.region_count
        ds = state.dataset
        if ds is not None:
            ds.remove_images(deleted_paths, regions_by_path=regions_by_path)
            state.notify_dataset_mutated()
        state.remove_samples(deleted_paths)
        self._session.refresh_undo_state()

    def _incremental_move_single(
        self,
        old_path_str: str,
        new_path_str: str,
        old_category: str,
        new_category: str,
    ) -> None:
        """Update Dataset + SampleSet in memory after a single-image move.

        Removes the image from its old category, adds it to the new one,
        and patches the SampleSet entry's image_path + category.  Falls
        back to a full rescan on any error.
        """
        from pathlib import Path as _P
        state = self._rt.state
        ds = state.dataset
        new_path = _P(new_path_str)

        try:
            # Detect if a label was copied alongside the image — needed
            # for both Dataset.has_label and SampleSet region bookkeeping.
            from core.annotation_writer import label_path_for_format
            project = state.project
            fmt = (project.annotation_format
                   if project else "labelme")
            lbl = label_path_for_format(new_path, fmt)
            label_copied = lbl.is_file()

            if ds is not None:
                # Remove from old category.  The single-move case has
                # no region delta visible on the dest-side yet (we
                # haven't parsed the moved label), so we let the
                # SampleSet-sync step below drive total_annotations.
                ds.remove_images({old_path_str})
                # Add to new category (create if missing)
                from core.models import ImageInfo
                new_img = ImageInfo(
                    path=new_path,
                    category=new_category,
                    width=0, height=0,
                    has_label=False,
                )
                if label_copied:
                    new_img.has_label = True
                    new_img.label_path = lbl

                cat = ds.category_by_name(new_category)
                if cat is None:
                    from core.models import Category
                    cat = Category(name=new_category)
                    ds.categories.append(cat)
                cat.images.append(new_img)
                cat.image_count = len(cat.images)
                cat.label_count = sum(1 for i in cat.images if i.has_label)
                ds.total_images += 1

            # Patch the SampleSet entry (old → new path / category).
            ss = state.sample_set
            if ss is not None:
                sample = ss.find(old_path_str)
                if sample is not None:
                    sample.image_path = new_path
                    sample.category = new_category
                # Re-derive total_annotations from the SampleSet so it
                # stays a region count (not a labeled-image count).
                if ds is not None:
                    ds.total_annotations = ss.total_regions
                state.notify_sample_set_mutated()

            if ds is not None:
                state.notify_dataset_mutated()

            self._session.refresh_undo_state()

        except Exception:
            logger.exception("incremental move failed, falling back to rescan")
            self._session.rescan(force=True)
