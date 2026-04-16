"""History viewer — display recent metadata operations from history.jsonl."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QGridLayout, QScrollArea, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    MessageBoxBase,
    SubtitleLabel,
)

from core.history import read_recent
from gui.theme import T


# Human-readable labels for the action kebab-case ids written by browser_view.
_ACTION_LABELS = {
    "rename-category": "重命名类别",
    "merge-categories": "合并类别",
    "split-category": "拆分类别",
    "move-to-category": "移动到类别",
    "batch-rename": "批量重命名",
    "delete-duplicates": "删除重复",
}


class HistoryDialog(MessageBoxBase):
    """Scrollable list of the last 100 operations on this dataset."""

    def __init__(self, root: Path, parent=None) -> None:
        super().__init__(parent=parent)
        self.titleLabel = SubtitleLabel("操作历史", self)
        self.viewLayout.addWidget(self.titleLabel)
        self.widget.setMinimumWidth(640)

        entries = read_recent(root, limit=100)

        if not entries:
            self.viewLayout.addWidget(
                CaptionLabel("暂无记录 — 修改类别或移动图片后会出现在这里"))
        else:
            # Scroll area so hundreds of rows don't push the dialog off-screen
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            scroll.setMinimumHeight(440)

            inner = QWidget()
            grid = QGridLayout(inner)
            grid.setSpacing(T.GAP)
            grid.setColumnStretch(2, 1)  # summary column takes the slack

            for i, e in enumerate(entries):
                # Time column — just HH:MM:SS on the local date portion
                ts = e.timestamp.replace("T", " ")[:19]
                time_lbl = CaptionLabel(ts)
                time_lbl.setAlignment(Qt.AlignmentFlag.AlignTop)
                grid.addWidget(time_lbl, i, 0)

                action_lbl = BodyLabel(_ACTION_LABELS.get(e.action, e.action))
                action_lbl.setAlignment(Qt.AlignmentFlag.AlignTop)
                grid.addWidget(action_lbl, i, 1)

                summary_lbl = BodyLabel(e.summary or "-")
                summary_lbl.setWordWrap(True)
                if not e.ok:
                    summary_lbl.setObjectName("hintWarn")
                grid.addWidget(summary_lbl, i, 2)

            inner.setLayout(grid)
            scroll.setWidget(inner)
            self.viewLayout.addWidget(scroll)

        self.yesButton.setText("关闭")
        self.cancelButton.hide()
