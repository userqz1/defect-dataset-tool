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

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel,
    FluentIcon as FIF,
    PushButton,
)

from gui.theme import T


TOOL_SIDEBAR_WIDTH = 180


def _make_tool_button(text: str, icon: FIF) -> PushButton:
    """Build a full-width, left-aligned tool-row button.

    Factory rather than a PushButton subclass: qfluentwidgets'
    ``PushButton.__init__`` is a singledispatchmethod whose registered
    overloads internally call ``self.__init__(parent=parent)`` to chain
    into the base init. A subclass with a stricter signature gets caught
    in that recursion via MRO and crashes ("missing required positional
    arguments"). Composition sidesteps the whole problem.

    Visual rules (left-align + padding) live in app.qss under the
    ``QPushButton#toolSidebarButton`` selector — review #9 enforces the
    three-layer styling rule for padding/alignment too, not just colors.
    """
    btn = PushButton(text=text, icon=icon)
    btn.setObjectName("toolSidebarButton")
    btn.setFixedHeight(32)
    return btn


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
        self.setFixedWidth(TOOL_SIDEBAR_WIDTH)

        root = QVBoxLayout(self)
        root.setContentsMargins(T.GAP, T.GAP_LG, T.GAP, T.GAP_LG)
        root.setSpacing(T.GAP_XS)

        # ── Row 1: session controls ──
        self._refresh_btn = _make_tool_button("刷新", FIF.SYNC)
        self._refresh_btn.clicked.connect(self.refresh_requested.emit)
        # FIF.RETURN reads as "back / undo" in Fluent; FIF.CANCEL was the
        # cross icon which most users parse as "cancel current op" (review #11).
        self._undo_btn = _make_tool_button("撤销", FIF.RETURN)
        self._undo_btn.clicked.connect(self.undo_requested.emit)
        root.addWidget(self._refresh_btn)
        root.addWidget(self._undo_btn)

        # ── Analysis ──
        root.addWidget(self._section_header("分析"))
        self._quality_btn = _make_tool_button("质检", FIF.SEARCH)
        self._quality_btn.clicked.connect(self.quality_requested.emit)
        self._dedup_btn = _make_tool_button("去重", FIF.COPY)
        self._dedup_btn.clicked.connect(self.dedup_requested.emit)
        root.addWidget(self._quality_btn)
        root.addWidget(self._dedup_btn)

        # ── Processing (used to be a nested dropdown) ──
        root.addWidget(self._section_header("处理"))
        self._resize_btn = _make_tool_button("缩放", FIF.ZOOM)
        self._resize_btn.clicked.connect(self.resize_requested.emit)
        self._crop_btn = _make_tool_button("裁剪", FIF.CUT)
        self._crop_btn.clicked.connect(self.crop_requested.emit)
        self._rotate_btn = _make_tool_button("旋转", FIF.ROTATE)
        self._rotate_btn.clicked.connect(self.rotate_requested.emit)
        self._flip_btn = _make_tool_button("翻转", FIF.IOT)
        self._flip_btn.clicked.connect(self.flip_requested.emit)
        self._convert_btn = _make_tool_button("格式转换", FIF.PHOTO)
        self._convert_btn.clicked.connect(self.convert_requested.emit)
        self._augment_btn = _make_tool_button("数据增强", FIF.ADD)
        self._augment_btn.clicked.connect(self.augment_requested.emit)
        self._predict_btn = _make_tool_button("AI 预标注", FIF.ROBOT)
        self._predict_btn.clicked.connect(self.predict_requested.emit)
        for btn in (self._resize_btn, self._crop_btn, self._rotate_btn,
                    self._flip_btn, self._convert_btn, self._augment_btn,
                    self._predict_btn):
            root.addWidget(btn)

        # ── Output ──
        root.addWidget(self._section_header("输出"))
        self._export_btn = _make_tool_button("导出", FIF.SHARE)
        self._export_btn.clicked.connect(self.export_requested.emit)
        root.addWidget(self._export_btn)

        # ── Other ──
        root.addWidget(self._section_header("其他"))
        self._history_btn = _make_tool_button("历史", FIF.HISTORY)
        self._history_btn.clicked.connect(self.history_requested.emit)
        self._stats_btn = _make_tool_button("统计", FIF.PIE_SINGLE)
        self._stats_btn.clicked.connect(self.stats_requested.emit)
        root.addWidget(self._history_btn)
        root.addWidget(self._stats_btn)

        root.addStretch(1)

        # All buttons disabled until a dataset is active
        self.set_enabled(False)
        # Undo is separately gated on the history having a reversible entry
        self.set_undo_enabled(False)

    def _section_header(self, text: str) -> QWidget:
        lbl = CaptionLabel(text)
        lbl.setObjectName("toolSidebarSection")
        # A thin spacer above each section so sections breathe visually
        wrap = QWidget()
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(T.GAP, T.GAP, T.GAP, 0)
        lay.setSpacing(0)
        lay.addWidget(lbl)
        return wrap

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
