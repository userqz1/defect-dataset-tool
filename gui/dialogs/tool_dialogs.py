"""Tool dialogs — quality check, dedup, augment, stats.

Each dialog collects parameters via MessageBoxBase and returns options.
The caller (DatasetBrowserView) handles the BatchWorker execution.
"""
from __future__ import annotations

from PyQt6.QtWidgets import QGridLayout, QHBoxLayout
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    MessageBoxBase,
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
        self._blur.setFixedWidth(140)
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
        self._threshold.setFixedWidth(140)
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

        self.yesButton.setText(f"永久删除 {total_dup} 张重复（不可恢复）")
        self.cancelButton.setText("取消")

    @property
    def groups(self):
        return self._groups


# ── Quality Review (review #16) ────────────────────────────────

class QualityReviewDialog(MessageBoxBase):
    """Post-quality-check dialog offering batch follow-up actions.

    Review #16: previously the user saw "25 张问题图片" in an InfoBar and
    had to hunt them down through the "有问题" filter chip + manual delete.
    This dialog closes the loop: shows the breakdown and lets the user
    run one of three actions over all issue images in a single click.
    """

    # Action keys returned via ``chosen_action``
    ACTION_NONE = "none"
    ACTION_DELETE = "delete"
    ACTION_MOVE = "move"

    _KIND_NAMES = {
        "blur": "模糊", "blank": "空白",
        "over": "过曝", "under": "欠曝", "corrupt": "损坏",
    }

    def __init__(self, issues: list, parent=None) -> None:
        super().__init__(parent=parent)
        self._issues = list(issues)
        self._action = self.ACTION_NONE

        self.titleLabel = SubtitleLabel(
            f"质量检查结果 — 共 {len(issues)} 张问题图片", self
        )
        self.viewLayout.addWidget(self.titleLabel)
        self.widget.setMinimumWidth(480)

        # Per-kind breakdown
        from collections import Counter
        kind_counts: Counter = Counter()
        for issue in issues:
            for k in issue.kinds:
                kind_counts[k] += 1
        if kind_counts:
            parts = [f"{c} 张 {self._KIND_NAMES.get(k, k)}"
                     for k, c in kind_counts.most_common()]
            self.viewLayout.addWidget(CaptionLabel(" · ".join(parts)))

        # Sample filename list (first 15)
        self.viewLayout.addWidget(CaptionLabel("问题样本:"))
        for issue in issues[:15]:
            kinds_cn = "/".join(self._KIND_NAMES.get(k, k) for k in issue.kinds)
            self.viewLayout.addWidget(
                CaptionLabel(f"  {issue.image.path.name} — {kinds_cn}")
            )
        if len(issues) > 15:
            self.viewLayout.addWidget(
                CaptionLabel(f"  … 及其余 {len(issues) - 15} 张")
            )

        # Action row — three explicit buttons instead of yes/no. Users who
        # just want to "see" pick 仅标记; the 删除/移类 paths close the loop.
        from PyQt6.QtWidgets import QHBoxLayout as _QHBoxLayout
        actions = _QHBoxLayout()
        actions.setSpacing(T.GAP)
        from qfluentwidgets import PushButton as _PB
        mark_btn = _PB("仅标记(稍后处理)", self)
        mark_btn.clicked.connect(lambda: self._choose(self.ACTION_NONE))
        move_btn = _PB("移到「质量问题」类别", self)
        move_btn.clicked.connect(lambda: self._choose(self.ACTION_MOVE))
        del_btn = _PB("永久删除（不可恢复）", self)
        del_btn.clicked.connect(lambda: self._choose(self.ACTION_DELETE))
        actions.addWidget(mark_btn)
        actions.addWidget(move_btn)
        actions.addWidget(del_btn)
        self.viewLayout.addLayout(actions)

        self.yesButton.hide()
        self.cancelButton.setText("取消")

    def _choose(self, action: str) -> None:
        self._action = action
        self.accept()

    def chosen_action(self) -> str:
        return self._action

    def issue_images(self):
        return [i.image for i in self._issues]


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
