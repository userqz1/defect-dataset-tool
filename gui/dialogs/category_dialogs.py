"""Dialogs for category management (rename / merge / split)."""
from __future__ import annotations

from qfluentwidgets import (
    BodyLabel,
    CheckBox,
    ComboBox,
    LineEdit,
    SubtitleLabel,
)

from gui.dialogs.op_dialogs import _OpDialogBase


class RenameCategoryDialog(_OpDialogBase):
    """Rename a single category."""

    def __init__(self, current_name: str, existing: list[str], parent=None) -> None:
        super().__init__("重命名类别", parent)
        self._existing = [n for n in existing if n != current_name]

        self.name_edit = LineEdit(self)
        self.name_edit.setText(current_name)
        self.name_edit.selectAll()
        self._add_row("新名称", self.name_edit)

        self.yesButton.setText("确定")
        self.cancelButton.setText("取消")
        self.yesButton.setEnabled(False)
        self.name_edit.textChanged.connect(self._validate)

    def _validate(self, text: str) -> None:
        text = text.strip()
        valid = bool(text) and "/" not in text and "\\" not in text and text not in self._existing
        self.yesButton.setEnabled(valid)

    def new_name(self) -> str:
        return self.name_edit.text().strip()


class MergeCategoriesDialog(_OpDialogBase):
    """Merge selected categories into a target."""

    def __init__(self, categories: list[str], current: str | None = None, parent=None) -> None:
        super().__init__("合并类别", parent)
        self._categories = categories

        self.viewLayout.addWidget(BodyLabel("选择要合并的源类别：", self))
        self._checkboxes: list[CheckBox] = []
        for name in categories:
            cb = CheckBox(name, self)
            if name == current:
                cb.setChecked(True)
            cb.stateChanged.connect(self._validate)
            self._checkboxes.append(cb)
            self.viewLayout.addWidget(cb)

        self.target_combo = ComboBox(self)
        self.target_combo.addItems(categories)
        if current and current in categories:
            self.target_combo.setCurrentText(current)
        self._add_row("合并到目标类别", self.target_combo)

        self.yesButton.setText("合并")
        self.cancelButton.setText("取消")
        self.yesButton.setEnabled(False)

    def _validate(self) -> None:
        checked = [cb for cb in self._checkboxes if cb.isChecked()]
        self.yesButton.setEnabled(len(checked) >= 1)

    def sources(self) -> list[str]:
        return [cb.text() for cb in self._checkboxes if cb.isChecked()]

    def target(self) -> str:
        return self.target_combo.currentText()


class SplitCategoryDialog(_OpDialogBase):
    """Split selected images into a new category."""

    def __init__(self, source: str, count: int, existing: list[str], parent=None) -> None:
        super().__init__("拆分类别", parent)
        self._existing = existing

        self.viewLayout.addWidget(
            BodyLabel(f"从 \"{source}\" 拆出 {count} 张图片到新类别", self)
        )

        self.name_edit = LineEdit(self)
        self.name_edit.setPlaceholderText("输入新类别名称")
        self._add_row("新类别名称", self.name_edit)

        self.yesButton.setText("拆分")
        self.cancelButton.setText("取消")
        self.yesButton.setEnabled(False)
        self.name_edit.textChanged.connect(self._validate)

    def _validate(self, text: str) -> None:
        text = text.strip()
        valid = bool(text) and "/" not in text and "\\" not in text and text not in self._existing
        self.yesButton.setEnabled(valid)

    def new_name(self) -> str:
        return self.name_edit.text().strip()
