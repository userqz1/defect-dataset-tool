"""Node configuration dialogs — double-click a node to open.

Each node type gets a tailored dialog with proper layout.
Uses qfluentwidgets MessageBoxBase for consistent Fluent style.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CaptionLabel,
    ComboBox,
    DoubleSpinBox,
    LineEdit,
    MessageBoxBase,
    PushButton,
    SpinBox,
    SubtitleLabel,
    SwitchButton,
)

from gui.theme import T


class NodeConfigDialog(MessageBoxBase):
    """Base node config dialog. Subclass or use the factory."""

    def __init__(self, node_name: str, display_name: str,
                 params: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._node_name = node_name
        self._params = dict(params)
        self._fields: dict[str, QWidget] = {}

        self.titleLabel = SubtitleLabel(display_name)
        self.viewLayout.addWidget(self.titleLabel)

        # Content area — subclasses/builders fill this
        self._form = QWidget()
        self._form_lay = QVBoxLayout(self._form)
        self._form_lay.setContentsMargins(0, 8, 0, 0)
        self._form_lay.setSpacing(10)
        self.viewLayout.addWidget(self._form)

        self.yesButton.setText("确定")
        self.cancelButton.setText("取消")

        # Build per-node content
        builder = _BUILDERS.get(node_name)
        if builder:
            builder(self)
        else:
            self._build_generic()

        self.widget.setMinimumWidth(460)
        self.widget.setMaximumWidth(520)
        self.widget.setMaximumHeight(600)

    def get_values(self) -> dict[str, Any]:
        """Read values from fields after dialog is accepted."""
        from core.nodes import NODES
        spec = NODES.get(self._node_name)
        if not spec:
            return self._params
        out: dict[str, Any] = {}
        for pdef in getattr(spec, "parameters", ()):
            w = self._fields.get(pdef.name)
            if w is None:
                out[pdef.name] = self._params.get(pdef.name, pdef.default)
                continue
            if pdef.type == "int":
                out[pdef.name] = w.value()
            elif pdef.type == "float":
                out[pdef.name] = w.value()
            elif pdef.type == "bool":
                out[pdef.name] = w.isChecked()
            elif pdef.type == "choice":
                out[pdef.name] = w.currentText()
            elif pdef.type == "path":
                out[pdef.name] = w.text()
            else:
                out[pdef.name] = w.text()
        return out

    # ---- helpers ----

    def _grid(self) -> QGridLayout:
        g = QGridLayout()
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(8)
        g.setColumnMinimumWidth(0, 80)
        return g

    def _add_int(self, grid: QGridLayout, row: int, key: str, label: str,
                 val: int, lo: int = 0, hi: int = 9999) -> SpinBox:
        grid.addWidget(CaptionLabel(label), row, 0, Qt.AlignmentFlag.AlignRight)
        w = SpinBox()
        w.setMinimum(lo)
        w.setMaximum(hi)
        w.setValue(val)
        self._fields[key] = w
        grid.addWidget(w, row, 1)
        return w

    def _add_float(self, grid: QGridLayout, row: int, key: str, label: str,
                   val: float, lo: float = 0, hi: float = 1) -> DoubleSpinBox:
        grid.addWidget(CaptionLabel(label), row, 0, Qt.AlignmentFlag.AlignRight)
        w = DoubleSpinBox()
        w.setDecimals(2)
        w.setSingleStep(0.05)
        w.setMinimum(lo)
        w.setMaximum(hi)
        w.setValue(val)
        self._fields[key] = w
        grid.addWidget(w, row, 1)
        return w

    def _add_bool(self, grid: QGridLayout, row: int, key: str, label: str,
                  val: bool) -> SwitchButton:
        grid.addWidget(CaptionLabel(label), row, 0, Qt.AlignmentFlag.AlignRight)
        w = SwitchButton()
        w.setChecked(val)
        self._fields[key] = w
        grid.addWidget(w, row, 1)
        return w

    def _add_choice(self, grid: QGridLayout, row: int, key: str, label: str,
                    choices: list[str], val: str) -> ComboBox:
        grid.addWidget(CaptionLabel(label), row, 0, Qt.AlignmentFlag.AlignRight)
        w = ComboBox()
        w.addItems(choices)
        w.setCurrentText(val)
        self._fields[key] = w
        grid.addWidget(w, row, 1)
        return w

    def _add_path(self, grid: QGridLayout, row: int, key: str, label: str,
                  val: str) -> LineEdit:
        grid.addWidget(CaptionLabel(label), row, 0, Qt.AlignmentFlag.AlignRight)
        frame = QFrame()
        h = QHBoxLayout(frame)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        w = LineEdit()
        w.setText(val)
        w.setPlaceholderText("选择目录…")
        h.addWidget(w, 1)
        btn = PushButton("…")
        btn.setFixedWidth(36)
        btn.clicked.connect(lambda: self._browse(w))
        h.addWidget(btn)
        self._fields[key] = w
        grid.addWidget(frame, row, 1)
        return w

    def _browse(self, le: LineEdit) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择目录", str(Path.home()))
        if d:
            le.setText(d)

    def _build_generic(self) -> None:
        from core.nodes import NODES
        spec = NODES.get(self._node_name)
        if not spec:
            return
        g = self._grid()
        row = 0
        for pdef in getattr(spec, "parameters", ()):
            val = self._params.get(pdef.name, pdef.default)
            if pdef.type == "int":
                self._add_int(g, row, pdef.name, pdef.label, int(val or 0),
                              int(pdef.min_val or 0), int(pdef.max_val or 9999))
            elif pdef.type == "float":
                self._add_float(g, row, pdef.name, pdef.label, float(val or 0),
                                float(pdef.min_val or 0), float(pdef.max_val or 1))
            elif pdef.type == "bool":
                self._add_bool(g, row, pdef.name, pdef.label, bool(val))
            elif pdef.type == "choice":
                self._add_choice(g, row, pdef.name, pdef.label,
                                 list(pdef.choices or []), str(val or ""))
            elif pdef.type == "path":
                self._add_path(g, row, pdef.name, pdef.label, str(val or ""))
            row += 1
        self._form_lay.addLayout(g)


# ---------------------------------------------------------------------------
# Per-node builders
# ---------------------------------------------------------------------------

def _b_data_source(dlg: NodeConfigDialog) -> None:
    g = dlg._grid()
    root = str(dlg._params.get("root_dir", ""))

    # Path row
    g.addWidget(CaptionLabel("根目录"), 0, 0, Qt.AlignmentFlag.AlignRight)
    path_frame = QFrame()
    h = QHBoxLayout(path_frame)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(4)
    le = LineEdit()
    le.setText(root)
    le.setPlaceholderText("选择目录…")
    h.addWidget(le, 1)
    dlg._fields["root_dir"] = le

    stats = CaptionLabel(_dir_stats(root) if root else "")
    tree = QTreeWidget()
    tree.setObjectName("inspectorDirTree")
    tree.setHeaderHidden(True)
    tree.setMinimumHeight(200)
    tree.setIndentation(14)
    if root:
        _fill_dir_tree(tree, Path(root))

    def _on_browse():
        d = QFileDialog.getExistingDirectory(dlg, "选择目录", str(Path.home()))
        if d:
            le.setText(d)
            _fill_dir_tree(tree, Path(d))
            stats.setText(_dir_stats(d))

    btn = PushButton("…")
    btn.setFixedWidth(36)
    btn.clicked.connect(_on_browse)
    h.addWidget(btn)
    g.addWidget(path_frame, 0, 1)
    dlg._form_lay.addLayout(g)

    dlg._form_lay.addWidget(stats)
    dlg._form_lay.addWidget(tree)


def _b_quality(dlg: NodeConfigDialog) -> None:
    g = dlg._grid()
    dlg._add_int(g, 0, "blur_threshold", "模糊阈值",
                 int(dlg._params.get("blur_threshold", 100)), 10, 500)
    dlg._form_lay.addLayout(g)


def _b_dedup(dlg: NodeConfigDialog) -> None:
    g = dlg._grid()
    dlg._add_int(g, 0, "threshold", "相似阈值",
                 int(dlg._params.get("threshold", 5)), 0, 20)
    dlg._form_lay.addLayout(g)


def _b_augment(dlg: NodeConfigDialog) -> None:
    g = dlg._grid()
    dlg._add_bool(g, 0, "flip_h", "水平翻转", bool(dlg._params.get("flip_h", True)))
    dlg._add_bool(g, 1, "flip_v", "垂直翻转", bool(dlg._params.get("flip_v", False)))
    dlg._add_bool(g, 2, "rotate", "随机旋转", bool(dlg._params.get("rotate", True)))
    dlg._add_bool(g, 3, "brightness", "亮度调整", bool(dlg._params.get("brightness", True)))
    dlg._form_lay.addLayout(g)


def _b_split(dlg: NodeConfigDialog) -> None:
    g = dlg._grid()
    dlg._add_float(g, 0, "train_ratio", "训练集",
                   float(dlg._params.get("train_ratio", 0.8)), 0, 1)
    dlg._add_float(g, 1, "val_ratio", "验证集",
                   float(dlg._params.get("val_ratio", 0.1)), 0, 1)
    dlg._add_float(g, 2, "test_ratio", "测试集",
                   float(dlg._params.get("test_ratio", 0.1)), 0, 1)
    dlg._add_bool(g, 3, "stratified", "分层采样", bool(dlg._params.get("stratified", True)))
    dlg._form_lay.addLayout(g)


def _b_export(dlg: NodeConfigDialog) -> None:
    g = dlg._grid()
    fmt = str(dlg._params.get("format", "YOLO"))
    combo = dlg._add_choice(g, 0, "format", "格式", ["YOLO", "COCO", "VOC", "CSV"], fmt)
    dlg._add_path(g, 1, "out_dir", "输出目录", str(dlg._params.get("out_dir", "")))
    dlg._form_lay.addLayout(g)

    # Output structure preview
    tree = QTreeWidget()
    tree.setObjectName("inspectorDirTree")
    tree.setHeaderHidden(True)
    tree.setMinimumHeight(140)
    tree.setIndentation(14)
    _fill_export_tree(tree, fmt)
    dlg._form_lay.addWidget(tree)

    combo.currentTextChanged.connect(lambda f: _fill_export_tree(tree, f))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dir_stats(root: str) -> str:
    p = Path(root)
    if not p.exists():
        return ""
    img_ext = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}
    imgs = jsons = dirs = 0
    try:
        for e in p.rglob("*"):
            if e.is_dir():
                dirs += 1
            elif e.suffix.lower() in img_ext:
                imgs += 1
            elif e.suffix.lower() == ".json":
                jsons += 1
    except PermissionError:
        pass
    return f"{dirs} 目录 · {imgs} 图片 · {jsons} 标注"


def _fill_dir_tree(tree: QTreeWidget, root: Path) -> None:
    tree.clear()
    if not root.exists():
        return
    ri = QTreeWidgetItem([root.name + "/"])
    tree.addTopLevelItem(ri)
    _add_children(ri, root, 3)
    ri.setExpanded(True)


def _add_children(parent: QTreeWidgetItem, path: Path, depth: int) -> None:
    if depth <= 0:
        return
    try:
        entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except PermissionError:
        return
    for i, entry in enumerate(entries):
        if i >= 40:
            parent.addChild(QTreeWidgetItem(["…"]))
            break
        if entry.is_dir():
            c = QTreeWidgetItem([entry.name + "/"])
            parent.addChild(c)
            _add_children(c, entry, depth - 1)
        else:
            parent.addChild(QTreeWidgetItem([entry.name]))


def _fill_export_tree(tree: QTreeWidget, fmt: str) -> None:
    tree.clear()
    root = QTreeWidgetItem(["output/"])
    tree.addTopLevelItem(root)
    if fmt == "YOLO":
        for s in ["train/", "val/", "test/"]:
            n = QTreeWidgetItem([s])
            root.addChild(n)
            n.addChild(QTreeWidgetItem(["images/"]))
            n.addChild(QTreeWidgetItem(["labels/"]))
        root.addChild(QTreeWidgetItem(["data.yaml"]))
    elif fmt == "COCO":
        for s in ["train/", "val/", "test/"]:
            root.addChild(QTreeWidgetItem([s]))
        a = QTreeWidgetItem(["annotations/"])
        root.addChild(a)
        a.addChild(QTreeWidgetItem(["instances_train.json"]))
        a.addChild(QTreeWidgetItem(["instances_val.json"]))
    elif fmt == "VOC":
        root.addChild(QTreeWidgetItem(["JPEGImages/"]))
        root.addChild(QTreeWidgetItem(["Annotations/"]))
        root.addChild(QTreeWidgetItem(["ImageSets/"]))
    elif fmt == "CSV":
        root.addChild(QTreeWidgetItem(["images/"]))
        root.addChild(QTreeWidgetItem(["annotations.csv"]))
    root.setExpanded(True)
    for i in range(root.childCount()):
        root.child(i).setExpanded(True)


_BUILDERS: dict[str, Any] = {
    "data_source": _b_data_source,
    "quality_check": _b_quality,
    "dedup": _b_dedup,
    "augment": _b_augment,
    "split": _b_split,
    "export": _b_export,
}
