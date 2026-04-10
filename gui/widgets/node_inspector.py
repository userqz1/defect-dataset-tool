"""Right-side node inspector — functional controls only, no fluff."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QScrollArea,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    ComboBox,
    DoubleSpinBox,
    FluentIcon as FIF,
    LineEdit,
    PushButton,
    SpinBox,
    SubtitleLabel,
    SwitchButton,
    TransparentToolButton,
)

from gui.theme import T


def _section(title: str) -> QFrame:
    f = QFrame()
    lay = QVBoxLayout(f)
    lay.setContentsMargins(0, T.GAP, 0, 2)
    lay.setSpacing(0)
    sep = QFrame()
    sep.setFixedHeight(1)
    sep.setObjectName("inspectorSep")
    lay.addWidget(sep)
    lbl = CaptionLabel(title)
    lbl.setObjectName("inspectorSectionTitle")
    lay.addWidget(lbl)
    return f


def _row(label: str, widget: QWidget) -> QFrame:
    f = QFrame()
    lay = QHBoxLayout(f)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)
    lbl = CaptionLabel(label)
    lbl.setFixedWidth(70)
    lay.addWidget(lbl)
    lay.addWidget(widget, 1)
    return f


class NodeInspector(QFrame):
    params_changed = pyqtSignal(str, dict)
    closed = pyqtSignal()
    WIDTH = 300

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("nodeInspector")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(self.WIDTH)
        self._node_name = ""
        self._fields: dict[str, QWidget] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        header = QFrame()
        header.setObjectName("inspectorHeader")
        header.setFixedHeight(44)
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(T.PAD_LG, 0, T.GAP, 0)
        self._title = SubtitleLabel("")
        h_lay.addWidget(self._title, 1)
        close_btn = TransparentToolButton(FIF.CLOSE)
        close_btn.setFixedSize(28, 28)
        close_btn.clicked.connect(self._on_close)
        h_lay.addWidget(close_btn)
        root.addWidget(header)

        # Scroll content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._content = QWidget()
        self._lay = QVBoxLayout(self._content)
        self._lay.setContentsMargins(T.PAD_LG, T.GAP, T.PAD_LG, T.PAD_LG)
        self._lay.setSpacing(6)
        self._lay.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(self._content)
        root.addWidget(scroll, 1)
        self.hide()

    def show_node(self, node_name: str, params: dict[str, Any]) -> None:
        from core.nodes import NODES
        spec = NODES.get(node_name)
        if not spec:
            return
        self._node_name = node_name
        self._title.setText(spec.display_name)
        self._fields.clear()
        self._clear()

        builder = _BUILDERS.get(node_name)
        if builder:
            builder(self, params)
        else:
            self._generic(params)
        self.show()

    def hide_node(self) -> None:
        self._node_name = ""
        self.hide()

    def collect_values(self) -> dict[str, Any]:
        from core.nodes import NODES
        spec = NODES.get(self._node_name)
        if not spec:
            return {}
        out: dict[str, Any] = {}
        for pdef in getattr(spec, "parameters", ()):
            w = self._fields.get(pdef.name)
            if w is None:
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

    def _clear(self) -> None:
        while self._lay.count():
            item = self._lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _emit(self, *_a) -> None:
        self.params_changed.emit(self._node_name, self.collect_values())

    def _on_close(self) -> None:
        self.hide_node()
        self.closed.emit()

    # ---- field helpers ----

    def _add_int(self, key: str, label: str, val: int, lo: int = 0, hi: int = 9999) -> SpinBox:
        w = SpinBox()
        w.setMinimum(lo)
        w.setMaximum(hi)
        w.setValue(val)
        w.valueChanged.connect(self._emit)
        self._fields[key] = w
        self._lay.addWidget(_row(label, w))
        return w

    def _add_float(self, key: str, label: str, val: float, lo: float = 0, hi: float = 1) -> DoubleSpinBox:
        w = DoubleSpinBox()
        w.setDecimals(2)
        w.setSingleStep(0.05)
        w.setMinimum(lo)
        w.setMaximum(hi)
        w.setValue(val)
        w.valueChanged.connect(self._emit)
        self._fields[key] = w
        self._lay.addWidget(_row(label, w))
        return w

    def _add_bool(self, key: str, label: str, val: bool) -> SwitchButton:
        w = SwitchButton()
        w.setChecked(val)
        w.checkedChanged.connect(self._emit)
        self._fields[key] = w
        self._lay.addWidget(_row(label, w))
        return w

    def _add_choice(self, key: str, label: str, choices: list[str], val: str) -> ComboBox:
        w = ComboBox()
        w.addItems(choices)
        w.setCurrentText(val)
        w.currentTextChanged.connect(self._emit)
        self._fields[key] = w
        self._lay.addWidget(_row(label, w))
        return w

    def _add_path(self, key: str, label: str, val: str) -> LineEdit:
        row = QFrame()
        r_lay = QHBoxLayout(row)
        r_lay.setContentsMargins(0, 0, 0, 0)
        r_lay.setSpacing(4)
        w = LineEdit()
        w.setText(val)
        w.setPlaceholderText("选择目录…")
        r_lay.addWidget(w, 1)
        btn = PushButton("…")
        btn.setFixedWidth(36)
        btn.clicked.connect(lambda: self._browse(w))
        r_lay.addWidget(btn)
        self._fields[key] = w
        lbl = CaptionLabel(label)
        self._lay.addWidget(lbl)
        self._lay.addWidget(row)
        return w

    def _browse(self, le: LineEdit) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择目录", str(Path.home()))
        if d:
            le.setText(d)
            self._emit()
            if self._node_name == "data_source":
                self._refresh_dir(d)

    # ---- directory tree ----

    def _make_tree(self, root_path: str) -> QTreeWidget:
        tree = QTreeWidget()
        tree.setObjectName("inspectorDirTree")
        tree.setHeaderHidden(True)
        tree.setMaximumHeight(220)
        tree.setIndentation(14)
        if root_path:
            self._fill_tree(tree, Path(root_path))
        return tree

    def _fill_tree(self, tree: QTreeWidget, root: Path) -> None:
        tree.clear()
        if not root.exists():
            return
        ri = QTreeWidgetItem([root.name + "/"])
        tree.addTopLevelItem(ri)
        self._tree_children(ri, root, 3)
        ri.setExpanded(True)

    def _tree_children(self, parent: QTreeWidgetItem, path: Path, depth: int) -> None:
        if depth <= 0:
            return
        try:
            entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except PermissionError:
            return
        img_ext = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}
        for i, entry in enumerate(entries):
            if i >= 40:
                parent.addChild(QTreeWidgetItem(["…"]))
                break
            if entry.is_dir():
                c = QTreeWidgetItem([entry.name + "/"])
                parent.addChild(c)
                self._tree_children(c, entry, depth - 1)
            else:
                parent.addChild(QTreeWidgetItem([entry.name]))

    def _refresh_dir(self, root_path: str) -> None:
        tree = self._fields.get("_tree")
        if isinstance(tree, QTreeWidget):
            self._fill_tree(tree, Path(root_path))
        stats = self._fields.get("_stats")
        if isinstance(stats, CaptionLabel):
            stats.setText(self._dir_stats(root_path))

    @staticmethod
    def _dir_stats(root_path: str) -> str:
        p = Path(root_path)
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

    # ---- generic fallback ----

    def _generic(self, params: dict) -> None:
        from core.nodes import NODES
        spec = NODES.get(self._node_name)
        if not spec:
            return
        for pdef in getattr(spec, "parameters", ()):
            val = params.get(pdef.name, pdef.default)
            if pdef.type == "int":
                self._add_int(pdef.name, pdef.label, int(val or 0),
                              int(pdef.min_val or 0), int(pdef.max_val or 9999))
            elif pdef.type == "float":
                self._add_float(pdef.name, pdef.label, float(val or 0),
                                float(pdef.min_val or 0), float(pdef.max_val or 1))
            elif pdef.type == "bool":
                self._add_bool(pdef.name, pdef.label, bool(val))
            elif pdef.type == "choice":
                self._add_choice(pdef.name, pdef.label, list(pdef.choices or []), str(val or ""))
            elif pdef.type == "path":
                self._add_path(pdef.name, pdef.label, str(val or ""))


# ---- Per-node builders ----

def _b_data_source(ins: NodeInspector, p: dict) -> None:
    root = str(p.get("root_dir", ""))
    ins._add_path("root_dir", "根目录", root)

    stats = CaptionLabel(ins._dir_stats(root) if root else "")
    ins._fields["_stats"] = stats
    ins._lay.addWidget(stats)

    ins._lay.addWidget(_section("目录结构"))
    tree = ins._make_tree(root)
    ins._fields["_tree"] = tree
    ins._lay.addWidget(tree)


def _b_quality(ins: NodeInspector, p: dict) -> None:
    ins._add_int("blur_threshold", "模糊阈值", int(p.get("blur_threshold", 100)), 10, 500)


def _b_dedup(ins: NodeInspector, p: dict) -> None:
    ins._add_int("threshold", "相似阈值", int(p.get("threshold", 5)), 0, 20)


def _b_augment(ins: NodeInspector, p: dict) -> None:
    ins._add_bool("flip_h", "水平翻转", bool(p.get("flip_h", True)))
    ins._add_bool("flip_v", "垂直翻转", bool(p.get("flip_v", False)))
    ins._add_bool("rotate", "随机旋转", bool(p.get("rotate", True)))
    ins._add_bool("brightness", "亮度调整", bool(p.get("brightness", True)))


def _b_split(ins: NodeInspector, p: dict) -> None:
    ins._add_float("train_ratio", "训练集", float(p.get("train_ratio", 0.8)), 0, 1)
    ins._add_float("val_ratio", "验证集", float(p.get("val_ratio", 0.1)), 0, 1)
    ins._add_float("test_ratio", "测试集", float(p.get("test_ratio", 0.1)), 0, 1)
    ins._add_bool("stratified", "分层采样", bool(p.get("stratified", True)))


def _b_export(ins: NodeInspector, p: dict) -> None:
    fmt = str(p.get("format", "YOLO"))
    w = ins._add_choice("format", "格式", ["YOLO", "COCO", "VOC", "CSV"], fmt)
    ins._add_path("out_dir", "输出目录", str(p.get("out_dir", "")))

    ins._lay.addWidget(_section("输出结构"))
    tree = QTreeWidget()
    tree.setObjectName("inspectorDirTree")
    tree.setHeaderHidden(True)
    tree.setMaximumHeight(160)
    tree.setIndentation(14)
    ins._fields["_export_tree"] = tree
    _fill_export(tree, fmt)
    ins._lay.addWidget(tree)

    w.currentTextChanged.connect(lambda f: _fill_export(tree, f))


def _fill_export(tree: QTreeWidget, fmt: str) -> None:
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
