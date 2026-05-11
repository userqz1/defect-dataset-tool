"""数据集版本 hub — freeze an immutable dataset snapshot.

Collects version parameters on a single scrollable form and writes
the result to a standalone ``versions/`` directory — the project
stays clean; mistakes are free.

Layout (four numbered sections → one CTA)::

    ┌──────────────────────────────────────────────────┐
    │  数据集版本                                       │
    │                                                  │
    │  当前项目                                         │
    │  图片 4,900 · 类别 12 · 标注 100%                 │
    │                                                  │
    │  ① 数据范围                                       │
    │  [整库] [当前筛选] [仅已就绪]                      │
    │                                                  │
    │  ② 数据划分                                       │
    │  Train 80% · Val 10% · Test 10%                  │
    │                                                  │
    │  ③ 目标格式                                       │
    │  [YOLO] [COCO] [LabelMe] [VOC] [...]             │
    │                                                  │
    │                       [生成数据集版本]             │
    │                                                  │
    │  ④ 已生成版本                                     │
    │  v_20260509_yolo  YOLO · 4,900 张 · ...           │
    └──────────────────────────────────────────────────┘

The Generate CTA emits a plain config dict. BrowserToolController turns it
into ``core.version_builder.TrainingVersionConfig`` and writes a versioned
snapshot under ``<project>/versions/``.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
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
    CheckBox,
    FluentIcon as FIF,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    StrongBodyLabel,
)

from gui import i18n
from core.target_readiness import (
    export_key_for_target_format,
    normalize_target_format,
    schema_key_for_target_format,
    target_format_is_exportable,
)
from gui.theme import T
from gui.widgets.scope_badge import Scope, ScopeBadge
from gui.widgets.split_slider import SplitSlider


# ── Section base ──────────────────────────────────────────────────

class _Section(QFrame):
    """Numbered section card — circled digit + title + body slot."""

    def __init__(
        self,
        number: str,
        title_key: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("tvSection")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        root = QVBoxLayout(self)
        root.setContentsMargins(T.PAD_XL, T.PAD_LG, T.PAD_XL, T.PAD_LG)
        root.setSpacing(T.GAP)

        # Header: circled number + title
        head = QHBoxLayout()
        head.setSpacing(T.GAP)
        num_lbl = StrongBodyLabel(number)
        num_lbl.setObjectName("tvSectionNumber")
        head.addWidget(num_lbl)
        self._title = StrongBodyLabel(i18n.t(title_key))
        self._title.setObjectName("tvSectionTitle")
        head.addWidget(self._title, 1)
        root.addLayout(head)

        self._title_key = title_key
        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(T.GAP)
        root.addLayout(self.body)

    def retranslate(self) -> None:
        self._title.setText(i18n.t(self._title_key))


# ── Chip (toggleable pill for scope / format selection) ───────────

class _ChoiceChip(QFrame):
    """Selectable pill — for exclusive or multi-select groups."""

    clicked = pyqtSignal()

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("tvChoiceChip")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(T.CONTROL_HEIGHT)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(T.PAD_LG, 0, T.PAD_LG, 0)
        self._label = BodyLabel(text)
        self._label.setObjectName("tvChoiceChipLabel")
        lay.addWidget(self._label)

        self._selected = False
        self.setProperty("selected", "false")

    def setText(self, text: str) -> None:
        self._label.setText(text)

    def text(self) -> str:
        return self._label.text()

    def setSelected(self, selected: bool) -> None:
        if selected == self._selected:
            return
        self._selected = selected
        self.setProperty("selected", "true" if selected else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def isSelected(self) -> bool:
        return self._selected

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)


class _VersionRow(QFrame):
    """One generated training version in the history section."""

    open_requested = pyqtSignal(str)
    delete_requested = pyqtSignal(str)

    def __init__(self, version, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("tvVersionRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._version = version
        self._path = str(getattr(version, "path", ""))

        root = QHBoxLayout(self)
        root.setContentsMargins(T.PAD_LG, T.PAD, T.PAD_LG, T.PAD)
        root.setSpacing(T.GAP)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(T.GAP_XS)
        self._name = StrongBodyLabel(str(getattr(version, "name", "")))
        self._name.setObjectName("tvVersionName")
        self._meta = CaptionLabel("")
        self._meta.setObjectName("tvVersionMeta")
        text_col.addWidget(self._name)
        text_col.addWidget(self._meta)
        root.addLayout(text_col, 1)

        self._open_btn = PushButton()
        self._open_btn.setIcon(FIF.FOLDER)
        self._open_btn.setFixedHeight(T.CONTROL_HEIGHT)
        self._open_btn.clicked.connect(
            lambda: self.open_requested.emit(self._path))
        root.addWidget(self._open_btn)

        self._delete_btn = PushButton()
        self._delete_btn.setFixedHeight(T.CONTROL_HEIGHT)
        self._delete_btn.clicked.connect(
            lambda: self.delete_requested.emit(self._path))
        root.addWidget(self._delete_btn)

        self.retranslate()

    def set_actions_enabled(self, enabled: bool) -> None:
        self._delete_btn.setEnabled(enabled)

    def retranslate(self) -> None:
        fmt = str(getattr(self._version, "fmt", "") or "—").upper()
        created = str(getattr(self._version, "created_at", "") or "—")
        created = created.replace("T", " ")
        self._meta.setText(i18n.t(
            "tv.history.meta",
            fmt=fmt,
            samples=f"{int(getattr(self._version, 'sample_count', 0)):,}",
            train=int(getattr(self._version, "train_count", 0)),
            val=int(getattr(self._version, "val_count", 0)),
            test=int(getattr(self._version, "test_count", 0)),
            created=created,
        ))
        self._open_btn.setText(i18n.t("tv.history.open"))
        self._delete_btn.setText(i18n.t("tv.history.delete"))


# ═══════════════════════════════════════════════════════════════════
# Main hub widget
# ═══════════════════════════════════════════════════════════════════

class TrainingVersionHub(QFrame):
    """数据集版本 stage body — parameter form + generate CTA."""

    generate_requested = pyqtSignal(object)
    open_version_requested = pyqtSignal(str)
    delete_version_requested = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("trainingVersionHub")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._actions_enabled = False
        self._format_exportable = False
        self._version_rows: list[_VersionRow] = []
        self._project_target_format = ""
        self._selected_format = ""
        self._sample_set = None
        self._total_images = 0
        self._class_count = 0
        self._task_type = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Scrollable form area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root.addWidget(scroll)

        inner = QWidget()
        self._lay = QVBoxLayout(inner)
        self._lay.setContentsMargins(
            T.PAD_2XL, T.PAD_XL, T.PAD_2XL, T.PAD_XL)
        self._lay.setSpacing(T.GAP_LG)

        # -- Project stats banner --
        self._build_stats_banner()

        # -- Section ① Data scope --
        self._build_scope_section()

        # -- Section ② Split --
        self._build_split_section()

        # -- Section ③ Current target format --
        self._build_format_summary_section()

        # -- Section ④ Version metadata --
        self._build_version_info_section()

        # -- Generate CTA --
        self._build_cta()

        # -- Generated versions --
        self._build_history_section()

        self._lay.addStretch(1)
        scroll.setWidget(inner)

        i18n.bus.language_changed.connect(self._retranslate)

    # ── Builders ──────────────────────────────────────────────────

    def _build_stats_banner(self) -> None:
        """Top banner showing current project stats."""
        banner = QFrame()
        banner.setObjectName("tvStatsBanner")
        banner.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        lay = QVBoxLayout(banner)
        lay.setContentsMargins(T.PAD_XL, T.PAD_LG, T.PAD_XL, T.PAD_LG)
        lay.setSpacing(T.GAP_XS)

        self._project_title = StrongBodyLabel(
            i18n.t("tv.stats.project"))
        self._project_title.setObjectName("tvProjectTitle")
        lay.addWidget(self._project_title)

        self._stats_label = CaptionLabel("—")
        self._stats_label.setObjectName("tvStatsLabel")
        lay.addWidget(self._stats_label)

        self._lay.addWidget(banner)

    def _build_scope_section(self) -> None:
        sec = _Section("①", "tv.scope.title")
        row = QHBoxLayout()
        row.setSpacing(T.GAP)

        self._scope_chips: list[_ChoiceChip] = []
        for key in ("tv.scope.all", "tv.scope.filtered", "tv.scope.ready"):
            chip = _ChoiceChip(i18n.t(key), parent=sec)
            chip.clicked.connect(lambda c=chip: self._on_scope_clicked(c))
            row.addWidget(chip)
            self._scope_chips.append(chip)
        row.addStretch(1)
        sec.body.addLayout(row)

        # Current Browser filter is not yet represented as a stable
        # version-builder input. Hide it instead of showing a disabled
        # commercial-looking primary choice that doesn't work yet.
        self._scope_chips[1].setEnabled(False)
        self._scope_chips[1].setVisible(False)
        self._scope_chips[1].setToolTip(i18n.t("tv.unsupported"))

        # Default: "整库"
        self._scope_chips[0].setSelected(True)
        self._scope_selection = 0

        self._scope_section = sec
        self._lay.addWidget(sec)

    def _build_split_section(self) -> None:
        sec = _Section("②", "tv.split.title")

        # Summary line
        self._split_summary = BodyLabel(
            i18n.t("tv.split.summary",
                   train=80, val=10, test=10))
        self._split_summary.setObjectName("tvSplitSummary")
        sec.body.addWidget(self._split_summary)

        # Three-way split slider (replaces three SpinBoxes)
        self._split_slider = SplitSlider()
        self._split_slider.set_ratios(80, 10, 10)
        self._split_slider.ratios_changed.connect(self._on_split_changed)
        sec.body.addWidget(self._split_slider)

        # Stratified checkbox
        self._stratified_cb = CheckBox(i18n.t("tv.split.stratified"))
        self._stratified_cb.setChecked(True)
        sec.body.addWidget(self._stratified_cb)

        self._split_section = sec
        self._lay.addWidget(sec)

    def _build_format_summary_section(self) -> None:
        sec = _Section("③", "tv.format.title")

        self._format_value = BodyLabel("—")
        self._format_value.setObjectName("tvSplitSummary")
        sec.body.addWidget(self._format_value)

        self._format_hint = CaptionLabel(i18n.t("tv.format.hint"))
        self._format_hint.setObjectName("tvHintLabel")
        self._format_hint.setWordWrap(True)
        sec.body.addWidget(self._format_hint)

        self._format_section = sec
        self._lay.addWidget(sec)

    def _build_version_info_section(self) -> None:
        sec = _Section("④", "tv.info.title")

        self._version_name_edit = LineEdit()
        self._version_name_edit.setPlaceholderText(i18n.t("tv.info.name_hint"))
        self._version_name_edit.setFixedHeight(T.CONTROL_HEIGHT)
        sec.body.addWidget(self._version_name_edit)

        self._version_info_hint = CaptionLabel(i18n.t("tv.info.hint"))
        self._version_info_hint.setObjectName("tvHintLabel")
        self._version_info_hint.setWordWrap(True)
        sec.body.addWidget(self._version_info_hint)

        self._info_section = sec
        self._lay.addWidget(sec)

    def _build_cta(self) -> None:
        """Generate Dataset Version button — the single CTA."""
        sec = _Section("⑤", "tv.generate.title")
        cta_frame = QFrame()
        cta_frame.setObjectName("tvCtaFrame")
        cta_row = QHBoxLayout(cta_frame)
        cta_row.setContentsMargins(0, 0, 0, 0)

        self._cta_badge = ScopeBadge(
            i18n.t("tv.cta.badge"), Scope.READONLY)
        cta_row.addWidget(self._cta_badge)

        self._generate_hint = CaptionLabel(i18n.t("tv.generate.hint"))
        self._generate_hint.setObjectName("tvHintLabel")
        cta_row.addWidget(self._generate_hint)
        cta_row.addStretch(1)

        self._cta_btn = PrimaryPushButton(i18n.t("tv.cta.generate"))
        self._cta_btn.setFixedHeight(40)
        self._cta_btn.setMinimumWidth(180)
        self._cta_btn.setEnabled(False)
        self._cta_btn.clicked.connect(self._on_generate)
        cta_row.addWidget(self._cta_btn)

        sec.body.addWidget(cta_frame)
        self._generate_section = sec
        self._lay.addWidget(sec)

    def _build_history_section(self) -> None:
        sec = _Section("⑥", "tv.history.title")

        self._history_empty = CaptionLabel(i18n.t("tv.history.empty"))
        self._history_empty.setObjectName("tvHintLabel")
        sec.body.addWidget(self._history_empty)

        self._history_lay = QVBoxLayout()
        self._history_lay.setContentsMargins(0, 0, 0, 0)
        self._history_lay.setSpacing(T.GAP)
        sec.body.addLayout(self._history_lay)

        self._history_section = sec
        self._lay.addWidget(sec)

    # ── Public API ────────────────────────────────────────────────

    def set_actions_enabled(self, enabled: bool) -> None:
        self._actions_enabled = enabled
        self._sync_cta_enabled()
        for row in self._version_rows:
            row.set_actions_enabled(enabled)

    def set_dataset(self, dataset) -> None:
        """Update project stats banner from the dataset."""
        if dataset is None:
            self._stats_label.setText("—")
            return

        self._total_images = getattr(dataset, "total_images", 0)
        self._class_count = len(getattr(dataset, "categories", []) or [])
        self._refresh_stats_summary()

    def set_sample_set(self, sample_set) -> None:
        """Update target-completion stats from the unified SampleSet."""
        self._sample_set = sample_set
        self._refresh_stats_summary()

    def set_project(self, project) -> None:
        """Display the project name in the stats banner."""
        name = getattr(project, "name", "") if project else ""
        self._project_title.setText(
            i18n.t("tv.stats.project_name", name=name)
            if name else i18n.t("tv.stats.project"))
        self._project_target_format = (
            getattr(project, "target_format", "") if project else ""
        )
        self._task_type = getattr(project, "task_type", None) if project else None
        self._refresh_stats_summary()
        self._refresh_format_summary()

    def set_versions(self, versions) -> None:
        """Render generated training-version history."""
        while self._history_lay.count():
            item = self._history_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._version_rows = []

        versions = list(versions or [])
        self._history_empty.setVisible(not versions)
        for version in versions:
            row = _VersionRow(version)
            row.set_actions_enabled(self._actions_enabled)
            row.open_requested.connect(
                lambda path: self.open_version_requested.emit(path))
            row.delete_requested.connect(
                lambda path: self.delete_version_requested.emit(path))
            self._history_lay.addWidget(row)
            self._version_rows.append(row)

    def set_task_type(self, task_type) -> None:
        """Kept for caller compatibility; target format lives in Annotate."""
        self._refresh_format_summary()

    # ── Internals ─────────────────────────────────────────────────

    _total_images: int = 0

    def _refresh_stats_summary(self) -> None:
        total = self._total_images
        cats = self._class_count
        pct = 0
        ss = self._sample_set
        if ss is not None:
            total = len(ss.samples)
            if total > 0:
                try:
                    from core.target_readiness import completed_paths_for_target
                    done = len(completed_paths_for_target(
                        ss.samples, self._project_target_format,
                        self._task_type))
                except Exception:
                    done = sum(1 for s in ss.samples if s.has_label)
                pct = int(done / total * 100)
        self._stats_label.setText(i18n.t(
            "tv.stats.summary",
            images=f"{total:,}",
            cats=cats,
            pct=pct,
        ))

    def _refresh_format_summary(self) -> None:
        self._selected_format = schema_key_for_target_format(
            self._project_target_format)
        display = self._project_target_format or "—"
        self._format_exportable = target_format_is_exportable(
            self._selected_format)
        schema_key = self._selected_format
        try:
            from core.schema import get
            schema = get(schema_key)
            is_caption_target = normalize_target_format(
                self._project_target_format) in {
                    "caption",
                    "captionjsonl",
                    "imagecaptionjsonl",
                }
            if schema is not None and not is_caption_target:
                display = schema.display_name
        except Exception:
            pass
        if self._project_target_format and not self._format_exportable:
            display = f"{display}（暂不支持生成版本）"
        if hasattr(self, "_format_value"):
            self._format_value.setText(i18n.t(
                "tv.format.current",
                fmt=display,
            ))
        self._sync_cta_enabled()

    def _sync_cta_enabled(self) -> None:
        if hasattr(self, "_cta_btn"):
            self._cta_btn.setEnabled(
                self._actions_enabled and self._format_exportable)

    def _on_scope_clicked(self, chip: _ChoiceChip) -> None:
        if not chip.isEnabled():
            return
        for i, c in enumerate(self._scope_chips):
            c.setSelected(c is chip)
            if c is chip:
                self._scope_selection = i

    def _on_split_changed(self, *_args) -> None:
        t, v, te = self._split_slider.ratios()
        self._split_summary.setText(
            i18n.t("tv.split.summary", train=t, val=v, test=te))

    def _on_generate(self) -> None:
        if not self._format_exportable:
            InfoBar.warning(
                "目标格式暂不支持生成版本",
                "请先在标注页选择一个可导出的目标格式。",
                parent=self.window(),
                duration=3000,
                position=InfoBarPosition.TOP,
            )
            return
        self.generate_requested.emit(self.version_config())

    def version_config(self) -> dict:
        t, v, te = self._split_slider.ratios()
        scope_keys = ("all", "filtered", "ready")
        scope = scope_keys[self._scope_selection]
        return {
            "format": export_key_for_target_format(self._selected_format),
            "scope": scope,
            "train_ratio": t,
            "val_ratio": v,
            "test_ratio": te,
            "stratified": self._stratified_cb.isChecked(),
            "version_name": self._version_name_edit.text().strip(),
        }

    def _retranslate(self, _lang: str) -> None:
        self._project_title.setText(i18n.t("tv.stats.project"))
        self._scope_section.retranslate()
        for chip, key in zip(
            self._scope_chips,
            ("tv.scope.all", "tv.scope.filtered", "tv.scope.ready"),
        ):
            chip.setText(i18n.t(key))

        self._split_section.retranslate()
        self._on_split_changed()
        self._stratified_cb.setText(i18n.t("tv.split.stratified"))

        self._format_section.retranslate()
        self._format_hint.setText(i18n.t("tv.format.hint"))
        self._refresh_format_summary()
        self._info_section.retranslate()
        self._version_name_edit.setPlaceholderText(i18n.t("tv.info.name_hint"))
        self._version_info_hint.setText(i18n.t("tv.info.hint"))
        self._generate_section.retranslate()
        self._generate_hint.setText(i18n.t("tv.generate.hint"))
        self._cta_badge.setText(i18n.t("tv.cta.badge"))
        self._cta_btn.setText(i18n.t("tv.cta.generate"))
        self._history_section.retranslate()
        self._history_empty.setText(i18n.t("tv.history.empty"))
        for row in self._version_rows:
            row.retranslate()
