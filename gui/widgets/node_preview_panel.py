"""Node data preview panel — shown on the right side of the canvas.

Displays data summary, category breakdown, and execution results
for the currently selected node.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import CaptionLabel, StrongBodyLabel

from gui.theme import T

KIND_LABEL = {"corrupt": "损坏", "blank": "空白", "blur": "模糊", "over": "过曝", "under": "欠曝"}


class NodePreviewPanel(QFrame):
    """Right-side panel showing data preview for the selected canvas node."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("nodeInspector")
        self.setFixedWidth(T.DETAIL_SIDEBAR_WIDTH)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header
        self._header = QFrame()
        self._header.setObjectName("inspectorHeader")
        self._header.setFixedHeight(44)
        h_lay = QVBoxLayout(self._header)
        h_lay.setContentsMargins(T.PAD_LG, 0, T.PAD_LG, 0)
        self._title = StrongBodyLabel("")
        h_lay.addWidget(self._title)
        outer.addWidget(self._header)

        # Scrollable content area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(T.PAD_LG, T.PAD, T.PAD_LG, T.PAD)
        self._content_layout.setSpacing(T.GAP)
        self._content_layout.addStretch(1)
        scroll.setWidget(self._content)
        outer.addWidget(scroll, 1)

        self.show_empty()

    # ---- Public API ----

    def show_empty(self) -> None:
        """Show default state when no node is selected."""
        self._title.setText("节点预览")
        self._clear()
        self._add_hint("选中画布上的节点查看数据")

    def show_node(self, node_item, node_result=None, dataset=None) -> None:
        """Display data preview for the given node."""
        self._title.setText(node_item.display_name)
        self._clear()

        name = node_item.node_name
        builder = {
            "data_source": self._build_datasource,
            "quality_check": self._build_quality,
            "dedup": self._build_dedup,
            "augment": self._build_augment,
            "predict": self._build_predict,
            "split": self._build_split,
            "export": self._build_export,
        }.get(name, self._build_generic)
        builder(node_item, node_result, dataset)

    # ---- Builders ----

    def _build_datasource(self, node_item, result, dataset) -> None:
        params = node_item.get_params()
        root = params.get("root_dir", "")
        if root:
            self._add_row("目录", _ellipsis(root, 30))

        if dataset:
            self._add_row("布局", dataset.layout)
            self._add_section("类别分布")
            grid = QGridLayout()
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setSpacing(2)
            for i, cat in enumerate(dataset.categories):
                grid.addWidget(self._dim_label(cat.name), i, 0)
                grid.addWidget(self._dim_label(
                    f"{cat.image_count} 张", align=Qt.AlignmentFlag.AlignRight), i, 1)
                lbl_text = f"({cat.label_count} 标注)" if cat.label_count else ""
                grid.addWidget(self._dim_label(
                    lbl_text, align=Qt.AlignmentFlag.AlignRight), i, 2)
            self._content_layout.insertLayout(self._content_layout.count() - 1, grid)
            self._add_divider()
            self._add_row("总计", f"{dataset.total_images} 张 · {dataset.total_annotations} 标注")
        elif not root:
            self._add_hint("双击节点选择数据集目录")

    def _build_quality(self, node_item, result, dataset) -> None:
        self._add_params(node_item, ["blur_threshold"])
        if result is None:
            self._add_hint("执行流程后查看结果")
            return
        sr = result.step_result
        if sr is None:
            return
        self._add_section("结果")
        self._add_row("合格", str(sr.ok_count))
        self._add_row("不合格", str(sr.fail_count))
        if sr.details:
            self._add_section("问题分布")
            from collections import Counter
            counts = Counter()
            for issue in sr.details:
                for k in issue.kinds:
                    counts[k] += 1
            for k, n in counts.most_common():
                self._add_row(KIND_LABEL.get(k, k), str(n))

    def _build_dedup(self, node_item, result, dataset) -> None:
        self._add_params(node_item, ["threshold"])
        if result is None:
            self._add_hint("执行流程后查看结果")
            return
        sr = result.step_result
        if sr is None:
            return
        self._add_section("结果")
        self._add_row("唯一", str(sr.ok_count))
        self._add_row("重复", str(sr.fail_count))
        if sr.details:
            self._add_row("重复组数", str(len(sr.details)))

    def _build_augment(self, node_item, result, dataset) -> None:
        self._add_params(node_item, ["flip_h", "rotate", "brightness", "n_each"])
        if result is None:
            self._add_hint("执行流程后查看结果")
            return
        sr = result.step_result
        if sr is None:
            return
        self._add_section("结果")
        self._add_row("生成", f"{sr.ok_count} 张")
        self._add_row("失败", str(sr.fail_count))

    def _build_predict(self, node_item, result, dataset) -> None:
        self._add_params(node_item, ["model", "confidence"])
        if result is None:
            self._add_hint("执行流程后查看结果")
            return
        sr = result.step_result
        if sr is None:
            return
        self._add_section("结果")
        self._add_row("已标注", f"{sr.ok_count} 张")
        self._add_row("失败", str(sr.fail_count))

    def _build_split(self, node_item, result, dataset) -> None:
        self._add_params(node_item, ["train_ratio", "val_ratio", "test_ratio"])
        if result is None:
            self._add_hint("执行流程后查看结果")
            return
        sr = result.step_result
        if sr is None or sr.details is None:
            return
        split = sr.details
        total = len(split.train) + len(split.val) + len(split.test)
        self._add_section("划分结果")
        self._add_row("Train", f"{len(split.train)}  ({_pct(len(split.train), total)})")
        self._add_row("Val", f"{len(split.val)}  ({_pct(len(split.val), total)})")
        self._add_row("Test", f"{len(split.test)}  ({_pct(len(split.test), total)})")
        self._add_divider()
        self._add_row("总计", str(total))

    def _build_export(self, node_item, result, dataset) -> None:
        params = node_item.get_params()
        fmt = params.get("format", "YOLO")
        self._add_row("格式", fmt)

        # Structure preview (always visible)
        tree = _STRUCTURE.get(fmt, "")
        if tree:
            self._add_section("输出结构")
            lbl = CaptionLabel(tree)
            lbl.setWordWrap(True)
            lbl.setStyleSheet(f"font-family: Consolas, monospace; color: {T.TEXT_2};")
            self._content_layout.insertWidget(self._content_layout.count() - 1, lbl)

        if result and result.step_result:
            sr = result.step_result
            count = getattr(sr.details, "written_images", sr.ok_count)
            self._add_section("结果")
            self._add_row("已写入", f"{count} 张")

    def _build_generic(self, node_item, result, dataset) -> None:
        from core.nodes import NODES
        spec = NODES.get(node_item.node_name)
        if spec:
            self._add_hint(spec.description)
        self._add_params(node_item, [])
        if result and result.step_result:
            sr = result.step_result
            self._add_section("结果")
            self._add_row("通过", str(sr.ok_count))
            if sr.fail_count:
                self._add_row("失败", str(sr.fail_count))

    # ---- Helpers ----

    def _clear(self) -> None:
        """Remove all content widgets."""
        while self._content_layout.count() > 1:  # keep the stretch
            item = self._content_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
            elif item.layout():
                _clear_layout(item.layout())

    def _add_section(self, title: str) -> None:
        lbl = QLabel(title)
        lbl.setObjectName("inspectorSectionTitle")
        self._content_layout.insertWidget(self._content_layout.count() - 1, lbl)

    def _add_row(self, key: str, value: str) -> None:
        row = QFrame()
        row.setFixedHeight(22)
        h = QGridLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        k = CaptionLabel(key)
        v = CaptionLabel(value)
        v.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        h.addWidget(k, 0, 0)
        h.addWidget(v, 0, 1)
        self._content_layout.insertWidget(self._content_layout.count() - 1, row)

    def _add_hint(self, text: str) -> None:
        lbl = QLabel(text)
        lbl.setObjectName("inspectorDesc")
        lbl.setWordWrap(True)
        self._content_layout.insertWidget(self._content_layout.count() - 1, lbl)

    def _add_divider(self) -> None:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFixedHeight(1)
        line.setStyleSheet(f"background-color: {T.BORDER};")
        self._content_layout.insertWidget(self._content_layout.count() - 1, line)

    def _add_params(self, node_item, keys: list[str]) -> None:
        """Show current parameter values."""
        params = node_item.get_params()
        if not params:
            return
        show = {k: v for k, v in params.items() if not keys or k in keys}
        if not show:
            return
        self._add_section("参数")
        from core.nodes import NODES
        spec = NODES.get(node_item.node_name)
        param_labels = {}
        if spec:
            for pdef in getattr(spec, "parameters", ()):
                param_labels[pdef.name] = pdef.label
        for k, v in show.items():
            display_v = "是" if v is True else "否" if v is False else str(v)
            self._add_row(param_labels.get(k, k), display_v)

    @staticmethod
    def _dim_label(text: str, align=Qt.AlignmentFlag.AlignLeft) -> CaptionLabel:
        lbl = CaptionLabel(text)
        lbl.setAlignment(align | Qt.AlignmentFlag.AlignVCenter)
        return lbl


# ---- Utilities ----

def _pct(n: int, total: int) -> str:
    if total == 0:
        return "0%"
    return f"{n * 100 / total:.0f}%"


def _ellipsis(s: str, maxlen: int) -> str:
    return s if len(s) <= maxlen else "..." + s[-(maxlen - 3):]


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w:
            w.deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


_STRUCTURE = {
    "YOLO": (
        "output/\n"
        "├── images/{train,val,test}/\n"
        "├── labels/{train,val,test}/\n"
        "├── classes.txt\n"
        "└── data.yaml"
    ),
    "COCO": (
        "output/\n"
        "├── {train,val,test}/  (图片)\n"
        "└── annotations/\n"
        "    └── instances_{split}.json"
    ),
    "VOC": (
        "output/\n"
        "├── JPEGImages/\n"
        "├── Annotations/  (XML)\n"
        "└── ImageSets/Main/"
    ),
    "CSV": (
        "output/\n"
        "└── annotations.csv"
    ),
}
