"""Vertical tool sidebar for the dataset browser.

Replaces the horizontal toolbar (which was running out of horizontal
space — 6+ buttons plus History/Stats on the right crammed every screen
below 1280 wide). Buttons are grouped by function with section headers
so the user scans vertically by intent:

  [ 刷新 / 撤销 ]
  ── 分析 ──
  [ 质检 / 去重 ]
  ── 处理 ──  (no more dropdown)
  [ 缩放 / 裁剪 / 旋转 / 翻转 / 格式转换 / 数据增强 / AI 预标注 ]
  ── 输出 ──
  [ 导出 ]
  ── 其他 ──
  [ 历史 / 统计 ]

Each button is a full-width row with an icon + label (left-aligned).
Signals mirror the old toolbar handlers; DatasetBrowserView wires them
to the same _on_* methods without any handler-level refactor.
"""
from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel,
    FluentIcon as FIF,
)

from gui import i18n
from gui.theme import T


class _ToolRow(QFrame):
    """Tool-row widget: 16px icon + gap + text (left-aligned).

    We build our own widget rather than reuse qfluentwidgets.PushButton
    because Chinese labels like "格式转换" / "AI 预标注" collide with the
    icon under PushButton's ``text-align: left`` QSS: icon and text both
    anchor to the same x-origin so long labels overlap the icon.
    Splitting into explicit QLabel children in an HBoxLayout gives the
    icon and text dedicated horizontal slots — no more overlap at any
    window width.

    States (background / border) come from app.qss under
    ``QFrame#toolSidebarButton`` + the ``toolKind`` property selector:

    - ``default`` — transparent, soft hover.
    - ``featured`` — white panel + 1px border (marquee actions, 导出).
    - ``ai`` — accent-soft hover (AI 预标注).
    """

    clicked = pyqtSignal()

    def __init__(self, text: str, icon: FIF, kind: str = "default") -> None:
        super().__init__()
        self.setObjectName("toolSidebarButton")
        self.setProperty("toolKind", kind)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setFixedHeight(32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 10, 0)
        lay.setSpacing(10)

        self._icon_label = QLabel()
        self._icon_label.setFixedSize(16, 16)
        self._icon_label.setPixmap(icon.icon().pixmap(QSize(16, 16)))
        self._icon_label.setObjectName("toolSidebarIcon")
        lay.addWidget(self._icon_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self._text_label = QLabel(text)
        self._text_label.setObjectName("toolSidebarText")
        lay.addWidget(self._text_label, 1)

    # -- click behavior --

    def mousePressEvent(self, e: QMouseEvent) -> None:  # type: ignore[override]
        if e.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self._pressed = True
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:  # type: ignore[override]
        if (e.button() == Qt.MouseButton.LeftButton
                and getattr(self, "_pressed", False)
                and self.rect().contains(e.position().toPoint())
                and self.isEnabled()):
            self.clicked.emit()
        self._pressed = False
        super().mouseReleaseEvent(e)

    # -- graceful disabled styling via Qt palette cascade --

    def setEnabled(self, enabled: bool) -> None:  # type: ignore[override]
        super().setEnabled(enabled)
        # Property-based QSS re-evaluation so [disabled="true"] rules kick in
        self.setProperty("btnDisabled", not enabled)
        self.style().unpolish(self)
        self.style().polish(self)


def _make_tool_button(i18n_key: str, icon: FIF, kind: str = "default") -> _ToolRow:
    """Build a tool row whose text comes from ``gui.i18n.t(i18n_key)``.

    The row tracks its own key so ``ToolSidebar._retranslate`` can re-apply
    text on language change without rebuilding the widget tree.
    """
    row = _ToolRow(i18n.t(i18n_key), icon, kind)
    row._i18n_key = i18n_key  # type: ignore[attr-defined]
    return row


class ToolSidebar(QFrame):
    """Left-hand tool sidebar — 14 actions across 4 function groups."""

    # Signals — direct 1:1 with existing handlers in DatasetBrowserView
    refresh_requested = pyqtSignal()
    undo_requested = pyqtSignal()

    quality_requested = pyqtSignal()
    dedup_requested = pyqtSignal()

    resize_requested = pyqtSignal()
    crop_requested = pyqtSignal()
    rotate_requested = pyqtSignal()
    flip_requested = pyqtSignal()
    convert_requested = pyqtSignal()
    augment_requested = pyqtSignal()
    predict_requested = pyqtSignal()

    export_requested = pyqtSignal()

    history_requested = pyqtSignal()
    stats_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("toolSidebar")
        # Design handoff: ToolsPanel is 248px wide (collapses to 60px).
        # We live as our own column now (not nested inside BrowserView).
        self.setFixedWidth(248)

        root = QVBoxLayout(self)
        root.setContentsMargins(T.GAP, T.GAP_LG, T.GAP, T.GAP_LG)
        root.setSpacing(T.GAP_XS)

        # Track (widget, i18n_key) pairs so language-switch retranslation
        # is a cheap walk + setText instead of rebuilding the tree.
        self._section_labels: list[tuple["CaptionLabel", str]] = []

        # ── Row 1: session controls ──
        self._refresh_btn = _make_tool_button("tools.refresh", FIF.SYNC)
        self._refresh_btn.clicked.connect(self.refresh_requested.emit)
        # FIF.RETURN reads as "back / undo" in Fluent; FIF.CANCEL was the
        # cross icon which most users parse as "cancel current op" (review #11).
        self._undo_btn = _make_tool_button("tools.undo", FIF.RETURN)
        self._undo_btn.clicked.connect(self.undo_requested.emit)
        root.addWidget(self._refresh_btn)
        root.addWidget(self._undo_btn)

        # ── Analysis ──
        root.addWidget(self._section_header("tools.group.analysis"))
        self._quality_btn = _make_tool_button("tools.quality", FIF.SEARCH)
        self._quality_btn.clicked.connect(self.quality_requested.emit)
        self._dedup_btn = _make_tool_button("tools.dedup", FIF.COPY)
        self._dedup_btn.clicked.connect(self.dedup_requested.emit)
        root.addWidget(self._quality_btn)
        root.addWidget(self._dedup_btn)

        # ── Processing ──
        root.addWidget(self._section_header("tools.group.process"))
        self._resize_btn = _make_tool_button("tools.resize", FIF.ZOOM)
        self._resize_btn.clicked.connect(self.resize_requested.emit)
        self._crop_btn = _make_tool_button("tools.crop", FIF.CUT)
        self._crop_btn.clicked.connect(self.crop_requested.emit)
        self._rotate_btn = _make_tool_button("tools.rotate", FIF.ROTATE)
        self._rotate_btn.clicked.connect(self.rotate_requested.emit)
        self._flip_btn = _make_tool_button("tools.flip", FIF.IOT)
        self._flip_btn.clicked.connect(self.flip_requested.emit)
        self._convert_btn = _make_tool_button("tools.convert", FIF.PHOTO)
        self._convert_btn.clicked.connect(self.convert_requested.emit)
        self._augment_btn = _make_tool_button("tools.augment", FIF.ADD)
        self._augment_btn.clicked.connect(self.augment_requested.emit)
        self._predict_btn = _make_tool_button("tools.predict", FIF.ROBOT, kind="ai")
        self._predict_btn.clicked.connect(self.predict_requested.emit)
        for btn in (self._resize_btn, self._crop_btn, self._rotate_btn,
                    self._flip_btn, self._convert_btn, self._augment_btn,
                    self._predict_btn):
            root.addWidget(btn)

        # ── Output ──
        root.addWidget(self._section_header("tools.group.output"))
        self._export_btn = _make_tool_button("tools.export", FIF.SHARE, kind="featured")
        self._export_btn.clicked.connect(self.export_requested.emit)
        root.addWidget(self._export_btn)

        # ── Other ──
        root.addWidget(self._section_header("tools.group.other"))
        self._history_btn = _make_tool_button("tools.history", FIF.HISTORY)
        self._history_btn.clicked.connect(self.history_requested.emit)
        self._stats_btn = _make_tool_button("tools.stats", FIF.PIE_SINGLE)
        self._stats_btn.clicked.connect(self.stats_requested.emit)
        root.addWidget(self._history_btn)
        root.addWidget(self._stats_btn)

        root.addStretch(1)

        # All buttons disabled until a dataset is active
        self.set_enabled(False)
        self.set_undo_enabled(False)

        # Subscribe to language changes for live re-text (header + section +
        # button labels in one sweep).
        i18n.bus.language_changed.connect(self._retranslate)

    def _section_header(self, i18n_key: str) -> QWidget:
        # Uppercase in Python since Qt QSS has no text-transform. The
        # widget is tracked in _section_labels so retranslate can swap
        # text without rebuilding the sidebar.
        lbl = CaptionLabel(i18n.t(i18n_key).upper())
        lbl.setObjectName("toolSidebarSection")
        self._section_labels.append((lbl, i18n_key))
        wrap = QWidget()
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(T.GAP, T.GAP_LG, T.GAP, 0)
        lay.setSpacing(0)
        lay.addWidget(lbl)
        return wrap

    def _retranslate(self, _lang: str) -> None:
        """Re-apply i18n text to all tracked labels & buttons."""
        for lbl, key in self._section_labels:
            lbl.setText(i18n.t(key).upper())
        for btn in (self._refresh_btn, self._undo_btn, self._quality_btn,
                     self._dedup_btn, self._resize_btn, self._crop_btn,
                     self._rotate_btn, self._flip_btn, self._convert_btn,
                     self._augment_btn, self._predict_btn, self._export_btn,
                     self._history_btn, self._stats_btn):
            key = getattr(btn, "_i18n_key", None)
            if key:
                btn._text_label.setText(i18n.t(key))

    # -- Public API used by DatasetBrowserView --

    def set_enabled(self, enabled: bool) -> None:
        """Enable/disable dataset-scoped buttons (all except undo)."""
        for btn in (self._refresh_btn, self._quality_btn, self._dedup_btn,
                    self._resize_btn, self._crop_btn, self._rotate_btn,
                    self._flip_btn, self._convert_btn, self._augment_btn,
                    self._predict_btn, self._export_btn,
                    self._history_btn, self._stats_btn):
            btn.setEnabled(enabled)

    def set_undo_enabled(self, enabled: bool) -> None:
        self._undo_btn.setEnabled(enabled)

    def set_undo_tooltip(self, text: str) -> None:
        self._undo_btn.setToolTip(text)
