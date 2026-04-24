"""Browser chrome controller — catalog/detail/sidebar panel orchestration.

Extracted from DatasetBrowserView to separate visual-shell switching
(catalog toggle, detail drill-in/out, side panel visibility) from
layout assembly.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gui.controllers.browser_runtime import BrowserRuntime


class BrowserChromeController:
    """Manages catalog visibility, detail/grid switching, and side panels."""

    def __init__(self, rt: BrowserRuntime) -> None:
        self._rt = rt
        self._catalog_user_open = True
        self._batch_list_open = False

    # -- Public API --

    def set_side_panels_visible(self, visible: bool) -> None:
        self._rt.tool_sidebar.setVisible(visible)
        self._rt.catalog.setVisible(visible and self._catalog_user_open)
        bl = self._rt.batch_list
        if bl is not None:
            bl.setVisible(visible and self._batch_list_open)

    def set_catalog_open(self, open_: bool) -> None:
        self._catalog_user_open = open_
        self._rt.catalog.setVisible(open_)
        self._rt.dataset_bar.set_catalog_open(open_)

    def toggle_batch_list(self) -> None:
        """Toggle the batch list panel visibility."""
        self._batch_list_open = not self._batch_list_open
        bl = self._rt.batch_list
        if bl is not None:
            bl.setVisible(self._batch_list_open)
            if self._batch_list_open:
                self.refresh_batch_list()

    def close_batch_list(self) -> None:
        self._batch_list_open = False
        bl = self._rt.batch_list
        if bl is not None:
            bl.setVisible(False)

    def refresh_batch_list(self) -> None:
        """Reload batch data from workflow state into the panel."""
        bl = self._rt.batch_list
        if bl is None:
            return
        wf = self._rt.state.workflow
        if wf is None:
            bl.set_batches([])
            return
        from core.inbox import all_batch_summaries
        bl.set_batches(all_batch_summaries(wf))

    def activate_detail(self, img, imgs) -> None:
        self._rt.detail.show_image(img, imgs)
        self._rt.browser_stack.setCurrentWidget(self._rt.detail)

    def back_to_browser(self) -> None:
        self._rt.browser_stack.setCurrentWidget(self._rt.browser)

    def on_stack_changed(self, index: int) -> None:
        on_browser = (
            self._rt.browser_stack.widget(index) is self._rt.browser
        )
        self.set_side_panels_visible(on_browser)
