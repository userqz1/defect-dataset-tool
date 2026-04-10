"""Node editor canvas — QGraphicsView-based visual pipeline builder.

Nodes are dragged from the sidebar, placed on the canvas, connected via ports,
and clicked to open configuration in the Inspector panel.

Components:
- NodeCanvas: QGraphicsView (zoom/pan/grid/drop target)
- NodeItem: rounded rect with icon + title + status + ports
- PortItem: connection point (input left, output right)
- ConnectionItem: bezier curve between ports
"""
from __future__ import annotations

import uuid
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
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QMenu,
    QWidget,
)

from gui.theme import T

# ---------- Sizing ----------
NODE_W = 220
NODE_H = 90
HEADER_H = 30
PORT_R = 7
GRID_SIZE = 20

# All nodes use the app accent color for a unified look
CAT_COLORS = {
    "input":      None,   # filled at paint time from T.ACCENT
    "processing": None,
    "output":     None,
}


# ---------- Port ----------

class PortItem(QGraphicsEllipseItem):
    """Input/output connection point on a node."""

    def __init__(self, name: str, is_output: bool, parent: "NodeItem") -> None:
        d = PORT_R * 2
        super().__init__(-PORT_R, -PORT_R, d, d, parent)
        self.port_name = name
        self.is_output = is_output
        self.node: NodeItem = parent
        self.connections: list[ConnectionItem] = []

        color = "#5a7acf" if is_output else "#5a9a5a"
        self.setBrush(QBrush(QColor(color)))
        self.setPen(QPen(QColor(color).darker(130), 1.5))
        self.setZValue(3)
        self.setCursor(Qt.CursorShape.CrossCursor)

        # Port label
        lbl = QGraphicsSimpleTextItem(name, parent)
        lbl.setFont(QFont("", 7))
        lbl.setBrush(QBrush(QColor(T.TEXT_3)))
        if is_output:
            lbl.setPos(self.pos().x() - lbl.boundingRect().width() - PORT_R - 4,
                       self.pos().y() - 6)
        else:
            lbl.setPos(self.pos().x() + PORT_R + 4, self.pos().y() - 6)
        self._label = lbl

    @property
    def center_scene(self) -> QPointF:
        return self.scenePos()

    def reposition_label(self) -> None:
        if self.is_output:
            self._label.setPos(self.x() - self._label.boundingRect().width() - PORT_R - 4,
                               self.y() - 6)
        else:
            self._label.setPos(self.x() + PORT_R + 4, self.y() - 6)


# ---------- Connection ----------

class ConnectionItem(QGraphicsPathItem):
    """Bezier curve between two ports."""

    def __init__(self, source: PortItem, target: PortItem) -> None:
        super().__init__()
        self.source = source
        self.target = target
        source.connections.append(self)
        target.connections.append(self)
        self.setPen(QPen(QColor(T.TEXT_3), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        self.setZValue(0)
        self.update_path()

    def update_path(self) -> None:
        p1 = self.source.center_scene
        p2 = self.target.center_scene
        dx = max(abs(p2.x() - p1.x()) * 0.5, 50)
        path = QPainterPath()
        path.moveTo(p1)
        path.cubicTo(p1.x() + dx, p1.y(), p2.x() - dx, p2.y(), p2.x(), p2.y())
        self.setPath(path)

    def remove(self) -> None:
        if self in self.source.connections:
            self.source.connections.remove(self)
        if self in self.target.connections:
            self.target.connections.remove(self)
        if self.scene():
            self.scene().removeItem(self)


# ---------- Node ----------

class NodeItem(QGraphicsRectItem):
    """A processing node on the canvas."""

    def __init__(self, node_id: str, label: str, category: str,
                 input_names: list[str], output_names: list[str],
                 x: float = 0, y: float = 0) -> None:
        super().__init__(0, 0, NODE_W, NODE_H)
        self.node_id = node_id
        self.instance_id = str(uuid.uuid4())[:8]
        self.display_name = label
        self.category = category
        self.inputs: list[PortItem] = []
        self.outputs: list[PortItem] = []
        self._params: dict[str, Any] = {}
        self._status_text = ""

        self.setPos(x, y)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setZValue(1)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setPen(QPen(Qt.PenStyle.NoPen))

        # Title text
        self._title = QGraphicsSimpleTextItem(label, self)
        self._title.setFont(QFont("", 10, QFont.Weight.Bold))
        self._title.setBrush(QBrush(QColor("#ffffff")))
        self._title.setPos(10, 5)

        # Status text
        self._status_item = QGraphicsSimpleTextItem("", self)
        self._status_item.setFont(QFont("", 8))
        self._status_item.setBrush(QBrush(QColor(T.TEXT_3)))
        self._status_item.setPos(10, HEADER_H + 8)

        # Ports
        n_in = max(len(input_names), 1) if input_names else 0
        n_out = max(len(output_names), 1) if output_names else 0
        port_start_y = HEADER_H + (NODE_H - HEADER_H) // 2

        for i, name in enumerate(input_names):
            p = PortItem(name, False, self)
            y_off = port_start_y + i * 24
            p.setPos(0, y_off)
            p.reposition_label()
            self.inputs.append(p)

        for i, name in enumerate(output_names):
            p = PortItem(name, True, self)
            y_off = port_start_y + i * 24
            p.setPos(NODE_W, y_off)
            p.reposition_label()
            self.outputs.append(p)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        radius = 8

        # Body shadow
        shadow = rect.adjusted(2, 2, 2, 2)
        painter.setBrush(QBrush(QColor(0, 0, 0, 40)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(shadow, radius, radius)

        # Body fill
        painter.setBrush(QBrush(QColor(T.CONTENT)))
        border_color = QColor(T.ACCENT) if self.isSelected() else QColor(T.BORDER)
        painter.setPen(QPen(border_color, 2 if self.isSelected() else 1))
        painter.drawRoundedRect(rect, radius, radius)

        # Header gradient — unified app accent color
        header = QRectF(rect.x(), rect.y(), rect.width(), HEADER_H)
        accent = QColor(T.ACCENT)
        grad = QLinearGradient(header.topLeft(), header.topRight())
        grad.setColorAt(0, accent)
        grad.setColorAt(1, accent.darker(120))

        header_path = QPainterPath()
        header_path.addRoundedRect(QRectF(rect.x(), rect.y(), rect.width(), HEADER_H + radius), radius, radius)
        clip = QPainterPath()
        clip.addRect(QRectF(rect.x(), rect.y() + HEADER_H, rect.width(), radius))
        header_path = header_path.subtracted(clip)
        # Simpler: draw full rounded rect then cover bottom corners
        painter.setBrush(QBrush(grad))
        painter.setPen(Qt.PenStyle.NoPen)
        full_header = QPainterPath()
        full_header.addRoundedRect(header, radius, radius)
        bottom_rect = QPainterPath()
        bottom_rect.addRect(QRectF(rect.x(), rect.y() + HEADER_H - radius, rect.width(), radius))
        painter.drawPath(full_header.united(bottom_rect))

    def set_status(self, text: str) -> None:
        self._status_text = text
        self._status_item.setText(text)

    def set_params(self, params: dict) -> None:
        self._params = dict(params)

    def get_params(self) -> dict:
        return dict(self._params)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            for port in self.inputs + self.outputs:
                for conn in port.connections:
                    conn.update_path()
        return super().itemChange(change, value)


# ---------- Canvas ----------

MIME_TYPE = "application/x-dataforge-node"


class NodeCanvas(QGraphicsView):
    """Zoomable/pannable canvas for node editing. Accepts drops from sidebar."""

    node_selected = pyqtSignal(object)     # NodeItem or None
    node_double_clicked = pyqtSignal(object)  # NodeItem

    def __init__(self, parent: QWidget | None = None) -> None:
        self._scene = QGraphicsScene()
        super().__init__(self._scene, parent)
        self._nodes: list[NodeItem] = []
        self._temp_line: QGraphicsPathItem | None = None
        self._drag_port: PortItem | None = None
        self._zoom = 1.0

        self.setAcceptDrops(True)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scene.setSceneRect(-3000, -3000, 6000, 6000)
        self.setBackgroundBrush(QBrush(QColor(T.SURFACE_DIM)))

    # ---- Public API ----

    def add_node_from_spec(self, node_id: str, x: float = 0, y: float = 0) -> NodeItem | None:
        from core.nodes import NODE_REGISTRY
        spec = NODE_REGISTRY.get(node_id)
        if not spec:
            return None
        node = NodeItem(
            node_id=spec.node_id,
            label=spec.label,
            category=spec.category,
            input_names=[p.name for p in spec.inputs],
            output_names=[p.name for p in spec.outputs],
            x=x, y=y,
        )
        # Set default params
        node.set_params({p.name: p.default for p in spec.parameters})
        self._scene.addItem(node)
        self._nodes.append(node)
        return node

    def get_nodes(self) -> list[NodeItem]:
        return list(self._nodes)

    def remove_selected(self) -> None:
        for item in list(self._scene.selectedItems()):
            if isinstance(item, NodeItem):
                for port in item.inputs + item.outputs:
                    for conn in list(port.connections):
                        conn.remove()
                self._scene.removeItem(item)
                if item in self._nodes:
                    self._nodes.remove(item)

    def clear_all(self) -> None:
        self._nodes.clear()
        self._scene.clear()

    # ---- Background grid ----

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawBackground(painter, rect)
        pen = QPen(QColor(T.BORDER), 0.5)
        painter.setPen(pen)
        left = int(rect.left()) - (int(rect.left()) % GRID_SIZE)
        top = int(rect.top()) - (int(rect.top()) % GRID_SIZE)
        x = left
        while x < rect.right():
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            x += GRID_SIZE
        y = top
        while y < rect.bottom():
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            y += GRID_SIZE

    # ---- Zoom / Pan ----

    def wheelEvent(self, event) -> None:
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self._zoom = max(0.2, min(3.0, self._zoom * factor))
        self.resetTransform()
        self.scale(self._zoom, self._zoom)

    def mousePressEvent(self, event) -> None:
        # Middle button → pan
        if event.button() == Qt.MouseButton.MiddleButton:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            fake = type(event)(event.type(), event.localPos(), Qt.MouseButton.LeftButton,
                               event.buttons(), event.modifiers())
            super().mousePressEvent(fake)
            return

        # Click on output port → start connection drag
        item = self.itemAt(event.pos())
        if isinstance(item, PortItem) and item.is_output:
            self._drag_port = item
            self._temp_line = QGraphicsPathItem()
            self._temp_line.setPen(QPen(QColor(T.TEXT_3), 2, Qt.PenStyle.DashLine))
            self._scene.addItem(self._temp_line)
            return

        super().mousePressEvent(event)

        # Emit selection
        sel = [i for i in self._scene.selectedItems() if isinstance(i, NodeItem)]
        self.node_selected.emit(sel[0] if sel else None)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_port and self._temp_line:
            p1 = self._drag_port.center_scene
            p2 = self.mapToScene(event.pos())
            dx = max(abs(p2.x() - p1.x()) * 0.5, 30)
            path = QPainterPath()
            path.moveTo(p1)
            path.cubicTo(p1.x() + dx, p1.y(), p2.x() - dx, p2.y(), p2.x(), p2.y())
            self._temp_line.setPath(path)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)

        if self._drag_port and self._temp_line:
            item = self.itemAt(event.pos())
            if isinstance(item, PortItem) and not item.is_output and item.node != self._drag_port.node:
                conn = ConnectionItem(self._drag_port, item)
                self._scene.addItem(conn)
            self._scene.removeItem(self._temp_line)
            self._temp_line = None
            self._drag_port = None
            return

        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        item = self.itemAt(event.pos())
        while item and not isinstance(item, NodeItem):
            item = item.parentItem()
        if isinstance(item, NodeItem):
            self.node_double_clicked.emit(item)
        super().mouseDoubleClickEvent(event)

    # ---- Drop from sidebar ----

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(MIME_TYPE):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(MIME_TYPE):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        if event.mimeData().hasFormat(MIME_TYPE):
            node_id = bytes(event.mimeData().data(MIME_TYPE)).decode()
            pos = self.mapToScene(event.position().toPoint())
            node = self.add_node_from_spec(node_id, pos.x(), pos.y())
            if node:
                # Auto-connect to previous node's output
                if len(self._nodes) >= 2:
                    prev = self._nodes[-2]
                    if prev.outputs and node.inputs:
                        conn = ConnectionItem(prev.outputs[0], node.inputs[0])
                        self._scene.addItem(conn)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    # ---- Context menu ----

    def contextMenuEvent(self, event) -> None:
        from core.nodes import NODE_REGISTRY
        menu = QMenu(self)
        for cat_label, cat_key in [("输入", "input"), ("处理", "processing"), ("输出", "output")]:
            sub = menu.addMenu(cat_label)
            for nid, spec in NODE_REGISTRY.items():
                if spec.category == cat_key:
                    pos = self.mapToScene(event.pos())
                    sub.addAction(spec.label, lambda checked=False, n=nid, p=pos:
                                  self.add_node_from_spec(n, p.x(), p.y()))
        menu.addSeparator()
        if self._scene.selectedItems():
            menu.addAction("删除选中", self.remove_selected)
        menu.exec(event.globalPos())

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Delete:
            self.remove_selected()
        else:
            super().keyPressEvent(event)
