"""Right-side node inspector panel (n8n style).

Click a node on the canvas → panel slides in from the right showing
the node's parameters. Close with the X button or click empty canvas.
Auto-generates form fields from ``ParamDef`` metadata.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QScrollArea,
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
    LineEdit,
    PushButton,
    SpinBox,
    StrongBodyLabel,
    SwitchButton,
    TransparentToolButton,
)

from gui.theme import T


class NodeInspector(QFrame):
    """Right-side parameter panel for the selected node."""

    params_changed = pyqtSignal(str, dict)  # (node_name, {param: value})
    closed = pyqtSignal()

    WIDTH = 280

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("nodeInspector")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(self.WIDTH)
        self._node_name: str = ""
        self._fields: dict[str, QWidget] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- Header ----
        header = QFrame()
        header.setObjectName("inspectorHeader")
        header.setFixedHeight(44)
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(T.PAD_LG, 0, T.GAP, 0)
        h_lay.setSpacing(T.GAP)
        self._title = StrongBodyLabel("")
        h_lay.addWidget(self._title, 1)
        close_btn = TransparentToolButton(FIF.CLOSE)
        close_btn.setFixedSize(28, 28)
        close_btn.clicked.connect(self._on_close)
        h_lay.addWidget(close_btn)
        root.addWidget(header)

        # ---- Description ----
        self._desc = CaptionLabel("")
        self._desc.setObjectName("inspectorDesc")
        self._desc.setWordWrap(True)
        self._desc.setContentsMargins(T.PAD_LG, T.GAP, T.PAD_LG, T.GAP)
        root.addWidget(self._desc)

        # ---- Scrollable form area ----
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._form_w = QWidget()
        self._form_lay = QVBoxLayout(self._form_w)
        self._form_lay.setContentsMargins(T.PAD_LG, T.GAP, T.PAD_LG, T.PAD_LG)
        self._form_lay.setSpacing(T.GAP_LG)
        self._form_lay.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(self._form_w)
        root.addWidget(scroll, 1)

        self.hide()

    # ---- Public API ----

    def show_node(self, node_name: str, current_params: dict[str, Any]) -> None:
        """Populate the inspector for the given node."""
        from core.nodes import NODES

        spec = NODES.get(node_name)
        if not spec:
            return

        self._node_name = node_name
        self._title.setText(spec.display_name)
        self._desc.setText(spec.description)

        # Clear old fields
        self._fields.clear()
        while self._form_lay.count():
            item = self._form_lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        # Generate form fields from ParamDef
        params = getattr(spec, "parameters", ())
        for pdef in params:
            val = current_params.get(pdef.name, pdef.default)
            row = self._make_field(pdef, val)
            if row:
                self._form_lay.addWidget(row)

        self.show()

    def hide_node(self) -> None:
        self._node_name = ""
        self.hide()

    def collect_values(self) -> dict[str, Any]:
        """Read current values from all form fields."""
        from core.nodes import NODES
        spec = NODES.get(self._node_name)
        if not spec:
            return {}
        result: dict[str, Any] = {}
        params = getattr(spec, "parameters", ())
        for pdef in params:
            w = self._fields.get(pdef.name)
            if w is None:
                continue
            if pdef.type == "int":
                result[pdef.name] = w.value()
            elif pdef.type == "float":
                result[pdef.name] = w.value()
            elif pdef.type == "bool":
                result[pdef.name] = w.isChecked()
            elif pdef.type == "choice":
                result[pdef.name] = w.currentText()
            elif pdef.type == "path":
                result[pdef.name] = w.text()
            else:
                result[pdef.name] = w.text()
        return result

    # ---- Internals ----

    def _make_field(self, pdef, value) -> QWidget | None:
        from core.nodes import ParamDef

        container = QFrame()
        lay = QVBoxLayout(container)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        label = CaptionLabel(pdef.label)
        lay.addWidget(label)

        if pdef.type == "int":
            w = SpinBox()
            if pdef.min_val is not None:
                w.setMinimum(int(pdef.min_val))
            if pdef.max_val is not None:
                w.setMaximum(int(pdef.max_val))
            w.setValue(int(value) if value is not None else 0)
            w.valueChanged.connect(self._on_value_changed)
            lay.addWidget(w)
            self._fields[pdef.name] = w

        elif pdef.type == "float":
            w = DoubleSpinBox()
            w.setDecimals(2)
            w.setSingleStep(0.05)
            if pdef.min_val is not None:
                w.setMinimum(pdef.min_val)
            if pdef.max_val is not None:
                w.setMaximum(pdef.max_val)
            w.setValue(float(value) if value is not None else 0.0)
            w.valueChanged.connect(self._on_value_changed)
            lay.addWidget(w)
            self._fields[pdef.name] = w

        elif pdef.type == "bool":
            w = SwitchButton()
            w.setChecked(bool(value))
            w.checkedChanged.connect(self._on_value_changed)
            lay.addWidget(w)
            self._fields[pdef.name] = w

        elif pdef.type == "choice":
            w = ComboBox()
            if pdef.choices:
                w.addItems(list(pdef.choices))
            if value:
                w.setCurrentText(str(value))
            w.currentTextChanged.connect(self._on_value_changed)
            lay.addWidget(w)
            self._fields[pdef.name] = w

        elif pdef.type == "path":
            row = QFrame()
            r_lay = QHBoxLayout(row)
            r_lay.setContentsMargins(0, 0, 0, 0)
            r_lay.setSpacing(4)
            w = LineEdit()
            w.setText(str(value) if value else "")
            w.setPlaceholderText("选择路径…")
            r_lay.addWidget(w, 1)
            browse = PushButton("…")
            browse.setFixedWidth(36)
            browse.clicked.connect(lambda: self._browse_path(w))
            r_lay.addWidget(browse)
            lay.addWidget(row)
            self._fields[pdef.name] = w

        else:
            w = LineEdit()
            w.setText(str(value) if value else "")
            w.textChanged.connect(self._on_value_changed)
            lay.addWidget(w)
            self._fields[pdef.name] = w

        return container

    def _browse_path(self, line_edit: LineEdit) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择目录", str(Path.home()))
        if d:
            line_edit.setText(d)
            self._on_value_changed()

    def _on_value_changed(self, *_args) -> None:
        values = self.collect_values()
        self.params_changed.emit(self._node_name, values)

    def _on_close(self) -> None:
        self.hide_node()
        self.closed.emit()
