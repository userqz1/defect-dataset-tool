"""数据清洗 — 质量检查 + 重复检测 参数配置 + 结果展示。

上半区：质量检查（模糊/空白/过曝/损坏）— 参数 + 结果列表
下半区：重复检测（pHash 相似度）— 参数 + 结果列表
共享操作：选中结果 → 删除到回收站

执行通过画布「执行流程」触发，不在此 view 内独立运行。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CaptionLabel,
    DoubleSpinBox,
    InfoBar,
    InfoBarPosition,
    MessageBox,
    PushButton,
    SpinBox,
    StrongBodyLabel,
    SubtitleLabel,
)

from core import fileops
from core.models import Dataset
from gui.theme import T

KIND_LABEL = {"corrupt": "损坏", "blank": "空白", "blur": "模糊", "over": "过曝", "under": "欠曝"}


class CleaningView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("cleaningView")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._dataset: Dataset | None = None
        self._node_item = None

        root = QVBoxLayout(self)
        root.setContentsMargins(T.PAD_2XL, T.PAD_2XL - 4, T.PAD_2XL, T.PAD_XL)
        root.setSpacing(T.GAP_LG)

        root.addWidget(SubtitleLabel("数据清洗"))

        splitter = QSplitter(Qt.Orientation.Vertical)

        # ============ 上半区：质量检查 ============
        quality_panel = QFrame()
        quality_panel.setObjectName("chartFrame")
        ql = QVBoxLayout(quality_panel)
        ql.setContentsMargins(T.PAD_XL, T.PAD_LG, T.PAD_XL, T.PAD_LG)
        ql.setSpacing(T.GAP)

        q_header = QHBoxLayout()
        q_header.addWidget(StrongBodyLabel("质量检查"))
        q_header.addStretch(1)
        q_header.addWidget(CaptionLabel("模糊阈值"))
        self.blur_spin = DoubleSpinBox()
        self.blur_spin.setRange(1, 5000)
        self.blur_spin.setValue(100)
        self.blur_spin.setFixedWidth(100)
        self.blur_spin.setToolTip("Laplacian 方差，越小越模糊")
        q_header.addWidget(self.blur_spin)
        ql.addLayout(q_header)

        self.quality_summary = CaptionLabel("")
        ql.addWidget(self.quality_summary)

        self.quality_list = QListWidget()
        self.quality_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        ql.addWidget(self.quality_list, 1)

        q_actions = QHBoxLayout()
        q_actions.addStretch(1)
        q_sel_btn = PushButton("全选")
        q_sel_btn.clicked.connect(self.quality_list.selectAll)
        q_actions.addWidget(q_sel_btn)
        q_del_btn = PushButton("删除选中")
        q_del_btn.clicked.connect(lambda: self._delete_selected(self.quality_list))
        q_actions.addWidget(q_del_btn)
        ql.addLayout(q_actions)

        splitter.addWidget(quality_panel)

        # ============ 下半区：重复检测 ============
        dedup_panel = QFrame()
        dedup_panel.setObjectName("chartFrame")
        dl = QVBoxLayout(dedup_panel)
        dl.setContentsMargins(T.PAD_XL, T.PAD_LG, T.PAD_XL, T.PAD_LG)
        dl.setSpacing(T.GAP)

        d_header = QHBoxLayout()
        d_header.addWidget(StrongBodyLabel("重复检测"))
        d_header.addStretch(1)
        d_header.addWidget(CaptionLabel("相似阈值"))
        self.threshold_spin = SpinBox()
        self.threshold_spin.setRange(0, 20)
        self.threshold_spin.setValue(5)
        self.threshold_spin.setFixedWidth(100)
        self.threshold_spin.setToolTip("0=完全相同  5=视觉近似  越大越宽松")
        d_header.addWidget(self.threshold_spin)
        dl.addLayout(d_header)

        self.dedup_summary = CaptionLabel("")
        dl.addWidget(self.dedup_summary)

        self.dedup_list = QListWidget()
        dl.addWidget(self.dedup_list, 1)

        splitter.addWidget(dedup_panel)

        root.addWidget(splitter, 1)

        # Wire controls → immediate write-back to NodeItem
        self.blur_spin.valueChanged.connect(self._push_params)
        self.threshold_spin.valueChanged.connect(self._push_params)

    # ---- NodeItem binding ----

    def bind_node(self, node_item) -> None:
        self._node_item = node_item
        params = node_item.get_params() if node_item else {}
        self.blur_spin.blockSignals(True)
        self.blur_spin.setValue(float(params.get("blur_threshold", 100)))
        self.blur_spin.blockSignals(False)
        self.threshold_spin.blockSignals(True)
        self.threshold_spin.setValue(int(params.get("threshold", 5)))
        self.threshold_spin.blockSignals(False)

    def _push_params(self) -> None:
        if self._node_item is None:
            return
        self._node_item.set_params({
            "blur_threshold": self.blur_spin.value(),
            "threshold": self.threshold_spin.value(),
        })

    # ---- Dataset / Results ----

    def set_dataset(self, dataset: Dataset | None) -> None:
        self._dataset = dataset
        n = sum(c.image_count for c in dataset.categories) if dataset else 0
        self.quality_summary.setText(f"待检查：{n:,} 张图片" if n else "")
        self.dedup_summary.setText(f"待检测：{n:,} 张图片" if n else "")
        self.quality_list.clear()
        self.dedup_list.clear()
        if n:
            self._add_placeholder(self.quality_list, "执行流程后查看结果")
            self._add_placeholder(self.dedup_list, "执行流程后查看结果")

    def set_results(self, input_data, step_result) -> None:
        """Display pipeline execution results."""
        if step_result is None:
            return
        issues = step_result.details
        if isinstance(issues, list) and issues and hasattr(issues[0], "kinds"):
            self._show_quality_results(issues)

    def _show_quality_results(self, issues) -> None:
        self.quality_list.clear()
        if not issues:
            self.quality_summary.setText("未发现质量问题 ✓")
            return
        self.quality_summary.setText(f"发现 {len(issues)} 张问题图片")
        for issue in issues:
            tags = " · ".join(KIND_LABEL.get(k, k) for k in issue.kinds)
            text = f"[{tags}]  {issue.image.category} / {issue.image.path.name}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, issue.image)
            self.quality_list.addItem(item)

    # ---- Helpers ----

    @staticmethod
    def _add_placeholder(lst: QListWidget, text: str) -> None:
        item = QListWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        item.setForeground(QColor(T.TEXT_3))
        lst.addItem(item)

    def _delete_selected(self, list_widget: QListWidget) -> None:
        items = list_widget.selectedItems()
        if not items:
            return
        sel_imgs = [it.data(Qt.ItemDataRole.UserRole) for it in items
                    if it.data(Qt.ItemDataRole.UserRole) is not None]
        if not sel_imgs:
            return
        box = MessageBox(
            "确认删除",
            f"将 {len(sel_imgs)} 个图片+标注移至回收站？",
            self.window(),
        )
        if not box.exec():
            return
        result = fileops.delete_pairs(sel_imgs, to_trash=True)
        ok_paths = set(result.succeeded)
        for it in items:
            img = it.data(Qt.ItemDataRole.UserRole)
            if img and img.path in ok_paths:
                list_widget.takeItem(list_widget.row(it))
        InfoBar.success(
            title="已删除", content=f"成功 {result.ok_count} · 失败 {result.fail_count}",
            isClosable=True, position=InfoBarPosition.TOP,
            duration=3000, parent=self.window(),
        )
