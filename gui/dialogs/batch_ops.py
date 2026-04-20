"""Batch-operation parameter dialogs.

Each dialog collects parameters and exposes them via ``.options()``;
the caller drives execution through BatchRunner. No dialog touches the
filesystem directly.

Covers seven ops previously missing UI entry points (review stage 2):
  Resize / Crop / Rotate / Flip  (core.transform)
  Convert                         (core.convert)
  Augment                         (core.augment)
  Predict                         (core.predictor)
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFileDialog, QGridLayout, QHBoxLayout
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CheckBox,
    ComboBox,
    DoubleSpinBox,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    MessageBoxBase,
    PushButton,
    SpinBox,
    StrongBodyLabel,
    SubtitleLabel,
)

from core.convert import SUPPORTED_FORMATS, ConvertOptions
from core.transform import CropOptions, FlipOptions, ResizeOptions, RotateOptions
from gui.theme import T


# ============================================================
# Base: shared layout helpers
# ============================================================

class _BatchOpBase(MessageBoxBase):
    """Shared title + form layout + minimum width (420).

    Subclasses should call ``_add_row(label, widget)`` per parameter and
    implement ``options()`` returning the driver's expected Options type.
    """

    def __init__(self, title: str, subtitle: str | None = None, parent=None) -> None:
        super().__init__(parent=parent)
        self.titleLabel = SubtitleLabel(title, self)
        self.viewLayout.addWidget(self.titleLabel)
        if subtitle:
            self.viewLayout.addWidget(CaptionLabel(subtitle, self))
        self.widget.setMinimumWidth(420)
        self.yesButton.setText("开始")
        self.cancelButton.setText("取消")

    def _add_row(self, label: str, widget) -> None:
        self.viewLayout.addWidget(BodyLabel(label, self))
        self.viewLayout.addWidget(widget)


# ============================================================
# Transforms (core.transform)
# ============================================================

class ResizeDialog(_BatchOpBase):
    def __init__(self, n_images: int, parent=None) -> None:
        super().__init__("批量缩放", f"将对 {n_images:,} 张图片缩放,并同步更新标注坐标", parent)

        self.w = SpinBox(self)
        self.w.setRange(0, 20000); self.w.setValue(1024)
        self.h = SpinBox(self)
        self.h.setRange(0, 20000); self.h.setValue(0)
        self._add_row("宽度 (0 = 保持原始)", self.w)
        self._add_row("高度 (0 = 保持原始)", self.h)

        self.keep_ratio = CheckBox("保持宽高比", self)
        self.keep_ratio.setChecked(True)
        self.viewLayout.addWidget(self.keep_ratio)

        self.inplace = CheckBox("原地替换(否则生成 *_resized 副本)", self)
        self.viewLayout.addWidget(self.inplace)

    def options(self) -> ResizeOptions:
        return ResizeOptions(
            width=self.w.value() or None,
            height=self.h.value() or None,
            keep_ratio=self.keep_ratio.isChecked(),
            inplace=self.inplace.isChecked(),
        )


class CropDialog(_BatchOpBase):
    def __init__(self, n_images: int, parent=None) -> None:
        super().__init__("批量裁剪", f"从 {n_images:,} 张图片裁出矩形区域,标注坐标同步", parent)

        row = QGridLayout()
        row.setHorizontalSpacing(T.GAP_LG)
        row.setVerticalSpacing(T.GAP)
        self.x = SpinBox(self); self.x.setRange(0, 20000)
        self.y = SpinBox(self); self.y.setRange(0, 20000)
        self.w = SpinBox(self); self.w.setRange(1, 20000); self.w.setValue(512)
        self.h = SpinBox(self); self.h.setRange(1, 20000); self.h.setValue(512)
        row.addWidget(BodyLabel("X"), 0, 0); row.addWidget(self.x, 0, 1)
        row.addWidget(BodyLabel("Y"), 0, 2); row.addWidget(self.y, 0, 3)
        row.addWidget(BodyLabel("宽"), 1, 0); row.addWidget(self.w, 1, 1)
        row.addWidget(BodyLabel("高"), 1, 2); row.addWidget(self.h, 1, 3)
        self.viewLayout.addLayout(row)

        self.inplace = CheckBox("原地替换(否则生成 *_cropped 副本)", self)
        self.viewLayout.addWidget(self.inplace)

    def options(self) -> CropOptions:
        return CropOptions(
            x=self.x.value(), y=self.y.value(),
            width=self.w.value(), height=self.h.value(),
            inplace=self.inplace.isChecked(),
        )


class RotateDialog(_BatchOpBase):
    def __init__(self, n_images: int, parent=None) -> None:
        super().__init__("批量旋转", f"将 {n_images:,} 张图片顺时针旋转", parent)
        self.angle = ComboBox(self)
        self.angle.addItems(["90", "180", "270"])
        self._add_row("角度(顺时针,度)", self.angle)

        self.inplace = CheckBox("原地替换(否则生成 *_rotated 副本)", self)
        self.viewLayout.addWidget(self.inplace)

    def options(self) -> RotateOptions:
        return RotateOptions(
            angle=int(self.angle.currentText()),  # type: ignore[arg-type]
            inplace=self.inplace.isChecked(),
        )


class FlipDialog(_BatchOpBase):
    def __init__(self, n_images: int, parent=None) -> None:
        super().__init__("批量翻转", f"将 {n_images:,} 张图片水平或垂直翻转", parent)
        self.dir = ComboBox(self)
        self.dir.addItem("水平翻转", userData="horizontal")
        self.dir.addItem("垂直翻转", userData="vertical")
        self._add_row("方向", self.dir)

        self.inplace = CheckBox("原地替换(否则生成 *_flipped 副本)", self)
        self.viewLayout.addWidget(self.inplace)

    def options(self) -> FlipOptions:
        return FlipOptions(
            direction=self.dir.currentData(),  # type: ignore[arg-type]
            inplace=self.inplace.isChecked(),
        )


# ============================================================
# Format convert (core.convert)
# ============================================================

class ConvertDialog(_BatchOpBase):
    def __init__(self, n_images: int, parent=None) -> None:
        super().__init__(
            "格式转换",
            f"将 {n_images:,} 张图片转换为其他格式(JPEG/PNG/WEBP/BMP/TIFF)",
            parent,
        )
        self.fmt = ComboBox(self)
        self.fmt.addItems(sorted(SUPPORTED_FORMATS.keys()))
        self.fmt.setCurrentText(".png")
        self._add_row("目标格式", self.fmt)

        self.quality = SpinBox(self)
        self.quality.setRange(1, 100); self.quality.setValue(92)
        self._add_row("JPEG / WEBP 质量", self.quality)

        self.overwrite = CheckBox("覆盖已存在文件", self)
        self.viewLayout.addWidget(self.overwrite)

        self.delete_original = CheckBox("转换后删除原图到回收站", self)
        self.viewLayout.addWidget(self.delete_original)

    def options(self) -> ConvertOptions:
        return ConvertOptions(
            target_ext=self.fmt.currentText(),
            quality=self.quality.value(),
            overwrite=self.overwrite.isChecked(),
            delete_original=self.delete_original.isChecked(),
        )


# ============================================================
# Augment (core.augment)
# ============================================================

class AugmentDialog(_BatchOpBase):
    def __init__(self, n_images: int, parent=None) -> None:
        super().__init__(
            "数据增强",
            f"对 {n_images:,} 张图片生成新样本(几何+光度),标注同步",
            parent,
        )

        self.viewLayout.addWidget(StrongBodyLabel("几何变换", self))
        geo = QGridLayout(); geo.setSpacing(T.GAP)
        self.flip_h = CheckBox("水平翻转", self); self.flip_h.setChecked(True)
        self.flip_v = CheckBox("垂直翻转", self)
        self.rotate90 = CheckBox("旋转 90°", self)
        self.random_crop = CheckBox("随机裁剪", self)
        geo.addWidget(self.flip_h, 0, 0); geo.addWidget(self.flip_v, 0, 1)
        geo.addWidget(self.rotate90, 1, 0); geo.addWidget(self.random_crop, 1, 1)
        self.viewLayout.addLayout(geo)

        self.viewLayout.addWidget(StrongBodyLabel("光度变换", self))
        photo = QGridLayout(); photo.setSpacing(T.GAP)
        self.brightness = CheckBox("亮度", self); self.brightness.setChecked(True)
        self.contrast = CheckBox("对比度", self); self.contrast.setChecked(True)
        self.color = CheckBox("色彩抖动", self)
        self.blur = CheckBox("高斯模糊", self)
        self.noise = CheckBox("高斯噪声", self)
        photo.addWidget(self.brightness, 0, 0); photo.addWidget(self.contrast, 0, 1)
        photo.addWidget(self.color, 1, 0); photo.addWidget(self.blur, 1, 1)
        photo.addWidget(self.noise, 2, 0)
        self.viewLayout.addLayout(photo)

        # N per image + out_dir
        n_row = QHBoxLayout(); n_row.setSpacing(T.GAP)
        n_row.addWidget(BodyLabel("每张生成"))
        self.n_per = SpinBox(self); self.n_per.setRange(1, 50); self.n_per.setValue(3)
        self.n_per.setFixedWidth(100)
        n_row.addWidget(self.n_per)
        n_row.addWidget(BodyLabel("张"))
        n_row.addStretch(1)
        self.viewLayout.addLayout(n_row)

        out_row = QHBoxLayout(); out_row.setSpacing(T.GAP)
        out_row.addWidget(BodyLabel("输出目录"))
        self._dir_label = CaptionLabel("未选择", self)
        out_row.addWidget(self._dir_label, 1)
        pick = PushButton("选择", self); pick.setFixedWidth(70)
        pick.clicked.connect(self._pick_dir)
        out_row.addWidget(pick)
        self.viewLayout.addLayout(out_row)

        self._out_dir: Path | None = None
        self.yesButton.setEnabled(False)

    def _pick_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择输出目录", str(Path.home()))
        if not d:
            return
        self._out_dir = Path(d)
        text = str(self._out_dir)
        if len(text) > 48:
            text = "..." + text[-45:]
        self._dir_label.setText(text)
        self.yesButton.setEnabled(True)

    def options(self) -> dict[str, Any]:
        """Returns {'opts': AugmentOptions, 'out_dir': Path}."""
        from core.augment import AugmentOptions
        return {
            "opts": AugmentOptions(
                flip_h=self.flip_h.isChecked(),
                flip_v=self.flip_v.isChecked(),
                rotate90=self.rotate90.isChecked(),
                random_crop=self.random_crop.isChecked(),
                brightness=self.brightness.isChecked(),
                contrast=self.contrast.isChecked(),
                color_jitter=self.color.isChecked(),
                gauss_blur=self.blur.isChecked(),
                gauss_noise=self.noise.isChecked(),
                n_per_image=self.n_per.value(),
            ),
            "out_dir": self._out_dir,
        }


# ============================================================
# AI pre-labeling (core.predictor)
# ============================================================

class PredictDialog(_BatchOpBase):
    """Configure a YOLOv8 predictor for batch pre-labeling.

    Loads the model lazily when the user accepts, so opening the dialog
    doesn't stall on import. If ``ultralytics`` isn't installed, the
    dialog still opens but warns — execution is blocked until deps are
    present.
    """

    def __init__(self, n_unlabeled: int, parent=None) -> None:
        super().__init__(
            "AI 预标注",
            f"用本地 YOLOv8 为 {n_unlabeled:,} 张未标注图片生成 LabelMe JSON",
            parent,
        )

        self.model = LineEdit(self)
        self.model.setText("yolov8n.pt")
        self.model.setPlaceholderText("模型权重(*.pt)- 默认自动下载 yolov8n")
        self._add_row("模型", self.model)

        self.conf = DoubleSpinBox(self)
        self.conf.setRange(0.05, 0.95); self.conf.setSingleStep(0.05)
        self.conf.setValue(0.25); self.conf.setDecimals(2)
        self._add_row("置信度阈值", self.conf)

        self.overwrite = CheckBox("覆盖已有标注(默认跳过已标注图片)", self)
        self.viewLayout.addWidget(self.overwrite)

        # Check ultralytics availability up front
        try:
            import ultralytics  # noqa: F401
            avail = True
        except Exception:
            avail = False
        if not avail:
            warn = CaptionLabel(
                "⚠ 未安装 ultralytics;执行前请 pip install ultralytics", self)
            warn.setObjectName("hintWarn")
            self.viewLayout.addWidget(warn)
            self.yesButton.setEnabled(False)

    def options(self) -> dict[str, Any]:
        return {
            "model_name": self.model.text().strip() or "yolov8n.pt",
            "conf": float(self.conf.value()),
            "overwrite": self.overwrite.isChecked(),
        }
