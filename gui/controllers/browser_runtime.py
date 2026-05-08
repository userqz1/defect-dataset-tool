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
    from gui.widgets.context_panel import ContextPanel
    from gui.widgets.data_process_hub import DataProcessHub
    from gui.widgets.dataset_bar import DatasetBar
    from gui.widgets.delivery_hub import DeliveryHub
    from gui.widgets.review_hub import ReviewHub
    from gui.widgets.workspace_sidebar import WorkspaceSidebar
    from gui.workers.thumbnail_worker import ThumbnailWorker


@dataclass
class BrowserRuntime:
    """Bag of references shared across browser controllers.

    Created once by DatasetBrowserView and passed to each controller.
    Controllers read widgets but never replace them.

    IA v3.1:
    - ``workspace_sidebar`` — left, slim stage nav (5 rows, 168px).
    - ``context_panel``     — right, stack of context pages (catalog
      on 标注工作台 grid; future per-image Inspector on detail).
    - ``process_hub`` / ``delivery_hub`` — split by mutation vs delivery scope.
    """

    state: AppState
    shell: QWidget
    browser: BrowserView
    detail: DetailView
    catalog: CatalogPanel
    dataset_bar: DatasetBar
    workspace_sidebar: WorkspaceSidebar
    context_panel: ContextPanel
    process_hub: DataProcessHub
    delivery_hub: DeliveryHub
    review_hub: ReviewHub
    thumb_worker: ThumbnailWorker
    browser_stack: QStackedWidget
    batch_list: BatchListPanel | None = None
