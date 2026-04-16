"""Tool dialogs — quality check, dedup, augment, stats.

Each dialog collects parameters via MessageBoxBase and returns options.
The caller (DatasetBrowserView) handles the BatchWorker execution.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CheckBox,
    MessageBoxBase,
    RadioButton,
    SpinBox,
    StrongBodyLabel,
    SubtitleLabel,
)

from gui.theme import T


# ── Quality Check ──────────────────────────────────────────────

class QualityCheckDialog(MessageBoxBase):
    """Collect blur threshold for quality check."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent=parent)
        self.titleLabel = SubtitleLabel("质量检查", self)
        self.viewLayout.addWidget(self.titleLabel)
        self.widget.setMinimumWidth(360)

        row = QHBoxLayout()
        row.addWidget(BodyLabel("模糊阈值"))
        self._blur = SpinBox()
        self._blur.setRange(10, 1000)
        self._blur.setValue(100)
        self._blur.setFixedWidth(100)
        row.addWidget(self._blur)
        self.viewLayout.addLayout(row)

        hint = CaptionLabel("值越小越严格，推荐 80-150")
        self.viewLayout.addWidget(hint)

        self.yesButton.setText("开始检查")
        self.cancelButton.setText("取消")

    def blur_threshold(self) -> float:
        return float(self._blur.value())


# ── Dedup ──────────────────────────────────────────────────────

class DedupDialog(MessageBoxBase):
    """Collect hamming distance threshold for dedup."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent=parent)
        self.titleLabel = SubtitleLabel("重复检测", self)
        self.viewLayout.addWidget(self.titleLabel)
        self.widget.setMinimumWidth(360)

        row = QHBoxLayout()
        row.addWidget(BodyLabel("相似度阈值"))
        self._threshold = SpinBox()
        self._threshold.setRange(0, 20)
        self._threshold.setValue(5)
        self._threshold.setFixedWidth(100)
        row.addWidget(self._threshold)
        self.viewLayout.addLayout(row)

        hint = CaptionLabel("哈希距离 ≤ 阈值视为重复，0=完全相同，推荐 3-8")
        self.viewLayout.addWidget(hint)

        self.yesButton.setText("开始检测")
        self.cancelButton.setText("取消")

    def threshold(self) -> int:
        return self._threshold.value()


class DedupResultDialog(MessageBoxBase):
    """Show dedup results and offer deletion."""

    def __init__(self, groups: list, parent=None) -> None:
        super().__init__(parent=parent)
        self._groups = groups
        total_dup = sum(g.size - 1 for g in groups)

        self.titleLabel = SubtitleLabel(
            f"发现 {len(groups)} 组重复（共 {total_dup} 张可删除）", self,
        )
        self.viewLayout.addWidget(self.titleLabel)
        self.widget.setMinimumWidth(480)

        # Show first N groups
        for i, g in enumerate(groups[:20]):
            names = [img.path.name for img in g.images]
            keep = names[0]
            dups = ", ".join(names[1:])
            row = CaptionLabel(f"组{i+1}: 保留 {keep}  |  重复 {dups}")
            self.viewLayout.addWidget(row)

        if len(groups) > 20:
            self.viewLayout.addWidget(
                CaptionLabel(f"…及其余 {len(groups) - 20} 组")
            )

        self.yesButton.setText(f"删除 {total_dup} 张重复到回收站")
        self.cancelButton.setText("取消")

    @property
    def groups(self):
        return self._groups


# ── Augment ────────────────────────────────────────────────────

class AugmentDialog(MessageBoxBase):
    """Augmentation options: transforms + output directory.

    Caller passes ``selected_count`` to enable a "仅已选中" source option;
    omit it (or pass 0) to hide that option.
    """

    def __init__(self, parent=None, selected_count: int = 0) -> None:
        super().__init__(parent=parent)
        self.titleLabel = SubtitleLabel("数据增强", self)
        self.viewLayout.addWidget(self.titleLabel)
        self.widget.setMinimumWidth(440)

        # Source selection (only meaningful when something is selected)
        self._source: str = "all"
        if selected_count > 0:
            self.viewLayout.addWidget(StrongBodyLabel("来源"))
            src_row = QHBoxLayout()
            src_row.setSpacing(T.GAP)
            self._src_all = RadioButton("全部图片")
            self._src_all.setChecked(True)
            self._src_sel = RadioButton(f"仅已选中（{selected_count} 张）")
            self._src_all.toggled.connect(
                lambda c: self._set_source("all") if c else None
            )
            self._src_sel.toggled.connect(
                lambda c: self._set_source("selected") if c else None
            )
            src_row.addWidget(self._src_all)
            src_row.addWidget(self._src_sel)
            src_row.addStretch()
            self.viewLayout.addLayout(src_row)

        # Geometric transforms
        self.viewLayout.addWidget(StrongBodyLabel("几何变换"))
        geo = QGridLayout()
        geo.setSpacing(T.GAP)
        self._flip_h = CheckBox("水平翻转")
        self._flip_h.setChecked(True)
        self._flip_v = CheckBox("垂直翻转")
        self._rotate90 = CheckBox("旋转90°")
        self._random_crop = CheckBox("随机裁剪")
        geo.addWidget(self._flip_h, 0, 0)
        geo.addWidget(self._flip_v, 0, 1)
        geo.addWidget(self._rotate90, 1, 0)
        geo.addWidget(self._random_crop, 1, 1)
        self.viewLayout.addLayout(geo)

        # Photometric transforms
        self.viewLayout.addWidget(StrongBodyLabel("光度变换"))
        photo = QGridLayout()
        photo.setSpacing(T.GAP)
        self._brightness = CheckBox("亮度")
        self._brightness.setChecked(True)
        self._contrast = CheckBox("对比度")
        self._contrast.setChecked(True)
        self._color = CheckBox("色彩抖动")
        self._blur = CheckBox("高斯模糊")
        self._noise = CheckBox("高斯噪声")
        photo.addWidget(self._brightness, 0, 0)
        photo.addWidget(self._contrast, 0, 1)
        photo.addWidget(self._color, 1, 0)
        photo.addWidget(self._blur, 1, 1)
        photo.addWidget(self._noise, 2, 0)
        self.viewLayout.addLayout(photo)

        # N per image
        n_row = QHBoxLayout()
        n_row.addWidget(BodyLabel("每张生成"))
        self._n_per = SpinBox()
        self._n_per.setRange(1, 50)
        self._n_per.setValue(3)
        self._n_per.setFixedWidth(80)
        n_row.addWidget(self._n_per)
        n_row.addWidget(BodyLabel("张"))
        n_row.addStretch()
        self.viewLayout.addLayout(n_row)

        # Output dir
        dir_row = QHBoxLayout()
        dir_row.addWidget(BodyLabel("输出目录"))
        self._dir_label = CaptionLabel("未选择")
        dir_row.addWidget(self._dir_label, 1)
        from qfluentwidgets import PushButton
        browse_btn = PushButton("选择")
        browse_btn.setFixedWidth(60)
        browse_btn.clicked.connect(self._pick_dir)
        dir_row.addWidget(browse_btn)
        self.viewLayout.addLayout(dir_row)

        self._out_dir: Path | None = None

        self.yesButton.setText("开始增强")
        self.yesButton.setEnabled(False)
        self.cancelButton.setText("取消")

    def _pick_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择输出目录", str(Path.home()))
        if d:
            self._out_dir = Path(d)
            self._dir_label.setText(str(self._out_dir))
            self.yesButton.setEnabled(True)

    def _set_source(self, s: str) -> None:
        self._source = s

    def options(self) -> dict:
        from core.augment import AugmentOptions
        return {
            "opts": AugmentOptions(
                flip_h=self._flip_h.isChecked(),
                flip_v=self._flip_v.isChecked(),
                rotate90=self._rotate90.isChecked(),
                random_crop=self._random_crop.isChecked(),
                brightness=self._brightness.isChecked(),
                contrast=self._contrast.isChecked(),
                color_jitter=self._color.isChecked(),
                gauss_blur=self._blur.isChecked(),
                gauss_noise=self._noise.isChecked(),
                n_per_image=self._n_per.value(),
            ),
            "out_dir": self._out_dir,
            "source": self._source,  # "all" | "selected"
        }


# ── Stats ──────────────────────────────────────────────────────

class StatsResultDialog(MessageBoxBase):
    """Display dataset statistics."""

    def __init__(self, stats, extended, parent=None) -> None:
        super().__init__(parent=parent)
        self.titleLabel = SubtitleLabel("数据集统计", self)
        self.viewLayout.addWidget(self.titleLabel)
        self.widget.setMinimumWidth(440)

        # Basic stats
        grid = QGridLayout()
        grid.setSpacing(T.GAP)
        rows = [
            ("总图片数", str(stats.total_images)),
            ("总标注数", str(stats.total_annotations)),
            ("类别数", str(stats.category_count)),
            ("未标注", str(stats.unlabeled_count)),
            ("标注覆盖率", f"{stats.label_completion_rate:.0%}"),
            ("平均标注/图", f"{stats.avg_annotations_per_image:.1f}"),
        ]
        for i, (label, value) in enumerate(rows):
            grid.addWidget(CaptionLabel(label), i, 0)
            grid.addWidget(StrongBodyLabel(value), i, 1)
        self.viewLayout.addLayout(grid)

        # Extended stats
        if extended:
            self.viewLayout.addWidget(StrongBodyLabel("详细统计"))
            ext_grid = QGridLayout()
            ext_grid.setSpacing(T.GAP)
            ext_rows = [
                ("目标数/图 (最小)", str(extended.objects_per_image_min)),
                ("目标数/图 (最大)", str(extended.objects_per_image_max)),
                ("目标数/图 (中位)", f"{extended.objects_per_image_median:.1f}"),
                ("不平衡比", f"{extended.imbalance_ratio:.2f}"),
            ]
            if extended.image_sizes:
                s = extended.image_sizes
                ext_rows.append(("图片尺寸范围",
                                 f"{s.min_w}x{s.min_h} ~ {s.max_w}x{s.max_h}"))
            for i, (label, value) in enumerate(ext_rows):
                ext_grid.addWidget(CaptionLabel(label), i, 0)
                ext_grid.addWidget(BodyLabel(value), i, 1)
            self.viewLayout.addLayout(ext_grid)

            # Warnings
            if extended.warnings:
                self.viewLayout.addWidget(StrongBodyLabel("警告"))
                for w in extended.warnings:
                    lbl = CaptionLabel(f"  {w}")
                    lbl.setObjectName("hintWarn")
                    self.viewLayout.addWidget(lbl)

        # Category distribution (top 10)
        if stats.category_distribution:
            self.viewLayout.addWidget(StrongBodyLabel("类别分布"))
            for name, count in stats.category_distribution[:10]:
                self.viewLayout.addWidget(CaptionLabel(f"  {name}: {count}"))
            if len(stats.category_distribution) > 10:
                self.viewLayout.addWidget(
                    CaptionLabel(f"  …及其余 {len(stats.category_distribution) - 10} 类")
                )

        self.yesButton.setText("关闭")
        self.cancelButton.hide()
