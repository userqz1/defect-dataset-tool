"""Pipeline view — custom node canvas workspace.

Double-click node → Fluent dialog to edit params.
Sidebar tools add nodes. Manual port connections.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from qfluentwidgets import (
    FluentIcon as FIF,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    StrongBodyLabel,
)
from PyQt6.QtWidgets import QFrame, QHBoxLayout

from core.models import Dataset
from gui.theme import T
from gui.widgets.node_editor import NodeCanvas, NodeItem
from gui.workers.batch_worker import BatchWorker


class PipelineView(QWidget):
    dataset_changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setObjectName("pipelineView")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._dataset: Dataset | None = None
        self._worker: BatchWorker | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Top bar
        topbar = QFrame()
        topbar.setObjectName("detailTopBar")
        topbar.setFixedHeight(44)
        tl = QHBoxLayout(topbar)
        tl.setContentsMargins(T.PAD_LG, 0, T.PAD_LG, 0)
        tl.setSpacing(T.GAP_LG)
        self._title = StrongBodyLabel("工作台")
        tl.addWidget(self._title)
        tl.addStretch(1)
        self._run_btn = PrimaryPushButton("执行")
        self._run_btn.setIcon(FIF.PLAY)
        self._run_btn.clicked.connect(self._on_run)
        tl.addWidget(self._run_btn)
        root.addWidget(topbar)

        # Canvas
        self._canvas = NodeCanvas()
        self._canvas.node_double_clicked.connect(self._on_node_double_clicked)
        root.addWidget(self._canvas, 1)

    def set_dataset(self, dataset: Dataset | None):
        self._dataset = dataset

    def set_task_type(self, task_type):
        self._task_type = task_type

    def add_node(self, node_id: str):
        n = len(self._canvas.get_nodes())
        self._canvas.add_node(node_id, 120 + n * 260, 180)

    def clear(self):
        self._canvas.clear_all()

    def _on_node_double_clicked(self, node: NodeItem):
        """Open Fluent dialog to edit node parameters."""
        from core.nodes import NODE_REGISTRY
        from qfluentwidgets import MessageBoxBase, SubtitleLabel, BodyLabel, LineEdit, CheckBox, ComboBox, DoubleSpinBox, SpinBox

        spec = NODE_REGISTRY.get(node.node_id)
        if not spec:
            return

        class _NodeConfigDialog(MessageBoxBase):
            def __init__(self, parent=None):
                super().__init__(parent=parent)
                self.titleLabel = SubtitleLabel(spec.label, self)
                self.viewLayout.addWidget(self.titleLabel)
                self.widget.setMinimumWidth(420)
                self._widgets = {}
                params = node.get_params()

                for p in spec.parameters:
                    self.viewLayout.addWidget(BodyLabel(p.label, self))
                    val = params.get(p.name, p.default)

                    if p.param_type == "bool":
                        w = CheckBox("", self)
                        w.setChecked(bool(val))
                        self._widgets[p.name] = ("bool", w)
                    elif p.param_type == "int":
                        w = SpinBox(self)
                        if p.min_val is not None: w.setMinimum(int(p.min_val))
                        if p.max_val is not None: w.setMaximum(int(p.max_val))
                        w.setValue(int(val) if val else 0)
                        self._widgets[p.name] = ("int", w)
                    elif p.param_type == "float":
                        w = DoubleSpinBox(self)
                        if p.min_val is not None: w.setMinimum(p.min_val)
                        if p.max_val is not None: w.setMaximum(p.max_val)
                        w.setValue(float(val) if val else 0.0)
                        w.setSingleStep(0.05 if p.max_val and p.max_val <= 1 else 1.0)
                        self._widgets[p.name] = ("float", w)
                    elif p.param_type == "choice":
                        w = ComboBox(self)
                        w.addItems(list(p.choices))
                        if val: w.setCurrentText(str(val))
                        self._widgets[p.name] = ("choice", w)
                    else:
                        w = LineEdit(self)
                        w.setText(str(val) if val else "")
                        if p.tooltip: w.setPlaceholderText(p.tooltip)
                        self._widgets[p.name] = ("str", w)

                    self.viewLayout.addWidget(w)

            def get_values(self) -> dict:
                result = {}
                for name, (typ, w) in self._widgets.items():
                    if typ == "bool":
                        result[name] = w.isChecked()
                    elif typ == "int":
                        result[name] = w.value()
                    elif typ == "float":
                        result[name] = w.value()
                    elif typ == "choice":
                        result[name] = w.currentText()
                    else:
                        result[name] = w.text()
                return result

        dlg = _NodeConfigDialog(parent=self.window())
        if dlg.exec():
            values = dlg.get_values()
            node.set_params(values)
            # Update node summary display
            summary = []
            for p in spec.parameters:
                v = values.get(p.name, p.default)
                if p.param_type == "bool":
                    summary.append(f"{'✓' if v else '✗'} {p.label}")
                else:
                    summary.append(f"{p.label}: {v}")
            node.update_param_summary(summary)

    def _on_run(self):
        nodes = self._canvas.get_nodes()
        if not nodes:
            InfoBar.warning("", "画布上没有节点", parent=self.window(),
                            duration=2000, position=InfoBarPosition.TOP)
            return
        names = [n.display_name for n in nodes]
        InfoBar.success("执行", f"{len(names)} 个节点: {' → '.join(names)}",
                        parent=self.window(), duration=3000, position=InfoBarPosition.TOP)
