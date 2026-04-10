"""数据清洗集成页:Pivot 切换 质量检查 / 重复检测。

把 QualityView、DedupView 作为子页复用,不重写其中逻辑。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QStackedWidget, QVBoxLayout, QWidget
from qfluentwidgets import CaptionLabel, Pivot, SubtitleLabel

from core.models import Dataset
from gui.theme import T
from gui.views.dedup_view import DedupView
from gui.views.quality_view import QualityView


class CleanView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("cleanView")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        root = QVBoxLayout(self)
        root.setContentsMargins(T.PAD_XL + 12, T.PAD_XL + 8, T.PAD_XL + 12, T.PAD_XL)
        root.setSpacing(T.GAP)

        root.addWidget(SubtitleLabel("数据清洗"))
        root.addWidget(CaptionLabel("检测并清除数据集中的异常/重复样本"))

        self.pivot = Pivot(self)
        self.stack = QStackedWidget(self)

        self.quality = QualityView()
        self.dedup = DedupView()
        # 去掉子页自带的 SubtitleLabel/CaptionLabel 副标题,避免与 pivot 重复
        for sub in (self.quality, self.dedup):
            lay = sub.layout()
            for i in range(min(2, lay.count())):
                item = lay.itemAt(i)
                w = item.widget() if item else None
                if w and w.__class__.__name__ in ("SubtitleLabel", "CaptionLabel"):
                    w.hide()

        self._add_sub("quality", "质量检查", self.quality)
        self._add_sub("dedup", "重复检测", self.dedup)

        self.pivot.currentItemChanged.connect(
            lambda k: self.stack.setCurrentWidget(
                self.quality if k == "quality" else self.dedup
            )
        )
        self.pivot.setCurrentItem("quality")
        self.stack.setCurrentWidget(self.quality)

        root.addWidget(self.pivot)
        root.addWidget(self.stack, 1)

    def _add_sub(self, key: str, text: str, widget: QWidget) -> None:
        self.stack.addWidget(widget)
        self.pivot.addItem(
            routeKey=key,
            text=text,
            onClick=lambda: self.stack.setCurrentWidget(widget),
        )

    # ---- 接口:把 set_dataset 透传到两个子页 ----

    def set_dataset(self, dataset: Dataset | None) -> None:
        self.quality.set_dataset(dataset)
        self.dedup.set_dataset(dataset)
