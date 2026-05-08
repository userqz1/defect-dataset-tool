"""Context panel — right-side per-stage / per-object context surface.

Sits as the rightmost column in the workbench shell.  Hosts a stack of
context pages and shows whichever page matches the user's current
focus:

- ``ContextPage.EMPTY``     — default; rendered as a 0-height placeholder
                              so nothing visually leaks while the panel
                              is collapsed.
- ``ContextPage.CATALOG``   — :class:`gui.widgets.catalog_panel.CatalogPanel`
                              (class tree + distribution chart) — shown
                              in 标注工作台 grid mode.
- ``ContextPage.INSPECTOR`` — reserved for a future per-image Inspector
                              that appears on detail drill-in.
- ``ContextPage.QUEUE``     — reserved for the future audit queue (审核修复).

Visibility is binary — the panel is either fully shown (fixed width
:data:`gui.theme.Tokens.CONTEXT_PANEL_WIDTH`) or fully collapsed (width
0).  The owning :class:`gui.controllers.browser_chrome_controller.
BrowserChromeController` is the sole driver of show/hide; pages get
swapped by :class:`gui.views.dataset_browser_view.DatasetBrowserView`
based on the active stage.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from gui.theme import T


class ContextPage:
    """Named indices for the context-panel stack."""

    EMPTY = 0
    CATALOG = 1
    # Reserved for future:
    INSPECTOR = 2
    QUEUE = 3


class ContextPanel(QFrame):
    """Right-side stack of stage- and object-scoped context pages."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("contextPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(T.CONTEXT_PANEL_WIDTH)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._stack = QStackedWidget()
        # Page 0 — empty placeholder so the stack always has a default
        # current widget regardless of registration order.
        self._stack.addWidget(QWidget())
        lay.addWidget(self._stack, 1)

    # -- Public API --

    def add_page(self, w: QWidget) -> int:
        """Register a context page widget. Returns its stack index."""
        return self._stack.addWidget(w)

    def show_page(self, index: int) -> None:
        """Promote a registered page to the front of the stack."""
        if 0 <= index < self._stack.count():
            self._stack.setCurrentIndex(index)

    def current_page(self) -> int:
        return self._stack.currentIndex()
