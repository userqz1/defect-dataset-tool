"""Top-level dataset browser — assembly shell.

Lays out ToolSidebar + BrowserView/DetailView stack + CatalogPanel and
wires signals to controllers. Business logic lives in:

- DatasetSessionController — scan, refresh, dataset lifecycle
- BrowserToolController — tool dispatch and execution
- BrowserChromeController — catalog/detail/sidebar panel switching
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (
    QHBoxLayout,
    QStackedWidget,
    QWidget,
)

from gui.app_state import AppState
from gui.controllers.browser_chrome_controller import BrowserChromeController
from gui.controllers.browser_runtime import BrowserRuntime
from gui.controllers.browser_tool_controller import BrowserToolController
from gui.controllers.dataset_session_controller import DatasetSessionController
from gui.views.browser_view import BrowserView
from gui.views.detail_view import DetailView
from gui.workers.thumbnail_worker import ThumbnailWorker


class DatasetBrowserView(QWidget):
    """Top-level browser: directory picker + scan + browse + detail."""

    def __init__(self, app_state: AppState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("datasetBrowserView")
        self._state = app_state

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Column 1: Tools panel
        from gui.widgets.tool_sidebar import ToolSidebar
        self._tool_sidebar = ToolSidebar()
        root.addWidget(self._tool_sidebar)

        # Column 2: Browser + Detail stack
        self._browser_stack = QStackedWidget()
        self._browser = BrowserView(app_state=self._state)
        self._detail = DetailView()
        self._dataset_bar = self._browser.dataset_bar
        root.addWidget(self._browser_stack, 1)

        # Column 3: Catalog panel
        from gui.widgets.catalog_panel import CatalogPanel
        self._catalog = CatalogPanel()
        self._catalog.category_selected.connect(self._browser.select_category)
        self._catalog.rename_requested.connect(self._browser.rename_category)
        self._catalog.merge_requested.connect(self._browser.merge_category)
        self._catalog.split_requested.connect(self._browser.split_category)
        self._browser.set_catalog_tree(self._catalog.tree)
        root.addWidget(self._catalog)

        # Column 4: Batch list panel (hidden by default)
        from gui.widgets.batch_list import BatchListPanel
        self._batch_list = BatchListPanel()
        self._batch_list.hide()
        root.addWidget(self._batch_list)

        # Thumbnail worker
        self._thumb = ThumbnailWorker(size=170, parent=self)
        self._thumb.start()
        self._browser.thumb_request.connect(self._thumb.request)
        self._browser.clear_thumb_queue.connect(self._thumb.clear_queue)
        self._thumb.thumb_ready.connect(self._browser.on_thumb_ready)

        # Stack pages
        self._browser_stack.addWidget(self._browser)
        self._browser_stack.addWidget(self._detail)

        # ---- Controllers ----
        self._rt = BrowserRuntime(
            state=app_state,
            shell=self,
            browser=self._browser,
            detail=self._detail,
            catalog=self._catalog,
            dataset_bar=self._dataset_bar,
            tool_sidebar=self._tool_sidebar,
            thumb_worker=self._thumb,
            browser_stack=self._browser_stack,
            batch_list=self._batch_list,
        )
        self._session = DatasetSessionController(self._rt, parent=self)
        self._tools = BrowserToolController(self._rt, self._session)
        self._chrome = BrowserChromeController(self._rt)

        # ---- Signal wiring ----
        self._tool_sidebar.tool_requested.connect(self._tools.dispatch)

        self._browser.open_clicked.connect(self._session.choose_and_open_directory)
        self._browser.image_activated.connect(self._chrome.activate_detail)
        self._detail.back_requested.connect(self._chrome.back_to_browser)
        self._browser_stack.currentChanged.connect(self._chrome.on_stack_changed)
        self._catalog.close_requested.connect(
            lambda: self._chrome.set_catalog_open(False))
        self._dataset_bar.catalog_toggled.connect(self._chrome.set_catalog_open)

        self._batch_list.close_requested.connect(self._chrome.close_batch_list)
        self._batch_list.commit_requested.connect(self._tools.commit_batch)
        self._batch_list.import_requested.connect(
            self._session.choose_and_open_directory)
        self._state.workflow_changed.connect(self._on_workflow_for_batches)

        self._detail.change_category_requested.connect(
            self._tools.change_category)
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
        self._state.sample_set_changed.connect(
            self._detail.set_sample_set
        )
        self._state.sample_set_changed.connect(
            self._dataset_bar.update_from_sample_set
        )
        self._state.sample_set_status_changed.connect(
            self._dataset_bar.set_sample_set_status
        )
        self._detail.work_status_changed.connect(
            self._on_work_status_changed
        )
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

    # -- Public API --

    def open_directory(self, root: Path) -> None:
        """Programmatic entry — called by MainWindow after welcome page action."""
        self._session.open_directory(root)

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

    def _set_catalog_open(self, on: bool) -> None:
        """Public entry for Settings popup catalog toggle."""
        self._chrome.set_catalog_open(on)

    def _on_workflow_for_batches(self, _wf) -> None:
        """Refresh batch list panel when workflow state changes."""
        self._chrome.refresh_batch_list()

    def _sync_annotation_format(self, project) -> None:
        """Push project's preferred annotation format to DetailView + bar."""
        fmt = getattr(project, "annotation_format", "labelme") if project else "labelme"
        self._detail.set_annotation_format(fmt)
        self._dataset_bar.set_annotation_format(fmt if project else "")

    def cleanup(self) -> None:
        """Stop workers. Called from MainWindow.closeEvent."""
        self._session.cleanup_workers()
        self._tools.cleanup_workers()
