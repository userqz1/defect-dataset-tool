"""Workspace sidebar — vertical stage nav (slim list, no context column).

Lives as the leftmost column inside the workbench shell — narrower than
the v3.0 attempt that bundled a context panel inside it.  v3.1 splits
responsibilities cleanly:

    [WorkspaceSidebar (this)]   [middle work area]   [ContextPanel]
        only stage nav             stage page body      catalog / inspector

Each row is a custom :class:`_StageRow` widget — small leading icon +
left-aligned label — explicitly NOT a ``PushButton`` with ``setIcon``,
because qfluentwidgets' PushButton paints icon + text from a centered
layout that collides with narrow Chinese labels (the v3.0 bug).

**v3.2 (IA v2 phase 1)** — Six rows now, with 概览 at the top as the
new default landing:
    [▢] 概览 (Project Overview)        ← NEW default landing
    [▢] 新数据 (New Data)
    [▢] 数据处理 (Data Processing)
    [▢] 标注工作台 (Annotation Workbench)
    [▢] 审核修复 (Review & Fix)
    [▢] 导出 (Export)

Bar emits ``stage_changed(index)`` whenever the active row flips; the
owning ``DatasetBrowserView`` routes that into its ``QStackedWidget``.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import BodyLabel, CaptionLabel, FluentIcon as FIF

from gui import i18n
from gui.theme import T


# (i18n_key, FluentIcon).  Order matches the StageIndex constants below.
_STAGES: list[tuple[str, FIF]] = [
    ("stage.overview", FIF.HOME),
    ("stage.inbox",    FIF.MAIL),
    ("stage.process",  FIF.DEVELOPER_TOOLS),
    ("stage.annotate", FIF.EDIT),
    ("stage.review",   FIF.CERTIFICATE),
    ("stage.delivery", FIF.SHARE),
]


# Named indices — callers import these instead of typing raw ints, so
# a later reorder doesn't silently break the wiring.
class StageIndex:
    OVERVIEW = 0    # 项目概览 (NEW · IA v2 phase 1)
    INBOX = 1       # 新数据
    PROCESS = 2     # 数据处理
    ANNOTATE = 3    # 标注工作台
    REVIEW = 4      # 审核修复
    DELIVERY = 5    # 导出


class _StageRow(QFrame):
    """Single stage row — icon + label, full-row hover + selected state.

    Built as a custom widget rather than ``PushButton.setIcon(...)``
    because qfluentwidgets' PushButton centers icon + text from a
    shared layout, which produces glyph-on-glyph collisions for narrow
    rows with multi-character Chinese labels.  Doing the layout
    ourselves keeps icon and text on a clean two-column row.
    """

    clicked = pyqtSignal()

    def __init__(self, icon_resource: FIF, label_text: str,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("workspaceSidebarRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(T.WORKSPACE_SIDEBAR_PILL_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(T.GAP_LG, 0, T.GAP_LG, 0)
        lay.setSpacing(T.GAP)

        self._icon_resource = icon_resource
        self._icon_label = QLabel()
        self._icon_label.setFixedSize(16, 16)
        self._icon_label.setObjectName("workspaceSidebarRowIcon")
        self._refresh_icon()
        lay.addWidget(self._icon_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self._text_label = BodyLabel(label_text)
        self._text_label.setObjectName("workspaceSidebarRowLabel")
        lay.addWidget(self._text_label, 1, Qt.AlignmentFlag.AlignVCenter)

        # Optional badge — count of pending items for this stage
        # (e.g. "12" on 新数据 when 12 batches are unprocessed).
        # Hidden until set_badge() is called with a non-zero value.
        self._badge_label = CaptionLabel("")
        self._badge_label.setObjectName("workspaceSidebarRowBadge")
        self._badge_label.setVisible(False)
        lay.addWidget(self._badge_label, 0, Qt.AlignmentFlag.AlignVCenter)

        # Track selected via a QSS dynamic property + a manual
        # unpolish/polish on flip — Qt won't re-evaluate selectors with
        # custom properties unless the style is reapplied.
        self._selected: bool = False
        self.setProperty("selected", "false")

    # -- Public --

    def setText(self, text: str) -> None:
        self._text_label.setText(text)

    def setBadge(self, count: int | None) -> None:
        """Set the right-aligned badge count.

        ``None`` or 0 hides the badge; positive integers show as a
        formatted count ("9999+" caps long values).
        """
        if not count:
            self._badge_label.setVisible(False)
            self._badge_label.setText("")
            return
        text = str(count) if count < 10000 else "9999+"
        self._badge_label.setText(text)
        self._badge_label.setVisible(True)

    def setSelected(self, selected: bool) -> None:
        if selected == self._selected:
            return
        self._selected = selected
        self.setProperty("selected", "true" if selected else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def isSelected(self) -> bool:
        return self._selected

    # -- Internals --

    def _refresh_icon(self) -> None:
        # FluentIcon.icon() honors the current Theme — no manual
        # color flip needed when the user toggles theme.
        self._icon_label.setPixmap(
            self._icon_resource.icon().pixmap(16, 16)
        )

    def mousePressEvent(self, e: QMouseEvent) -> None:  # type: ignore[override]
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)


class WorkspaceSidebar(QFrame):
    """Slim vertical stage nav — five rows, no context column."""

    stage_changed = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("workspaceSidebar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(T.WORKSPACE_SIDEBAR_WIDTH)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(T.GAP, T.GAP_LG, T.GAP, T.GAP_LG)
        lay.setSpacing(T.GAP_XS)

        self._rows: list[_StageRow] = []
        for idx, (key, icon) in enumerate(_STAGES):
            row = _StageRow(icon, i18n.t(key))
            row.clicked.connect(lambda i=idx: self._select(i))
            lay.addWidget(row)
            self._rows.append(row)
        lay.addStretch(1)

        # Default selection — Overview, the new IA v2 default landing
        # where users see the whole project at a glance before diving
        # into a specific tool surface.  Signal firing is suppressed
        # during construction (we set _current after).
        self._current: int = -1
        self._rows[StageIndex.OVERVIEW].setSelected(True)
        self._current = StageIndex.OVERVIEW

        i18n.bus.language_changed.connect(self._retranslate)

    # -- Public API --

    def current_stage(self) -> int:
        return self._current

    def set_current_stage(self, index: int) -> None:
        """Programmatically select a stage (no signal emission)."""
        if 0 <= index < len(self._rows) and index != self._current:
            self._set_active(index, emit=False)

    def set_badge(self, stage_index: int, count: int | None) -> None:
        """Set the count badge for a stage row.

        ``count=None`` or ``0`` hides the badge.  Wired by the owning
        view from AppState.workflow_summary so users see at-a-glance
        what's pending in each stage.
        """
        if 0 <= stage_index < len(self._rows):
            self._rows[stage_index].setBadge(count)

    # -- Internals --

    def _select(self, index: int) -> None:
        if index == self._current:
            return
        self._set_active(index, emit=True)

    def _set_active(self, index: int, *, emit: bool) -> None:
        for i, row in enumerate(self._rows):
            row.setSelected(i == index)
        self._current = index
        if emit:
            self.stage_changed.emit(index)

    def _retranslate(self, _lang: str) -> None:
        for idx, (key, _icon) in enumerate(_STAGES):
            self._rows[idx].setText(i18n.t(key))
