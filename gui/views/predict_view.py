"""AI 预标注 — 参数配置 + 结果展示。

执行通过画布「执行流程」触发。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CheckBox,
    ComboBox,
    DoubleSpinBox,
    LineEdit,
    SubtitleLabel,
)

from gui.theme import T
from gui.widgets.node_workspace import NodeWorkspace


class PredictView(NodeWorkspace):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("predictView")

        root = QVBoxLayout(self)
        root.setContentsMargins(T.PAD_2XL, T.PAD_2XL - 4, T.PAD_2XL, T.PAD_XL)
        root.setSpacing(T.GAP_LG)

        root.addWidget(SubtitleLabel("AI 预标注"))

        # 后端
        backend_row = QHBoxLayout()
        backend_row.addWidget(BodyLabel("后端"))
        self.backend_combo = ComboBox()
        self.backend_combo.addItem("YOLOv8 (本地)")
        backend_row.addWidget(self.backend_combo)
        backend_row.addSpacing(T.GAP_LG)
        backend_row.addWidget(BodyLabel("模型"))
        self.model_edit = LineEdit()
        self.model_edit.setText("yolov8n.pt")
        self.model_edit.setFixedWidth(180)
        self.model_edit.setToolTip("本地路径或 ultralytics 自动下载的模型名")
        backend_row.addWidget(self.model_edit)
        backend_row.addSpacing(T.GAP_LG)
        backend_row.addWidget(BodyLabel("置信阈值"))
        self.conf_spin = DoubleSpinBox()
        self.conf_spin.setRange(0.05, 0.95)
        self.conf_spin.setSingleStep(0.05)
        self.conf_spin.setValue(0.25)
        backend_row.addWidget(self.conf_spin)
        backend_row.addStretch(1)
        root.addLayout(backend_row)

        # 选项
        opt_row = QHBoxLayout()
        self.overwrite_chk = CheckBox("覆盖已有标注")
        opt_row.addWidget(self.overwrite_chk)
        opt_row.addStretch(1)
        root.addLayout(opt_row)

        self.summary_label = BodyLabel("执行流程后查看结果")
        root.addWidget(self.summary_label)
        root.addStretch(1)

        # Wire controls → immediate write-back
        self.model_edit.textChanged.connect(self._push_params)
        self.conf_spin.valueChanged.connect(self._push_params)
        self.overwrite_chk.stateChanged.connect(self._push_params)

    # ---- NodeItem binding ----

    def bind_node(self, node_item) -> None:
        self._node_item = node_item
        params = node_item.get_params() if node_item else {}
        self.model_edit.blockSignals(True)
        self.model_edit.setText(str(params.get("model", "yolov8n.pt")))
        self.model_edit.blockSignals(False)
        self.conf_spin.blockSignals(True)
        self.conf_spin.setValue(float(params.get("confidence", 0.25)))
        self.conf_spin.blockSignals(False)
        self.overwrite_chk.blockSignals(True)
        self.overwrite_chk.setChecked(bool(params.get("overwrite", False)))
        self.overwrite_chk.blockSignals(False)

    def _push_params(self) -> None:
        if self._node_item is None:
            return
        self._node_item.set_params({
            "model": self.model_edit.text(),
            "confidence": self.conf_spin.value(),
            "overwrite": self.overwrite_chk.isChecked(),
        })

    # ---- Dataset / Results ----

    def set_dataset(self, dataset: Dataset | None) -> None:
        self._dataset = dataset
        if dataset is None:
            self.summary_label.setText("请先加载数据集")
            return
        n = sum(c.image_count for c in dataset.categories)
        n_un = sum(1 for c in dataset.categories for img in c.images if not img.has_label)
        self.summary_label.setText(f"未标注 {n_un:,} / 总计 {n:,}")

