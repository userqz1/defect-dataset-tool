"""Node editor canvas — n8n-style node graph with typed multi-port nodes.

Nodes have dynamic input/output ports defined by ``PortDef`` in core/nodes.
Visual states: idle → running → done / error.
Ports: input (left, neutral) vs output (right, accent). Filled when connected.
"""
from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
)
from PyQt6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QMenu,
    QWidget,
)

from gui.theme import T

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NODE_W = 160
NODE_PAD_TOP = 32       # header area (icon + name)
PORT_SPACING = 22       # vertical gap between ports
PORT_PAD = 8            # top/bottom padding in port area
PORT_R = 5
ICON_SIZE = 24
ICON_RAD = 5
NODE_RAD = 8
GRID_SIZE = 20
GRID_MAJOR = 100
DOT_R = 0.8
DOT_R_MAJOR = 1.2
SNAP = 20
CONN_W = 1.8


SNAP_DIST = 25   # px — snap-to-port distance during connection drag


def _snap(v: float) -> float:
    return round(v / SNAP) * SNAP


def _set_bezier(item: QGraphicsPathItem, p1: QPointF, p2: QPointF) -> None:
    """Set a smooth bezier path between two points (n8n / React Flow style).

    Uses generous horizontal offsets so curves look natural even when
    nodes are close together or vertically aligned.
    """
    dx = abs(p2.x() - p1.x())
    dy = abs(p2.y() - p1.y())
    # Offset grows with distance but has a solid minimum
    off = max(80, dx * 0.5, dy * 0.3)
    path = QPainterPath()
    path.moveTo(p1)
    path.cubicTo(p1.x() + off, p1.y(), p2.x() - off, p2.y(), p2.x(), p2.y())
    item.setPath(path)


# ---------------------------------------------------------------------------
# PortItem
# ---------------------------------------------------------------------------

class PortItem(QGraphicsEllipseItem):
    """Connection dot. Input = left/neutral, output = right/accent."""

    def __init__(self, name: str, label: str, is_output: bool,
                 data_type: str, parent: "NodeItem") -> None:
        d = PORT_R * 2
        super().__init__(-PORT_R, -PORT_R, d, d, parent)
        self.port_name = name
        self.port_label = label
        self.is_output = is_output
        self.data_type = data_type
        self.node: NodeItem = parent
        self.connections: list[ConnectionItem] = []
        self._hovered = False
        self._highlight = False

        self.setAcceptHoverEvents(True)
        self.setZValue(2)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setToolTip(f"{label} ({data_type})")
        self.setBrush(QBrush(Qt.GlobalColor.transparent))
        self.setPen(QPen(Qt.PenStyle.NoPen))

    @property
    def center_scene(self) -> QPointF:
        return self.scenePos()

    @property
    def is_connected(self) -> bool:
        return len(self.connections) > 0

    def paint(self, painter: QPainter, option, widget=None) -> None:  # noqa: ARG002
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(-PORT_R, -PORT_R, PORT_R * 2, PORT_R * 2)

        # Highlight ring during connection drag
        if self._highlight:
            glow = QColor(T.ACCENT)
            glow.setAlpha(50)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(glow))
            painter.drawEllipse(r.adjusted(-4, -4, 4, 4))

        # Port circle
        accent = QColor(T.ACCENT)
        neutral = QColor(T.TEXT_3)
        base = accent if self.is_output else neutral
        filled = self.is_connected or self._hovered

        painter.setBrush(QBrush(base) if filled else QBrush(QColor(T.NODE_BG)))
        painter.setPen(QPen(base if self._hovered else QColor(T.BORDER), 1))
        painter.drawEllipse(r)

    def boundingRect(self) -> QRectF:
        # Large hit area (15px radius) so connections are easy to grab
        m = 10
        return QRectF(-PORT_R - m, -PORT_R - m, PORT_R * 2 + m * 2, PORT_R * 2 + m * 2)

    def shape(self) -> QPainterPath:
        """Generous circular hit area for easier clicking."""
        path = QPainterPath()
        path.addEllipse(QRectF(-12, -12, 24, 24))
        return path

    def hoverEnterEvent(self, event) -> None:
        self._hovered = True
        self.update()

    def hoverLeaveEvent(self, event) -> None:
        self._hovered = False
        self.update()

    def set_highlight(self, on: bool) -> None:
        self._highlight = on
        self.update()


# ---------------------------------------------------------------------------
# ConnectionItem
# ---------------------------------------------------------------------------

class ConnectionItem(QGraphicsPathItem):
    """Smooth bezier curve between two ports."""

    def __init__(self, source: PortItem, target: PortItem) -> None:
        super().__init__()
        self.source = source
        self.target = target
        source.connections.append(self)
        target.connections.append(self)
        self._hovered = False
        self.setAcceptHoverEvents(True)
        self.setZValue(0)
        self.update_path()

    def update_path(self) -> None:
        _set_bezier(self, self.source.center_scene, self.target.center_scene)

    def paint(self, painter: QPainter, option, widget=None) -> None:  # noqa: ARG002
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QColor(T.ACCENT) if self._hovered else QColor(T.TEXT_3)
        pen = QPen(c, CONN_W + (0.5 if self._hovered else 0))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawPath(self.path())

    def hoverEnterEvent(self, event) -> None:
        self._hovered = True
        self.update()

    def hoverLeaveEvent(self, event) -> None:
        self._hovered = False
        self.update()

    def remove(self) -> None:
        if self in self.source.connections:
            self.source.connections.remove(self)
        if self in self.target.connections:
            self.target.connections.remove(self)
        scene = self.scene()
        if scene:
            scene.removeItem(self)


# ---------------------------------------------------------------------------
# NodeItem
# ---------------------------------------------------------------------------

# Execution states
STATE_IDLE = ""
STATE_RUNNING = "running"
STATE_DONE = "done"
STATE_ERROR = "error"


class NodeItem(QGraphicsRectItem):
    """n8n-style node card with dynamic multi-port layout."""

    def __init__(
        self,
        node_name: str,
        display_name: str,
        step_type: str = "",
        x: float = 0,
        y: float = 0,
    ) -> None:
        self.node_name = node_name
        self.display_name = display_name
        self.step_type = step_type
        self.inputs: list[PortItem] = []
        self.outputs: list[PortItem] = []
        self._params: dict[str, Any] = {}
        self._state: str = STATE_IDLE

        # Build ports from spec
        from core.nodes import NODES
        spec = NODES.get(node_name)
        port_defs = getattr(spec, "ports", ()) if spec else ()
        in_defs = [p for p in port_defs if p.direction == "input"]
        out_defs = [p for p in port_defs if p.direction == "output"]

        # Calculate height
        n_rows = max(len(in_defs), len(out_defs), 1)
        port_area = n_rows * PORT_SPACING + PORT_PAD * 2
        total_h = NODE_PAD_TOP + port_area

        super().__init__(0, 0, NODE_W, total_h)
        self.setPos(x, y)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setZValue(1)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setBrush(QBrush(Qt.GlobalColor.transparent))
        self.setPen(QPen(Qt.PenStyle.NoPen))

        # Shadow
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(6)
        shadow.setOffset(0, 1)
        shadow.setColor(QColor(0, 0, 0, 25))
        self.setGraphicsEffect(shadow)

        # Create input ports (left edge)
        for i, pdef in enumerate(in_defs):
            py = NODE_PAD_TOP + PORT_PAD + i * PORT_SPACING + PORT_SPACING // 2
            port = PortItem(pdef.name, pdef.label, False, pdef.data_type, self)
            port.setPos(0, py)
            self.inputs.append(port)

        # Create output ports (right edge)
        for i, pdef in enumerate(out_defs):
            py = NODE_PAD_TOP + PORT_PAD + i * PORT_SPACING + PORT_SPACING // 2
            port = PortItem(pdef.name, pdef.label, True, pdef.data_type, self)
            port.setPos(NODE_W, py)
            self.outputs.append(port)

    # -- public API --

    def set_params(self, params: dict[str, Any]) -> None:
        self._params = dict(params)
        self.update()

    def get_params(self) -> dict[str, Any]:
        return dict(self._params)

    def set_status(self, text: str) -> None:
        if "完成" in text or "成功" in text:
            self._state = STATE_DONE
        elif "失败" in text or "错误" in text:
            self._state = STATE_ERROR
        elif text:
            self._state = STATE_RUNNING
        else:
            self._state = STATE_IDLE
        self.update()

    def set_state(self, state: str) -> None:
        self._state = state
        self.update()

    # -- paint --

    def paint(self, painter: QPainter, option, widget=None) -> None:  # noqa: ARG002
        rect = self.rect()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Border color depends on state
        if self._state == STATE_ERROR:
            border_c = QColor(T.WARNING)
            border_w = 1.5
        elif self._state == STATE_RUNNING:
            border_c = QColor(T.ACCENT)
            border_w = 1.5
        elif self.isSelected():
            border_c = QColor(T.ACCENT)
            border_w = 1.5
        else:
            border_c = QColor(T.BORDER)
            border_w = 0.5

        # 1. Card body
        painter.setBrush(QBrush(QColor(T.NODE_BG)))
        painter.setPen(QPen(border_c, border_w))
        painter.drawRoundedRect(rect, NODE_RAD, NODE_RAD)

        # 2. Icon square
        ix = rect.x() + 8
        iy = rect.y() + (NODE_PAD_TOP - ICON_SIZE) / 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(T.ACCENT)))
        painter.drawRoundedRect(QRectF(ix, iy, ICON_SIZE, ICON_SIZE), ICON_RAD, ICON_RAD)

        # Icon letter
        painter.setPen(QPen(QColor("#ffffff")))
        icon_f = QFont()
        icon_f.setBold(True)
        icon_f.setPointSize(10)
        painter.setFont(icon_f)
        painter.drawText(
            QRectF(ix, iy, ICON_SIZE, ICON_SIZE),
            Qt.AlignmentFlag.AlignCenter,
            self.display_name[0] if self.display_name else "?",
        )

        # 3. Node name
        painter.setPen(QPen(QColor(T.TEXT)))
        nf = QFont()
        nf.setPointSize(9)
        painter.setFont(nf)
        tx = ix + ICON_SIZE + 6
        painter.drawText(
            QRectF(tx, rect.y(), rect.width() - tx - 4, NODE_PAD_TOP),
            Qt.AlignmentFlag.AlignVCenter, self.display_name,
        )

        # 4. Header divider
        painter.setPen(QPen(QColor(T.BORDER), 0.5))
        painter.drawLine(
            QPointF(rect.x() + 6, rect.y() + NODE_PAD_TOP),
            QPointF(rect.right() - 6, rect.y() + NODE_PAD_TOP),
        )

        # 5. Port labels
        painter.setPen(QPen(QColor(T.TEXT_3)))
        pf = QFont()
        pf.setPointSize(7)
        painter.setFont(pf)
        for port in self.inputs:
            py = port.pos().y()
            painter.drawText(
                QRectF(PORT_R + 4, py - 7, 60, 14),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                port.port_label,
            )
        for port in self.outputs:
            py = port.pos().y()
            painter.drawText(
                QRectF(rect.width() - PORT_R - 64, py - 7, 60, 14),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                port.port_label,
            )

        # 6. State indicator (bottom-right of icon)
        if self._state and self._state != STATE_IDLE:
            sc = {
                STATE_DONE: QColor(T.SUCCESS),
                STATE_ERROR: QColor(T.WARNING),
                STATE_RUNNING: QColor(T.ACCENT),
            }.get(self._state, QColor(T.TEXT_3))
            painter.setBrush(QBrush(sc))
            painter.setPen(QPen(QColor(T.NODE_BG), 1.5))
            painter.drawEllipse(QPointF(ix + ICON_SIZE - 1, iy + ICON_SIZE - 1), 4, 4)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            for port in self.inputs + self.outputs:
                for conn in port.connections:
                    conn.update_path()
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        pos = self.pos()
        self.setPos(_snap(pos.x()), _snap(pos.y()))


# ---------------------------------------------------------------------------
# GhostNodeItem
# ---------------------------------------------------------------------------

class GhostNodeItem(QGraphicsRectItem):
    """Semi-transparent preview during drag-over."""

    def __init__(self, display_name: str, step_type: str) -> None:
        super().__init__(0, 0, NODE_W, NODE_PAD_TOP + PORT_PAD * 2 + PORT_SPACING)
        self.display_name = display_name
        self.setZValue(10)
        self.setOpacity(0.5)
        self.setBrush(QBrush(Qt.GlobalColor.transparent))
        self.setPen(QPen(Qt.PenStyle.NoPen))

    def paint(self, painter: QPainter, option, widget=None) -> None:  # noqa: ARG002
        rect = self.rect()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bg = QColor(T.NODE_BG)
        bg.setAlpha(200)
        painter.setBrush(QBrush(bg))
        painter.setPen(QPen(QColor(T.ACCENT), 1.5, Qt.PenStyle.DashLine))
        painter.drawRoundedRect(rect, NODE_RAD, NODE_RAD)

        # Icon
        ix, iy = rect.x() + 8, rect.y() + (NODE_PAD_TOP - ICON_SIZE) / 2
        ac = QColor(T.ACCENT)
        ac.setAlpha(150)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(ac))
        painter.drawRoundedRect(QRectF(ix, iy, ICON_SIZE, ICON_SIZE), ICON_RAD, ICON_RAD)

        # Name
        painter.setPen(QPen(QColor(T.TEXT_2)))
        f = QFont()
        f.setPointSize(9)
        painter.setFont(f)
        painter.drawText(
            QRectF(ix + ICON_SIZE + 6, rect.y(), rect.width() - 48, NODE_PAD_TOP),
            Qt.AlignmentFlag.AlignVCenter, self.display_name,
        )


# ---------------------------------------------------------------------------
# NodeCanvas
# ---------------------------------------------------------------------------

class NodeCanvas(QGraphicsView):
    """Zoomable / pannable canvas with dot grid."""

    node_selected = pyqtSignal(str, str)
    node_double_clicked = pyqtSignal(str)

    MIME_TYPE = "application/x-dataforge-node"

    def __init__(self, parent: QWidget | None = None) -> None:
        self._scene = QGraphicsScene()
        super().__init__(self._scene, parent)
        self._nodes: list[NodeItem] = []
        self._temp_conn: QGraphicsPathItem | None = None
        self._drag_port: PortItem | None = None
        self._ghost: GhostNodeItem | None = None
        self._zoom = 1.0

        self.setAcceptDrops(True)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scene.setSceneRect(-2000, -2000, 4000, 4000)
        self.setBackgroundBrush(QBrush(QColor(T.SURFACE_DIM)))

    # ---- public API ----

    def add_node(self, node_name: str, display_name: str,
                 x: float = 0, y: float = 0, step_type: str = "") -> NodeItem:
        node = NodeItem(node_name, display_name, step_type, _snap(x), _snap(y))
        self._scene.addItem(node)
        self._nodes.append(node)
        return node

    def remove_selected(self) -> None:
        for item in list(self._scene.selectedItems()):
            if isinstance(item, NodeItem):
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

    def zoom_by(self, factor: float) -> None:
        self._zoom *= factor
        self._zoom = max(0.2, min(3.0, self._zoom))
        self.resetTransform()
        self.scale(self._zoom, self._zoom)

    def zoom_fit(self) -> None:
        rect = self._scene.itemsBoundingRect()
        if rect.isEmpty():
            return
        self.fitInView(rect.adjusted(-60, -60, 60, 60), Qt.AspectRatioMode.KeepAspectRatio)
        self._zoom = self.transform().m11()

    # ---- dot grid ----

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawBackground(painter, rect)
        minor_c = QColor(T.BORDER)
        minor_c.setAlpha(80)
        major_c = QColor(T.BORDER)
        major_c.setAlpha(160)
        left = int(rect.left()) - (int(rect.left()) % GRID_SIZE)
        top = int(rect.top()) - (int(rect.top()) % GRID_SIZE)
        painter.setPen(Qt.PenStyle.NoPen)
        x = left
        while x < rect.right():
            y = top
            while y < rect.bottom():
                is_major = (x % GRID_MAJOR == 0) and (y % GRID_MAJOR == 0)
                painter.setBrush(QBrush(major_c if is_major else minor_c))
                painter.drawEllipse(QPointF(x, y), DOT_R_MAJOR if is_major else DOT_R, DOT_R_MAJOR if is_major else DOT_R)
                y += GRID_SIZE
            x += GRID_SIZE

    # ---- zoom / pan ----

    def wheelEvent(self, event) -> None:
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self._zoom *= factor
        self._zoom = max(0.2, min(3.0, self._zoom))
        self.resetTransform()
        self.scale(self._zoom, self._zoom)

    # ---- mouse: port-connection drag + pan ----

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            fake = type(event)(
                event.type(), event.localPos(), Qt.MouseButton.LeftButton,
                event.buttons(), event.modifiers(),
            )
            super().mousePressEvent(fake)
            return

        item = self.itemAt(event.pos())
        if isinstance(item, PortItem) and item.is_output:
            self._drag_port = item
            self._temp_conn = QGraphicsPathItem()
            self._temp_conn.setPen(QPen(QColor(T.TEXT_3), CONN_W, Qt.PenStyle.DashLine))
            self._scene.addItem(self._temp_conn)
            self._highlight_ports(item, True)
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_port and self._temp_conn:
            p1 = self._drag_port.center_scene
            cursor = self.mapToScene(event.pos())

            # Snap to nearest compatible input port
            target = self._find_nearest_port(cursor)
            p2 = target.center_scene if target else cursor

            _set_bezier(self._temp_conn, p1, p2)

            # Highlight the snap target
            if target != getattr(self, "_snap_target", None):
                old = getattr(self, "_snap_target", None)
                if old:
                    old.set_highlight(False)
                if target:
                    target.set_highlight(True)
                self._snap_target = target
            return
        super().mouseMoveEvent(event)

    def _find_nearest_port(self, pos: QPointF) -> PortItem | None:
        """Find the nearest compatible input port within snap distance."""
        best: PortItem | None = None
        best_d = SNAP_DIST ** 2
        for node in self._nodes:
            if node is self._drag_port.node:
                continue
            for port in node.inputs:
                d = (port.center_scene.x() - pos.x()) ** 2 + (port.center_scene.y() - pos.y()) ** 2
                if d < best_d:
                    best_d = d
                    best = port
        return best

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)

        if self._drag_port and self._temp_conn:
            self._highlight_ports(self._drag_port, False)
            # Clear snap highlight
            old_snap = getattr(self, "_snap_target", None)
            if old_snap:
                old_snap.set_highlight(False)
            self._snap_target = None

            # Try exact hit first, then snap
            item = self.itemAt(event.pos())
            target = None
            if isinstance(item, PortItem) and not item.is_output and item.node != self._drag_port.node:
                target = item
            else:
                cursor = self.mapToScene(event.pos())
                target = self._find_nearest_port(cursor)

            if target:
                conn = ConnectionItem(self._drag_port, target)
                self._scene.addItem(conn)

            self._scene.removeItem(self._temp_conn)
            self._temp_conn = None
            self._drag_port = None
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        item = self.itemAt(event.pos())
        while item and not isinstance(item, NodeItem):
            item = item.parentItem()
        if isinstance(item, NodeItem):
            self.node_double_clicked.emit(item.node_name)
        super().mouseDoubleClickEvent(event)

    def _highlight_ports(self, source: PortItem, on: bool) -> None:
        for node in self._nodes:
            if node is source.node:
                continue
            for port in node.inputs:
                port.set_highlight(on)

    # ---- context menu ----

    def contextMenuEvent(self, event) -> None:
        from core.nodes import NODES
        menu = QMenu(self)
        for name, node in NODES.items():
            action = menu.addAction(f"添加: {node.display_name}")
            pos = self.mapToScene(event.pos())
            action.triggered.connect(
                lambda checked, n=name, dn=node.display_name, st=node.step_type, p=pos:
                self.add_node(n, dn, p.x(), p.y(), st)
            )
        menu.addSeparator()
        if self._scene.selectedItems():
            menu.addAction("删除选中", self.remove_selected)
        menu.exec(event.globalPos())

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Delete:
            self.remove_selected()
        else:
            super().keyPressEvent(event)

    # ---- drag & drop from sidebar ----

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(self.MIME_TYPE):
            data = bytes(event.mimeData().data(self.MIME_TYPE)).decode()
            parts = data.split("|")
            if len(parts) >= 2:
                self._ghost = GhostNodeItem(parts[1], parts[2] if len(parts) > 2 else "")
                self._scene.addItem(self._ghost)
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(self.MIME_TYPE):
            if self._ghost:
                pos = self.mapToScene(event.position().toPoint())
                gh = self._ghost.rect().height()
                self._ghost.setPos(_snap(pos.x() - NODE_W / 2), _snap(pos.y() - gh / 2))
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dragLeaveEvent(self, event) -> None:
        self._remove_ghost()
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        self._remove_ghost()
        if event.mimeData().hasFormat(self.MIME_TYPE):
            data = bytes(event.mimeData().data(self.MIME_TYPE)).decode()
            parts = data.split("|")
            if len(parts) >= 2:
                node_name, display_name = parts[0], parts[1]
                step_type = parts[2] if len(parts) >= 3 else ""
                pos = self.mapToScene(event.position().toPoint())
                self.add_node(node_name, display_name,
                              pos.x() - NODE_W / 2, pos.y() - 30,
                              step_type)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    def _remove_ghost(self) -> None:
        if self._ghost:
            self._scene.removeItem(self._ghost)
            self._ghost = None
