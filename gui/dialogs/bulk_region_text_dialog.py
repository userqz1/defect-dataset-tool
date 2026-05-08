"""批量填入区域文本 — write one Grounding caption to all matching regions.

Solves the workflow that the per-image AnnotationPane editor doesn't
scale to: 4 000+ Loose images, every Loose region needs the same
"螺栓上的红色防松标记线未对齐..." caption.

Returns a payload dict via ``options()``.  The caller (DatasetBrowserView)
runs the actual mutation in a background worker via BatchRunner.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QButtonGroup, QHBoxLayout, QVBoxLayout
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    ComboBox,
    MessageBoxBase,
    PlainTextEdit,
    RadioButton,
    StrongBodyLabel,
    SubtitleLabel,
)

from core.grounding_bulk import count_fill_scope
from gui import i18n
from gui.theme import T


class BulkRegionTextDialog(MessageBoxBase):
    """One template, one click → fills every matching region's text."""

    # Sentinel stored in combo userData when the "all categories" row
    # is selected.  Comparing against userData (instead of currentText)
    # keeps the i18n label decoupled from logic — switching language
    # mid-dialog won't break category resolution.
    _ALL_SENTINEL = ""

    def __init__(self, dataset, sample_set,
                 initial_category: str = "", parent=None) -> None:
        super().__init__(parent=parent)
        self._dataset = dataset
        self._sample_set = sample_set
        self.widget.setMinimumWidth(540)

        self.viewLayout.addWidget(SubtitleLabel(i18n.t("bulk_fill.title")))

        # ── Category ────────────────────────────────────────────────
        self.viewLayout.addWidget(StrongBodyLabel(i18n.t("bulk_fill.category")))
        self._cat_combo = ComboBox()
        # Store the canonical category name in userData so resolution
        # is i18n-stable.  The displayed text can be translated; the
        # data is the source of truth.
        self._cat_combo.addItem(
            i18n.t("bulk_fill.category.all"), self._ALL_SENTINEL)
        for c in dataset.categories:
            self._cat_combo.addItem(c.name, c.name)
        # Default to the caller-provided active category so users who
        # already picked "Loose" in the catalog tree (or in a previous
        # dialog) don't have to reselect.  Fall back to "all" sentinel
        # if no scope is active or the name is unknown.
        if initial_category:
            idx = self._cat_combo.findData(initial_category)
            self._cat_combo.setCurrentIndex(idx if idx >= 0 else 0)
        else:
            self._cat_combo.setCurrentIndex(0)
        self._cat_combo.currentIndexChanged.connect(self._refresh_preview)
        self.viewLayout.addWidget(self._cat_combo)

        # ── Mode ───────────────────────────────────────────────────
        self.viewLayout.addWidget(StrongBodyLabel(i18n.t("bulk_fill.mode")))
        mode_row = QHBoxLayout()
        mode_row.setSpacing(T.GAP_LG)
        self._mode_skip = RadioButton(i18n.t("bulk_fill.mode.skip"))
        self._mode_overwrite = RadioButton(i18n.t("bulk_fill.mode.overwrite"))
        self._mode_skip.setChecked(True)
        self._mode_group = QButtonGroup(self)
        self._mode_group.addButton(self._mode_skip)
        self._mode_group.addButton(self._mode_overwrite)
        self._mode_skip.toggled.connect(self._refresh_preview)
        mode_row.addWidget(self._mode_skip)
        mode_row.addWidget(self._mode_overwrite)
        mode_row.addStretch(1)
        self.viewLayout.addLayout(mode_row)

        # ── Template text ──────────────────────────────────────────
        self.viewLayout.addWidget(StrongBodyLabel(i18n.t("bulk_fill.template")))
        self._template_edit = PlainTextEdit()
        self._template_edit.setPlaceholderText(
            i18n.t("bulk_fill.template.placeholder"))
        self._template_edit.setFixedHeight(110)
        self._template_edit.textChanged.connect(self._refresh_yes_enabled)
        self.viewLayout.addWidget(self._template_edit)

        # ── Live preview ───────────────────────────────────────────
        self._preview = CaptionLabel("")
        self._preview.setWordWrap(True)
        self.viewLayout.addWidget(self._preview)

        self.yesButton.setText(i18n.t("bulk_fill.btn.apply"))
        self.cancelButton.setText(i18n.t("bulk_fill.btn.cancel"))
        self._refresh_yes_enabled()
        self._refresh_preview()

    # ---------- internals ----------

    def _selected_category(self) -> str:
        # Read userData, not display text — the latter is i18n-translated.
        data = self._cat_combo.currentData()
        return data if isinstance(data, str) else ""

    def _refresh_yes_enabled(self) -> None:
        text = self._template_edit.toPlainText().strip()
        self.yesButton.setEnabled(bool(text))

    def _refresh_preview(self) -> None:
        if self._sample_set is None:
            self._preview.setText(i18n.t("bulk_fill.preview.empty"))
            return
        category = self._selected_category()
        overwrite = self._mode_overwrite.isChecked()
        n_imgs, n_regs, n_skip = count_fill_scope(
            self._sample_set, category=category, overwrite=overwrite)
        scope = category or i18n.t("bulk_fill.preview.scope_all")
        if overwrite:
            self._preview.setText(i18n.t(
                "bulk_fill.preview.overwrite",
                scope=scope, n_imgs=n_imgs, n_regs=n_regs,
            ))
        else:
            self._preview.setText(i18n.t(
                "bulk_fill.preview.skip",
                scope=scope, n_imgs=n_imgs, n_regs=n_regs, n_skip=n_skip,
            ))

    # ---------- result ----------

    def options(self) -> dict:
        return {
            "category": self._selected_category(),
            "template": self._template_edit.toPlainText().strip(),
            "overwrite": self._mode_overwrite.isChecked(),
        }
