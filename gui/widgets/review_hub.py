"""审核修复 (Review) hub — issue queue + duplicate-group queue + detail.

P1.3 rebuild — turns the v3 button list into a real review workbench:

    ┌─────────────────────────────────────────────────────────────┐
    │ [运行质量检查]  [运行重复检测]  [查看统计]                       │  <- toolbar
    │                                                             │
    │ 问题 12 · 重复组 4 · 待修补 8 · 可导出 320                     │  <- summary
    │                                                             │
    │ ┌────────────────────┬────────────────────────────────────┐ │
    │ │ [问题] [重复组]      │ filename                            │ │
    │ │                    │ ┌────────────────────────────────┐ │ │
    │ │ ● blur foo.jpg     │ │       image preview            │ │ │
    │ │ ● corrupt bar.jpg  │ │                                │ │ │
    │ │ …                  │ └────────────────────────────────┘ │ │
    │ │                    │ 问题类型 · 模糊                       │ │
    │ │                    │ 原因 · Laplacian 方差 12             │ │
    │ │                    │ 影响范围 · 当前图                      │ │
    │ │                    │                                    │ │
    │ │                    │ [打开图片] [设为需修补] [从队列移除]    │ │
    │ └────────────────────┴────────────────────────────────────┘ │
    └─────────────────────────────────────────────────────────────┘

The hub renders directly off :class:`gui.app_state.AppState` artifacts:
``quality_issues`` and ``duplicate_groups``.  No separate worker; the
existing toolbar runs the analyses, AppState publishes results, and
this hub repaints from them.

"Ignore" is session-only: paths added to ``_ignored`` skip rendering
this session but persist nowhere on disk — restart clears the slate
and the user can re-evaluate.

"Mark needs fix" emits a :class:`pyqtSignal` so :class:`DatasetBrowserView`
can reuse the same workflow-status path that DetailView's status pane
already drives.

"Open image" emits ``jump_to_image_requested(ImageInfo)``; the shell
swaps stage to 标注工作台 and opens DetailView on the chosen image.

Backwards-compat: keeps the v3 zero-arg signals (``quality_requested``
/ ``dedup_requested`` / ``stats_requested``) so the existing
controller wires keep working unchanged.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    FluentIcon as FIF,
    Pivot,
    PushButton,
    StrongBodyLabel,
    TitleLabel,
)

from core.models import ImageInfo
from gui import i18n
from gui.theme import T
from gui.widgets.scope_badge import Scope, ScopeBadge


# ── Display helpers ─────────────────────────────────────────────────

# QualityIssue.kinds → i18n display key.
_KIND_LABEL_KEY = {
    "corrupt":     "review.kind.corrupt",
    "blank":       "review.kind.blank",
    "blur":        "review.kind.blur",
    "over":        "review.kind.over",
    "under":       "review.kind.under",
    "empty_label": "review.kind.empty_label",
    "zero_area":   "review.kind.zero_area",
    "oob":         "review.kind.oob",
}

# Reason templates — keyed by kind. Values are i18n template keys; the
# template string carries {field} placeholders filled from the issue's
# metrics dict.
_KIND_REASON_KEY = {
    "corrupt":     "review.reason.corrupt",
    "blank":       "review.reason.blank",
    "blur":        "review.reason.blur",
    "over":        "review.reason.over",
    "under":       "review.reason.under",
    "empty_label": "review.reason.empty_label",
    "zero_area":   "review.reason.zero_area",
    "oob":         "review.reason.oob",
}


def _kind_label(kind: str) -> str:
    """Map a quality-kind code to its display label, fallback to raw key."""
    key = _KIND_LABEL_KEY.get(kind)
    return i18n.t(key) if key else kind


def _kind_reason(kind: str, metrics: dict | None) -> str:
    """Render a one-line reason string for a kind + metrics dict.

    Metric-free kinds (corrupt / empty_label / zero_area / oob) use the
    plain reason template; metric-driven kinds (blank / blur / over /
    under) format ``std`` / ``lap_var`` / ``mean`` into the template.
    Missing metrics fall back to "—" so the string never crashes.
    """
    key = _KIND_REASON_KEY.get(kind)
    if key is None:
        return ""
    template = i18n.t(key)
    metrics = metrics or {}
    try:
        return template.format(
            std=metrics.get("std", float("nan")),
            lap_var=metrics.get("lap_var", float("nan")),
            mean=metrics.get("mean", float("nan")),
        )
    except (KeyError, ValueError):
        return template


def _btn_with_scope(btn: PushButton, badge: ScopeBadge) -> QHBoxLayout:
    """Tight horizontal pair so a scope badge always rides with its button."""
    h = QHBoxLayout()
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(T.GAP_XS)
    h.addWidget(btn)
    h.addWidget(badge)
    return h


# ── Top toolbar + summary strip ────────────────────────────────────

class _ReviewToolbar(QFrame):
    """Top toolbar — three primary "run analysis / view" actions."""

    quality_clicked = pyqtSignal()
    dedup_clicked = pyqtSignal()
    stats_clicked = pyqtSignal()
    fix_oob_clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("reviewToolbar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(T.PAD_XL, T.GAP_LG, T.PAD_XL, T.GAP_LG)
        lay.setSpacing(T.GAP_LG)

        # Each button is paired with a neutral "整库 N" scope badge
        # so the user can see that these analyses run against the whole
        # project, not the current selection. Counts are pushed via
        # ``set_dataset_count`` on dataset_changed.
        self._quality_btn = PushButton(i18n.t("review.toolbar.run_quality"))
        self._quality_btn.setIcon(FIF.SEARCH)
        self._quality_btn.setFixedHeight(32)
        self._quality_btn.clicked.connect(self.quality_clicked.emit)
        self._quality_scope = ScopeBadge(
            i18n.t("scope.dataset_unknown"), Scope.NEUTRAL)
        lay.addLayout(self._pair(self._quality_btn, self._quality_scope))

        self._dedup_btn = PushButton(i18n.t("review.toolbar.run_dedup"))
        self._dedup_btn.setIcon(FIF.COPY)
        self._dedup_btn.setFixedHeight(32)
        self._dedup_btn.clicked.connect(self.dedup_clicked.emit)
        self._dedup_scope = ScopeBadge(
            i18n.t("scope.dataset_unknown"), Scope.NEUTRAL)
        lay.addLayout(self._pair(self._dedup_btn, self._dedup_scope))

        self._stats_btn = PushButton(i18n.t("review.toolbar.view_stats"))
        self._stats_btn.setIcon(FIF.PIE_SINGLE)
        self._stats_btn.setFixedHeight(32)
        self._stats_btn.clicked.connect(self.stats_clicked.emit)
        self._stats_scope = ScopeBadge(
            i18n.t("scope.dataset_unknown"), Scope.NEUTRAL)
        lay.addLayout(self._pair(self._stats_btn, self._stats_scope))

        # 修复越界框 — clamp OOB boxes to the image edge + drop strays.
        # A write action (unlike the three analyses above) but it belongs
        # here: 质检 is what surfaces the oob / zero_area counts this fixes.
        self._fix_oob_btn = PushButton(i18n.t("review.toolbar.fix_oob"))
        self._fix_oob_btn.setIcon(FIF.EDIT)
        self._fix_oob_btn.setFixedHeight(32)
        self._fix_oob_btn.clicked.connect(self.fix_oob_clicked.emit)
        self._fix_oob_scope = ScopeBadge(
            i18n.t("scope.dataset_unknown"), Scope.NEUTRAL)
        lay.addLayout(self._pair(self._fix_oob_btn, self._fix_oob_scope))

        lay.addStretch(1)
        self._dataset_count: int = 0

    @staticmethod
    def _pair(btn: PushButton, badge: ScopeBadge) -> QHBoxLayout:
        """Tight horizontal pair so the badge always rides with the button."""
        h = QHBoxLayout()
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(T.GAP_XS)
        h.addWidget(btn)
        h.addWidget(badge)
        return h

    def set_enabled(self, enabled: bool) -> None:
        for btn in (self._quality_btn, self._dedup_btn, self._stats_btn,
                    self._fix_oob_btn):
            btn.setEnabled(enabled)

    def set_dataset_count(self, n: int) -> None:
        """Refresh the "整库 N 张" copy on every scope badge."""
        self._dataset_count = n
        text = (i18n.t("scope.dataset", n=n) if n > 0
                else i18n.t("scope.dataset_unknown"))
        for badge in (self._quality_scope, self._dedup_scope,
                      self._stats_scope, self._fix_oob_scope):
            badge.setText(text)

    def retranslate(self) -> None:
        self._quality_btn.setText(i18n.t("review.toolbar.run_quality"))
        self._dedup_btn.setText(i18n.t("review.toolbar.run_dedup"))
        self._stats_btn.setText(i18n.t("review.toolbar.view_stats"))
        self._fix_oob_btn.setText(i18n.t("review.toolbar.fix_oob"))
        # Repaint the scope badges so the localized template applies.
        self.set_dataset_count(self._dataset_count)


class _SummaryStrip(QFrame):
    """4-cell summary strip showing review-level dataset counts."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("reviewSummary")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(T.PAD_XL, T.PAD_LG, T.PAD_XL, T.PAD_LG)
        lay.setSpacing(T.PAD_2XL)

        self._issues = self._cell("review.summary.issues")
        self._dup = self._cell("review.summary.dup_groups")
        self._needs_fix = self._cell("review.summary.needs_fix", warn=True)
        self._ready = self._cell("review.summary.ready")

        for cell in (self._issues, self._dup,
                     self._needs_fix, self._ready):
            lay.addLayout(cell["lay"])
        lay.addStretch(1)

    def _cell(self, key_i18n: str, *, warn: bool = False) -> dict:
        v = StrongBodyLabel("—")
        v.setObjectName("reviewSummaryValue")
        if warn:
            v.setProperty("warn", "true")
        k = CaptionLabel(i18n.t(key_i18n))
        k.setObjectName("reviewSummaryKey")
        lay = QVBoxLayout()
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(v)
        lay.addWidget(k)
        return {"value": v, "key": k, "key_i18n": key_i18n, "lay": lay}

    def set_counts(self, *, issues: int, dup_groups: int,
                    needs_fix: int, ready: int) -> None:
        self._issues["value"].setText(f"{issues:,}")
        self._dup["value"].setText(f"{dup_groups:,}")
        self._needs_fix["value"].setText(f"{needs_fix:,}")
        self._ready["value"].setText(f"{ready:,}")

    def retranslate(self) -> None:
        for cell in (self._issues, self._dup,
                     self._needs_fix, self._ready):
            cell["key"].setText(i18n.t(cell["key_i18n"]))


# ── Detail pane ────────────────────────────────────────────────────

class _IssueDetailPane(QFrame):
    """Right-side detail surface — preview + meta + actions."""

    jump_requested = pyqtSignal(object)               # ImageInfo
    mark_fix_requested = pyqtSignal(object)           # ImageInfo
    ignore_requested = pyqtSignal(object, str)        # ImageInfo, kind/group

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("reviewDetail")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(T.PAD_XL, T.PAD_LG, T.PAD_XL, T.PAD_LG)
        lay.setSpacing(T.GAP_LG)

        # Stack: empty placeholder ↔ live detail content
        self._stack = QStackedWidget()
        self._stack.setObjectName("reviewDetailStack")
        lay.addWidget(self._stack, 1)

        # -- Page 0: empty
        empty = QWidget()
        empty_lay = QVBoxLayout(empty)
        empty_lay.addStretch(1)
        empty_msg = CaptionLabel(i18n.t("review.empty.detail"))
        empty_msg.setObjectName("reviewDetailEmpty")
        empty_msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_lay.addWidget(empty_msg)
        empty_lay.addStretch(1)
        self._stack.addWidget(empty)
        self._empty_msg = empty_msg

        # -- Page 1: live detail
        live = QWidget()
        live_lay = QVBoxLayout(live)
        live_lay.setContentsMargins(0, 0, 0, 0)
        live_lay.setSpacing(T.GAP_LG)

        self._title = TitleLabel("—")
        self._title.setObjectName("reviewDetailTitle")
        live_lay.addWidget(self._title)

        # Image preview — fixed-height frame; pixmap is loaded
        # synchronously and scaled on bind.
        self._preview = QLabel()
        self._preview.setObjectName("reviewDetailPreview")
        self._preview.setMinimumHeight(220)
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setAttribute(
            Qt.WidgetAttribute.WA_StyledBackground, True)
        live_lay.addWidget(self._preview)

        # Three meta rows (问题类型 / 原因 / 影响范围)
        meta = QFrame()
        meta_lay = QVBoxLayout(meta)
        meta_lay.setContentsMargins(0, 0, 0, 0)
        meta_lay.setSpacing(T.GAP)

        self._meta_kind = self._meta_row("review.detail.kind")
        self._meta_reason = self._meta_row("review.detail.reason")
        self._meta_scope = self._meta_row("review.detail.scope")
        meta_lay.addLayout(self._meta_kind["lay"])
        meta_lay.addLayout(self._meta_reason["lay"])
        meta_lay.addLayout(self._meta_scope["lay"])
        live_lay.addWidget(meta)

        # Action row — every button carries a scope badge so the user
        # reads the impact at a glance: jump/mark are 当前图,
        # 设为需修补 is also project-writing, ignore is session-only.
        actions = QHBoxLayout()
        actions.setSpacing(T.GAP_LG)
        actions.addStretch(1)

        self._jump_btn = PushButton(i18n.t("review.action.jump"))
        self._jump_btn.setIcon(FIF.RIGHT_ARROW)
        self._jump_btn.setFixedHeight(32)
        self._jump_btn.clicked.connect(self._on_jump)
        self._jump_scope = ScopeBadge(
            i18n.t("scope.current_image"), Scope.NEUTRAL)
        actions.addLayout(_btn_with_scope(self._jump_btn, self._jump_scope))

        self._mark_btn = PushButton(i18n.t("review.action.mark_fix"))
        self._mark_btn.setFixedHeight(32)
        self._mark_btn.clicked.connect(self._on_mark)
        self._mark_scope = ScopeBadge(
            i18n.t("scope.writes_project"), Scope.WRITES)
        actions.addLayout(_btn_with_scope(self._mark_btn, self._mark_scope))

        self._ignore_btn = PushButton(i18n.t("review.action.ignore"))
        self._ignore_btn.setFixedHeight(32)
        self._ignore_btn.clicked.connect(self._on_ignore)
        self._ignore_scope = ScopeBadge(
            i18n.t("scope.session_only"), Scope.NEUTRAL)
        actions.addLayout(
            _btn_with_scope(self._ignore_btn, self._ignore_scope))

        live_lay.addLayout(actions)

        live_lay.addStretch(1)
        self._stack.addWidget(live)

        # State for action handlers
        self._current_image: ImageInfo | None = None
        self._current_kind: str = ""

        self._stack.setCurrentIndex(0)

    def _meta_row(self, key_i18n: str) -> dict:
        k = CaptionLabel(i18n.t(key_i18n))
        k.setObjectName("reviewDetailMetaKey")
        k.setFixedWidth(72)
        v = BodyLabel("—")
        v.setObjectName("reviewDetailMetaValue")
        v.setWordWrap(True)
        lay = QHBoxLayout()
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(T.GAP)
        lay.addWidget(k, 0, Qt.AlignmentFlag.AlignTop)
        lay.addWidget(v, 1)
        return {"key": k, "value": v, "key_i18n": key_i18n, "lay": lay}

    # -- Public API --

    def show_empty(self) -> None:
        self._current_image = None
        self._current_kind = ""
        self._stack.setCurrentIndex(0)

    def show_issue(self, image: ImageInfo, kind: str,
                   metrics: dict | None) -> None:
        self._current_image = image
        self._current_kind = kind
        self._title.setText(image.path.name)
        self._load_preview(image.path)
        self._meta_kind["value"].setText(_kind_label(kind))
        self._meta_reason["value"].setText(_kind_reason(kind, metrics))
        self._meta_scope["value"].setText(
            i18n.t("review.detail.scope_image"))
        self._stack.setCurrentIndex(1)

    def show_dup_group(self, group) -> None:
        self._current_image = group.images[0] if group.images else None
        self._current_kind = "duplicate"
        if self._current_image is not None:
            self._title.setText(self._current_image.path.name)
            self._load_preview(self._current_image.path)
        else:
            self._title.setText("—")
            self._preview.clear()
        self._meta_kind["value"].setText(i18n.t("review.kind.duplicate"))
        try:
            template = i18n.t("review.reason.duplicate")
            self._meta_reason["value"].setText(
                template.format(hash=group.hash_value))
        except (KeyError, ValueError):
            self._meta_reason["value"].setText("")
        self._meta_scope["value"].setText(
            i18n.t("review.detail.scope_group", n=len(group.images)))
        self._stack.setCurrentIndex(1)

    def retranslate(self) -> None:
        self._empty_msg.setText(i18n.t("review.empty.detail"))
        for row in (self._meta_kind, self._meta_reason, self._meta_scope):
            row["key"].setText(i18n.t(row["key_i18n"]))
        self._jump_btn.setText(i18n.t("review.action.jump"))
        self._mark_btn.setText(i18n.t("review.action.mark_fix"))
        self._ignore_btn.setText(i18n.t("review.action.ignore"))
        self._jump_scope.setText(i18n.t("scope.current_image"))
        self._mark_scope.setText(i18n.t("scope.writes_project"))
        self._ignore_scope.setText(i18n.t("scope.session_only"))

    # -- Internals --

    def _load_preview(self, image_path: Path) -> None:
        """Synchronous downscaled preview load.

        The review pane is interactive but not super-tight on
        latency — a fast QPixmap load + smooth scale fits in a frame
        for any normal-sized photo.  Skips on read failures (corrupt
        images leave the preview blank, which is a useful signal).
        """
        try:
            pix = QPixmap(str(image_path))
        except Exception:
            pix = QPixmap()
        if pix.isNull():
            self._preview.clear()
            self._preview.setText("—")
            return
        target = self._preview.size()
        scaled = pix.scaled(
            target.width() if target.width() > 0 else 320,
            target.height() if target.height() > 0 else 220,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._preview.setPixmap(scaled)

    def _on_jump(self) -> None:
        if self._current_image is not None:
            self.jump_requested.emit(self._current_image)

    def _on_mark(self) -> None:
        if self._current_image is not None:
            self.mark_fix_requested.emit(self._current_image)

    def _on_ignore(self) -> None:
        if self._current_image is not None:
            self.ignore_requested.emit(
                self._current_image, self._current_kind)


# ── Hub ─────────────────────────────────────────────────────────────

class ReviewHub(QFrame):
    """审核修复 stage body — issue/duplicate queue + detail pane."""

    # Backwards-compat zero-arg signals (controller wire stays unchanged).
    quality_requested = pyqtSignal()
    dedup_requested = pyqtSignal()
    stats_requested = pyqtSignal()
    fix_oob_requested = pyqtSignal()

    # New — DatasetBrowserView subscribes to drive the workbench shell.
    jump_to_image_requested = pyqtSignal(object)         # ImageInfo
    mark_needs_fix_requested = pyqtSignal(object)        # ImageInfo

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("reviewHub")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        # Session-only ignore set: paths whose issues the user has
        # dismissed for this session.  No on-disk persistence — the
        # next quality run regenerates a fresh queue.
        self._ignored_paths: set[str] = set()
        # Cached AppState artifacts (so retranslate / re-render don't
        # need to ask the state object again).
        self._issues: list = []
        self._dup_groups: list = []
        self._wf_needs_fix: int = 0
        self._wf_ready: int = 0
        # The currently-selected queue entry, kept so we can re-render
        # the detail pane after a re-list (ignore action).
        self._sel_kind: str = ""           # "issue" | "dup" | ""
        self._sel_index: int = -1

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # -- Top toolbar (run analyses / view stats) ---------------------
        self._toolbar = _ReviewToolbar()
        self._toolbar.quality_clicked.connect(self.quality_requested.emit)
        self._toolbar.dedup_clicked.connect(self.dedup_requested.emit)
        self._toolbar.stats_clicked.connect(self.stats_requested.emit)
        self._toolbar.fix_oob_clicked.connect(self.fix_oob_requested.emit)
        root.addWidget(self._toolbar)

        # -- Summary strip ----------------------------------------------
        self._summary = _SummaryStrip()
        root.addWidget(self._summary)

        # -- Body: queue list (left) + detail pane (right) --------------
        body = QHBoxLayout()
        body.setContentsMargins(T.PAD_XL, 0, T.PAD_XL, T.PAD_XL)
        body.setSpacing(T.GAP_LG)

        # Queue card with two tabs (问题 / 重复组).
        queue_card = QFrame()
        queue_card.setObjectName("reviewQueueCard")
        queue_card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        queue_card.setFixedWidth(320)
        q_lay = QVBoxLayout(queue_card)
        q_lay.setContentsMargins(0, 0, 0, 0)
        q_lay.setSpacing(0)

        self._pivot = Pivot()
        self._pivot.addItem(routeKey="issues",
                            text=i18n.t("review.tab.issues"),
                            onClick=lambda: self._show_tab("issues"))
        self._pivot.addItem(routeKey="dup",
                            text=i18n.t("review.tab.duplicates"),
                            onClick=lambda: self._show_tab("dup"))
        self._pivot.setCurrentItem("issues")
        q_lay.addWidget(self._pivot)

        self._queue_stack = QStackedWidget()
        # Issues list
        self._issue_list = QListWidget()
        self._issue_list.setObjectName("reviewQueueList")
        self._issue_list.itemSelectionChanged.connect(
            self._on_issue_selected)
        self._issue_list.itemDoubleClicked.connect(
            self._on_issue_double_clicked)
        self._queue_stack.addWidget(self._issue_list)

        # Duplicates list
        self._dup_list = QListWidget()
        self._dup_list.setObjectName("reviewQueueList")
        self._dup_list.itemSelectionChanged.connect(
            self._on_dup_selected)
        self._dup_list.itemDoubleClicked.connect(
            self._on_dup_double_clicked)
        self._queue_stack.addWidget(self._dup_list)

        q_lay.addWidget(self._queue_stack, 1)
        body.addWidget(queue_card)

        # Detail pane — image preview + meta + actions.
        self._detail = _IssueDetailPane()
        self._detail.jump_requested.connect(
            self.jump_to_image_requested.emit)
        self._detail.mark_fix_requested.connect(self._on_mark_fix)
        self._detail.ignore_requested.connect(self._on_ignore)
        body.addWidget(self._detail, 1)

        root.addLayout(body, 1)

        # Initial empty state — repaint with no data.
        self._render_issues()
        self._render_duplicates()
        self._refresh_summary()

        i18n.bus.language_changed.connect(self._retranslate)

    # ════════════════════════════════════════════════════════════════
    # Public API (called by DatasetBrowserView from AppState signals)
    # ════════════════════════════════════════════════════════════════

    def set_actions_enabled(self, enabled: bool) -> None:
        """Gate the top toolbar buttons (kept for backwards compat)."""
        self._toolbar.set_enabled(enabled)

    def set_quality_issues(self, issues: list | None) -> None:
        self._issues = list(issues or [])
        self._render_issues()
        self._refresh_summary()

    def set_duplicate_groups(self, groups: list | None) -> None:
        self._dup_groups = list(groups or [])
        self._render_duplicates()
        self._refresh_summary()

    def set_workflow_summary(self, summary) -> None:
        """Pull needs_fix + ready counts from WorkflowSummary."""
        if summary is None:
            self._wf_needs_fix = 0
            self._wf_ready = 0
        else:
            self._wf_needs_fix = summary.needs_fix
            self._wf_ready = summary.ready + summary.exported
        self._refresh_summary()

    def set_dataset(self, dataset) -> None:
        """Push the dataset image count down to the toolbar's scope badges."""
        n = sum(len(cat.images) for cat in dataset.categories) \
            if dataset is not None else 0
        self._toolbar.set_dataset_count(n)

    # ════════════════════════════════════════════════════════════════
    # Queue rendering
    # ════════════════════════════════════════════════════════════════

    def _render_issues(self) -> None:
        self._issue_list.blockSignals(True)
        self._issue_list.clear()

        live = [iss for iss in self._issues
                if str(iss.image.path) not in self._ignored_paths]

        if not self._issues:
            item = QListWidgetItem(i18n.t("review.empty.no_quality_run"))
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._issue_list.addItem(item)
        elif not live:
            item = QListWidgetItem(i18n.t("review.empty.clean"))
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._issue_list.addItem(item)
        else:
            for iss in live:
                # One entry per (image × first kind) — kinds rarely
                # exceed 1 in practice; collapsing keeps the list
                # short. The detail pane shows all kinds anyway.
                kind = iss.kinds[0] if iss.kinds else ""
                label = f"● {_kind_label(kind)}  ·  {iss.image.path.name}"
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, iss)
                self._issue_list.addItem(item)

        self._issue_list.blockSignals(False)

        # If detail pane was showing an issue that just got ignored,
        # collapse it to empty.
        if self._sel_kind == "issue":
            self._sel_index = -1
            self._detail.show_empty()

    def _render_duplicates(self) -> None:
        self._dup_list.blockSignals(True)
        self._dup_list.clear()

        if not self._dup_groups:
            item = QListWidgetItem(i18n.t("review.empty.no_dedup_run"))
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._dup_list.addItem(item)
        else:
            for group in self._dup_groups:
                first = group.images[0].path.name if group.images else "—"
                label = f"● {len(group.images)} 张  ·  {first}"
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, group)
                self._dup_list.addItem(item)

        self._dup_list.blockSignals(False)

        if self._sel_kind == "dup":
            self._sel_index = -1
            self._detail.show_empty()

    def _refresh_summary(self) -> None:
        live_issues = sum(
            1 for iss in self._issues
            if str(iss.image.path) not in self._ignored_paths
        )
        self._summary.set_counts(
            issues=live_issues,
            dup_groups=len(self._dup_groups),
            needs_fix=self._wf_needs_fix,
            ready=self._wf_ready,
        )

    # ════════════════════════════════════════════════════════════════
    # Selection + actions
    # ════════════════════════════════════════════════════════════════

    def _show_tab(self, key: str) -> None:
        if key == "issues":
            self._queue_stack.setCurrentIndex(0)
        else:
            self._queue_stack.setCurrentIndex(1)
        # Switching tabs blanks the detail pane until the user picks
        # an entry from the new tab.
        self._sel_kind = ""
        self._sel_index = -1
        self._detail.show_empty()

    def _on_issue_selected(self) -> None:
        item = self._issue_list.currentItem()
        if item is None:
            return
        issue = item.data(Qt.ItemDataRole.UserRole)
        if issue is None:
            return
        kind = issue.kinds[0] if issue.kinds else ""
        self._sel_kind = "issue"
        self._sel_index = self._issue_list.currentRow()
        self._detail.show_issue(issue.image, kind, issue.metrics)

    def _on_issue_double_clicked(self, item: QListWidgetItem) -> None:
        issue = item.data(Qt.ItemDataRole.UserRole)
        if issue is not None:
            self.jump_to_image_requested.emit(issue.image)

    def _on_dup_selected(self) -> None:
        item = self._dup_list.currentItem()
        if item is None:
            return
        group = item.data(Qt.ItemDataRole.UserRole)
        if group is None:
            return
        self._sel_kind = "dup"
        self._sel_index = self._dup_list.currentRow()
        self._detail.show_dup_group(group)

    def _on_dup_double_clicked(self, item: QListWidgetItem) -> None:
        group = item.data(Qt.ItemDataRole.UserRole)
        if group is not None and group.images:
            self.jump_to_image_requested.emit(group.images[0])

    def _on_mark_fix(self, image: ImageInfo) -> None:
        # The shell's _on_work_status_changed handler does the actual
        # workflow-store write; we just hand off the (image, status)
        # pair via the dedicated signal.
        self.mark_needs_fix_requested.emit(image)

    def _on_ignore(self, image: ImageInfo, kind: str) -> None:
        # ``kind`` lets future passes target a single kind on a multi-
        # kind image (today we just remove the whole image entry from
        # the live queue).
        self._ignored_paths.add(str(image.path))
        if self._sel_kind == "issue":
            self._render_issues()
            self._refresh_summary()

    def _retranslate(self, _lang: str) -> None:
        self._toolbar.retranslate()
        self._summary.retranslate()
        self._detail.retranslate()
        # Re-label tab pivots (qfluentwidgets Pivot exposes setText
        # via its NavigationItem widgets).
        try:
            for key, label_key in (("issues", "review.tab.issues"),
                                   ("dup", "review.tab.duplicates")):
                w = getattr(self._pivot, "items", {}).get(key)
                if w is None:
                    continue
                btn = getattr(w, "widget", None)
                if btn is not None and hasattr(btn, "setText"):
                    btn.setText(i18n.t(label_key))
        except Exception:
            pass
        # Re-render queues so empty-state strings retranslate.
        self._render_issues()
        self._render_duplicates()
