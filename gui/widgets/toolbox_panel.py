"""Sidebar drag filter — makes navigation items draggable onto the node canvas."""
from __future__ import annotations

from PyQt6.QtCore import QByteArray, QEvent, QMimeData, QObject, QPoint, Qt
from PyQt6.QtGui import QColor, QDrag, QFont, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication

from gui.theme import T
from gui.widgets.node_editor import NodeCanvas


class NodeDragFilter(QObject):
    """Event filter that adds QDrag to a qfluentwidgets nav item.

    Install on ``widget.itemWidget`` after ``addItem()``::

        w = self.navigationInterface.addItem(...)
        filt = NodeDragFilter(node_name, display_name, step_type, w.itemWidget)
        w.itemWidget.installEventFilter(filt)
    """

    def __init__(self, node_name: str, display_name: str,
                 step_type: str, parent: QObject | None = None) -> None:
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
            return False
        if etype == QEvent.Type.MouseMove:
            if (self._press_pos is not None
                    and (event.pos() - self._press_pos).manhattanLength()
                    >= QApplication.startDragDistance()):
                self._start_drag(obj)
                self._press_pos = None
                return True
            return False
        if etype == QEvent.Type.MouseButtonRelease:
            self._press_pos = None
            return False
        return False

    def _start_drag(self, source: QObject) -> None:
        drag = QDrag(source)
        mime = QMimeData()
        payload = f"{self._node_name}|{self._display_name}|{self._step_type}"
        mime.setData(NodeCanvas.MIME_TYPE, QByteArray(payload.encode()))
        drag.setMimeData(mime)

        # Small drag pixmap
        pix = QPixmap(120, 32)
        pix.fill(QColor(0, 0, 0, 0))
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        accent = QColor(T.ACCENT)
        accent.setAlpha(40)
        p.setBrush(accent)
        p.setPen(QColor(T.ACCENT))
        p.drawRoundedRect(1, 1, 118, 30, 6, 6)
        p.setPen(QColor(T.TEXT))
        f = QFont()
        f.setPointSize(9)
        f.setBold(True)
        p.setFont(f)
        p.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, self._display_name)
        p.end()
        drag.setPixmap(pix)
        drag.setHotSpot(QPoint(60, 16))
        drag.exec(Qt.DropAction.CopyAction)
