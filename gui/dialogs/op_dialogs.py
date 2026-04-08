"""Parameter dialogs for batch operations.

Each dialog only collects parameters and exposes them as attributes; running
the actual operation is the caller's responsibility (via BatchWorker).
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
)

from core.convert import SUPPORTED_FORMATS, ConvertOptions
from core.transform import CropOptions, FlipOptions, ResizeOptions, RotateOptions


def _wrap(form: QFormLayout) -> QDialog:
    dlg = QDialog()
    layout = QVBoxLayout(dlg)
    layout.addLayout(form)
    btns = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    btns.accepted.connect(dlg.accept)
    btns.rejected.connect(dlg.reject)
    layout.addWidget(btns)
    return dlg


class ConvertDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("格式转换"))
        form = QFormLayout()
        self.fmt = QComboBox()
        self.fmt.addItems(sorted(SUPPORTED_FORMATS.keys()))
        self.fmt.setCurrentText(".png")
        form.addRow(self.tr("目标格式"), self.fmt)
        self.quality = QSpinBox()
        self.quality.setRange(1, 100)
        self.quality.setValue(92)
        form.addRow(self.tr("JPEG 质量"), self.quality)
        self.delete_original = QCheckBox(self.tr("转换后删除原文件"))
        form.addRow("", self.delete_original)
        self.overwrite = QCheckBox(self.tr("覆盖已存在文件"))
        form.addRow("", self.overwrite)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def options(self) -> ConvertOptions:
        return ConvertOptions(
            target_ext=self.fmt.currentText(),
            quality=self.quality.value(),
            delete_original=self.delete_original.isChecked(),
            overwrite=self.overwrite.isChecked(),
        )


class ResizeDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("缩放"))
        form = QFormLayout()
        self.w = QSpinBox(); self.w.setRange(0, 20000); self.w.setValue(1024)
        self.h = QSpinBox(); self.h.setRange(0, 20000); self.h.setValue(0)
        self.keep = QCheckBox(self.tr("保持纵横比")); self.keep.setChecked(True)
        form.addRow(self.tr("宽 (0=自动)"), self.w)
        form.addRow(self.tr("高 (0=自动)"), self.h)
        form.addRow("", self.keep)
        layout = QVBoxLayout(self); layout.addLayout(form)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def options(self) -> ResizeOptions:
        return ResizeOptions(
            width=self.w.value() or None,
            height=self.h.value() or None,
            keep_ratio=self.keep.isChecked(),
        )


class CropDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("裁剪"))
        form = QFormLayout()
        self.x = QSpinBox(); self.x.setRange(0, 20000)
        self.y = QSpinBox(); self.y.setRange(0, 20000)
        self.w = QSpinBox(); self.w.setRange(1, 20000); self.w.setValue(512)
        self.h = QSpinBox(); self.h.setRange(1, 20000); self.h.setValue(512)
        form.addRow("X", self.x)
        form.addRow("Y", self.y)
        form.addRow(self.tr("宽"), self.w)
        form.addRow(self.tr("高"), self.h)
        layout = QVBoxLayout(self); layout.addLayout(form)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def options(self) -> CropOptions:
        return CropOptions(
            x=self.x.value(), y=self.y.value(),
            width=self.w.value(), height=self.h.value(),
        )


class RotateDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("旋转"))
        form = QFormLayout()
        self.angle = QComboBox()
        self.angle.addItems(["90", "180", "270"])
        form.addRow(self.tr("角度 (顺时针)"), self.angle)
        layout = QVBoxLayout(self); layout.addLayout(form)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def options(self) -> RotateOptions:
        return RotateOptions(angle=int(self.angle.currentText()))  # type: ignore[arg-type]


class FlipDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("翻转"))
        form = QFormLayout()
        self.dir = QComboBox()
        self.dir.addItems(["horizontal", "vertical"])
        form.addRow(self.tr("方向"), self.dir)
        layout = QVBoxLayout(self); layout.addLayout(form)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def options(self) -> FlipOptions:
        return FlipOptions(direction=self.dir.currentText())  # type: ignore[arg-type]


class RenameDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("批量重命名"))
        form = QFormLayout()
        self.pattern = QLineEdit("{cat}_{idx:04d}")
        self.start = QSpinBox(); self.start.setRange(0, 100000); self.start.setValue(1)
        form.addRow(self.tr("命名模板"), self.pattern)
        form.addRow(self.tr("起始编号"), self.start)
        hint = QLabel(self.tr("可用占位符: {cat} {idx} {stem}"))
        hint.setStyleSheet("color: #9a958a; font-size: 11px;")
        layout = QVBoxLayout(self); layout.addLayout(form); layout.addWidget(hint)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        layout.addWidget(btns)
