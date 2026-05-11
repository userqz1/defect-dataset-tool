"""Batch list panel — the 导入数据 (Inbox) stage body.

Three-block layout:
  1. **拖拽导入区** — drag-drop zone + primary CTA (select folder)
  2. **待整理批次** — batch cards with status bar + single CTA each
  3. **上下文页脚** — inline rules + next-step hint (only when batches exist)

Empty project: only the drop zone is visible — one surface, one action.

Pure presentation — all mutations go through signals.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QDragEnterEvent, QDropEvent, QPainter
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
    StrongBodyLabel,
)

from gui import i18n
from gui.theme import T


# ── Status colors ─────────────────────────────────────────────────

def _status_colors() -> dict[str, str]:
    return {
        "new": T.STATUS_NEW,
        "prelabeled": T.STATUS_PRELABELED,
        "annotating": T.STATUS_ANNOTATING,
        "review_pending": T.STATUS_REVIEW_PENDING,
        "needs_fix": T.STATUS_NEEDS_FIX,
        "ready": T.STATUS_READY,
        "exported": T.STATUS_EXPORTED,
    }


# ── Status bar widget ────────────────────────────────────────────

class _StatusBar(QWidget):
    """Horizontal stacked bar showing per-status proportions."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(6)
        self._segments: list[tuple[str, int]] = []
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


# ── Batch status logic ───────────────────────────────────────────

_STATUS_MAP = {
    "pending":  ("待整理", "inbox.batch_status.pending"),
    "confirm":  ("待确认", "inbox.batch_status.confirm"),
    "done":     ("已入库", "inbox.batch_status.done"),
    "conflict": ("有冲突", "inbox.batch_status.conflict"),
}


def _batch_status(info: dict) -> str:
    """Determine the batch status from its counts."""
    counts = info.get("status_counts", {})
    inbox = info.get("inbox_count", 0)
    needs_fix = counts.get("needs_fix", 0)
    if needs_fix > 0:
        return "conflict"
    if inbox > 0:
        new_count = counts.get("new", 0)
        if new_count > 0:
            return "pending"
        return "confirm"
    return "done"


def _batch_cta(status: str) -> tuple[str, str]:
    """Return (button_label_key, icon_hint) for the batch status."""
    return {
        "pending":  ("inbox.batch_cta.organize",   "organize"),
        "confirm":  ("inbox.batch_cta.continue",    "continue"),
        "conflict": ("inbox.batch_cta.conflict",    "conflict"),
        "done":     ("inbox.batch_cta.done",        "done"),
    }.get(status, ("inbox.batch_cta.organize", "organize"))


# ── Batch card ───────────────────────────────────────────────────

class _BatchCard(QFrame):
    """One batch entry — name, date, count, source, status, single CTA."""

    commit_clicked = pyqtSignal(str)   # batch_id
    open_source = pyqtSignal(str)      # source dir path

    def __init__(self, info: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("batchCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._batch_id: str = info["batch_id"]

        lay = QVBoxLayout(self)
        lay.setContentsMargins(T.PAD_LG, T.PAD_LG, T.PAD_LG, T.PAD_LG)
        lay.setSpacing(6)

        # Row 1: batch name + date
        row1 = QHBoxLayout()
        row1.setSpacing(T.GAP)
        name_lbl = StrongBodyLabel(info.get("name", "未命名批次"))
        row1.addWidget(name_lbl, 1)
        date_str = info.get("created_at", "")[:10]
        if date_str:
            row1.addWidget(CaptionLabel(date_str))
        lay.addLayout(row1)

        # Row 2: source dir + image count
        sources = info.get("source_dirs", [])
        item_count = info.get("item_count", 0)
        meta_parts = []
        if sources:
            src = sources[0]
            if len(src) > 35:
                src = "…" + src[-32:]
            meta_parts.append(src)
        meta_parts.append(f"{item_count:,} 张图片")
        meta_lbl = CaptionLabel(" · ".join(meta_parts))
        lay.addWidget(meta_lbl)

        # Row 3: status bar
        counts = info.get("status_counts", {})
        bar = _StatusBar()
        bar.set_counts(counts)
        lay.addWidget(bar)

        # Row 4: status label + CTA button
        row4 = QHBoxLayout()
        row4.setSpacing(T.GAP)

        status = _batch_status(info)
        status_label_key = _STATUS_MAP.get(status, _STATUS_MAP["pending"])[1]
        status_lbl = CaptionLabel(i18n.t(status_label_key))
        row4.addWidget(status_lbl)
        row4.addStretch(1)

        # Single main CTA
        cta_key, _ = _batch_cta(status)
        if status != "done":
            cta_btn = PushButton(i18n.t(cta_key))
            cta_btn.setFixedHeight(28)
            cta_btn.clicked.connect(
                lambda: self.commit_clicked.emit(self._batch_id))
            row4.addWidget(cta_btn)
        else:
            done_lbl = CaptionLabel(i18n.t(cta_key))
            row4.addWidget(done_lbl)

        lay.addLayout(row4)


# ── Drop zone ────────────────────────────────────────────────────

class _DropZone(QFrame):
    """Large drag-and-drop area with a primary CTA button.

    Accepts directory drops and emits ``folder_dropped(str)``; also has
    a regular ``button_clicked`` signal for the "选择图片文件夹" button.
    """

    button_clicked = pyqtSignal()
    folder_dropped = pyqtSignal(str)   # path of the dropped directory

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAcceptDrops(True)
        self.setMinimumHeight(180)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(T.PAD_2XL, T.PAD_3XL, T.PAD_2XL, T.PAD_3XL)
        lay.setSpacing(T.GAP_LG)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Primary label
        self._title = StrongBodyLabel(
            i18n.t("inbox.drop.title"))
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._title)

        # Button
        self._btn = PrimaryPushButton(i18n.t("inbox.drop.btn"))
        self._btn.setIcon(FIF.FOLDER_ADD)
        self._btn.setFixedHeight(T.CONTROL_HEIGHT)
        self._btn.clicked.connect(self.button_clicked.emit)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(self._btn)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)

        # Safety note
        self._note = CaptionLabel(i18n.t("inbox.drop.note"))
        self._note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._note)

        self._hovering = False

    # ── Drag-and-drop ─────────────────────────────────────────────

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        mime = event.mimeData()
        if mime and mime.hasUrls():
            event.acceptProposedAction()
            self._hovering = True
            self.update()

    def dragLeaveEvent(self, event) -> None:
        self._hovering = False
        self.update()

    def dropEvent(self, event: QDropEvent) -> None:
        self._hovering = False
        self.update()
        mime = event.mimeData()
        if not mime:
            return
        for url in mime.urls():
            path = url.toLocalFile()
            if path:
                self.folder_dropped.emit(path)
                return  # only handle the first one

    def paintEvent(self, event) -> None:
        """Draw dashed border — stronger when hovering."""
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen_color = QColor(T.ACCENT) if self._hovering else QColor(T.BORDER)
        pen_width = 2.5 if self._hovering else 1.5
        from PyQt6.QtCore import QRectF
        from PyQt6.QtGui import QPen
        pen = QPen(pen_color, pen_width, Qt.PenStyle.DashLine)
        p.setPen(pen)
        r = T.RADIUS_LG
        margin = pen_width / 2 + 1
        rect = QRectF(margin, margin,
                      self.width() - 2 * margin,
                      self.height() - 2 * margin)
        p.drawRoundedRect(rect, r, r)
        p.end()

    def retranslate(self) -> None:
        self._title.setText(i18n.t("inbox.drop.title"))
        self._btn.setText(i18n.t("inbox.drop.btn"))
        self._note.setText(i18n.t("inbox.drop.note"))


# ── Main panel ───────────────────────────────────────────────────

class BatchListPanel(QFrame):
    """Inbox stage body — 3-block layout.

    Block 1: Drag-drop zone (always visible — the single import entry)
    Block 2: Batch cards (hidden when no batches)
    Block 3: Context footer — rules + next step (hidden when no batches)

    Empty state = just the drop zone.
    """

    import_requested = pyqtSignal()          # new import from folder
    folder_dropped = pyqtSignal(str)         # path from drag-and-drop
    commit_requested = pyqtSignal(str)       # batch_id to commit
    navigate_stage = pyqtSignal(int)         # jump to another stage

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("batchListPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._project_name = ""
        self._project_root: Path | None = None
        self._has_batches = False
        self._summaries: list[dict] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Outer scroll
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        body = QWidget()
        self._body_lay = QVBoxLayout(body)
        self._body_lay.setContentsMargins(
            T.PAD_2XL, T.PAD_XL, T.PAD_2XL, T.PAD_XL)
        self._body_lay.setSpacing(T.GAP_XL)

        # ── Block 1: Drop zone ──
        self._drop_zone = _DropZone()
        self._drop_zone.button_clicked.connect(self.import_requested.emit)
        self._drop_zone.folder_dropped.connect(self.folder_dropped.emit)
        self._body_lay.addWidget(self._drop_zone)

        # ── Block 2: Batch list ──
        self._batch_section = QWidget()
        batch_lay = QVBoxLayout(self._batch_section)
        batch_lay.setContentsMargins(0, 0, 0, 0)
        batch_lay.setSpacing(T.GAP)

        batch_header = QHBoxLayout()
        self._batch_title = StrongBodyLabel(
            i18n.t("inbox.batches.title"))
        self._batch_title.setObjectName("hubSectionTitle")
        batch_header.addWidget(self._batch_title)
        batch_header.addStretch(1)
        self._batch_count = CaptionLabel("")
        batch_header.addWidget(self._batch_count)
        batch_lay.addLayout(batch_header)

        self._batch_container = QVBoxLayout()
        self._batch_container.setSpacing(T.GAP)
        batch_lay.addLayout(self._batch_container)

        self._batch_section.hide()
        self._body_lay.addWidget(self._batch_section)

        # ── Block 3: Context footer (rules + next step) ──
        self._footer = QFrame()
        self._footer.setObjectName("chartFrame")
        self._footer.setAttribute(
            Qt.WidgetAttribute.WA_StyledBackground, True)
        footer_lay = QVBoxLayout(self._footer)
        footer_lay.setContentsMargins(T.PAD_XL, T.PAD_LG, T.PAD_XL, T.PAD_LG)
        footer_lay.setSpacing(T.GAP)

        # Rules (compact inline)
        self._rule_line = CaptionLabel("")
        self._rule_line.setWordWrap(True)
        footer_lay.addWidget(self._rule_line)

        # Next step
        next_row = QHBoxLayout()
        next_row.setSpacing(T.GAP_LG)
        self._next_hint = BodyLabel("")
        next_row.addWidget(self._next_hint, 1)
        self._next_btn = PrimaryPushButton("")
        self._next_btn.setFixedHeight(T.CONTROL_HEIGHT)
        self._next_btn.clicked.connect(self._on_next_clicked)
        next_row.addWidget(self._next_btn)
        footer_lay.addLayout(next_row)

        self._next_action: str = "import"
        self._pending_batch_id: str = ""

        self._footer.hide()
        self._body_lay.addWidget(self._footer)

        self._body_lay.addStretch(1)
        scroll.setWidget(body)
        root.addWidget(scroll)

        i18n.bus.language_changed.connect(self._retranslate)

    # ── Public API ────────────────────────────────────────────────

    def set_project_info(self, name: str, root: Path | None) -> None:
        """Update project context for rules summary."""
        self._project_name = name or ""
        self._project_root = root
        self._refresh_rules()

    def set_batches(self, summaries: list[dict]) -> None:
        """Populate batch list from ``all_batch_summaries()``."""
        self._summaries = summaries
        self._has_batches = bool(summaries)

        # Clear old cards
        while self._batch_container.count():
            item = self._batch_container.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        if not summaries:
            self._batch_section.hide()
            self._footer.hide()
            self._batch_count.setText("")
        else:
            self._batch_section.show()
            self._footer.show()

            total_items = sum(s.get("item_count", 0) for s in summaries)
            self._batch_count.setText(
                f"{len(summaries)} 批次 · {total_items:,} 张")

            # Show newest first
            for info in reversed(summaries):
                card = _BatchCard(info)
                card.commit_clicked.connect(self.commit_requested.emit)
                self._batch_container.addWidget(card)

        # Track first pending batch for next-step commit
        self._pending_batch_id = ""
        for s in reversed(summaries):  # newest first
            if _batch_status(s) in ("pending", "confirm"):
                self._pending_batch_id = s["batch_id"]
                break

        self._refresh_next_step()

    # ── Internals ─────────────────────────────────────────────────

    def _refresh_rules(self) -> None:
        """Update the compact rules line."""
        name = self._project_name or "—"
        root = self._project_root
        inbox = str(root / "_inbox") if root else "—"
        self._rule_line.setText(
            f"{i18n.t('inbox.rules.project')}: {name}  ·  "
            f"{i18n.t('inbox.rules.method')}: "
            f"{i18n.t('inbox.rules.method_copy')}  ·  "
            f"{i18n.t('inbox.rules.location')}: {inbox}"
        )

    def _refresh_next_step(self) -> None:
        """Update the next-step hint based on batch state."""
        from gui.widgets.workspace_sidebar import StageIndex

        summaries = self._summaries
        has_pending = any(
            _batch_status(s) in ("pending", "confirm")
            for s in summaries
        )
        has_conflict = any(
            _batch_status(s) == "conflict" for s in summaries
        )
        has_done = any(
            _batch_status(s) == "done" for s in summaries
        )

        if not summaries:
            # Footer is hidden — no next step needed
            self._next_action = "import"
            return
        elif has_conflict:
            self._next_hint.setText(i18n.t("inbox.next.conflict"))
            self._next_btn.setText(i18n.t("inbox.next.conflict_btn"))
            self._next_btn.setIcon(FIF.CERTIFICATE)
            self._next_action = f"stage:{StageIndex.REVIEW}"
        elif has_pending:
            self._next_hint.setText(i18n.t("inbox.next.pending"))
            self._next_btn.setText(i18n.t("inbox.next.pending_btn"))
            self._next_btn.setIcon(FIF.ACCEPT)
            self._next_action = "commit"
        elif has_done:
            self._next_hint.setText(i18n.t("inbox.next.done"))
            self._next_btn.setText(i18n.t("inbox.next.done_btn"))
            self._next_btn.setIcon(FIF.EDIT)
            self._next_action = f"stage:{StageIndex.ANNOTATE}"
        else:
            self._next_action = "import"

    def _on_next_clicked(self) -> None:
        action = getattr(self, "_next_action", "import")
        if action == "import":
            self.import_requested.emit()
        elif action == "commit":
            if self._pending_batch_id:
                self.commit_requested.emit(self._pending_batch_id)
        elif action.startswith("stage:"):
            try:
                stage = int(action.split(":")[1])
                self.navigate_stage.emit(stage)
            except (ValueError, IndexError):
                pass

    def _retranslate(self, _lang: str) -> None:
        self._drop_zone.retranslate()
        self._batch_title.setText(i18n.t("inbox.batches.title"))
        self._refresh_rules()
        self._refresh_next_step()
