"""Parameter dialogs for batch operations.

All dialogs are built on `qfluentwidgets.MessageBoxBase` so they share the
same Fluent look as the rest of the app. Each dialog only collects parameters
and exposes them as `.options()`; the caller runs the actual op via BatchWorker.
"""
from __future__ import annotations

from qfluentwidgets import (
    BodyLabel,
    CheckBox,
    ComboBox,
    LineEdit,
    MessageBoxBase,
    SpinBox,
    SubtitleLabel,
)

from core.convert import SUPPORTED_FORMATS, ConvertOptions
from core.transform import CropOptions, FlipOptions, ResizeOptions, RotateOptions


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


class ConvertDialog(_OpDialogBase):
    def __init__(self, parent=None) -> None:
        super().__init__(self.tr("格式转换"), parent)
        self.fmt = ComboBox(self)
        self.fmt.addItems(sorted(SUPPORTED_FORMATS.keys()))
        self.fmt.setCurrentText(".png")
        self._add_row(self.tr("目标格式"), self.fmt)

        self.quality = SpinBox(self)
        self.quality.setRange(1, 100)
        self.quality.setValue(92)
        self._add_row(self.tr("JPEG 质量"), self.quality)

        self.delete_original = CheckBox(self.tr("转换后删除原文件"), self)
        self.viewLayout.addWidget(self.delete_original)
        self.overwrite = CheckBox(self.tr("覆盖已存在文件"), self)
        self.viewLayout.addWidget(self.overwrite)

    def options(self) -> ConvertOptions:
        return ConvertOptions(
            target_ext=self.fmt.currentText(),
            quality=self.quality.value(),
            delete_original=self.delete_original.isChecked(),
            overwrite=self.overwrite.isChecked(),
        )


class ResizeDialog(_OpDialogBase):
    def __init__(self, parent=None) -> None:
        super().__init__(self.tr("缩放"), parent)
        self.w = SpinBox(self); self.w.setRange(0, 20000); self.w.setValue(1024)
        self.h = SpinBox(self); self.h.setRange(0, 20000); self.h.setValue(0)
        self._add_row(self.tr("宽 (0=自动)"), self.w)
        self._add_row(self.tr("高 (0=自动)"), self.h)
        self.keep = CheckBox(self.tr("保持纵横比"), self); self.keep.setChecked(True)
        self.viewLayout.addWidget(self.keep)

    def options(self) -> ResizeOptions:
        return ResizeOptions(
            width=self.w.value() or None,
            height=self.h.value() or None,
            keep_ratio=self.keep.isChecked(),
        )


class CropDialog(_OpDialogBase):
    def __init__(self, parent=None) -> None:
        super().__init__(self.tr("裁剪"), parent)
        self.x = SpinBox(self); self.x.setRange(0, 20000)
        self.y = SpinBox(self); self.y.setRange(0, 20000)
        self.w = SpinBox(self); self.w.setRange(1, 20000); self.w.setValue(512)
        self.h = SpinBox(self); self.h.setRange(1, 20000); self.h.setValue(512)
        self._add_row("X", self.x)
        self._add_row("Y", self.y)
        self._add_row(self.tr("宽"), self.w)
        self._add_row(self.tr("高"), self.h)

    def options(self) -> CropOptions:
        return CropOptions(
            x=self.x.value(), y=self.y.value(),
            width=self.w.value(), height=self.h.value(),
        )


class RotateDialog(_OpDialogBase):
    def __init__(self, parent=None) -> None:
        super().__init__(self.tr("旋转"), parent)
        self.angle = ComboBox(self)
        self.angle.addItems(["90", "180", "270"])
        self._add_row(self.tr("角度 (顺时针)"), self.angle)

    def options(self) -> RotateOptions:
        return RotateOptions(angle=int(self.angle.currentText()))  # type: ignore[arg-type]


class FlipDialog(_OpDialogBase):
    def __init__(self, parent=None) -> None:
        super().__init__(self.tr("翻转"), parent)
        self.dir = ComboBox(self)
        self.dir.addItems(["horizontal", "vertical"])
        self._add_row(self.tr("方向"), self.dir)

    def options(self) -> FlipOptions:
        return FlipOptions(direction=self.dir.currentText())  # type: ignore[arg-type]


class RenameDialog(_OpDialogBase):
    def __init__(self, parent=None) -> None:
        super().__init__(self.tr("批量重命名"), parent)
        self.pattern = LineEdit(self)
        self.pattern.setText("{cat}_{idx:04d}")
        self._add_row(self.tr("命名模板"), self.pattern)
        self.start = SpinBox(self); self.start.setRange(0, 100000); self.start.setValue(1)
        self._add_row(self.tr("起始编号"), self.start)
        from qfluentwidgets import CaptionLabel
        self.viewLayout.addWidget(
            CaptionLabel(self.tr("可用占位符: {cat} {idx} {stem}"), self)
        )


class MoveToCategoryDialog(_OpDialogBase):
    def __init__(self, categories: list[str], parent=None) -> None:
        super().__init__(self.tr("移动到类别"), parent)
        self.combo = ComboBox(self)
        self.combo.addItems(categories)
        self._add_row(self.tr("目标类别"), self.combo)

    def target(self) -> str:
        return self.combo.currentText()


class ProgressDialog(_OpDialogBase):
    """Fluent 风格的进度对话框（不可取消，由调用方关闭）。"""

    def __init__(self, title: str, parent=None) -> None:
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
