"""Pre-export validation dialog showing split distribution per class."""
from __future__ import annotations

from collections import Counter

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QGridLayout
from qfluentwidgets import BodyLabel, CaptionLabel, SubtitleLabel

from core.models import Dataset
from core.splitter import SplitResult
from gui.dialogs.op_dialogs import _OpDialogBase
from gui.theme import T


class ExportValidationDialog(_OpDialogBase):
    """Show per-category split distribution and warnings before export."""

    def __init__(self, split: SplitResult, dataset: Dataset, parent=None) -> None:
        super().__init__("导出前检查", parent)
        self.widget.setMinimumWidth(480)

        # Count per-category images in each split
        train_counts: Counter[str] = Counter()
        val_counts: Counter[str] = Counter()
        test_counts: Counter[str] = Counter()
        for img in split.train:
            train_counts[img.category] += 1
        for img in split.val:
            val_counts[img.category] += 1
        for img in split.test:
            test_counts[img.category] += 1

        categories = sorted(
            {img.category for img in split.train + split.val + split.test}
        )

        # Summary
        total = len(split.train) + len(split.val) + len(split.test)
        self.viewLayout.addWidget(
            CaptionLabel(f"共 {total} 张图片 · {len(categories)} 个类别")
        )

        # Distribution table
        grid = QGridLayout()
        grid.setHorizontalSpacing(T.GAP_XL)
        grid.setVerticalSpacing(T.GAP_XS)

        # Header
        for col, header in enumerate(["类别", "Train", "Val", "Test"]):
            lbl = CaptionLabel(header)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter if col > 0 else Qt.AlignmentFlag.AlignLeft)
            grid.addWidget(lbl, 0, col)

        warnings: list[str] = []
        for row, cat in enumerate(categories, start=1):
            t, v, te = train_counts[cat], val_counts[cat], test_counts[cat]

            name_lbl = BodyLabel(cat)
            grid.addWidget(name_lbl, row, 0)

            for col, count in enumerate([t, v, te], start=1):
                lbl = BodyLabel(str(count))
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                if count < 10:
                    lbl.setObjectName("hintWarn")
                grid.addWidget(lbl, row, col)

            if t < 10:
                warnings.append(f"\"{cat}\" 训练集仅 {t} 张")
            if t + v + te < 5:
                warnings.append(f"\"{cat}\" 总计仅 {t + v + te} 张")

        self.viewLayout.addLayout(grid)

        # Imbalance check
        all_counts = [train_counts[c] + val_counts[c] + test_counts[c] for c in categories]
        if all_counts and min(all_counts) > 0:
            ratio = max(all_counts) / min(all_counts)
            if ratio > 5:
                warnings.append(f"类别不平衡比 {ratio:.1f}:1")

        # Warnings
        if warnings:
            self.viewLayout.addWidget(CaptionLabel(""))
            warn_title = CaptionLabel("⚠ 警告")
            warn_title.setObjectName("hintWarn")
            self.viewLayout.addWidget(warn_title)
            for msg in warnings:
                w = BodyLabel(f"  {msg}")
                w.setObjectName("hintWarn")
                self.viewLayout.addWidget(w)

        self.yesButton.setText("继续导出")
        self.cancelButton.setText("取消")
