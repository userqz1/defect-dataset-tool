"""Browser chrome controller — ContextPanel page swapping + drill-in/out.

Extracted from DatasetBrowserView to keep visual-shell switching out
of layout assembly.  Owns the right ContextPanel's page selection
across two orthogonal axes:

- The user's "catalog open" preference (DatasetBar toggle / Settings
  popup) — only meaningful while on the browser grid.
- The browser-vs-detail drill state — when the user double-clicks an
  image, the panel swaps to the inspector page; on back, it returns
  to the catalog page (subject to the open preference).

Non-标注 stages (新数据 / 审核修复 / 导出 / 项目设置) hide the
panel entirely; that gating lives in
:meth:`DatasetBrowserView._on_stage_changed`.  This controller is only
called while the workbench is on the 标注工作台 stage.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gui.controllers.browser_runtime import BrowserRuntime


class BrowserChromeController:
    """Manages right ContextPanel + 标注工作台 drill-in / drill-out."""

    def __init__(self, rt: BrowserRuntime) -> None:
        self._rt = rt
        # User's preferred catalog state (DatasetBar toggle).  Only
        # applies while the browser grid is the active page; the
        # inspector view ignores this and is always visible on detail
        # so the user keeps access to the annotation panes.
        self._catalog_user_open = True

    # -- Public API --

    def set_catalog_open(self, open_: bool) -> None:
        """Toggle the catalog context (DatasetBar button + Settings popup).

        Updates the user preference and re-applies the appropriate
        page based on the current browser/detail drill state.
        """
        self._catalog_user_open = open_
        self._rt.dataset_bar.set_catalog_open(open_)
        # Only re-apply if we're currently on the browser grid; on
        # detail we keep the inspector visible regardless.
        on_browser = (
            self._rt.browser_stack.currentWidget() is self._rt.browser
        )
        if on_browser:
            self._rt.context_panel.setVisible(open_)

    def refresh_batch_list(self) -> None:
        """Reload batch data from workflow state into the 新数据 page."""
        bl = self._rt.batch_list
        if bl is None:
            return
        # Feed project context for rules summary
        proj = self._rt.state.project
        if proj is not None:
            bl.set_project_info(
                proj.name,
                getattr(proj, "root_path", None))
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
        """Swap the right ContextPanel's page based on drill state.

        - On the browser grid → CATALOG page; visibility honours the
          user's "catalog open" preference.
        - On the detail viewer → INSPECTOR page; always visible (the
          panes are part of the per-image workbench, hiding them would
          strand the user's annotation surface).
        """
        from gui.widgets.context_panel import ContextPage

        on_browser = (
            self._rt.browser_stack.widget(index) is self._rt.browser
        )
        if on_browser:
            self._rt.context_panel.show_page(ContextPage.CATALOG)
            self._rt.context_panel.setVisible(self._catalog_user_open)
        else:
            self._rt.context_panel.show_page(ContextPage.INSPECTOR)
            self._rt.context_panel.setVisible(True)

    # -- Backwards-compat shims --

    def set_side_panels_visible(self, visible: bool) -> None:
        """Legacy entry — predates the page-swap behavior.

        Older call sites (none currently expected; the v3.6 split
        replaced them with on_stack_changed) used this to toggle the
        whole right column. Forward to the page-aware logic.
        """
        # Treat as "user wants context panel" → re-evaluate the active
        # page against current drill state.
        if not visible:
            self._rt.context_panel.setVisible(False)
        else:
            self.on_stack_changed(self._rt.browser_stack.currentIndex())
