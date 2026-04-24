"""Project creation dialog — collect name, root directory, and task type."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QVBoxLayout,
)
from qfluentwidgets import (
    BodyLabel,
    LineEdit,
    MessageBoxBase,
    PushButton,
    StrongBodyLabel,
    SubtitleLabel,
    FluentIcon as FIF,
)

from core.task_types import TASK_REGISTRY, TaskType
from gui.theme import T


class _TaskCard(QFrame):
    """Selectable card for a task type (reused from task_type_dialog)."""

    def __init__(self, task_type: TaskType, display_name: str,
                 parent=None) -> None:
        super().__init__(parent)
        self.task_type = task_type
        self.setObjectName("formatCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(160, 52)
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


class CreateProjectDialog(MessageBoxBase):
    """Dialog for creating a new empty project."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent=parent)
        self._selected_task: TaskType = TaskType.DETECTION
        self._root: Path | None = None

        self.titleLabel = SubtitleLabel("新建项目", self)
        self.viewLayout.addWidget(self.titleLabel)
        self.widget.setMinimumWidth(560)

        # -- Project name --
        self.viewLayout.addWidget(BodyLabel("项目名称"))
        self._name_edit = LineEdit(self)
        self._name_edit.setPlaceholderText("输入项目名称")
        self._name_edit.setClearButtonEnabled(True)
        self.viewLayout.addWidget(self._name_edit)

        # -- Root directory --
        self.viewLayout.addSpacing(T.GAP)
        self.viewLayout.addWidget(BodyLabel("项目目录"))
        dir_row = QHBoxLayout()
        self._dir_edit = LineEdit(self)
        self._dir_edit.setPlaceholderText("选择一个空目录作为项目根")
        self._dir_edit.setReadOnly(True)
        dir_row.addWidget(self._dir_edit)
        browse_btn = PushButton("浏览…")
        browse_btn.setIcon(FIF.FOLDER)
        browse_btn.setFixedWidth(100)
        browse_btn.clicked.connect(self._browse_dir)
        dir_row.addWidget(browse_btn)
        self.viewLayout.addLayout(dir_row)

        # -- Task type grid --
        self.viewLayout.addSpacing(T.GAP)
        self.viewLayout.addWidget(BodyLabel("任务类型"))

        grid = QGridLayout()
        grid.setSpacing(T.GAP)
        self._cards: list[_TaskCard] = []
        for i, (tt, info) in enumerate(TASK_REGISTRY.items()):
            card = _TaskCard(tt, info.display_name, self)
            card.mousePressEvent = lambda e, c=card: self._on_card_click(c)
            self._cards.append(card)
            grid.addWidget(card, i // 3, i % 3)
        self.viewLayout.addLayout(grid)

        # Buttons
        self.yesButton.setText("创建")
        self.cancelButton.setText("取消")
        self.yesButton.setEnabled(False)

        # Pre-select DETECTION
        for card in self._cards:
            if card.task_type == TaskType.DETECTION:
                self._on_card_click(card)
                break

        # Validate on input
        self._name_edit.textChanged.connect(self._validate)

    # -- Accessors --

    def project_name(self) -> str:
        return self._name_edit.text().strip()

    def root_path(self) -> Path | None:
        return self._root

    def selected_task_type(self) -> TaskType:
        return self._selected_task

    # -- Internals --

    def _browse_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(
            self, "选择项目目录", str(Path.home()),
        )
        if d:
            self._root = Path(d)
            self._dir_edit.setText(d)
            if not self._name_edit.text().strip():
                self._name_edit.setText(self._root.name)
            self._validate()

    def _on_card_click(self, card: _TaskCard) -> None:
        for c in self._cards:
            c.set_selected(c is card)
        self._selected_task = card.task_type
        self._validate()

    def _validate(self, _text: str = "") -> None:
        ok = bool(self._name_edit.text().strip() and self._root)
        self.yesButton.setEnabled(ok)
