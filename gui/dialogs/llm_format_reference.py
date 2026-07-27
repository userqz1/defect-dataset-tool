"""LLM-data format reference — comparative table for the export user.

Opened from :class:`gui.widgets.llm_data_card.LlmDataCard`'s help link
when the user isn't sure which target format to pick.  Renders the
five common formats (LLaVA / ShareGPT / ms-swift+Qwen-VL / Caption
JSONL) side-by-side with their core fields, grounding/coord rules,
and the gotchas that bite users at training time (esp. Qwen2.5-VL's
absolute-coord requirement and resize sync).

Pure presentational dialog — no state, no signals beyond accept/cancel.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QScrollArea,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    MessageBoxBase,
    StrongBodyLabel,
    SubtitleLabel,
)

from gui import i18n
from gui.theme import T


# Each row: format-i18n-key + per-cell i18n-keys for usage/fields/bbox/note.
_FORMAT_ROWS: list[tuple[str, str, str, str, str]] = [
    ("llm.format.llava",
     "llm.help.row.llava.usage",
     "llm.help.row.llava.fields",
     "llm.help.row.llava.bbox",
     "llm.help.row.llava.note"),
    ("llm.format.sharegpt",
     "llm.help.row.sharegpt.usage",
     "llm.help.row.sharegpt.fields",
     "llm.help.row.sharegpt.bbox",
     "llm.help.row.sharegpt.note"),
    ("llm.format.swift",
     "llm.help.row.swift.usage",
     "llm.help.row.swift.fields",
     "llm.help.row.swift.bbox",
     "llm.help.row.swift.note"),
    ("llm.format.caption",
     "llm.help.row.caption.usage",
     "llm.help.row.caption.fields",
     "llm.help.row.caption.bbox",
     "llm.help.row.caption.note"),
]


class LlmFormatReferenceDialog(MessageBoxBase):
    """Read-only reference table for the four primary export formats."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        # Wider than the default — the table needs the room.
        self.widget.setMinimumWidth(720)
        self.widget.setMaximumWidth(900)

        self.titleLabel = SubtitleLabel(i18n.t("llm.help.title"), self)
        self.viewLayout.addWidget(self.titleLabel)

        intro = CaptionLabel(i18n.t("llm.help.intro"))
        intro.setObjectName("llmHelpIntro")
        intro.setWordWrap(True)
        self.viewLayout.addWidget(intro)
        self.viewLayout.addSpacing(T.GAP)

        # Scrollable table — content gets long on small screens.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMinimumHeight(360)
        scroll.setMaximumHeight(440)

        table_host = QWidget()
        grid = QGridLayout(table_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(T.PAD_LG)
        grid.setVerticalSpacing(T.GAP)
        # Column stretch — let the wide "fields" / "note" columns breathe.
        grid.setColumnStretch(0, 0)   # format name
        grid.setColumnStretch(1, 1)   # usage
        grid.setColumnStretch(2, 2)   # fields
        grid.setColumnStretch(3, 2)   # bbox / coords
        grid.setColumnStretch(4, 2)   # notes

        # Header row.
        header_keys = (
            "llm.help.col.format",
            "llm.help.col.usage",
            "llm.help.col.fields",
            "llm.help.col.bbox",
            "llm.help.col.note",
        )
        for col, key in enumerate(header_keys):
            head = StrongBodyLabel(i18n.t(key))
            head.setObjectName("llmHelpHeader")
            grid.addWidget(head, 0, col, Qt.AlignmentFlag.AlignLeft)

        # Body rows.
        for row, (fmt_key, usage_key, fields_key, bbox_key, note_key) in \
                enumerate(_FORMAT_ROWS, start=1):
            fmt_lbl = StrongBodyLabel(i18n.t(fmt_key))
            fmt_lbl.setObjectName("llmHelpFormatName")
            grid.addWidget(fmt_lbl, row, 0,
                           Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

            for col, key in enumerate(
                    (usage_key, fields_key, bbox_key, note_key), start=1):
                cell = BodyLabel(i18n.t(key))
                cell.setObjectName("llmHelpCell")
                cell.setWordWrap(True)
                grid.addWidget(cell, row, col,
                               Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        # Add stretch to push rows up if the table is short.
        grid.setRowStretch(len(_FORMAT_ROWS) + 1, 1)

        scroll.setWidget(table_host)
        self.viewLayout.addWidget(scroll)

        # Coord warning — the single most common training-bug source.
        self.viewLayout.addSpacing(T.GAP)
        warn = CaptionLabel(i18n.t("llm.help.coord_warning"))
        warn.setObjectName("llmHelpWarn")
        warn.setWordWrap(True)
        self.viewLayout.addWidget(warn)

        # Single-button dialog — no destructive action, just dismiss.
        self.yesButton.setText(i18n.t("llm.help.close"))
        self.cancelButton.hide()
