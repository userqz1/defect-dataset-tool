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
    """Smooth bezier curve between two ports. Selectable + deletable."""

    def __init__(self, source: PortItem, target: PortItem) -> None:
        super().__init__()
        self.source = source
        self.target = target
        source.connections.append(self)
        target.connections.append(self)
        self._hovered = False
        self._data_count: int | None = None  # shown on connection after execution
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setZValue(0)
        self.update_path()

    def update_path(self) -> None:
        _set_bezier(self, self.source.center_scene, self.target.center_scene)

    def shape(self) -> QPainterPath:
        """Wide hit area (8px) for easy selection."""
        from PyQt6.QtGui import QPainterPathStroker
        stroker = QPainterPathStroker()
        stroker.setWidth(10)
        return stroker.createStroke(self.path())

    def boundingRect(self) -> QRectF:
        return self.shape().boundingRect()

    def paint(self, painter: QPainter, option, widget=None) -> None:  # noqa: ARG002
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        selected = self.isSelected()
        if selected or self._hovered:
            c = QColor(T.ACCENT)
            w = CONN_W + 0.5
        else:
            c = QColor(T.TEXT_3)
            w = CONN_W
        pen = QPen(c, w)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawPath(self.path())

        # Data count label at midpoint of bezier
        if self._data_count is not None:
            mid = self.path().pointAtPercent(0.5)
            text = str(self._data_count)
            font = QFont()
            font.setPointSize(7)
            painter.setFont(font)
            fm = painter.fontMetrics()
            tw = fm.horizontalAdvance(text) + 8
            th = fm.height() + 4
            badge = QRectF(mid.x() - tw / 2, mid.y() - th / 2, tw, th)
            painter.setBrush(QBrush(QColor(T.SURFACE_DIM)))
            painter.setPen(QPen(QColor(T.BORDER), 0.5))
            painter.drawRoundedRect(badge, 4, 4)
            painter.setPen(QPen(QColor(T.TEXT_2)))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, text)

    def set_data_count(self, count: int | None) -> None:
        self._data_count = count
        self.update()

    def hoverEnterEvent(self, event) -> None:
        self._hovered = True
        self.update()

    def hoverLeaveEvent(self, event) -> None:
        self._hovered = False
        self.update()

    def contextMenuEvent(self, event) -> None:
        menu = QMenu()
        menu.addAction("删除连线", self.remove)
        menu.exec(event.screenPos())

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
        self._status_text: str = ""

        # Build ports from spec
        from core.nodes import NODES
        spec = NODES.get(node_name)
        port_defs = getattr(spec, "ports", ()) if spec else ()
        in_defs = [p for p in port_defs if p.direction == "input"]
        out_defs = [p for p in port_defs if p.direction == "output"]

        # Calculate height (extra 18px for status text area)
        n_rows = max(len(in_defs), len(out_defs), 1)
        port_area = n_rows * PORT_SPACING + PORT_PAD * 2
        total_h = NODE_PAD_TOP + port_area + 18

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
        self._status_text = text
        self.update()

    def set_state(self, state: str) -> None:
        self._state = state
        if not state or state == STATE_IDLE:
            self._status_text = ""
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

        # 7. Status text (below ports, in the bottom margin)
        if self._status_text:
            sf = QFont()
            sf.setPointSize(7)
            painter.setFont(sf)
            painter.setPen(QPen(QColor(T.TEXT_2)))
            status_rect = QRectF(6, rect.height() - 16, rect.width() - 12, 14)
            painter.drawText(
                status_rect,
                Qt.AlignmentFlag.AlignCenter,
                self._status_text,
            )

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

    node_selected = pyqtSignal(object)         # emits NodeItem on single-click
    node_deselected = pyqtSignal()             # emits when clicking empty area
    node_double_clicked = pyqtSignal(object)   # emits NodeItem directly

    MIME_TYPE = "application/x-dataforge-node"

    def __init__(self, parent: QWidget | None = None) -> None:
        self._scene = QGraphicsScene()
        super().__init__(self._scene, parent)
        self._nodes: list[NodeItem] = []
        self._temp_conn: QGraphicsPathItem | None = None
        self._drag_port: PortItem | None = None
        self._ghost: GhostNodeItem | None = None
        self._snap_target: PortItem | None = None
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
        """Delete selected connections first, then selected nodes."""
        for item in list(self._scene.selectedItems()):
            if isinstance(item, ConnectionItem):
                item.remove()
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

    def load_scheme(self, scheme) -> None:
        """Load a Scheme into the canvas."""
        from core.scheme import Scheme
        self.clear_all()
        if not isinstance(scheme, Scheme):
            return
        # Create nodes
        for sn in scheme.nodes:
            self.add_node(sn.node_name, sn.display_name, sn.x, sn.y, sn.step_type)
            if sn.params:
                self._nodes[-1].set_params(sn.params)
        # Create connections
        for sc in scheme.connections:
            if sc.src_idx >= len(self._nodes) or sc.tgt_idx >= len(self._nodes):
                continue
            src_node = self._nodes[sc.src_idx]
            tgt_node = self._nodes[sc.tgt_idx]
            src_port = next((p for p in src_node.outputs if p.port_name == sc.src_port), None)
            tgt_port = next((p for p in tgt_node.inputs if p.port_name == sc.tgt_port), None)
            if src_port and tgt_port:
                conn = ConnectionItem(src_port, tgt_port)
                self._scene.addItem(conn)

    def to_scheme(self, name: str = "未命名方案") -> "Scheme":
        """Serialize canvas state to a Scheme object."""
        from core.scheme import Scheme, SchemeNode, SchemeConnection
        nodes = []
        node_idx = {id(n): i for i, n in enumerate(self._nodes)}
        for n in self._nodes:
            nodes.append(SchemeNode(
                n.node_name, n.display_name, n.step_type,
                n.pos().x(), n.pos().y(), n.get_params(),
            ))
        conns = []
        seen = set()
        for n in self._nodes:
            for port in n.outputs:
                for conn in port.connections:
                    cid = id(conn)
                    if cid in seen:
                        continue
                    seen.add(cid)
                    src_i = node_idx.get(id(conn.source.node))
                    tgt_i = node_idx.get(id(conn.target.node))
                    if src_i is not None and tgt_i is not None:
                        conns.append(SchemeConnection(
                            src_i, conn.source.port_name,
                            tgt_i, conn.target.port_name,
                        ))
        return Scheme(name=name, nodes=nodes, connections=conns)

    # ---- connection validation ----

    def _can_connect(self, src: PortItem, tgt: PortItem) -> bool:
        """Validate a proposed connection."""
        if src.node is tgt.node:
            return False                    # no self-loops
        if src.data_type != tgt.data_type:
            return False                    # type mismatch
        if any(c.source is src for c in tgt.connections):
            return False                    # duplicate
        if self._would_cycle(src.node, tgt.node):
            return False                    # cycle
        return True

    def _would_cycle(self, from_node: NodeItem, to_node: NodeItem) -> bool:
        """DFS from to_node's outputs — if we reach from_node, it's a cycle."""
        visited: set[NodeItem] = set()
        stack = [to_node]
        while stack:
            n = stack.pop()
            if n is from_node:
                return True
            if n in visited:
                continue
            visited.add(n)
            for port in n.outputs:
                for conn in port.connections:
                    stack.append(conn.target.node)
        return False

    def _try_connect(self, src: PortItem, tgt: PortItem) -> bool:
        """Validate and create a connection. Replace existing if input occupied."""
        if not self._can_connect(src, tgt):
            return False
        # Input port allows max 1 connection — replace old one
        if tgt.connections:
            for old in list(tgt.connections):
                old.remove()
        conn = ConnectionItem(src, tgt)
        self._scene.addItem(conn)
        return True

    # ---- graph serialization ----

    def build_graph(self) -> list[dict]:
        """Serialize canvas into an executable graph for GraphEngine.

        Returns list of node dicts:
        {
            "id": <node object id>,
            "node_name": str,
            "display_name": str,
            "params": dict,
            "inputs": {port_name: (upstream_id, upstream_port_name)},
        }
        """
        id_map = {id(n): n for n in self._nodes}
        result = []
        for node in self._nodes:
            nid = id(node)
            inputs: dict[str, tuple[int, str]] = {}
            for port in node.inputs:
                if port.connections:
                    conn = port.connections[0]  # max 1 per input
                    upstream_node = conn.source.node
                    inputs[port.port_name] = (id(upstream_node), conn.source.port_name)
            result.append({
                "id": nid,
                "node_name": node.node_name,
                "display_name": node.display_name,
                "params": node.get_params(),
                "inputs": inputs,
            })
        return result

    def node_by_id(self, nid: int) -> NodeItem | None:
        """Find node by python id (used by pipeline_view for status updates)."""
        for n in self._nodes:
            if id(n) == nid:
                return n
        return None

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
                self._try_connect(self._drag_port, target)

            self._scene.removeItem(self._temp_conn)
            self._temp_conn = None
            self._drag_port = None
            return
        super().mouseReleaseEvent(event)

        # Emit node selection signal after Qt processes selection
        if event.button() == Qt.MouseButton.LeftButton:
            selected = [it for it in self._scene.selectedItems() if isinstance(it, NodeItem)]
            if len(selected) == 1:
                self.node_selected.emit(selected[0])
            elif not selected:
                self.node_deselected.emit()

    def mouseDoubleClickEvent(self, event) -> None:
        item = self.itemAt(event.pos())
        while item and not isinstance(item, NodeItem):
            item = item.parentItem()
        if isinstance(item, NodeItem):
            self.node_double_clicked.emit(item)
        super().mouseDoubleClickEvent(event)

    def _highlight_ports(self, source: PortItem, on: bool) -> None:
        for node in self._nodes:
            if node is source.node:
                continue
            for port in node.inputs:
                port.set_highlight(on)

    # ---- context menu ----

    def contextMenuEvent(self, event) -> None:
        item = self.itemAt(event.pos())
        # Walk up to find NodeItem
        while item and not isinstance(item, NodeItem):
            item = item.parentItem()

        menu = QMenu(self)

        if isinstance(item, NodeItem):
            # ---- Node context menu ----
            menu.addAction("打开配置", lambda: self.node_double_clicked.emit(item))
            menu.addSeparator()
            menu.addAction("断开所有连线", lambda: self._disconnect_node(item))
            menu.addAction("删除节点", lambda: self._remove_node(item))
        else:
            # ---- Canvas context menu ----
            from core.nodes import NODES
            pos = self.mapToScene(event.pos())
            for name, node in NODES.items():
                action = menu.addAction(f"添加  {node.display_name}")
                action.triggered.connect(
                    lambda checked, n=name, dn=node.display_name, st=node.step_type, p=pos:
                    self.add_node(n, dn, p.x(), p.y(), st)
                )
            if self._scene.selectedItems():
                menu.addSeparator()
                menu.addAction("删除选中", self.remove_selected)

        menu.exec(event.globalPos())

    def _disconnect_node(self, node: NodeItem) -> None:
        """Remove all connections from a node."""
        for port in node.inputs + node.outputs:
            for conn in list(port.connections):
                conn.remove()

    def _remove_node(self, node: NodeItem) -> None:
        """Remove a single node and its connections."""
        self._disconnect_node(node)
        self._scene.removeItem(node)
        if node in self._nodes:
            self._nodes.remove(node)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
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
