"""大模型标注向导 — 选类目 + 本次字段，一键准备好工作环境。

Bundles three things the user previously had to do across three stages
into one dialog:

1. **本次字段** — decides which missing VLM fields count as incomplete.
2. **类目筛选** — narrows the grid to one category.
3. **打开第一张未完成图** — drops the user onto an actionable
   image, not an overview.

Returns a ``result_dict`` the caller translates into stage swap +
category filter + drill-in.  No project capability flags are mutated.

Pure dialog: no side effects.  Button labels in Chinese to match the
rest of the workbench.
"""
from __future__ import annotations

from qfluentwidgets import (
    CheckBox,
    ComboBox,
    MessageBoxBase,
    StrongBodyLabel,
    SubtitleLabel,
)

from gui.theme import T


class VlmStartDialog(MessageBoxBase):
    """Pick category + fields for this VLM annotation run."""

    def __init__(self, dataset, project,
                 initial_category: str = "", parent=None) -> None:
        super().__init__(parent=parent)
        self._dataset = dataset
        self._project = project
        self.widget.setMinimumWidth(440)

        self.viewLayout.addWidget(SubtitleLabel("大模型标注向导"))

        # ── Category ────────────────────────────────────────────────
        self.viewLayout.addWidget(StrongBodyLabel("类目"))
        self._cat_combo = ComboBox()
        self._cat_combo.addItem("全部")
        for c in dataset.categories:
            self._cat_combo.addItem(c.name)
        # Default to caller-provided category (typically the catalog
        # tree's current selection) so picking "Loose" once propagates
        # through the workflow.  Falls back to "全部" when no scope is
        # active or the name no longer exists in the dataset.
        if initial_category:
            idx = self._cat_combo.findText(initial_category)
            self._cat_combo.setCurrentIndex(idx if idx >= 0 else 0)
        else:
            self._cat_combo.setCurrentIndex(0)
        self.viewLayout.addWidget(self._cat_combo)

        # ── Fields for this run ─────────────────────────────────────
        self.viewLayout.addWidget(StrongBodyLabel("字段"))

        self._cap_caption = CheckBox("Caption · 整图描述")
        self._cap_caption.setChecked(True)
        self._cap_conv = CheckBox("Conversations · 多轮对话")
        self._cap_conv.setChecked(False)
        self._cap_grounding = CheckBox("Grounding · 区域定位 + 文字")
        self._cap_grounding.setChecked(True)

        self.viewLayout.addWidget(self._cap_caption)
        self.viewLayout.addWidget(self._cap_conv)
        self.viewLayout.addWidget(self._cap_grounding)

        # 开始 disabled when nothing is checked — there's no useful
        # workbench state to set up without at least one cap.
        for chk in (self._cap_caption, self._cap_conv, self._cap_grounding):
            chk.toggled.connect(self._refresh_yes_enabled)

        self.yesButton.setText("开始标注")
        self.cancelButton.setText("取消")
        self._refresh_yes_enabled()

    # ---------- internals ----------

    def _refresh_yes_enabled(self) -> None:
        any_on = (self._cap_caption.isChecked()
                  or self._cap_conv.isChecked()
                  or self._cap_grounding.isChecked())
        self.yesButton.setEnabled(any_on)

    # ---------- result ----------

    def result_dict(self) -> dict:
        cat = self._cat_combo.currentText()
        return {
            # Empty string = no category filter (apply to whole dataset).
            "category": "" if cat == "全部" else cat,
            "caption": self._cap_caption.isChecked(),
            "conversations": self._cap_conv.isChecked(),
            "grounding": self._cap_grounding.isChecked(),
        }
