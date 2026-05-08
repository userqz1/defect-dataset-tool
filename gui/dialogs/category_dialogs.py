"""Dialogs for category management (rename / merge / split)."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QListWidget, QListWidgetItem
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CheckBox,
    ComboBox,
    LineEdit,
    PushButton,
    SubtitleLabel,
)

from core.models import ImageInfo
from gui.dialogs.op_dialogs import _OpDialogBase
from gui.theme import T


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
    """Split images out of a source category into a new one.

    Review #13: the old dialog only asked for the new name and trusted
    the caller to have populated the grid's selection beforehand — users
    who right-clicked the category tree got an unhelpful "please select
    images in the grid" error after committing to "拆分". Now the dialog
    embeds a checkable list of the source category's images so it's
    self-sufficient no matter where the user launched it from.
    """

    def __init__(self, source: str, images: list[ImageInfo],
                 existing: list[str], preselected: list[ImageInfo] | None = None,
                 parent=None) -> None:
        super().__init__("拆分类别", parent)
        self._existing = existing
        self._images = list(images)
        preselected_paths = {str(i.path) for i in (preselected or [])}

        self.widget.setMinimumWidth(480)

        self.viewLayout.addWidget(
            BodyLabel(
                f"从 \"{source}\"（{len(self._images):,} 张）选择要拆出的图片",
                self,
            )
        )

        # Check-all helper row
        tools_row = QHBoxLayout()
        tools_row.setSpacing(T.GAP)
        # CLAUDE.md gotcha: don't setFixedWidth on Chinese-text buttons.
        # adjustSize() lets the buttons shrink-wrap their actual text +
        # padding, so they fit zh-2-char "全选" and en "Select all" alike.
        all_btn = PushButton("全选", self)
        all_btn.adjustSize()
        all_btn.clicked.connect(self._select_all)
        none_btn = PushButton("清空", self)
        none_btn.adjustSize()
        none_btn.clicked.connect(self._select_none)
        tools_row.addWidget(all_btn)
        tools_row.addWidget(none_btn)
        tools_row.addStretch(1)
        self._counter = CaptionLabel("已选 0", self)
        tools_row.addWidget(self._counter)
        self.viewLayout.addLayout(tools_row)

        self.list = QListWidget(self)
        self.list.setMaximumHeight(280)
        for img in self._images:
            item = QListWidgetItem(img.path.name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            pre = str(img.path) in preselected_paths
            item.setCheckState(Qt.CheckState.Checked if pre else Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, img)
            self.list.addItem(item)
        self.list.itemChanged.connect(lambda _i: self._validate())
        self.viewLayout.addWidget(self.list)

        self.name_edit = LineEdit(self)
        self.name_edit.setPlaceholderText("输入新类别名称")
        self._add_row("新类别名称", self.name_edit)

        self.yesButton.setText("拆分")
        self.cancelButton.setText("取消")
        self.yesButton.setEnabled(False)
        self.name_edit.textChanged.connect(lambda _t: self._validate())
        self._validate()

    def _select_all(self) -> None:
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(Qt.CheckState.Checked)

    def _select_none(self) -> None:
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(Qt.CheckState.Unchecked)

    def _validate(self) -> None:
        name = self.name_edit.text().strip()
        name_ok = bool(name) and "/" not in name and "\\" not in name \
                  and name not in self._existing
        checked = sum(
            1 for i in range(self.list.count())
            if self.list.item(i).checkState() == Qt.CheckState.Checked
        )
        self._counter.setText(f"已选 {checked}")
        self.yesButton.setEnabled(name_ok and checked > 0)

    def new_name(self) -> str:
        return self.name_edit.text().strip()

    def selected_images(self) -> list[ImageInfo]:
        """ImageInfos the user ticked in the list widget."""
        out: list[ImageInfo] = []
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                out.append(item.data(Qt.ItemDataRole.UserRole))
        return out
