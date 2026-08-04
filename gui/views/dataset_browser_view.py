"""Top-level workbench — assembly shell.

IA v3.1: 3-column chrome:

    [WorkspaceSidebar]  [middle work area]  [ContextPanel]
       slim stage nav     DatasetBar +         catalog / inspector
       (5 rows, 168px)    stage stack          (340px, collapsible)

The middle column hosts the five stage pages:

- **项目概览**     — ProjectOverviewHub (console + next-step CTA, default landing).
- **新数据**       — BatchListPanel (incoming-batch staging).
- **标注工作台**    — Browser↔Detail flow.
- **审核修复**     — ReviewHub (quality / dedup / stats).
- **导出**         — DeliveryHub (export-first: direct export / VLM export / copy conversion;
  also a read-only cleanup list for any legacy generated versions).

The right ContextPanel hosts a stack of pages and surfaces whichever
matches the user's current focus — Catalog on the 标注工作台 grid,
ImageInspector on detail drill-in (future).  Empty pages collapse the
panel so the work area gets the freed space.

Global toolbar actions (refresh / undo) live on the DatasetBar so
they're reachable from every stage, not just one.

Business logic lives in:

- DatasetSessionController — scan, refresh, dataset lifecycle
- BrowserToolController — hub-signal execution (no string dispatch)
- BrowserChromeController — context panel + detail drill-in/out
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from gui.app_state import AppState
from gui.controllers.browser_chrome_controller import BrowserChromeController
from gui.controllers.browser_runtime import BrowserRuntime
from gui.controllers.browser_tool_controller import BrowserToolController
from gui.controllers.dataset_session_controller import DatasetSessionController
from gui.views.browser_view import BrowserView
from gui.views.detail_view import DetailView
from gui.widgets.context_panel import ContextPage, ContextPanel
from gui.widgets.workspace_sidebar import StageIndex, WorkspaceSidebar
from gui.workers.thumbnail_worker import ThumbnailWorker


class DatasetBrowserView(QWidget):
    """Top-level browser: directory picker + scan + browse + detail."""

    # Import request from the 导入数据 stage bubbles up to MainWindow
    # which owns OrganizeView routing.
    request_organize_view = pyqtSignal()
    # Drag-and-drop import — carries the dropped folder path.
    folder_dropped = pyqtSignal(str)

    def __init__(self, app_state: AppState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("datasetBrowserView")
        self._state = app_state

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Column 1: WorkspaceSidebar — slim vertical stage nav (5 list
        # rows, 168px). No context column — that lives on the right.
        self._workspace_sidebar = WorkspaceSidebar()
        root.addWidget(self._workspace_sidebar)

        # Column 2: middle column — DatasetBar (global toolbar) + stage
        # stack. Stage stack holds the five work-area pages; the
        # 标注工作台 page wraps the existing browser_stack
        # (BrowserView ↔ DetailView drill) so all current flows keep
        # working unchanged.
        from gui.widgets.dataset_bar import DatasetBar
        self._dataset_bar = DatasetBar()

        self._browser = BrowserView(app_state=self._state)
        self._detail = DetailView()
        self._browser_stack = QStackedWidget()
        self._browser_stack.addWidget(self._browser)
        self._browser_stack.addWidget(self._detail)

        # 项目概览 stage body — default landing page.
        from gui.widgets.project_overview_hub import ProjectOverviewHub
        self._overview_hub = ProjectOverviewHub()

        # 导入数据 stage body — the batch list is the whole page.
        from gui.widgets.batch_list import BatchListPanel
        self._batch_list = BatchListPanel()

        # 导出 stage body — output-producing actions only.
        from gui.widgets.delivery_hub import DeliveryHub
        self._delivery_hub = DeliveryHub()

        # 审核修复 stage body — primary entries for 质检 / 去重 / 统计.
        from gui.widgets.review_hub import ReviewHub
        self._review_hub = ReviewHub()

        # Build the 5 stage pages (Overview is the default landing).
        self._stage_stack = QStackedWidget()
        self._stage_stack.insertWidget(StageIndex.OVERVIEW, self._overview_hub)
        self._stage_stack.insertWidget(StageIndex.INBOX,    self._batch_list)
        self._stage_stack.insertWidget(StageIndex.ANNOTATE, self._browser_stack)
        self._stage_stack.insertWidget(StageIndex.REVIEW,   self._review_hub)
        self._stage_stack.insertWidget(StageIndex.DELIVERY, self._delivery_hub)
        self._stage_stack.setCurrentIndex(StageIndex.OVERVIEW)

        middle = QWidget()
        mid_lay = QVBoxLayout(middle)
        mid_lay.setContentsMargins(0, 0, 0, 0)
        mid_lay.setSpacing(0)
        mid_lay.addWidget(self._dataset_bar)
        mid_lay.addWidget(self._stage_stack, 1)
        root.addWidget(middle, 1)

        # Column 3: ContextPanel — right-side stack of stage- and
        # object-scoped context pages.  v3.1 hosts CatalogPanel as the
        # ANNOTATE-grid page; future passes add a per-image Inspector
        # (when on detail) and an audit queue (when on 审核修复).
        self._context_panel = ContextPanel()

        from gui.widgets.catalog_panel import CatalogPanel
        self._catalog = CatalogPanel()
        # Catalog ↔ browser wiring (browser already exists at this point).
        self._catalog.category_selected.connect(self._browser.select_category)
        self._catalog.rename_requested.connect(self._browser.rename_category)
        self._catalog.merge_requested.connect(self._browser.merge_category)
        self._catalog.split_requested.connect(self._browser.split_category)
        self._browser.set_catalog_tree(self._catalog.tree)
        # Register pages.  Order matches the ContextPage constants:
        # page 0 is the empty placeholder (added in ContextPanel.__init__),
        # page 1 = CATALOG (grid mode), page 2 = INSPECTOR (detail mode).
        self._context_panel.add_page(self._catalog)
        # DetailView built its inspector frame but never added it to its
        # own body — the workbench shell hosts it instead so the right
        # column is a single source of "what context goes with the
        # current focus".
        self._context_panel.add_page(self._detail.inspector)

        root.addWidget(self._context_panel)

        # Thumbnail worker
        self._thumb = ThumbnailWorker(size=170, parent=self)
        self._thumb.start()
        self._browser.thumb_request.connect(self._thumb.request)
        self._browser.clear_thumb_queue.connect(self._thumb.clear_queue)
        self._thumb.thumb_ready.connect(self._browser.on_thumb_ready)

        # ---- Controllers ----
        self._rt = BrowserRuntime(
            state=app_state,
            shell=self,
            browser=self._browser,
            detail=self._detail,
            catalog=self._catalog,
            dataset_bar=self._dataset_bar,
            workspace_sidebar=self._workspace_sidebar,
            context_panel=self._context_panel,
            delivery_hub=self._delivery_hub,
            review_hub=self._review_hub,
            thumb_worker=self._thumb,
            browser_stack=self._browser_stack,
            batch_list=self._batch_list,
        )
        self._session = DatasetSessionController(self._rt, parent=self)
        self._tools = BrowserToolController(self._rt, self._session)
        self._chrome = BrowserChromeController(self._rt)

        # ---- Signal wiring ----

        # DatasetBar — global toolbar actions + primary open + catalog
        # toggle.
        self._dataset_bar.open_clicked.connect(
            self._session.choose_and_open_directory)
        self._dataset_bar.refresh_clicked.connect(self._tools.run_refresh)
        self._dataset_bar.undo_clicked.connect(self._tools.run_undo)

        # DeliveryHub — output-producing actions only.
        self._delivery_hub.convert_annot_requested.connect(
            self._tools.run_convert_annot)
        self._delivery_hub.export_requested.connect(self._tools.run_export)
        self._delivery_hub.open_version_requested.connect(
            self._tools.open_training_version)
        self._delivery_hub.delete_version_requested.connect(
            self._tools.delete_training_version)
        # 大模型标注向导 — pick caps + category, then prep workbench:
        # apply caps → switch to ANNOTATE → filter category → drill
        # into first incomplete image.
        self._delivery_hub.start_vlm_workflow_requested.connect(
            self._on_start_vlm_workflow)
        # 批量填入区域文本 — write one template to every region of a
        # category, persist sidecars, refresh sample-set state.
        self._delivery_hub.bulk_fill_region_text_requested.connect(
            self._on_bulk_fill_region_text)

        # ProjectOverviewHub — project console (status + class + nav).
        self._state.dataset_changed.connect(self._overview_hub.set_dataset)
        self._state.project_changed.connect(self._overview_hub.set_project)
        self._state.workflow_summary_changed.connect(
            self._overview_hub.set_workflow_summary)
        self._overview_hub.navigate_stage.connect(self.set_active_stage)

        self._browser.target_format_changed.connect(
            self._on_target_format_changed)

        # Class-management actions — re-use the existing BrowserView
        # rename / merge / split methods so the dialogs that already
        # work from the catalog right-click context menu are kept as
        # the single source of truth for these flows.
        # Class list refreshes on dataset_changed so the row counts
        # track adds / merges / renames done elsewhere.

        # ReviewHub — top toolbar runs analyses; new jump-to-image + mark-
        # needs-fix signals close the review→fix loop.
        self._review_hub.quality_requested.connect(self._tools.run_quality)
        self._review_hub.dedup_requested.connect(self._tools.run_dedup)
        self._review_hub.stats_requested.connect(self._tools.run_stats)
        self._review_hub.fix_oob_requested.connect(self._tools.run_fix_oob)
        self._review_hub.jump_to_image_requested.connect(
            self._on_review_jump_to_image)
        self._review_hub.mark_needs_fix_requested.connect(
            self._on_review_mark_needs_fix)
        # AppState artifacts → ReviewHub queues + summary.
        self._state.quality_changed.connect(
            self._review_hub.set_quality_issues)
        self._state.duplicates_changed.connect(
            self._review_hub.set_duplicate_groups)
        self._state.workflow_summary_changed.connect(
            self._review_hub.set_workflow_summary)
        # Push the dataset image count so the review toolbar's scope
        # badges read "整库 N 张" instead of the placeholder.
        self._state.dataset_changed.connect(self._review_hub.set_dataset)
        self._browser.image_activated.connect(self._chrome.activate_detail)
        self._detail.back_requested.connect(self._chrome.back_to_browser)
        self._browser_stack.currentChanged.connect(self._chrome.on_stack_changed)
        # Drill-in / drill-out swaps which undo stack the global 撤销
        # button is talking to (DetailView local stack vs. dataset-level
        # history). Keep the button enabled state honest by re-running
        # the resolver on every stack flip and on every shape edit.
        self._browser_stack.currentChanged.connect(
            lambda _i: self._session.refresh_undo_state())
        self._detail.undo_state_changed.connect(
            self._session.refresh_undo_state)
        self._workspace_sidebar.stage_changed.connect(self._on_stage_changed)
        self._catalog.close_requested.connect(
            lambda: self._chrome.set_catalog_open(False))
        self._dataset_bar.catalog_toggled.connect(self._chrome.set_catalog_open)

        self._batch_list.commit_requested.connect(self._tools.commit_batch)
        # Import = copy new images into inbox via OrganizeView
        self._batch_list.import_requested.connect(
            self.request_organize_view.emit)
        # Drag-drop = same flow but with a pre-known source path
        self._batch_list.folder_dropped.connect(self.folder_dropped.emit)
        self._batch_list.navigate_stage.connect(self.set_active_stage)
        self._state.workflow_changed.connect(self._on_workflow_for_batches)

        self._detail.change_category_requested.connect(
            self._tools.change_category)
        self._detail.delete_image_requested.connect(
            self._tools.delete_current_image)
        self._browser.dataset_changed.connect(
            lambda: self._session.rescan(force=True)
        )
        self._browser.add_to_split.connect(self._tools.add_to_split)
        self._browser.batch_status_requested.connect(self._on_batch_status)
        self._state.dataset_changed.connect(self._session.handle_dataset_changed)
        self._state.quality_changed.connect(
            lambda issues: self._dataset_bar.set_flagged_count(
                len(issues or [])
            )
        )
        self._state.workflow_summary_changed.connect(
            self._dataset_bar.set_workflow_summary
        )
        self._state.workflow_summary_changed.connect(
            self._on_workflow_summary_for_sidebar
        )
        self._state.sample_set_changed.connect(
            self._detail.set_sample_set
        )
        self._state.sample_set_changed.connect(
            self._dataset_bar.update_from_sample_set
        )
        # LLM-data zone in DeliveryHub reads caption / conversations /
        # grounding counts off the live SampleSet — wire it here so
        # status numbers reflect every save / batch import.
        self._state.sample_set_changed.connect(
            self._delivery_hub.set_sample_set
        )
        self._state.sample_set_status_changed.connect(
            self._dataset_bar.set_sample_set_status
        )
        self._detail.work_status_changed.connect(
            self._on_work_status_changed
        )
        self._detail.annotation_saved.connect(self._on_annotation_saved)
        self._detail.caption_saved.connect(self._on_caption_saved)
        self._detail.conversations_saved.connect(self._on_conversations_saved)
        self._detail.grounding_saved.connect(self._on_grounding_saved)
        # Sync annotation format from project to DetailView for write-back
        self._state.project_changed.connect(self._sync_annotation_format)
        # Gate writes while the scan worker is still building SampleSet.
        # Matches AppState.scan_active semantics: True → no writes.
        # DetailView goes read-only; DatasetBar shows "模型加载中" text
        # next to the path so the user sees why save buttons are off.
        self._state.scan_active_changed.connect(
            lambda active: self._detail.set_write_enabled(not active)
        )
        self._state.scan_active_changed.connect(self._dataset_bar.set_loading)

        # Initial ContextPanel state — IA v2 phase 1 default stage is
        # 概览 which doesn't need the catalog panel; collapse it.  When
        # the user later switches to 标注工作台 the catalog opens via
        # the user's preference (default True) — handled by
        # ``BrowserChromeController.on_stack_changed``.
        self._context_panel.show_page(ContextPage.CATALOG)
        self._chrome.set_catalog_open(False)
        # Default landing is OVERVIEW — hide the catalog toggle so the
        # user doesn't poke a no-op button before clicking 标注 stage.
        self._dataset_bar.set_catalog_btn_visible(False)

    # -- Public API --

    def open_directory(self, root: Path) -> None:
        """Programmatic entry — called by MainWindow after welcome page action."""
        self._session.open_directory(root)

    def set_active_stage(self, stage_index: int) -> None:
        """Programmatic stage swap — used by intent routing from home.

        Updates both the workspace sidebar's selection and the stage
        stack's current index in one call so the visual selection and
        the visible page stay coherent.
        """
        self._workspace_sidebar.set_current_stage(stage_index)
        self._on_stage_changed(stage_index)

    # -- Stage stack --

    def _on_stage_changed(self, index: int) -> None:
        """Swap the stage page + gate the right ContextPanel.

        Catalog is 标注工作台-scoped (it mirrors the grid's dataset);
        we only surface it in the right ContextPanel while the user
        is on that stage.  Other stages collapse the panel (placeholder
        pages get filled in later passes for review queue / inbox
        summary / etc.).

        Entering 新数据 triggers a batch-list refresh so the user sees
        up-to-date counts without having to rescan manually.
        """
        self._stage_stack.setCurrentIndex(index)
        # Catalog toggle button is meaningless off the 标注 stage —
        # the context panel is force-hidden there, so the click would
        # produce no visible effect.  Hide the button itself so the
        # user doesn't poke a non-functional control.
        self._dataset_bar.set_catalog_btn_visible(
            index == StageIndex.ANNOTATE)
        if index == StageIndex.ANNOTATE:
            self._context_panel.show_page(ContextPage.CATALOG)
            # Re-apply the user's "catalog open" preference + drill-in
            # state via the chrome controller.
            self._chrome.on_stack_changed(
                self._browser_stack.currentIndex())
        else:
            self._context_panel.show_page(ContextPage.EMPTY)
            self._context_panel.setVisible(False)
            if index == StageIndex.INBOX:
                self._chrome.refresh_batch_list()

    def _on_batch_status(self, images: list, new_status: str) -> None:
        """Handle bulk workflow status change from browser context menu."""
        n = self._tools.batch_set_status(images, new_status)
        if n > 0:
            from gui import i18n
            from qfluentwidgets import InfoBar, InfoBarPosition
            InfoBar.success(
                "", i18n.t("wf.batch_done", n=n),
                parent=self, duration=3000,
                position=InfoBarPosition.TOP,
            )

    def _on_annotation_saved(self, _image) -> None:
        """Refresh aggregate UI after DetailView saves shape annotations."""
        self._sync_project_classes_from_samples()
        self._state.notify_sample_set_mutated()

    def _sync_project_classes_from_samples(self) -> None:
        project = self._state.project
        ss = self._state.sample_set
        if project is None or ss is None:
            return
        existing = list(getattr(project, "class_names", []) or [])
        seen = set(existing)
        added: list[str] = []
        for sample in ss.samples:
            for region in sample.regions:
                label = (region.label or "").strip()
                if not label or label in seen:
                    continue
                seen.add(label)
                added.append(label)
        if not added:
            return
        project.class_names = existing + sorted(added)
        try:
            from core.project import save_project
            save_project(project)
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                "save_project failed after class-name sync")
        self._state.notify_project_mutated()

    def _on_work_status_changed(self, image, new_status: str) -> None:
        """Persist workflow status change from DetailView."""
        from core.workflow import WorkStatus
        wf = self._state.workflow
        project = self._state.project
        if wf is None or project is None:
            return
        # Find the WorkItem by relative path
        try:
            rel = image.path.relative_to(project.root_path).as_posix()
        except (ValueError, AttributeError):
            return
        from core import workflow_store
        try:
            status = WorkStatus(new_status)
        except ValueError:
            return
        updated = workflow_store.update_status(
            project.root_path, item_ids=[], new_status=status)
        # Manual per-item update (update_status takes IDs, but we have path)
        for item in wf.items:
            if item.relative_path == rel:
                item.status = status
                break
        # Persist + re-derive summary from SampleSet
        from core import workflow_store as ws
        ws.save(project.root_path, wf)
        self._state.refresh_workflow_summary()
        self._state.notify_sample_set_mutated()

    def _on_caption_saved(self, image, caption: str) -> None:
        """Persist VLM caption to disk as a sidecar .txt file.

        In-memory update already happened via DetailView._on_save_caption.
        Here we write to ``<image_stem>.txt`` next to the image on disk.
        """
        from core.annotation_writer import write_caption
        try:
            write_caption(image.path, caption)
        except OSError:
            import logging
            logging.getLogger(__name__).exception(
                "caption write failed for %s", image.path)
        self._state.notify_sample_set_mutated()

    def _on_conversations_saved(self, image, conversations: list) -> None:
        """Persist VLM conversations to disk as a sidecar .json file.

        In-memory update already happened via DetailView._on_save_conversations.
        Here we write to ``<image_stem>.conversations.json`` on disk.
        """
        from core.annotation_writer import write_conversations
        try:
            write_conversations(image.path, conversations)
        except OSError:
            import logging
            logging.getLogger(__name__).exception(
                "conversations write failed for %s", image.path)
        self._state.notify_sample_set_mutated()

    def _on_change_preset(self) -> None:
        """Open the preset picker for the active project and apply the choice.

        Applies the preset, persists it, then broadcasts project_changed
        so DetailView/DeliveryHub refresh their project-derived state.
        """
        project = self._state.project
        if project is None:
            return

        from core.annotation_preset import preset_by_id
        from core.project import apply_preset, save_project
        from gui.dialogs.preset_picker_dialog import PresetPickerDialog

        dlg = PresetPickerDialog(project.preset_id, parent=self.window())
        if not dlg.exec():
            return
        new_id = dlg.selected_preset_id()
        if new_id == project.preset_id:
            return

        # Apply the preset's caps to the in-memory project object first
        # so AppState observers (DetailView spec rebuild, DeliveryHub LLM
        # card empty-state, sidebar badges) all see the same shape on
        # the next notify_project_mutated tick.
        apply_preset(project, new_id)
        try:
            save_project(project)
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                "save_project failed after preset change")
        self._state.notify_project_mutated()

        from qfluentwidgets import InfoBar, InfoBarPosition
        preset = preset_by_id(new_id)
        msg = (preset.display_name if preset is not None
               else "自定义（手动调整能力开关）")
        InfoBar.success(
            "预设已更新", msg,
            parent=self.window(), duration=2500,
            position=InfoBarPosition.TOP,
        )

    def _on_start_vlm_workflow(self) -> None:
        """大模型标注向导 — choose fields + filter + drill into first todo.

        Field choices are this run's working scope only; VLM editors are
        always available and no project capability flag is mutated.

        After this handler runs the user is on the right pane of the
        right image, ready to type.
        """
        ds = self._state.dataset
        project = self._state.project
        if ds is None or project is None:
            return

        from gui.dialogs.vlm_start_dialog import VlmStartDialog

        dlg = VlmStartDialog(
            ds, project,
            initial_category=self._browser.active_category(),
            parent=self.window(),
        )
        if not dlg.exec():
            return
        result = dlg.result_dict()

        # 1) Swap the workbench to 标注工作台 + restore catalog context.
        self._stage_stack.setCurrentIndex(StageIndex.ANNOTATE)
        self._workspace_sidebar.set_current_stage(StageIndex.ANNOTATE)
        self._context_panel.show_page(ContextPage.CATALOG)

        # 2) Apply category filter (empty string = "全部" — clears the filter).
        target_cat = result["category"]
        self._browser.select_category(target_cat)

        # 3) Build the candidate image list matching the filter, then
        #    drop the user onto the first image still missing the VLM
        #    data they selected for this run.  Falls back to the first image
        #    when nothing matches "incomplete" (everything done already
        #    OR SampleSet not yet hydrated).
        if target_cat:
            cat = ds.category_by_name(target_cat)
            candidate_images = list(cat.images) if cat else []
        else:
            candidate_images = []
            for c in ds.categories:
                candidate_images.extend(c.images)
        if not candidate_images:
            return

        first_img = self._find_first_incomplete_image(
            candidate_images, result) or candidate_images[0]
        self._chrome.activate_detail(first_img, candidate_images)

    def _find_first_incomplete_image(self, images, caps: dict):
        """Scan *images* and return the first ImageInfo whose Sample
        is incomplete for the selected field set, or None when no
        SampleSet is loaded yet / everything is already done."""
        ss = self._state.sample_set
        if ss is None:
            return None
        sample_index = {str(s.image_path): s for s in ss.samples}
        for img in images:
            sample = sample_index.get(str(img.path))
            if sample is None:
                continue
            if self._sample_incomplete_for_caps(sample, caps):
                return img
        return None

    @staticmethod
    def _sample_incomplete_for_caps(sample, caps: dict) -> bool:
        """Mirrors DetailView._is_sample_incomplete but parameterised
        on a caps dict (so we can use the about-to-be-applied set,
        before DetailView's spec rebuild has happened)."""
        if caps.get("caption") and not (sample.caption or "").strip():
            return True
        if caps.get("conversations") and not sample.conversations:
            return True
        if caps.get("grounding"):
            if not sample.regions:
                return True
            if any(not (r.text or "").strip() for r in sample.regions):
                return True
        return False

    def _on_bulk_fill_region_text(self) -> None:
        """批量填入区域文本 — write one template to every region of a
        category.  Per-image AnnotationPane editing doesn't scale to
        4 000+ Loose images that share a single grounding caption,
        this does.

        Persists each affected sample's grounding sidecar on disk and
        rebuilds ``Sample.grounding`` so the LLM-data card's per-region
        count refreshes once the worker emits done.
        """
        ds = self._state.dataset
        ss = self._state.sample_set
        if ds is None:
            return
        if ss is None or not self._state.sample_set_ready:
            from qfluentwidgets import InfoBar, InfoBarPosition
            InfoBar.warning(
                "数据未就绪", "等待扫描完成后再批量填入",
                parent=self.window(), duration=3000,
                position=InfoBarPosition.TOP,
            )
            return

        from gui.dialogs.bulk_region_text_dialog import BulkRegionTextDialog

        dlg = BulkRegionTextDialog(
            ds, ss,
            initial_category=self._browser.active_category(),
            parent=self.window(),
        )
        if not dlg.exec():
            return
        opts = dlg.options()
        if not opts["template"]:
            return

        # Propagate the user's chosen scope back into the catalog
        # filter so the next dialog (export wizard) defaults to the
        # same category.  No-op when the user picked "全部".
        chosen_cat = opts["category"]
        if chosen_cat and chosen_cat != self._browser.active_category():
            self._browser.select_category(chosen_cat)

        from core.grounding_bulk import bulk_fill_region_text
        from gui.workers.batch_runner import BatchRunner

        def task(progress_cb):
            return bulk_fill_region_text(
                ss,
                template=opts["template"],
                category=opts["category"],
                overwrite=opts["overwrite"],
                progress_cb=progress_cb,
            )

        def on_done(result) -> None:
            # Push the in-place SampleSet mutation to subscribers
            # (LlmDataCard re-renders status, browser re-renders chips).
            self._state.notify_sample_set_mutated()
            from qfluentwidgets import InfoBar, InfoBarPosition
            scope = opts["category"] or "全部类目"
            msg = (f"{scope} · 写入 {result.affected_images:,} 张图片 · "
                   f"{result.affected_regions:,} 个区域")
            # Surface the "skipped because text already exists" count
            # so users who forgot to flip 覆盖所有区域 can instantly see
            # WHY 0/0 came back.
            if result.skipped_already_filled:
                msg += (f" · 跳过 {result.skipped_already_filled:,} 个"
                        f"已有文本的区域 (改用「覆盖所有区域」可重写)")
            if result.skipped_no_regions:
                msg += f" · {result.skipped_no_regions:,} 张图片无区域"
            if result.failed:
                msg += f" · {len(result.failed)} 个写盘失败"
                InfoBar.warning(
                    "批量填入完成 (有失败)", msg,
                    parent=self.window(), duration=8000,
                    position=InfoBarPosition.TOP,
                )
            elif result.affected_images == 0:
                # 0/0 with no errors = everything skipped — surface as
                # info, not success, so the user notices.
                InfoBar.info(
                    "批量填入：未写入任何区域", msg,
                    parent=self.window(), duration=8000,
                    position=InfoBarPosition.TOP,
                )
            else:
                InfoBar.success(
                    "批量填入完成", msg,
                    parent=self.window(), duration=4000,
                    position=InfoBarPosition.TOP,
                )

        BatchRunner(self, "批量填入区域文本").run(
            task=task, on_done=on_done)

    def _on_review_jump_to_image(self, image) -> None:
        """Switch to 标注工作台 and open the chosen image in DetailView.

        Triggered when the user double-clicks a queue entry or hits
        ``打开图片`` in the review detail pane — closes the
        review→fix loop without making the user re-navigate.
        """
        ds = self._state.dataset
        if ds is None or image is None:
            return
        # Flatten all images so DetailView's prev/next nav has the full
        # context (so the user can fan out from one issue to nearby
        # ones without bouncing back to review).
        all_images = []
        for cat in ds.categories:
            all_images.extend(cat.images)
        if not all_images:
            return
        # 1) Swap the stage stack to 标注工作台.
        self._stage_stack.setCurrentIndex(StageIndex.ANNOTATE)
        self._workspace_sidebar.set_current_stage(StageIndex.ANNOTATE)
        # 2) Restore the catalog context for the new stage.
        self._context_panel.show_page(ContextPage.CATALOG)
        # 3) Drill into DetailView for the chosen image.
        self._chrome.activate_detail(image, all_images)

    def _on_review_mark_needs_fix(self, image) -> None:
        """Apply the ``needs_fix`` workflow status to a single image.

        Re-uses the same path DetailView's status pane drives — keeps
        a single workflow-mutation funnel.
        """
        self._on_work_status_changed(image, "needs_fix")

    def _on_workflow_summary_for_sidebar(self, summary) -> None:
        """Surface stage-pending counts as sidebar badges.

        - 新数据 badge: workflow items still awaiting annotation
          (new + prelabeled).
        - 审核 badge: review queue depth (review_pending + needs_fix).
        - Other stages have no workflow-derived count yet (data delivery
          / management aren't queue-shaped concepts).
        """
        if summary is None:
            self._workspace_sidebar.set_badge(StageIndex.INBOX, None)
            self._workspace_sidebar.set_badge(StageIndex.REVIEW, None)
            return
        pending = summary.new + summary.prelabeled
        review = summary.review_pending + summary.needs_fix
        self._workspace_sidebar.set_badge(StageIndex.INBOX, pending)
        self._workspace_sidebar.set_badge(StageIndex.REVIEW, review)

    def _on_grounding_saved(self, image, grounding: list) -> None:
        """Persist grounding (region text) to disk as a sidecar .json file.

        In-memory update already happened via DetailView._on_save_grounding.
        Here we write to ``<image_stem>.grounding.json`` on disk.
        """
        from core.annotation_writer import write_grounding
        try:
            write_grounding(image.path, grounding)
        except OSError:
            import logging
            logging.getLogger(__name__).exception(
                "grounding write failed for %s", image.path)
        self._state.notify_sample_set_mutated()

    def _set_catalog_open(self, on: bool) -> None:
        """Public entry for Settings popup catalog toggle."""
        self._chrome.set_catalog_open(on)

    def _on_workflow_for_batches(self, _wf) -> None:
        """Refresh batch list panel when workflow state changes."""
        self._chrome.refresh_batch_list()

    def _on_target_format_changed(self, format_key: str) -> None:
        """Persist target format and refresh workbench UI."""
        project = self._state.project
        if project is None or not format_key:
            return
        if project.target_format == format_key:
            return

        project.target_format = format_key
        try:
            from core.project import save_project
            save_project(project)
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                "save_project failed after target format change")

        self._state.notify_project_mutated()

    def _sync_annotation_format(self, project) -> None:
        """Push project-derived settings to DetailView + DatasetBar + Hubs.

        Three independent pokes:

        - ``annotation_format`` → DetailView write-back preference + bar
          indicator.
        - full ``project``      → DetailView workbench spec (task type).
        - full ``project``      → DeliveryHub project-aware status copy.
        """
        fmt = getattr(project, "annotation_format", "labelme") if project else "labelme"
        if project is not None:
            try:
                from core.project import (
                    default_target_format_for_task,
                    exportable_target_format_for_task,
                    save_project,
                )
                target = getattr(project, "target_format", "")
                fixed_target = (
                    default_target_format_for_task(project.task_type)
                    if not target else exportable_target_format_for_task(
                        project.task_type, target)
                )
                if project.target_format != fixed_target:
                    project.target_format = fixed_target
                    save_project(project)
            except Exception:
                import logging
                logging.getLogger(__name__).exception(
                    "failed to initialize project target format")
        self._detail.set_annotation_format(fmt)
        self._dataset_bar.set_annotation_format(fmt if project else "")
        self._dataset_bar.set_target_context(project)
        self._detail.set_project_profile(project)
        self._browser.set_target_format(project)
        self._delivery_hub.set_project(project)
        self._refresh_training_versions(project)

    def _refresh_training_versions(self, project) -> None:
        if project is None:
            self._delivery_hub.set_versions([])
            return
        try:
            from core.version_builder import list_training_versions
            versions = list_training_versions(project.root_path)
        except Exception:
            versions = []
        self._delivery_hub.set_versions(versions)

    def cleanup(self) -> None:
        """Stop workers. Called from MainWindow.closeEvent."""
        self._session.cleanup_workers()
        self._tools.cleanup_workers()
