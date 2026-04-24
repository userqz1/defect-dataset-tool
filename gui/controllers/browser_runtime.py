"""Shared widget references for browser controllers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QStackedWidget, QWidget

    from gui.app_state import AppState
    from gui.views.browser_view import BrowserView
    from gui.views.detail_view import DetailView
    from gui.widgets.batch_list import BatchListPanel
    from gui.widgets.catalog_panel import CatalogPanel
    from gui.widgets.dataset_bar import DatasetBar
    from gui.widgets.tool_sidebar import ToolSidebar
    from gui.workers.thumbnail_worker import ThumbnailWorker


@dataclass
class BrowserRuntime:
    """Bag of references shared across browser controllers.

    Created once by DatasetBrowserView and passed to each controller.
    Controllers read widgets but never replace them.
    """

    state: AppState
    shell: QWidget
    browser: BrowserView
    detail: DetailView
    catalog: CatalogPanel
    dataset_bar: DatasetBar
    tool_sidebar: ToolSidebar
    thumb_worker: ThumbnailWorker
    browser_stack: QStackedWidget
    batch_list: BatchListPanel | None = None
