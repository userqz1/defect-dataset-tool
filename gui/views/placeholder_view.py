"""Placeholder view for features whose GUI is not yet wired.

Shows the feature name, a one-line status, and (when a dataset is loaded) a
hint nudging the user forward. All real functionality lives in the
corresponding core/ module — see 解决方案.md §八.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CaptionLabel, SubtitleLabel

from core.models import Dataset
from gui.theme import T


class PlaceholderView(QWidget):
    """Simple 'coming soon' page for unimplemented workflow modules."""

    def __init__(self, object_name: str, title: str, description: str) -> None:
        super().__init__()
        self.setObjectName(object_name)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(T.PAD_2XL, T.PAD_2XL - 4, T.PAD_2XL, T.PAD_XL)
        layout.setSpacing(T.GAP)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._title = SubtitleLabel(title)
        self._desc = CaptionLabel(description)
        layout.addWidget(self._title)
        layout.addWidget(self._desc)

        layout.addSpacing(T.GAP_XL * 2)
        self._status = BodyLabel("此模块 GUI 尚未接入。核心逻辑已在 core/ 中实现。")
        self._status.setObjectName("placeholderStatus")
        layout.addWidget(self._status)

    def set_dataset(self, dataset: Dataset | None) -> None:
        if dataset is None:
            self._status.setText("请先从顶部「打开」加载数据集。")
        else:
            self._status.setText(
                f"已加载数据集「{dataset.name}」· 当前模块界面尚未接入 "
                "— 运行 /wire 可以自动接上。"
            )
