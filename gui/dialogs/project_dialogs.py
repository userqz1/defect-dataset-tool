"""Project creation dialog — collect name, root directory, and dataset preset.

Preset replaces the previous "task type + extra field checkboxes" surface:
the user picks one card describing the dataset they're building (YOLO 检测,
LLaVA VLM, ImageFolder 分类, …) and the matching task_type is applied
automatically.  ``CUSTOM`` is a fallback card that reveals the
legacy task-type grid for advanced cases.
"""
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
    CaptionLabel,
    LineEdit,
    MessageBoxBase,
    PushButton,
    StrongBodyLabel,
    SubtitleLabel,
    FluentIcon as FIF,
)

from core.annotation_preset import CUSTOM_ID, PRESETS, AnnotationPreset
from core.task_types import TASK_REGISTRY, TaskType
from gui.theme import T


class _PresetCard(QFrame):
    """Selectable card describing an :class:`AnnotationPreset`."""

    def __init__(self, preset: AnnotationPreset | None,
                 display_name: str, description: str,
                 parent=None) -> None:
        super().__init__(parent)
        # ``preset`` is None for the synthetic "自定义" card.
        self.preset = preset
        self.preset_id = preset.id if preset is not None else CUSTOM_ID
        self.setObjectName("formatCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Min-width only — `setFixedWidth` on a CJK-bearing card clips
        # longer descriptions like "caption + 多轮对话 + 区域描述,导出
        # 为 ms-swift". `setWordWrap(True)` lets overflow wrap to a 2nd
        # line; the grid then equalises every card's height per row.
        self.setMinimumWidth(240)
        self.setProperty("selected", False)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(T.PAD_LG, T.GAP, T.PAD_LG, T.GAP)
        lay.setSpacing(2)

        name_label = StrongBodyLabel(display_name)
        name_label.setObjectName("formatCardName")
        name_label.setWordWrap(True)
        lay.addWidget(name_label)
        self._name_label = name_label

        desc_label = CaptionLabel(description)
        desc_label.setObjectName("formatCardDesc")
        desc_label.setWordWrap(True)
        lay.addWidget(desc_label)
        self._desc_label = desc_label

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        self._name_label.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)
        self._name_label.style().unpolish(self._name_label)
        self._name_label.style().polish(self._name_label)


class _TaskCard(QFrame):
    """Selectable task-type card — only shown under the 自定义 preset."""

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
        # Default to YOLO detection — the most common pick on this tool.
        self._selected_preset_id: str = (
            PRESETS[0].id if PRESETS else CUSTOM_ID)
        self._selected_task: TaskType = TaskType.DETECTION
        self._root: Path | None = None

        self.titleLabel = SubtitleLabel("新建项目", self)
        self.viewLayout.addWidget(self.titleLabel)
        self.widget.setMinimumWidth(720)

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
        # CLAUDE.md gotcha: no setFixedWidth on icon+text buttons —
        # icon eats button space; en/de/fr labels easily exceed 100px.
        browse_btn = PushButton("浏览…")
        browse_btn.setIcon(FIF.FOLDER)
        browse_btn.clicked.connect(self._browse_dir)
        dir_row.addWidget(browse_btn)
        self.viewLayout.addLayout(dir_row)

        # -- Preset grid --
        self.viewLayout.addSpacing(T.GAP)
        self.viewLayout.addWidget(BodyLabel("数据集预设"))

        preset_grid = QGridLayout()
        preset_grid.setSpacing(T.GAP)
        self._preset_cards: list[_PresetCard] = []
        per_row = 3
        for i, preset in enumerate(PRESETS):
            card = _PresetCard(preset, preset.display_name, preset.description)
            card.mousePressEvent = lambda e, c=card: self._on_preset_click(c)
            self._preset_cards.append(card)
            preset_grid.addWidget(card, i // per_row, i % per_row)
        # Synthetic 自定义 card last
        custom_card = _PresetCard(
            None, "自定义", "自己挑任务类型 + 能力开关")
        custom_card.mousePressEvent = (
            lambda e, c=custom_card: self._on_preset_click(c))
        self._preset_cards.append(custom_card)
        idx = len(PRESETS)
        preset_grid.addWidget(custom_card, idx // per_row, idx % per_row)
        self.viewLayout.addLayout(preset_grid)

        # -- Custom-only: task type grid (hidden unless 自定义 picked) --
        self._custom_frame = QFrame()
        cf_lay = QVBoxLayout(self._custom_frame)
        cf_lay.setContentsMargins(0, T.GAP, 0, 0)
        cf_lay.setSpacing(T.GAP)
        cf_lay.addWidget(BodyLabel("任务类型"))
        task_grid = QGridLayout()
        task_grid.setSpacing(T.GAP)
        self._task_cards: list[_TaskCard] = []
        for i, (tt, info) in enumerate(TASK_REGISTRY.items()):
            tcard = _TaskCard(tt, info.display_name)
            tcard.mousePressEvent = (
                lambda e, c=tcard: self._on_task_click(c))
            self._task_cards.append(tcard)
            task_grid.addWidget(tcard, i // 3, i % 3)
        cf_lay.addLayout(task_grid)
        self._custom_frame.setVisible(False)
        self.viewLayout.addWidget(self._custom_frame)

        # Buttons
        self.yesButton.setText("创建")
        self.cancelButton.setText("取消")
        self.yesButton.setEnabled(False)

        # Pre-select the default preset
        for card in self._preset_cards:
            if card.preset_id == self._selected_preset_id:
                self._on_preset_click(card)
                break
        # And pre-select detection in the task grid (only visible under 自定义)
        for tcard in self._task_cards:
            if tcard.task_type == TaskType.DETECTION:
                self._on_task_click(tcard)
                break

        # Validate on input
        self._name_edit.textChanged.connect(self._validate)

    # -- Accessors --

    def project_name(self) -> str:
        return self._name_edit.text().strip()

    def root_path(self) -> Path | None:
        return self._root

    def selected_preset_id(self) -> str:
        return self._selected_preset_id

    def selected_task_type(self) -> TaskType:
        # Returned only when preset == custom; otherwise the preset
        # determines task_type and core.create_project will use that.
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

    def _on_preset_click(self, card: _PresetCard) -> None:
        for c in self._preset_cards:
            c.set_selected(c is card)
        self._selected_preset_id = card.preset_id
        # Reveal the task-type grid only when 自定义 is picked.
        self._custom_frame.setVisible(card.preset_id == CUSTOM_ID)
        self._validate()

    def _on_task_click(self, card: _TaskCard) -> None:
        for c in self._task_cards:
            c.set_selected(c is card)
        self._selected_task = card.task_type
        self._validate()

    def _validate(self, _text: str = "") -> None:
        ok = bool(self._name_edit.text().strip() and self._root)
        self.yesButton.setEnabled(ok)
