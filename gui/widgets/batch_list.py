"""Batch list panel — shows import batches with per-batch status progress.

Displays each IngestBatch as a card with:
- Batch name + creation date
- Source directory (truncated)
- Item count + status breakdown bar
- Commit button (for items still in _inbox)

Designed as a toggleable side panel inside DatasetBrowserView,
similar to CatalogPanel.

Pure presentation — all mutations go through signals.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    FluentIcon as FIF,
    PrimaryPushButton,
    PushButton,
    ToolButton,
)

from gui import i18n
from gui.theme import T


def _status_colors() -> dict[str, str]:
    """Workflow-status → hex color, pulled from the active theme.

    Returns a fresh dict each call so the values track live theme swaps
    (``T`` is a proxy). Status colors are theme-invariant by design —
    workflow semantics shouldn't shift meaning between light/dark — but
    keeping them as tokens rather than module-level literals means the
    three-layer styling audit stays clean and a future theme can
    override without touching this file.
    """
    return {
        "new": T.STATUS_NEW,
        "prelabeled": T.STATUS_PRELABELED,
        "annotating": T.STATUS_ANNOTATING,
        "review_pending": T.STATUS_REVIEW_PENDING,
        "needs_fix": T.STATUS_NEEDS_FIX,
        "ready": T.STATUS_READY,
        "exported": T.STATUS_EXPORTED,
    }


class _StatusBar(QWidget):
    """Horizontal stacked bar showing per-status proportions."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(6)
        self._segments: list[tuple[str, int]] = []  # (color_hex, count)
        self._total = 0

    def set_counts(self, counts: dict[str, int]) -> None:
        self._segments = []
        self._total = sum(counts.values())
        for status, color in _status_colors().items():
            n = counts.get(status, 0)
            if n > 0:
                self._segments.append((color, n))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        if self._total == 0 or not self._segments:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = self.height()
        x = 0.0
        for color, count in self._segments:
            seg_w = (count / self._total) * w
            p.fillRect(int(x), 0, max(int(seg_w), 1), h, QColor(color))
            x += seg_w
        p.end()


class _BatchCard(QFrame):
    """One batch entry in the list."""

    commit_clicked = pyqtSignal(str)  # batch_id

    def __init__(self, info: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("batchCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._batch_id: str = info["batch_id"]

        lay = QVBoxLayout(self)
        lay.setContentsMargins(T.PAD_LG, T.PAD, T.PAD_LG, T.PAD)
        lay.setSpacing(4)

        # Row 1: name + date
        row1 = QHBoxLayout()
        row1.setSpacing(T.GAP)
        name_lbl = BodyLabel(info["name"])
        name_lbl.setObjectName("batchName")
        row1.addWidget(name_lbl, 1)

        date_str = info.get("created_at", "")[:10]  # ISO date portion
        if date_str:
            date_lbl = CaptionLabel(date_str)
            row1.addWidget(date_lbl)
        lay.addLayout(row1)

        # Row 2: source dirs (truncated)
        sources = info.get("source_dirs", [])
        if sources:
            src_text = sources[0]
            if len(src_text) > 40:
                src_text = "…" + src_text[-37:]
            if len(sources) > 1:
                src_text += f"  +{len(sources)-1}"
            src_lbl = CaptionLabel(src_text)
            lay.addWidget(src_lbl)

        # Row 3: status bar
        counts = info.get("status_counts", {})
        bar = _StatusBar()
        bar.set_counts(counts)
        lay.addWidget(bar)

        # Row 4: status summary text + commit button
        row4 = QHBoxLayout()
        row4.setSpacing(T.GAP)

        total = info.get("item_count", 0)
        parts = []
        for status_key, label in [
            ("new", i18n.t("batch.status.new")),
            ("annotating", i18n.t("batch.status.wip")),
            ("ready", i18n.t("batch.status.ready")),
        ]:
            n = counts.get(status_key, 0)
            if n > 0:
                parts.append(f"{n} {label}")
        summary = f"{total} {i18n.t('batch.total')}"
        if parts:
            summary += "  ·  " + " · ".join(parts)
        sum_lbl = CaptionLabel(summary)
        row4.addWidget(sum_lbl, 1)

        inbox_count = info.get("inbox_count", 0)
        if inbox_count > 0:
            commit_btn = PushButton(i18n.t("batch.commit"))
            commit_btn.setFixedHeight(26)
            commit_btn.setFixedWidth(70)
            commit_btn.clicked.connect(
                lambda: self.commit_clicked.emit(self._batch_id))
            row4.addWidget(commit_btn)

        lay.addLayout(row4)


class BatchListPanel(QFrame):
    """Side panel listing all import batches with status progress."""

    close_requested = pyqtSignal()
    import_requested = pyqtSignal()          # user wants to import a new batch
    commit_requested = pyqtSignal(str)       # batch_id to commit

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("batchListPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(320)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        head = QFrame()
        head_lay = QHBoxLayout(head)
        head_lay.setContentsMargins(T.PAD_LG, T.PAD_LG, T.PAD_LG, T.GAP)
        head_lay.setSpacing(T.GAP)

        head_text = QVBoxLayout()
        head_text.setContentsMargins(0, 0, 0, 0)
        head_text.setSpacing(2)
        self._title = BodyLabel(i18n.t("batch.title"))
        self._title.setObjectName("batchPanelTitle")
        self._subtitle = CaptionLabel(i18n.t("batch.subtitle"))
        self._subtitle.setObjectName("batchPanelSubtitle")
        head_text.addWidget(self._title)
        head_text.addWidget(self._subtitle)
        head_lay.addLayout(head_text, 1)

        close_btn = ToolButton(FIF.CLOSE)
        close_btn.setFixedSize(22, 22)
        close_btn.clicked.connect(self.close_requested.emit)
        head_lay.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignTop)

        root.addWidget(head)

        # Scroll area for batch cards
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll_content = QWidget()
        self._card_layout = QVBoxLayout(self._scroll_content)
        self._card_layout.setContentsMargins(T.PAD, T.GAP, T.PAD, T.PAD)
        self._card_layout.setSpacing(T.GAP)
        self._card_layout.addStretch(1)
        scroll.setWidget(self._scroll_content)
        root.addWidget(scroll, 1)

        # Empty state label (shown when no batches)
        self._empty_label = CaptionLabel(i18n.t("batch.empty"))
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._card_layout.insertWidget(0, self._empty_label)

        # Footer: import button
        footer = QFrame()
        footer_lay = QHBoxLayout(footer)
        footer_lay.setContentsMargins(T.PAD_LG, T.GAP, T.PAD_LG, T.PAD_LG)
        import_btn = PrimaryPushButton(i18n.t("batch.import_new"))
        import_btn.setIcon(FIF.ADD)
        import_btn.clicked.connect(self.import_requested.emit)
        footer_lay.addWidget(import_btn)
        root.addWidget(footer)

        # Connect language changes
        i18n.bus.language_changed.connect(self._retranslate)

    def set_batches(self, summaries: list[dict]) -> None:
        """Populate the panel with batch summary dicts from
        ``core.inbox.all_batch_summaries()``.
        """
        # Clear existing cards
        while self._card_layout.count() > 1:
            item = self._card_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        self._empty_label = None  # old one was deleted

        if not summaries:
            empty = CaptionLabel(i18n.t("batch.empty"))
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._empty_label = empty
            self._card_layout.insertWidget(0, empty)
            self._subtitle.setText(i18n.t("batch.subtitle"))
            return

        # Update subtitle with count
        total_items = sum(s.get("item_count", 0) for s in summaries)
        self._subtitle.setText(
            f"{len(summaries)} {i18n.t('batch.batches')} · {total_items} {i18n.t('batch.items')}"
        )

        # Insert cards newest-first
        for idx, info in enumerate(reversed(summaries)):
            card = _BatchCard(info)
            card.commit_clicked.connect(self.commit_requested.emit)
            self._card_layout.insertWidget(idx, card)

    def _retranslate(self, _lang: str) -> None:
        self._title.setText(i18n.t("batch.title"))
