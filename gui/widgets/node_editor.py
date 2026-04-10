"""Custom node editor — QGraphicsView canvas with themed nodes.

Design: white card nodes, accent title bar, manual port connections,
parameters as read-only summary on node, double-click to edit.
"""
from __future__ import annotations

import uuid
from typing import Any

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QGraphicsEllipseItem, QGraphicsItem, QGraphicsPathItem,
    QGraphicsRectItem, QGraphicsScene, QGraphicsSimpleTextItem,
    QGraphicsView, QMenu, QWidget,
)

from gui.theme import T

# ---------- Sizing ----------
NODE_W = 200
HEADER_H = 28
PORT_R = 6
PORT_SPACING = 22
PARAM_LINE_H = 18
GRID = 20
BODY_PAD = 10


class PortItem(QGraphicsEllipseItem):
    def __init__(self, name: str, is_output: bool, parent: "NodeItem"):
        d = PORT_R * 2
        super().__init__(-PORT_R, -PORT_R, d, d, parent)
        self.port_name = name
        self.is_output = is_output
        self.node: NodeItem = parent
        self.connections: list[ConnectionItem] = []
        color = QColor(T.ACCENT)
        self.setBrush(QBrush(color))
        self.setPen(QPen(color.darker(120), 1))
        self.setZValue(3)
        self.setCursor(Qt.CursorShape.CrossCursor)
        # Label
        lbl = QGraphicsSimpleTextItem(name, parent)
        f = QFont(); f.setPointSize(8)
        lbl.setFont(f)
        lbl.setBrush(QBrush(QColor(T.TEXT_2)))
        w = lbl.boundingRect().width()
        if is_output:
            lbl.setPos(self.x() - w - PORT_R - 4, self.y() - 6)
        else:
            lbl.setPos(self.x() + PORT_R + 4, self.y() - 6)
        self._lbl = lbl

    @property
    def center_scene(self) -> QPointF:
        return self.scenePos()


class ConnectionItem(QGraphicsPathItem):
    def __init__(self, src: PortItem, tgt: PortItem):
        super().__init__()
        self.source = src
        self.target = tgt
        src.connections.append(self)
        tgt.connections.append(self)
        self.setPen(QPen(QColor(T.TEXT_3), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        self.setZValue(0)
        self.update_path()

    def update_path(self):
        p1, p2 = self.source.center_scene, self.target.center_scene
        dx = max(abs(p2.x() - p1.x()) * 0.5, 40)
        path = QPainterPath()
        path.moveTo(p1)
        path.cubicTo(p1.x() + dx, p1.y(), p2.x() - dx, p2.y(), p2.x(), p2.y())
        self.setPath(path)

    def remove(self):
        for lst in (self.source.connections, self.target.connections):
            if self in lst:
                lst.remove(self)
        if self.scene():
            self.scene().removeItem(self)


class NodeItem(QGraphicsRectItem):
    def __init__(self, node_id: str, label: str, category: str,
                 input_names: list[str], output_names: list[str],
                 param_summary: list[str],
                 x: float = 0, y: float = 0):
        self.node_id = node_id
        self.instance_id = str(uuid.uuid4())[:8]
        self.display_name = label
        self.category = category
        self.inputs: list[PortItem] = []
        self.outputs: list[PortItem] = []
        self._params: dict[str, Any] = {}
        self._param_labels: list[QGraphicsSimpleTextItem] = []

        n_ports = max(len(input_names), len(output_names), 1)
        n_params = len(param_summary)
        body_h = max(n_ports * PORT_SPACING, n_params * PARAM_LINE_H + BODY_PAD * 2, 40)
        total_h = HEADER_H + body_h

        super().__init__(0, 0, NODE_W, total_h)
        self.setPos(x, y)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setZValue(1)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setPen(QPen(Qt.PenStyle.NoPen))

        # Title
        t = QGraphicsSimpleTextItem(label, self)
        f = QFont(); f.setPointSize(9); f.setBold(True)
        t.setFont(f)
        t.setBrush(QBrush(QColor("#fff")))
        t.setPos(10, 5)

        # Param summary lines
        py = HEADER_H + BODY_PAD
        pf = QFont(); pf.setPointSize(8)
        for text in param_summary:
            lbl = QGraphicsSimpleTextItem(text, self)
            lbl.setFont(pf)
            lbl.setBrush(QBrush(QColor(T.TEXT_2)))
            lbl.setPos(10, py)
            self._param_labels.append(lbl)
            py += PARAM_LINE_H

        # Ports
        port_y_start = HEADER_H + body_h // (max(len(input_names), 1) + 1)
        for i, name in enumerate(input_names):
            p = PortItem(name, False, self)
            p.setPos(0, HEADER_H + (i + 1) * body_h // (len(input_names) + 1))
            self.inputs.append(p)
        for i, name in enumerate(output_names):
            p = PortItem(name, True, self)
            p.setPos(NODE_W, HEADER_H + (i + 1) * body_h // (len(output_names) + 1))
            self.outputs.append(p)

    def update_param_summary(self, lines: list[str]):
        pf = QFont(); pf.setPointSize(8)
        for i, lbl in enumerate(self._param_labels):
            if i < len(lines):
                lbl.setText(lines[i])
            else:
                lbl.setText("")

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        r = 8
        # Shadow
        painter.setBrush(QBrush(QColor(0, 0, 0, 30)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect.adjusted(2, 2, 2, 2), r, r)
        # Body
        painter.setBrush(QBrush(QColor(T.CONTENT)))
        bc = QColor(T.ACCENT) if self.isSelected() else QColor(T.BORDER)
        painter.setPen(QPen(bc, 2 if self.isSelected() else 1))
        painter.drawRoundedRect(rect, r, r)
        # Header
        accent = QColor(T.ACCENT)
        grad = QLinearGradient(rect.topLeft(), QPointF(rect.right(), rect.top()))
        grad.setColorAt(0, accent)
        grad.setColorAt(1, accent.darker(115))
        painter.setBrush(QBrush(grad))
        painter.setPen(Qt.PenStyle.NoPen)
        hp = QPainterPath()
        hp.addRoundedRect(QRectF(rect.x(), rect.y(), rect.width(), HEADER_H), r, r)
        bp = QPainterPath()
        bp.addRect(QRectF(rect.x(), rect.y() + HEADER_H - r, rect.width(), r))
        painter.drawPath(hp.united(bp))

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            for port in self.inputs + self.outputs:
                for conn in port.connections:
                    conn.update_path()
        return super().itemChange(change, value)


MIME_TYPE = "application/x-dataforge-node"


class NodeCanvas(QGraphicsView):
    node_selected = pyqtSignal(object)
    node_double_clicked = pyqtSignal(object)

    def __init__(self, parent: QWidget | None = None):
        self._scene = QGraphicsScene()
        super().__init__(self._scene, parent)
        self._nodes: list[NodeItem] = []
        self._temp: QGraphicsPathItem | None = None
        self._drag_port: PortItem | None = None
        self._zoom = 1.0
        self._pan_start: QPointF | None = None

        self.setAcceptDrops(True)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scene.setSceneRect(-3000, -3000, 6000, 6000)
        self.setBackgroundBrush(QBrush(QColor(T.SURFACE_DIM)))

    def add_node(self, node_id: str, x: float = 0, y: float = 0) -> NodeItem | None:
        from core.nodes import NODE_REGISTRY
        spec = NODE_REGISTRY.get(node_id)
        if not spec:
            return None
        summary = []
        for p in spec.parameters:
            if p.param_type == "bool":
                summary.append(f"{'✓' if p.default else '✗'} {p.label}")
            elif p.param_type == "choice":
                summary.append(f"{p.label}: {p.default}")
            else:
                summary.append(f"{p.label}: {p.default}")
        node = NodeItem(
            node_id, spec.label, spec.category,
            [p.name for p in spec.inputs], [p.name for p in spec.outputs],
            summary, x, y,
        )
        node.set_params({p.name: p.default for p in spec.parameters})
        self._scene.addItem(node)
        self._nodes.append(node)
        return node

    def get_nodes(self) -> list[NodeItem]:
        return list(self._nodes)

    def remove_selected(self):
        for item in list(self._scene.selectedItems()):
            if isinstance(item, NodeItem):
                for port in item.inputs + item.outputs:
                    for c in list(port.connections):
                        c.remove()
                self._scene.removeItem(item)
                if item in self._nodes:
                    self._nodes.remove(item)

    def clear_all(self):
        self._nodes.clear()
        self._scene.clear()

    # ---- Grid ----
    def drawBackground(self, painter: QPainter, rect: QRectF):
        super().drawBackground(painter, rect)
        pen = QPen(QColor(T.BORDER), 0.4)
        painter.setPen(pen)
        l = int(rect.left()) - (int(rect.left()) % GRID)
        t = int(rect.top()) - (int(rect.top()) % GRID)
        x = l
        while x < rect.right():
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            x += GRID
        y = t
        while y < rect.bottom():
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            y += GRID

    # ---- Zoom ----
    def wheelEvent(self, event):
        f = 1.12 if event.angleDelta().y() > 0 else 1 / 1.12
        self._zoom = max(0.15, min(4.0, self._zoom * f))
        self.resetTransform()
        self.scale(self._zoom, self._zoom)

    # ---- Pan (middle button) + port drag ----
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_start = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        item = self.itemAt(event.pos())
        if isinstance(item, PortItem) and item.is_output:
            self._drag_port = item
            self._temp = QGraphicsPathItem()
            self._temp.setPen(QPen(QColor(T.ACCENT), 2, Qt.PenStyle.DashLine))
            self._scene.addItem(self._temp)
            event.accept()
            return
        super().mousePressEvent(event)
        sel = [i for i in self._scene.selectedItems() if isinstance(i, NodeItem)]
        self.node_selected.emit(sel[0] if sel else None)

    def mouseMoveEvent(self, event):
        if self._pan_start is not None:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(int(self.horizontalScrollBar().value() - delta.x()))
            self.verticalScrollBar().setValue(int(self.verticalScrollBar().value() - delta.y()))
            event.accept()
            return
        if self._drag_port and self._temp:
            p1 = self._drag_port.center_scene
            p2 = self.mapToScene(event.pos())
            dx = max(abs(p2.x() - p1.x()) * 0.5, 30)
            path = QPainterPath()
            path.moveTo(p1)
            path.cubicTo(p1.x() + dx, p1.y(), p2.x() - dx, p2.y(), p2.x(), p2.y())
            self._temp.setPath(path)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton and self._pan_start is not None:
            self._pan_start = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        if self._drag_port and self._temp:
            item = self.itemAt(event.pos())
            if isinstance(item, PortItem) and not item.is_output and item.node != self._drag_port.node:
                conn = ConnectionItem(self._drag_port, item)
                self._scene.addItem(conn)
            self._scene.removeItem(self._temp)
            self._temp = None
            self._drag_port = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        items = self.items(event.pos())
        node = None
        for it in items:
            if isinstance(it, NodeItem):
                node = it
                break
            p = it.parentItem()
            while p:
                if isinstance(p, NodeItem):
                    node = p
                    break
                p = p.parentItem()
            if node:
                break
        if node:
            self.node_double_clicked.emit(node)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    # ---- Drop from sidebar ----
    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(MIME_TYPE):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(MIME_TYPE):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasFormat(MIME_TYPE):
            nid = bytes(event.mimeData().data(MIME_TYPE)).decode()
            pos = self.mapToScene(event.position().toPoint())
            self.add_node(nid, pos.x(), pos.y())
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    # ---- Context menu ----
    def contextMenuEvent(self, event):
        from core.nodes import NODE_REGISTRY
        menu = QMenu(self)
        cats = {"input": "输入", "processing": "处理", "output": "输出"}
        for ck, cl in cats.items():
            sub = menu.addMenu(cl)
            for nid, spec in NODE_REGISTRY.items():
                if spec.category == ck:
                    pos = self.mapToScene(event.pos())
                    sub.addAction(spec.label, lambda checked=False, n=nid, p=pos: self.add_node(n, p.x(), p.y()))
        menu.addSeparator()
        if self._scene.selectedItems():
            menu.addAction("删除选中", self.remove_selected)
        menu.exec(event.globalPos())

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Delete:
            self.remove_selected()
        else:
            super().keyPressEvent(event)
