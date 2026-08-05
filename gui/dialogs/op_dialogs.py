"""Parameter dialogs for batch operations.

All dialogs are built on `qfluentwidgets.MessageBoxBase` so they share the
same Fluent look as the rest of the app. Each dialog only collects parameters
and exposes them as `.options()`; the caller runs the actual op via BatchWorker.
"""
from __future__ import annotations

from qfluentwidgets import (
    BodyLabel,
    ComboBox,
    LineEdit,
    MessageBoxBase,
    SubtitleLabel,
)

class _OpDialogBase(MessageBoxBase):
    """共享的标题/表单基类。子类调用 _add_row 添加表单项。"""

    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent=parent)
        self.titleLabel = SubtitleLabel(title, self)
        self.viewLayout.addWidget(self.titleLabel)
        self.widget.setMinimumWidth(360)

    def _add_row(self, label: str, widget) -> None:
        self.viewLayout.addWidget(BodyLabel(label, self))
        self.viewLayout.addWidget(widget)


class MoveToCategoryDialog(_OpDialogBase):
    def __init__(self, categories: list[str], parent=None) -> None:
        super().__init__(self.tr("移动到类别"), parent)
        self.combo = ComboBox(self)
        self.combo.addItems(categories)
        self._add_row(self.tr("目标类别"), self.combo)

    def target(self) -> str:
        return self.combo.currentText()


class ProgressDialog(_OpDialogBase):
    """Fluent 风格的进度对话框。

    Pass ``cancelable=True`` to show a working "取消" button and receive
    ``canceled`` via the dialog's signal. Default stays non-cancelable
    for ops that can't be safely interrupted (most batch ops that write
    files).
    """

    from PyQt6.QtCore import pyqtSignal as _pyqtSignal
    canceled = _pyqtSignal()

    def __init__(self, title: str, parent=None, cancelable: bool = False) -> None:
        super().__init__(title, parent)
        from qfluentwidgets import IndeterminateProgressBar, ProgressBar

        self.label = BodyLabel("", self)
        self.viewLayout.addWidget(self.label)

        self.bar = ProgressBar(self)
        self.bar.setRange(0, 0)
        self.viewLayout.addWidget(self.bar)

        self.indet = IndeterminateProgressBar(self)
        self.viewLayout.addWidget(self.indet)

        self.yesButton.hide()
        if cancelable:
            self.cancelButton.setText("取消")
            self.cancelButton.clicked.connect(self.canceled.emit)
        else:
            self.cancelButton.hide()
            self.buttonGroup.setFixedHeight(0)
        self.widget.setMinimumWidth(420)
        self._has_total = False

    def set_progress(self, done: int, total: int, name: str) -> None:
        if total > 0:
            if not self._has_total:
                self.indet.hide()
                self._has_total = True
            self.bar.setRange(0, total)
            self.bar.setValue(done)
        self.label.setText(f"{done}/{total}  {name}" if total else name)


class FailureDetailDialog(_OpDialogBase):
    """显示批量操作的失败明细。"""

    def __init__(self, ok: int, fail: int, details: str, parent=None) -> None:
        super().__init__(parent.tr("完成（有失败）") if parent else "完成（有失败）", parent)
        from qfluentwidgets import TextEdit

        msg = BodyLabel(
            self.tr("成功 {ok} 个，失败 {fail} 个").format(ok=ok, fail=fail), self
        )
        self.viewLayout.addWidget(msg)
        self.detail = TextEdit(self)
        self.detail.setReadOnly(True)
        self.detail.setPlainText(details)
        self.detail.setMinimumSize(560, 320)
        self.viewLayout.addWidget(self.detail)
        self.widget.setMinimumWidth(620)
        self.cancelButton.hide()


class ShortcutsDialog(_OpDialogBase):
    """详情页快捷键速查表。"""

    SHORTCUTS = [
        ("A  /  ←", "上一张"),
        ("D  /  →", "下一张"),
        ("H", "显示 / 隐藏标注"),
        ("E", "进入 / 退出编辑"),
        ("R", "矩形框"),
        ("P", "多边形"),
        ("K", "关键点"),
        ("Enter", "闭合多边形"),
        ("Del", "删除选中标注"),
        ("1 – 9", "把选中标注改为第 N 个类别"),
        ("Ctrl+S", "保存标注"),
        ("Ctrl+Z", "撤销形状编辑"),
        ("Tab", "下一张未完成"),
        ("滚轮", "缩放"),
        ("拖动", "平移"),
        ("Esc", "返回浏览"),
    ]

    def __init__(self, parent=None) -> None:
        super().__init__("快捷键", parent)
        from PyQt6.QtWidgets import QGridLayout
        from qfluentwidgets import CaptionLabel, StrongBodyLabel

        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(8)
        for i, (key, desc) in enumerate(self.SHORTCUTS):
            grid.addWidget(StrongBodyLabel(key, self), i, 0)
            grid.addWidget(CaptionLabel(desc, self), i, 1)
        self.viewLayout.addLayout(grid)
        self.cancelButton.hide()
        self.yesButton.setText("知道了")
        self.widget.setMinimumWidth(320)


class NewProjectDialog(_OpDialogBase):
    """Dialog shown when opening a directory that has no project.json yet."""

    def __init__(self, default_name: str, parent=None) -> None:
        super().__init__("新建项目", parent)
        from core.task_types import TASK_REGISTRY

        self.name_edit = LineEdit(self)
        self.name_edit.setText(default_name)
        self._add_row("项目名称", self.name_edit)

        self.task_combo = ComboBox(self)
        self._task_types = list(TASK_REGISTRY.values())
        self.task_combo.addItems([t.display_name for t in self._task_types])
        # Default to 目标检测
        for i, t in enumerate(self._task_types):
            if t.task_type.value == "object_detection":
                self.task_combo.setCurrentIndex(i)
                break
        self._add_row("任务类型", self.task_combo)

        self.widget.setMinimumWidth(400)

    def options(self):
        idx = self.task_combo.currentIndex()
        task_type = self._task_types[idx].task_type
        return self.name_edit.text().strip() or "未命名", task_type
