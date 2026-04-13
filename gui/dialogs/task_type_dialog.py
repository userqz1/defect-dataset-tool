"""Task type selection dialog — shown when opening a dataset for the first time."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QVBoxLayout
from qfluentwidgets import (
    BodyLabel,
    FluentIcon as FIF,
    MessageBoxBase,
    StrongBodyLabel,
    SubtitleLabel,
)

from core.task_types import TASK_REGISTRY, TaskType
from gui.theme import T

# Icon mapping for each task type
_TASK_ICONS = {
    TaskType.CLASSIFICATION: FIF.TAG,
    TaskType.MULTI_LABEL: FIF.BOOK_SHELF,
    TaskType.ANOMALY: FIF.SEARCH,
    TaskType.DETECTION: FIF.ZOOM,
    TaskType.ORIENTED_DET: FIF.ROTATE,
    TaskType.SEMANTIC_SEG: FIF.PALETTE,
    TaskType.INSTANCE_SEG: FIF.TILES,
    TaskType.KEYPOINT: FIF.PIN,
    TaskType.IMAGE_PAIR: FIF.SYNC,
}


class _TaskCard(QFrame):
    """Selectable card for a task type."""

    def __init__(self, task_type: TaskType, display_name: str,
                 parent=None) -> None:
        super().__init__(parent)
        self.task_type = task_type
        self.setObjectName("formatCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(160, 60)
        self.setProperty("selected", False)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(T.PAD_LG, T.GAP, T.PAD_LG, T.GAP)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        name_label = StrongBodyLabel(display_name)
        name_label.setObjectName("formatCardName")
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(name_label)
        self._name_label = name_label

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        self._name_label.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)
        self._name_label.style().unpolish(self._name_label)
        self._name_label.style().polish(self._name_label)


class TaskTypeDialog(MessageBoxBase):
    """Grid dialog for selecting a CV task type."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent=parent)
        self._selected: TaskType | None = None

        self.titleLabel = SubtitleLabel("选择任务类型", self)
        self.viewLayout.addWidget(self.titleLabel)
        self.widget.setMinimumWidth(560)

        # Grid of task type cards
        grid = QGridLayout()
        grid.setSpacing(T.GAP)
        self._cards: list[_TaskCard] = []

        for i, (tt, info) in enumerate(TASK_REGISTRY.items()):
            card = _TaskCard(tt, info.display_name, self)
            card.mousePressEvent = lambda e, c=card: self._on_card_click(c)
            self._cards.append(card)
            grid.addWidget(card, i // 3, i % 3)

        self.viewLayout.addLayout(grid)

        self.yesButton.setText("确定")
        self.cancelButton.setText("取消")
        self.yesButton.setEnabled(False)

        # Pre-select DETECTION as default
        for card in self._cards:
            if card.task_type == TaskType.DETECTION:
                self._on_card_click(card)
                break

    def _on_card_click(self, card: _TaskCard) -> None:
        for c in self._cards:
            c.set_selected(c is card)
        self._selected = card.task_type
        self.yesButton.setEnabled(True)

    def selected_task_type(self) -> TaskType | None:
        return self._selected
