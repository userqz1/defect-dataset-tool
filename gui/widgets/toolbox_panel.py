"""Floating toolbox panel + sidebar drag filter for the node canvas.

Provides two drag sources that both produce the same MIME payload
(``application/x-dataforge-node``):

1. **ToolboxPanel** — floating overlay on the canvas left edge.
2. **NodeDragFilter** — QObject event filter installed on FluentWindow
   sidebar navigation items to make them draggable too.
"""
from __future__ import annotations

from PyQt6.QtCore import QByteArray, QEvent, QMimeData, QObject, QPoint, Qt
from PyQt6.QtGui import QColor, QDrag, QFont, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CaptionLabel,
    FluentIcon as FIF,
    SearchLineEdit,
    TransparentToolButton,
)

from gui.theme import T
from gui.widgets.node_editor import NodeCanvas


# ---------------------------------------------------------------------------
# ToolboxItem — single draggable entry
# ---------------------------------------------------------------------------

class ToolboxItem(QFrame):
    """A tool in the toolbox. Drag it onto the canvas to create a node."""

    def __init__(
        self,
        node_name: str,
        display_name: str,
        step_type: str,
        color_token: str,
        icon: FIF,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.node_name = node_name
        self.display_name = display_name
        self.step_type = step_type
        self._color_token = color_token
        self.setObjectName("toolboxItem")
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setFixedHeight(36)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        # Category color dot
        self._dot = QLabel()
        self._dot.setFixedSize(8, 8)
        self._dot.setStyleSheet(
            f"background:{getattr(T, color_token, T.ACCENT)};"
            f"border-radius:4px;"
        )
        layout.addWidget(self._dot)

        # Icon
        self._icon_w = TransparentToolButton(icon)
        self._icon_w.setFixedSize(20, 20)
        self._icon_w.setEnabled(False)
        layout.addWidget(self._icon_w)

        # Name
        self._label = CaptionLabel(display_name)
        layout.addWidget(self._label, 1)

        self._drag_start = QPoint()

    def set_collapsed(self, collapsed: bool) -> None:
        self._label.setVisible(not collapsed)
        self.setFixedWidth(44 if collapsed else 180)

    # -- drag initiation --

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if (event.pos() - self._drag_start).manhattanLength() < 10:
            return

        drag = QDrag(self)
        mime = QMimeData()
        payload = f"{self.node_name}|{self.display_name}|{self.step_type}"
        mime.setData(NodeCanvas.MIME_TYPE, QByteArray(payload.encode()))
        drag.setMimeData(mime)

        # Create drag pixmap
        cat_color = QColor(getattr(T, self._color_token, T.ACCENT))
        pixmap = QPixmap(130, 36)
        pixmap.fill(QColor(0, 0, 0, 0))
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bg = QColor(cat_color)
        bg.setAlpha(40)
        p.setBrush(bg)
        p.setPen(cat_color)
        p.drawRoundedRect(1, 1, 128, 34, 6, 6)
        p.setPen(QColor(T.TEXT))
        f = QFont()
        f.setPointSize(9)
        f.setBold(True)
        p.setFont(f)
        p.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, self.display_name)
        p.end()
        drag.setPixmap(pixmap)
        drag.setHotSpot(QPoint(65, 18))

        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        drag.exec(Qt.DropAction.CopyAction)
        self.setCursor(Qt.CursorShape.OpenHandCursor)


# ---------------------------------------------------------------------------
# ToolboxPanel — floating overlay
# ---------------------------------------------------------------------------

class ToolboxPanel(QFrame):
    """Floating toolbox overlay on the canvas left edge."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("toolboxPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._collapsed = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        header = QFrame()
        header.setFixedHeight(32)
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(10, 0, 4, 0)
        self._title = CaptionLabel("工具箱")
        self._title.setObjectName("toolboxTitle")
        h_lay.addWidget(self._title)
        h_lay.addStretch()
        self._toggle = TransparentToolButton(FIF.MINIMIZE)
        self._toggle.setFixedSize(24, 24)
        self._toggle.setToolTip("折叠/展开")
        self._toggle.clicked.connect(self._on_toggle)
        h_lay.addWidget(self._toggle)
        root.addWidget(header)

        # Search
        self._search = SearchLineEdit()
        self._search.setPlaceholderText("搜索工具…")
        self._search.setFixedHeight(28)
        self._search.setContentsMargins(6, 0, 6, 4)
        self._search.textChanged.connect(self._on_filter)
        root.addWidget(self._search)

        # Tool list (scrollable)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._list_w = QWidget()
        self._list_lay = QVBoxLayout(self._list_w)
        self._list_lay.setContentsMargins(4, 4, 4, 4)
        self._list_lay.setSpacing(2)
        self._list_lay.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(self._list_w)
        root.addWidget(scroll, 1)

        self._items: list[ToolboxItem] = []
        self._sections: list[QLabel] = []
        self._populate()
        self._update_size()

    def _populate(self) -> None:
        from core.nodes import CATEGORY_META, NODES

        _icons = {
            "quality_check": FIF.CERTIFICATE,
            "dedup": FIF.COPY,
            "augment": FIF.ADD,
            "split": FIF.TILES,
        }

        # Group by step_type
        groups: dict[str, list] = {}
        for name, node in NODES.items():
            groups.setdefault(node.step_type, []).append((name, node))

        for step_type, entries in groups.items():
            meta = CATEGORY_META.get(step_type)
            if meta:
                sec = CaptionLabel(meta.display_name)
                sec.setObjectName("toolboxSection")
                self._list_lay.addWidget(sec)
                self._sections.append(sec)

            for name, node in entries:
                icon = _icons.get(name, FIF.TAG)
                color_tok = meta.color_token if meta else "ACCENT"
                item = ToolboxItem(name, node.display_name, node.step_type, color_tok, icon)
                self._list_lay.addWidget(item)
                self._items.append(item)

    def _on_toggle(self) -> None:
        self._collapsed = not self._collapsed
        self._title.setVisible(not self._collapsed)
        self._search.setVisible(not self._collapsed)
        for sec in self._sections:
            sec.setVisible(not self._collapsed)
        self._toggle.setIcon(FIF.CHEVRON_RIGHT if self._collapsed else FIF.MINIMIZE)
        for item in self._items:
            item.set_collapsed(self._collapsed)
        self._update_size()

    def _update_size(self) -> None:
        self.setFixedWidth(56 if self._collapsed else 200)

    def _on_filter(self, text: str) -> None:
        lo = text.lower()
        for item in self._items:
            item.setVisible(lo in item.display_name.lower() or not text)


# ---------------------------------------------------------------------------
# NodeDragFilter — makes sidebar navigation items draggable
# ---------------------------------------------------------------------------

class NodeDragFilter(QObject):
    """Event filter that adds QDrag support to a qfluentwidgets nav item.

    Install on the *itemWidget* (NavigationTreeItem) of a sidebar tool
    so the user can drag it onto the node canvas.

    Usage::

        w = self.navigationInterface.addItem(routeKey=..., ...)
        filt = NodeDragFilter(node_name, display_name, step_type, w.itemWidget)
        w.itemWidget.installEventFilter(filt)
    """

    def __init__(
        self,
        node_name: str,
        display_name: str,
        step_type: str,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._node_name = node_name
        self._display_name = display_name
        self._step_type = step_type
        self._press_pos: QPoint | None = None

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        etype = event.type()

        if etype == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                self._press_pos = event.pos()
            return False  # let the click through for onClick callback

        if etype == QEvent.Type.MouseMove:
            if (
                self._press_pos is not None
                and (event.pos() - self._press_pos).manhattanLength()
                >= QApplication.startDragDistance()
            ):
                self._start_drag(obj)
                self._press_pos = None
                return True  # consume the move — we started a drag
            return False

        if etype == QEvent.Type.MouseButtonRelease:
            self._press_pos = None
            return False

        return False

    def _start_drag(self, source: QObject) -> None:
        from core.nodes import CATEGORY_META

        drag = QDrag(source)
        mime = QMimeData()
        payload = f"{self._node_name}|{self._display_name}|{self._step_type}"
        mime.setData(NodeCanvas.MIME_TYPE, QByteArray(payload.encode()))
        drag.setMimeData(mime)

        # Drag pixmap — small badge with category tint
        meta = CATEGORY_META.get(self._step_type)
        cat_color = QColor(getattr(T, meta.color_token, T.ACCENT)) if meta else QColor(T.ACCENT)

        pix = QPixmap(130, 36)
        pix.fill(QColor(0, 0, 0, 0))
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bg = QColor(cat_color)
        bg.setAlpha(40)
        p.setBrush(bg)
        p.setPen(cat_color)
        p.drawRoundedRect(1, 1, 128, 34, 6, 6)
        p.setPen(QColor(T.TEXT))
        f = QFont()
        f.setPointSize(9)
        f.setBold(True)
        p.setFont(f)
        p.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, self._display_name)
        p.end()

        drag.setPixmap(pix)
        drag.setHotSpot(QPoint(65, 18))
        drag.exec(Qt.DropAction.CopyAction)
