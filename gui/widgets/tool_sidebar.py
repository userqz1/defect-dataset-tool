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
    BodyLabel,
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
        self.setFixedHeight(T.CONTROL_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(T.PAD, 0, T.PAD, 0)
        lay.setSpacing(T.PAD)

        # Icon holder stays as a raw QLabel — the rule-5 exception
        # explicitly allows icon-only QLabel (setPixmap target). The
        # readable label below is the one that must be semantic.
        self._icon_label = QLabel()
        self._icon_label.setFixedSize(16, 16)
        self._icon_label.setPixmap(icon.icon().pixmap(QSize(16, 16)))
        self._icon_label.setObjectName("toolSidebarIcon")
        lay.addWidget(self._icon_label, 0, Qt.AlignmentFlag.AlignVCenter)

        # BodyLabel (qfluentwidgets) subclasses QLabel, so the existing
        # ``QLabel#toolSidebarText`` QSS selector still matches — no
        # QSS churn needed. Swapping in the semantic widget just keeps
        # the style-cop "no bare QLabel for human-readable text" rule
        # happy across the codebase.
        self._text_label = BodyLabel(text)
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


def _make_tool_button(kind: str, i18n_key: str, icon: FIF,
                       variant: str = "default") -> _ToolRow:
    """Build a tool row whose text comes from ``gui.i18n.t(i18n_key)``.

    ``kind`` is the dispatch tag emitted via ToolSidebar.tool_requested
    (e.g. "quality", "dedup"). ``variant`` maps to the QSS ``toolKind``
    property for styling (``default`` / ``featured`` / ``ai``).
    The row tracks its own key so ``ToolSidebar._retranslate`` can
    re-apply text on language change without rebuilding the tree.
    """
    row = _ToolRow(i18n.t(i18n_key), icon, variant)
    row._i18n_key = i18n_key  # type: ignore[attr-defined]
    row._kind = kind  # type: ignore[attr-defined]
    return row


# (kind, i18n_key, FIF icon, variant) — adding a new tool is a single
# line here plus a handler entry in DatasetBrowserView.TOOL_HANDLERS.
# Group boundaries are marked by None entries (rendered as section header).
_TOOL_LAYOUT: list = [
    # Common
    ("refresh", "tools.refresh", FIF.SYNC, "default"),
    ("undo", "tools.undo", FIF.RETURN, "default"),
    # Analysis
    ("__section__", "tools.group.analysis"),
    ("quality", "tools.quality", FIF.SEARCH, "default"),
    ("dedup", "tools.dedup", FIF.COPY, "default"),
    # Processing
    ("__section__", "tools.group.process"),
    ("resize", "tools.resize", FIF.ZOOM, "default"),
    ("crop", "tools.crop", FIF.CUT, "default"),
    ("rotate", "tools.rotate", FIF.ROTATE, "default"),
    ("flip", "tools.flip", FIF.IOT, "default"),
    ("convert", "tools.convert", FIF.PHOTO, "default"),
    ("augment", "tools.augment", FIF.ADD, "default"),
    ("predict", "tools.predict", FIF.ROBOT, "ai"),
    # Format center
    ("__section__", "tools.group.output"),
    ("import_annot", "tools.import_annot", FIF.FOLDER_ADD, "default"),
    ("convert_annot", "tools.convert_annot", FIF.SYNC, "default"),
    ("migrate_format", "tools.migrate_format", FIF.UPDATE, "default"),
    ("export", "tools.export", FIF.SHARE, "featured"),
    # Other
    ("__section__", "tools.group.other"),
    ("inbox", "tools.inbox", FIF.MAIL, "default"),
    ("history", "tools.history", FIF.HISTORY, "default"),
    ("stats", "tools.stats", FIF.PIE_SINGLE, "default"),
]


class ToolSidebar(QFrame):
    """Left-hand tool sidebar — data-driven layout + one dispatch signal.

    Adding a tool used to require touching three places (signal
    declaration, signal emit, DatasetBrowserView handler). With a
    single ``tool_requested(kind)`` signal + the ``_TOOL_LAYOUT`` table,
    a new tool is one row in the table + one entry in the outer
    view's handler map — review #15.
    """

    # Single dispatch signal — ``kind`` matches the tag in _TOOL_LAYOUT.
    tool_requested = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("toolSidebar")
        self.setFixedWidth(248)

        root = QVBoxLayout(self)
        root.setContentsMargins(T.GAP, T.GAP_LG, T.GAP, T.GAP_LG)
        root.setSpacing(T.GAP_XS)

        self._section_labels: list[tuple["CaptionLabel", str]] = []
        self._buttons: dict[str, _ToolRow] = {}

        for entry in _TOOL_LAYOUT:
            if entry[0] == "__section__":
                root.addWidget(self._section_header(entry[1]))
                continue
            kind, key, icon, variant = entry
            btn = _make_tool_button(kind, key, icon, variant=variant)
            btn.clicked.connect(
                lambda _b=False, k=kind: self.tool_requested.emit(k)
            )
            self._buttons[kind] = btn
            root.addWidget(btn)

        root.addStretch(1)

        self.set_enabled(False)
        self.set_undo_enabled(False)
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
        for btn in self._buttons.values():
            key = getattr(btn, "_i18n_key", None)
            if key:
                btn._text_label.setText(i18n.t(key))

    # -- Public API used by DatasetBrowserView --

    def set_enabled(self, enabled: bool) -> None:
        """Enable/disable dataset-scoped buttons (all except undo)."""
        for kind, btn in self._buttons.items():
            if kind == "undo":
                continue  # undo is separately gated
            btn.setEnabled(enabled)

    def set_undo_enabled(self, enabled: bool) -> None:
        btn = self._buttons.get("undo")
        if btn is not None:
            btn.setEnabled(enabled)

    def set_undo_tooltip(self, text: str) -> None:
        btn = self._buttons.get("undo")
        if btn is not None:
            btn.setToolTip(text)
