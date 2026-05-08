"""Preset picker — used by 项目管理 to switch a project's annotation preset.

Mirrors the preset card grid in :mod:`gui.dialogs.project_dialogs` but
without name / directory input — the project already exists.  Picking
a non-custom preset re-applies its task_type + caps via
:func:`core.project.apply_preset` upstream.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QGridLayout, QVBoxLayout
from qfluentwidgets import (
    CaptionLabel,
    MessageBoxBase,
    StrongBodyLabel,
    SubtitleLabel,
)

from core.annotation_preset import CUSTOM_ID, PRESETS, AnnotationPreset
from gui.theme import T


class _PresetCard(QFrame):
    """Selectable preset card. Slim copy of project_dialogs._PresetCard."""

    def __init__(self, preset: AnnotationPreset | None,
                 display_name: str, description: str,
                 parent=None) -> None:
        super().__init__(parent)
        self.preset = preset
        self.preset_id = preset.id if preset is not None else CUSTOM_ID
        self.setObjectName("formatCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # See note in project_dialogs._PresetCard — fixed width clips
        # the longer VLM preset descriptions in CJK.
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

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        self._name_label.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)
        self._name_label.style().unpolish(self._name_label)
        self._name_label.style().polish(self._name_label)


class PresetPickerDialog(MessageBoxBase):
    """Dialog for changing an existing project's annotation preset."""

    def __init__(self, current_preset_id: str = "",
                 parent=None) -> None:
        super().__init__(parent=parent)
        self._selected_preset_id: str = current_preset_id or CUSTOM_ID

        self.titleLabel = SubtitleLabel("更改数据集预设", self)
        self.viewLayout.addWidget(self.titleLabel)
        self.widget.setMinimumWidth(720)

        hint = CaptionLabel(
            "切换预设会改写当前项目的任务类型与能力开关,已有标注不受影响。")
        hint.setWordWrap(True)
        self.viewLayout.addWidget(hint)
        self.viewLayout.addSpacing(T.GAP)

        grid = QGridLayout()
        grid.setSpacing(T.GAP)
        self._cards: list[_PresetCard] = []
        per_row = 3
        for i, preset in enumerate(PRESETS):
            card = _PresetCard(preset, preset.display_name, preset.description)
            card.mousePressEvent = lambda e, c=card: self._on_card_click(c)
            self._cards.append(card)
            grid.addWidget(card, i // per_row, i % per_row)
        custom_card = _PresetCard(
            None, "自定义", "自己挑任务类型 + 能力开关")
        custom_card.mousePressEvent = (
            lambda e, c=custom_card: self._on_card_click(c))
        self._cards.append(custom_card)
        idx = len(PRESETS)
        grid.addWidget(custom_card, idx // per_row, idx % per_row)
        self.viewLayout.addLayout(grid)

        self.yesButton.setText("应用")
        self.cancelButton.setText("取消")

        # Pre-select the current preset.
        for card in self._cards:
            if card.preset_id == self._selected_preset_id:
                card.set_selected(True)
                break

    def selected_preset_id(self) -> str:
        return self._selected_preset_id

    def _on_card_click(self, card: _PresetCard) -> None:
        for c in self._cards:
            c.set_selected(c is card)
        self._selected_preset_id = card.preset_id
