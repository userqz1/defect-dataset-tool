"""Node editor canvas — drag-and-drop visual pipeline builder.

QGraphicsView-based node graph editor. Users drag tools from the sidebar,
place nodes on the canvas, connect ports, and click nodes to configure.

Components:
- NodeCanvas: QGraphicsView + QGraphicsScene (zoom/pan/grid background)
- NodeItem: QGraphicsItem (title bar + ports + body)
- PortItem: input/output connection point
- ConnectionItem: bezier curve between two ports
"""
from __future__ import annotations

import math
from typing import Any

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PyQt6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QMenu,
    QWidget,
)

from gui.theme import T


# ---------- Constants ----------

NODE_WIDTH = 180
NODE_HEADER_H = 32
NODE_PORT_H = 24
NODE_BODY_PAD = 8
PORT_RADIUS = 6
GRID_SIZE = 20

# Colors (will reference tokens at paint time)
_C = {
    "node_bg": "#2d2a26",
    "node_header": "#c96442",
    "node_border": "#3a3733",
    "port_in": "#5a9a5a",
    "port_out": "#5a7acf",
    "connection": "#9a958a",
    "text": "#ece7df",
    "grid": "#3a3733",
    "canvas": "#1f1d1b",
}


def _update_colors():
    """Refresh colors from current theme tokens."""
    _C["node_bg"] = T.CONTENT
    _C["node_header"] = T.ACCENT
    _C["node_border"] = T.BORDER
    _C["port_in"] = T.SUCCESS
    _C["port_out"] = "#5a7acf"
    _C["connection"] = T.TEXT_3
    _C["text"] = T.TEXT
    _C["grid"] = T.BORDER
    _C["canvas"] = T.SURFACE_DIM


# ---------- Port ----------

class PortItem(QGraphicsEllipseItem):
    """Input or output port on a node."""

    def __init__(self, name: str, is_output: bool, parent: NodeItem) -> None:
        super().__init__(-PORT_RADIUS, -PORT_RADIUS, PORT_RADIUS * 2, PORT_RADIUS * 2, parent)
        self.name = name
        self.is_output = is_output
        self.node: NodeItem = parent
        self.connections: list[ConnectionItem] = []

        color = QColor(_C["port_out"] if is_output else _C["port_in"])
        self.setBrush(QBrush(color))
        self.setPen(QPen(QColor(_C["node_border"]), 1))
        self.setZValue(2)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setToolTip(name)

    @property
    def center_scene(self) -> QPointF:
        return self.scenePos()


# ---------- Connection ----------

class ConnectionItem(QGraphicsPathItem):
    """Bezier curve connecting two ports."""

    def __init__(self, source: PortItem, target: PortItem) -> None:
        super().__init__()
        self.source = source
        self.target = target
        source.connections.append(self)
        target.connections.append(self)
        self.setPen(QPen(QColor(_C["connection"]), 2))
        self.setZValue(0)
        self.update_path()

    def update_path(self) -> None:
        p1 = self.source.center_scene
        p2 = self.target.center_scene
        dx = abs(p2.x() - p1.x()) * 0.5
        path = QPainterPath()
        path.moveTo(p1)
        path.cubicTo(p1.x() + dx, p1.y(), p2.x() - dx, p2.y(), p2.x(), p2.y())
        self.setPath(path)

    def remove(self) -> None:
        if self in self.source.connections:
            self.source.connections.remove(self)
        if self in self.target.connections:
            self.target.connections.remove(self)
        scene = self.scene()
        if scene:
            scene.removeItem(self)


# ---------- Node ----------

class NodeItem(QGraphicsRectItem):
    """A processing node on the canvas."""

    def __init__(self, node_name: str, display_name: str, x: float = 0, y: float = 0) -> None:
        self.node_name = node_name
        self.display_name = display_name
        self.inputs: list[PortItem] = []
        self.outputs: list[PortItem] = []
        self._options: dict[str, Any] = {}
        self._status: str = ""

        # Calculate size
        n_ports = max(1, 1)  # 1 input, 1 output
        body_h = n_ports * NODE_PORT_H + NODE_BODY_PAD * 2
        total_h = NODE_HEADER_H + body_h

        super().__init__(0, 0, NODE_WIDTH, total_h)
        self.setPos(x, y)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setZValue(1)
        self.setCursor(Qt.CursorShape.SizeAllCursor)

        # Styling
        self.setBrush(QBrush(QColor(_C["node_bg"])))
        self.setPen(QPen(QColor(_C["node_border"]), 1.5))
        self.setRect(0, 0, NODE_WIDTH, total_h)

        # Title
        self._title = QGraphicsTextItem(display_name, self)
        self._title.setDefaultTextColor(QColor("#ffffff"))
        font = QFont()
        font.setBold(True)
        font.setPointSize(9)
        self._title.setFont(font)
        self._title.setPos(8, 4)

        # Status text
        self._status_item = QGraphicsTextItem("", self)
        self._status_item.setDefaultTextColor(QColor(_C["connection"]))
        sfont = QFont()
        sfont.setPointSize(8)
        self._status_item.setFont(sfont)
        self._status_item.setPos(8, NODE_HEADER_H + 4)

        # Ports
        port_y = NODE_HEADER_H + NODE_BODY_PAD + NODE_PORT_H // 2

        inp = PortItem("输入", False, self)
        inp.setPos(0, port_y)
        self.inputs.append(inp)

        out = PortItem("输出", True, self)
        out.setPos(NODE_WIDTH, port_y)
        self.outputs.append(out)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        # Body
        rect = self.rect()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Background
        painter.setBrush(QBrush(QColor(_C["node_bg"])))
        border_color = QColor(T.ACCENT) if self.isSelected() else QColor(_C["node_border"])
        painter.setPen(QPen(border_color, 2 if self.isSelected() else 1))
        painter.drawRoundedRect(rect, 6, 6)

        # Header bar
        header = QRectF(rect.x(), rect.y(), rect.width(), NODE_HEADER_H)
        grad = QLinearGradient(header.topLeft(), header.topRight())
        grad.setColorAt(0, QColor(_C["node_header"]))
        grad.setColorAt(1, QColor(_C["node_header"]).darker(120))
        painter.setBrush(QBrush(grad))
        painter.setPen(Qt.PenStyle.NoPen)
        path = QPainterPath()
        path.addRoundedRect(header, 6, 6)
        # Clip bottom corners of header
        clip = QRectF(rect.x(), rect.y() + NODE_HEADER_H - 6, rect.width(), 6)
        path.addRect(clip)
        painter.drawPath(path)

    def set_status(self, text: str) -> None:
        self._status = text
        self._status_item.setPlainText(text)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            # Update all connections
            for port in self.inputs + self.outputs:
                for conn in port.connections:
                    conn.update_path()
        return super().itemChange(change, value)


# ---------- Canvas ----------

class NodeCanvas(QGraphicsView):
    """Zoomable/pannable canvas for node editing."""

    node_selected = pyqtSignal(str, str)  # (node_name, display_name)
    node_double_clicked = pyqtSignal(str)  # node_name

    def __init__(self, parent: QWidget | None = None) -> None:
        self._scene = QGraphicsScene()
        super().__init__(self._scene, parent)
        self._nodes: list[NodeItem] = []
        self._temp_connection: QGraphicsPathItem | None = None
        self._drag_source_port: PortItem | None = None
        self._zoom = 1.0

        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scene.setSceneRect(-2000, -2000, 4000, 4000)
        _update_colors()
        self.setBackgroundBrush(QBrush(QColor(_C["canvas"])))

    def add_node(self, node_name: str, display_name: str, x: float = 0, y: float = 0) -> NodeItem:
        """Add a node to the canvas."""
        node = NodeItem(node_name, display_name, x, y)
        self._scene.addItem(node)
        self._nodes.append(node)
        return node

    def remove_selected(self) -> None:
        """Remove all selected nodes and their connections."""
        for item in list(self._scene.selectedItems()):
            if isinstance(item, NodeItem):
                # Remove connections
                for port in item.inputs + item.outputs:
                    for conn in list(port.connections):
                        conn.remove()
                self._scene.removeItem(item)
                if item in self._nodes:
                    self._nodes.remove(item)

    def get_nodes(self) -> list[NodeItem]:
        return list(self._nodes)

    def clear_all(self) -> None:
        self._nodes.clear()
        self._scene.clear()

    # ---- Events ----

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawBackground(painter, rect)
        # Draw grid
        pen = QPen(QColor(_C["grid"]), 0.5)
        painter.setPen(pen)

        left = int(rect.left()) - (int(rect.left()) % GRID_SIZE)
        top = int(rect.top()) - (int(rect.top()) % GRID_SIZE)

        lines = []
        x = left
        while x < rect.right():
            lines.append((QPointF(x, rect.top()), QPointF(x, rect.bottom())))
            x += GRID_SIZE
        y = top
        while y < rect.bottom():
            lines.append((QPointF(rect.left(), y), QPointF(rect.right(), y)))
            y += GRID_SIZE

        for p1, p2 in lines:
            painter.drawLine(p1, p2)

    def wheelEvent(self, event) -> None:
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self._zoom *= factor
        self._zoom = max(0.2, min(3.0, self._zoom))
        self.setTransform(self.transform().scale(factor, factor) if abs(factor - 1) > 0.001 else self.transform())
        # Simpler zoom
        self.resetTransform()
        self.scale(self._zoom, self._zoom)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            fake = type(event)(
                event.type(), event.localPos(), Qt.MouseButton.LeftButton,
                event.buttons(), event.modifiers()
            )
            super().mousePressEvent(fake)
            return

        # Check if clicking on a port
        item = self.itemAt(event.pos())
        if isinstance(item, PortItem) and item.is_output:
            self._drag_source_port = item
            self._temp_connection = QGraphicsPathItem()
            self._temp_connection.setPen(QPen(QColor(_C["connection"]), 2, Qt.PenStyle.DashLine))
            self._scene.addItem(self._temp_connection)
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_source_port and self._temp_connection:
            p1 = self._drag_source_port.center_scene
            p2 = self.mapToScene(event.pos())
            dx = abs(p2.x() - p1.x()) * 0.5
            path = QPainterPath()
            path.moveTo(p1)
            path.cubicTo(p1.x() + dx, p1.y(), p2.x() - dx, p2.y(), p2.x(), p2.y())
            self._temp_connection.setPath(path)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)

        if self._drag_source_port and self._temp_connection:
            # Check if released on an input port
            item = self.itemAt(event.pos())
            if isinstance(item, PortItem) and not item.is_output and item.node != self._drag_source_port.node:
                conn = ConnectionItem(self._drag_source_port, item)
                self._scene.addItem(conn)

            self._scene.removeItem(self._temp_connection)
            self._temp_connection = None
            self._drag_source_port = None
            return

        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        item = self.itemAt(event.pos())
        while item and not isinstance(item, NodeItem):
            item = item.parentItem()
        if isinstance(item, NodeItem):
            self.node_double_clicked.emit(item.node_name)
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event) -> None:
        from core.nodes import NODES
        menu = QMenu(self)
        for name, node in NODES.items():
            action = menu.addAction(f"添加: {node.display_name}")
            pos = self.mapToScene(event.pos())
            action.triggered.connect(lambda checked, n=name, dn=node.display_name, p=pos:
                                      self.add_node(n, dn, p.x(), p.y()))
        menu.addSeparator()
        if self._scene.selectedItems():
            menu.addAction("删除选中", self.remove_selected)
        menu.exec(event.globalPos())

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Delete:
            self.remove_selected()
        else:
            super().keyPressEvent(event)
