"""Pipeline view — full-screen node canvas + right-side Inspector panel.

The central workspace: users see nodes on the canvas, select a node
to configure its parameters in the Inspector, then execute the pipeline.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CheckBox,
    ComboBox,
    DoubleSpinBox,
    FluentIcon as FIF,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    SpinBox,
    StrongBodyLabel,
)

from core.models import Dataset
from gui.theme import T
from gui.widgets.node_editor import NodeCanvas, NodeItem
from gui.workers.batch_worker import BatchWorker


class _Inspector(QFrame):
    """Right-side panel: shows parameters for the selected node."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("detailSidebar")
        self.setFixedWidth(280)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(T.PAD_LG, T.PAD_LG, T.PAD_LG, T.PAD_LG)
        layout.setSpacing(T.GAP_LG)

        self._title = StrongBodyLabel("选择节点查看参数")
        layout.addWidget(self._title)

        self._desc = CaptionLabel("")
        layout.addWidget(self._desc)

        # Scrollable param area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._param_container = QWidget()
        self._param_layout = QVBoxLayout(self._param_container)
        self._param_layout.setContentsMargins(0, 0, 0, 0)
        self._param_layout.setSpacing(T.GAP)
        self._param_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(self._param_container)
        layout.addWidget(scroll, 1)

        self._node: NodeItem | None = None
        self._widgets: list[QWidget] = []

    def show_node(self, node: NodeItem | None) -> None:
        """Display parameters for the given node."""
        self._node = node

        # Clear old widgets
        for w in self._widgets:
            self._param_layout.removeWidget(w)
            w.deleteLater()
        self._widgets.clear()

        if node is None:
            self._title.setText("选择节点查看参数")
            self._desc.setText("")
            return

        from core.nodes import NODE_REGISTRY
        spec = NODE_REGISTRY.get(node.node_id)
        if not spec:
            self._title.setText(node.display_name)
            self._desc.setText("未知节点类型")
            return

        self._title.setText(spec.label)
        self._desc.setText(f"类型: {spec.category}")

        params = node.get_params()

        for param in spec.parameters:
            # Label
            lbl = CaptionLabel(param.label)
            if param.tooltip:
                lbl.setToolTip(param.tooltip)
            self._param_layout.addWidget(lbl)
            self._widgets.append(lbl)

            # Widget based on param_type
            val = params.get(param.name, param.default)

            if param.param_type == "bool":
                w = CheckBox("")
                w.setChecked(bool(val))
                w.checkStateChanged.connect(
                    lambda state, n=param.name: self._on_param_changed(n, state == Qt.CheckState.Checked)
                )

            elif param.param_type == "int":
                w = SpinBox()
                if param.min_val is not None:
                    w.setMinimum(int(param.min_val))
                if param.max_val is not None:
                    w.setMaximum(int(param.max_val))
                w.setValue(int(val) if val else 0)
                w.valueChanged.connect(lambda v, n=param.name: self._on_param_changed(n, v))

            elif param.param_type == "float":
                w = DoubleSpinBox()
                if param.min_val is not None:
                    w.setMinimum(param.min_val)
                if param.max_val is not None:
                    w.setMaximum(param.max_val)
                w.setValue(float(val) if val else 0.0)
                w.setSingleStep(0.05 if param.max_val and param.max_val <= 1 else 1.0)
                w.valueChanged.connect(lambda v, n=param.name: self._on_param_changed(n, v))

            elif param.param_type == "choice":
                w = ComboBox()
                w.addItems(list(param.choices))
                if val in param.choices:
                    w.setCurrentText(str(val))
                w.currentTextChanged.connect(lambda v, n=param.name: self._on_param_changed(n, v))

            elif param.param_type == "path":
                row = QWidget()
                rl = QHBoxLayout(row)
                rl.setContentsMargins(0, 0, 0, 0)
                le = LineEdit()
                le.setText(str(val) if val else "")
                le.textChanged.connect(lambda v, n=param.name: self._on_param_changed(n, v))
                rl.addWidget(le, 1)
                browse = PushButton("...")
                browse.setFixedWidth(36)
                browse.clicked.connect(lambda checked, edit=le: self._browse_path(edit))
                rl.addWidget(browse)
                w = row

            else:  # str
                w = LineEdit()
                w.setText(str(val) if val else "")
                w.textChanged.connect(lambda v, n=param.name: self._on_param_changed(n, v))

            self._param_layout.addWidget(w)
            self._widgets.append(w)

    def _on_param_changed(self, name: str, value: object) -> None:
        if self._node:
            params = self._node.get_params()
            params[name] = value
            self._node.set_params(params)

    def _browse_path(self, line_edit: LineEdit) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择目录")
        if d:
            line_edit.setText(d)


class PipelineView(QWidget):
    """Node canvas + Inspector panel."""

    dataset_changed = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("pipelineView")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._dataset: Dataset | None = None
        self._worker: BatchWorker | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- Top bar ----
        topbar = QFrame()
        topbar.setObjectName("detailTopBar")
        topbar.setFixedHeight(44)
        top_layout = QHBoxLayout(topbar)
        top_layout.setContentsMargins(T.PAD_LG, 0, T.PAD_LG, 0)
        top_layout.setSpacing(T.GAP_LG)

        self._task_label = StrongBodyLabel("工作台")
        top_layout.addWidget(self._task_label)
        top_layout.addStretch(1)

        self._run_btn = PrimaryPushButton("执行")
        self._run_btn.setIcon(FIF.PLAY)
        self._run_btn.clicked.connect(self._on_run)
        top_layout.addWidget(self._run_btn)

        root.addWidget(topbar)

        # ---- Canvas + Inspector ----
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self._canvas = NodeCanvas()
        self._canvas.node_selected.connect(self._on_node_selected)
        splitter.addWidget(self._canvas)

        self._inspector = _Inspector()
        splitter.addWidget(self._inspector)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        root.addWidget(splitter, 1)

    # ---- Public API ----

    def set_dataset(self, dataset: Dataset | None) -> None:
        self._dataset = dataset

    def set_task_type(self, task_type) -> None:
        self._task_type = task_type

    def add_node(self, node_id: str) -> None:
        """Add a node to the canvas at a smart position."""
        n = len(self._canvas.get_nodes())
        x = 100 + n * 260
        y = 200
        node = self._canvas.add_node_from_spec(node_id, x, y)
        # Auto-connect
        nodes = self._canvas.get_nodes()
        if node and len(nodes) >= 2:
            prev = nodes[-2]
            if prev.outputs and node.inputs:
                from gui.widgets.node_editor import ConnectionItem
                conn = ConnectionItem(prev.outputs[0], node.inputs[0])
                self._canvas._scene.addItem(conn)

    def clear(self) -> None:
        self._canvas.clear_all()
        self._inspector.show_node(None)

    # ---- Internal ----

    def _on_node_selected(self, node: NodeItem | None) -> None:
        self._inspector.show_node(node)

    def _on_run(self) -> None:
        nodes = self._canvas.get_nodes()
        if not nodes:
            InfoBar.warning("", "画布上没有节点", parent=self.window(),
                            duration=2000, position=InfoBarPosition.TOP)
            return

        InfoBar.success(
            "执行",
            f"将执行 {len(nodes)} 个节点: {' → '.join(n.display_name for n in nodes)}",
            parent=self.window(),
            duration=3000,
            position=InfoBarPosition.TOP,
        )
