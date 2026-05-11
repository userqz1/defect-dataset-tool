"""LLM-data card — full delivery zone for VLM/LLM training data.

Replaces the v3.5 read-only stub on :class:`gui.widgets.delivery_hub.
DeliveryHub`.  This card is now the user's single answer to "I want
to train a vision-LLM on my dataset — where do I do it?":

    [ 大模型数据 ]                                    [scope: 整库 VLM]
    训练 VLM (视觉大模型) 所需的图文对话与定位数据

    数据状态
        Caption        320 / 4,900
        对话           80  / 4,900
        Grounding 区域 1,200

    导出目标格式      [查看格式说明 ?]
        ◉ LLaVA        LLaVA 系列微调 · id / image / conversations
        ○ ShareGPT     多模态对话/描述 · 与 LLaVA 兼容
        ○ ms-swift / Qwen-VL  Qwen-VL / InternVL · messages / images / objects
        ○ Caption JSONL  图文对齐 · image / caption · 适合 SD / CLIP 预训练

    [ 导出大模型数据 ]
    规划中: 导入 Caption · 导入对话 · 批量生成

Status counts come from :class:`core.unified.SampleSet` — caption
count = samples with ``s.caption``, conversations count = samples
with ``s.conversations``, grounding region count = ``sum(len(s.grounding))``
(structured grounding is per-region, not per-image).

Pure presentation: emits :pyattr:`export_requested` with the chosen
format key when the user clicks the CTA.  The DeliveryHub forwards
that into :meth:`BrowserToolController.run_export` which already
handles per-format export wizard wiring — for v3.7 the format hint
is stored on AppState.export_format_hint so the wizard can preselect
it.  Caption/conversation import are left as "planned" placeholders so
the surface stays honest about what's wired.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    FluentIcon as FIF,
    HyperlinkButton,
    PrimaryPushButton,
    PushButton,
    RadioButton,
    StrongBodyLabel,
)

from gui import i18n
from gui.theme import T
from gui.widgets.scope_badge import Scope, ScopeBadge


# (key, title_i18n, desc_i18n) — drives the radio group + label rendering.
# ``key`` is what gets emitted on export and what AppState stashes as the
# format hint for the export wizard to read.
LLM_FORMATS: list[tuple[str, str, str]] = [
    ("llava",
     "llm.format.llava", "llm.format.llava.desc"),
    ("sharegpt",
     "llm.format.sharegpt", "llm.format.sharegpt.desc"),
    ("swift",
     "llm.format.swift", "llm.format.swift.desc"),
    ("caption_jsonl",
     "llm.format.caption", "llm.format.caption.desc"),
]


class LlmDataCard(QFrame):
    """Full delivery zone for VLM training data."""

    # Emitted when the user hits the export CTA. Payload is the chosen
    # format key (one of the strings in LLM_FORMATS); DeliveryHub
    # converts that into the wizard hint.
    export_requested = pyqtSignal(str)

    # Emitted by the "开始大模型标注向导" launcher.  Shell opens
    # VlmStartDialog → applies caps → switches to ANNOTATE → filters
    # category → drills into the first incomplete image.  No payload —
    # the dialog itself collects the user's choices.
    start_vlm_workflow_requested = pyqtSignal()

    # Emitted by the "批量填入区域文本" launcher.  Shell opens
    # BulkRegionTextDialog → runs core.grounding_bulk in a worker →
    # notifies AppState so the per-region count refreshes.
    bulk_fill_region_text_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("taskCard")  # reuse task-card visual baseline
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        # Track project state locally so retranslate / repaint can
        # rerun against the cached snapshot without round-tripping
        # through AppState.
        self._project = None
        self._sample_set = None
        # Selected format key (radio button id) — defaults to the most
        # popular entry: LLaVA-style. Persists across re-renders.
        self._selected_format: str = "llava"
        # Tracks i18n widgets so retranslate refreshes labels without
        # rebuilding the layout.
        self._i18n_refs: list[tuple[QWidget, str]] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(T.PAD_XL, T.PAD_LG, T.PAD_XL, T.PAD_LG)
        root.setSpacing(T.GAP)

        # ── Header ─────────────────────────────────────────────────
        head = QHBoxLayout()
        head.setSpacing(T.GAP)
        title = StrongBodyLabel(i18n.t("llm.section.title"))
        title.setObjectName("taskCardTitle")
        head.addWidget(title)
        self._i18n_refs.append((title, "llm.section.title"))
        head.addStretch(1)
        scope = ScopeBadge(i18n.t("scope.readonly"), Scope.READONLY)
        head.addWidget(scope)
        self._i18n_refs.append((scope, "scope.readonly"))
        root.addLayout(head)

        subtitle = CaptionLabel(i18n.t("llm.section.subtitle"))
        subtitle.setObjectName("taskCardKey")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)
        self._i18n_refs.append((subtitle, "llm.section.subtitle"))

        root.addWidget(self._build_main_page())

    # ════════════════════════════════════════════════════════════════
    # Public API
    # ════════════════════════════════════════════════════════════════

    def set_project(self, project) -> None:
        """Cache the active project for future extension hooks."""
        self._project = project
        self._select_format_for_project(project)

    def set_sample_set(self, ss) -> None:
        """Refresh the data-status counts from the live SampleSet."""
        self._sample_set = ss
        self._refresh_status_counts()

    def set_actions_enabled(self, enabled: bool) -> None:
        """Gate the export CTA on dataset-loaded state."""
        self._export_btn.setEnabled(enabled)

    def selected_format(self) -> str:
        return self._selected_format

    # ════════════════════════════════════════════════════════════════
    # Page builders
    # ════════════════════════════════════════════════════════════════

    def _build_main_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, T.GAP, 0, 0)
        lay.setSpacing(T.PAD_LG)

        # Workflow launcher CTAs — give users a one-click path into
        # "filter to one category, open first incomplete image, panes
        # ready for VLM editing" instead of stitching it together
        # across three stages by themselves.  The bulk-fill button is
        # the "skip the per-image dance, write one template, hit
        # apply" alternative for projects where every region of a
        # category shares the same description.
        launcher_row = QHBoxLayout()
        launcher_row.setSpacing(T.GAP)
        self._start_workflow_btn = PushButton(i18n.t("llm.cta.start_workflow"))
        self._start_workflow_btn.setIcon(FIF.PLAY)
        self._start_workflow_btn.setFixedHeight(32)
        self._start_workflow_btn.clicked.connect(
            self.start_vlm_workflow_requested.emit)
        launcher_row.addWidget(self._start_workflow_btn)
        self._i18n_refs.append(
            (self._start_workflow_btn, "llm.cta.start_workflow"))

        self._bulk_fill_btn = PushButton(i18n.t("llm.cta.bulk_fill"))
        self._bulk_fill_btn.setIcon(FIF.EDIT)
        self._bulk_fill_btn.setFixedHeight(32)
        self._bulk_fill_btn.clicked.connect(
            self.bulk_fill_region_text_requested.emit)
        launcher_row.addWidget(self._bulk_fill_btn)
        self._i18n_refs.append((self._bulk_fill_btn, "llm.cta.bulk_fill"))

        launcher_row.addStretch(1)
        lay.addLayout(launcher_row)

        lay.addWidget(self._build_status_block())
        lay.addWidget(self._build_format_block())
        lay.addLayout(self._build_cta_row())
        lay.addWidget(self._build_planned_caption())
        return page

    def _build_status_block(self) -> QWidget:
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(T.GAP_XS)

        header = CaptionLabel(i18n.t("llm.status.title"))
        header.setObjectName("llmStatusHeader")
        v.addWidget(header)
        self._i18n_refs.append((header, "llm.status.title"))

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(T.PAD_LG)
        grid.setVerticalSpacing(T.GAP_XS)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)

        # Three rows — caption / conversations / grounding regions.
        # Each row stays in the layout always; we set value text via
        # set_sample_set later. Saves a rebuild on every count update.
        self._status_caption_value = BodyLabel("—")
        self._status_caption_value.setObjectName("llmStatusValue")
        self._status_convs_value = BodyLabel("—")
        self._status_convs_value.setObjectName("llmStatusValue")
        self._status_grounding_value = BodyLabel("—")
        self._status_grounding_value.setObjectName("llmStatusValue")

        rows = [
            ("llm.status.caption", self._status_caption_value),
            ("llm.status.conversations", self._status_convs_value),
            ("llm.status.grounding", self._status_grounding_value),
        ]
        for r, (key, value_lbl) in enumerate(rows):
            key_lbl = CaptionLabel(i18n.t(key))
            key_lbl.setObjectName("llmStatusKey")
            grid.addWidget(key_lbl, r, 0, Qt.AlignmentFlag.AlignLeft)
            grid.addWidget(value_lbl, r, 1, Qt.AlignmentFlag.AlignLeft)
            self._i18n_refs.append((key_lbl, key))

        v.addLayout(grid)
        return wrap

    def _build_format_block(self) -> QWidget:
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(T.GAP_XS)

        # Header row — title + help link aligned to the right.
        head = QHBoxLayout()
        head.setSpacing(T.GAP)
        head_title = CaptionLabel(i18n.t("llm.format.title"))
        head_title.setObjectName("llmStatusHeader")
        head.addWidget(head_title)
        head.addStretch(1)
        self._i18n_refs.append((head_title, "llm.format.title"))

        help_btn = HyperlinkButton(url="", text=i18n.t("llm.help.button"))
        help_btn.setObjectName("llmHelpLink")
        help_btn.clicked.connect(self._show_help_dialog)
        head.addWidget(help_btn)
        self._i18n_refs.append((help_btn, "llm.help.button"))
        v.addLayout(head)

        # Radio group — exclusive selection.
        self._fmt_group = QButtonGroup(self)
        self._fmt_group.setExclusive(True)
        self._fmt_radios: dict[str, RadioButton] = {}
        self._fmt_descs: dict[str, CaptionLabel] = {}
        for idx, (key, title_key, desc_key) in enumerate(LLM_FORMATS):
            row = QHBoxLayout()
            row.setSpacing(T.GAP)
            radio = RadioButton(i18n.t(title_key))
            radio.setObjectName("llmFormatRadio")
            radio.toggled.connect(
                lambda on, k=key: self._on_format_toggled(k, on))
            self._fmt_group.addButton(radio, idx)
            row.addWidget(radio)
            desc = CaptionLabel(i18n.t(desc_key))
            desc.setObjectName("llmFormatDesc")
            row.addWidget(desc, 1)
            v.addLayout(row)
            self._fmt_radios[key] = radio
            self._fmt_descs[key] = desc
            self._i18n_refs.append((radio, title_key))
            self._i18n_refs.append((desc, desc_key))

        # Pre-select the default — without firing the toggled handler
        # before _selected_format has a chance to receive it (we check
        # ``on`` inside the slot anyway, but blockSignals is cheaper).
        default_radio = self._fmt_radios.get(self._selected_format)
        if default_radio is not None:
            default_radio.setChecked(True)
        return wrap

    def _build_cta_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(T.GAP)
        row.addStretch(1)
        self._export_btn = PrimaryPushButton(i18n.t("llm.cta.export"))
        self._export_btn.setFixedHeight(32)
        self._export_btn.setEnabled(False)  # gated by set_actions_enabled
        self._export_btn.clicked.connect(self._on_export_clicked)
        row.addWidget(self._export_btn)
        self._i18n_refs.append((self._export_btn, "llm.cta.export"))
        return row

    def _build_planned_caption(self) -> QWidget:
        # "Planned" footer — was originally "import Caption · import
        # Conversations · 批量生成".  批量生成 has shipped (see the
        # 批量填入区域文本 launcher above); only the two import paths
        # remain on the roadmap.  Drop the line entirely if everything
        # listed has already shipped to keep the card from carrying
        # stale "coming soon" copy.
        text = "{label}: {a} · {b}".format(
            label=i18n.t("llm.next.label"),
            a=i18n.t("llm.next.import_caption"),
            b=i18n.t("llm.next.import_convs"),
        )
        lbl = CaptionLabel(text)
        lbl.setObjectName("llmPlannedFooter")
        lbl.setWordWrap(True)
        self._planned_label = lbl
        return lbl

    # ════════════════════════════════════════════════════════════════
    # State-driven repaints
    # ════════════════════════════════════════════════════════════════

    def _refresh_status_counts(self) -> None:
        if not hasattr(self, "_status_caption_value"):
            return
        ss = self._sample_set
        if ss is None or not getattr(ss, "samples", None):
            empty = i18n.t("llm.status.empty_value")
            self._status_caption_value.setText(empty)
            self._status_convs_value.setText(empty)
            self._status_grounding_value.setText(empty)
            return
        total = len(ss.samples)
        n_caption = sum(1 for s in ss.samples if (s.caption or "").strip())
        n_convs = sum(1 for s in ss.samples if s.conversations)
        n_regions = 0
        for s in ss.samples:
            if s.grounding:
                n_regions += len(s.grounding)
        self._status_caption_value.setText(i18n.t(
            "llm.status.fraction", n=n_caption, total=total))
        self._status_convs_value.setText(i18n.t(
            "llm.status.fraction", n=n_convs, total=total))
        self._status_grounding_value.setText(i18n.t(
            "llm.status.regions_count", n=n_regions))

    # ════════════════════════════════════════════════════════════════
    # Internals
    # ════════════════════════════════════════════════════════════════

    def _on_format_toggled(self, key: str, on: bool) -> None:
        if on:
            self._selected_format = key

    def _select_format_for_project(self, project) -> None:
        if project is None:
            return
        target = (getattr(project, "target_format", "") or "").lower()
        compact = (
            target.replace(" ", "")
            .replace("-", "")
            .replace("_", "")
            .replace("/", "")
        )
        target_key = {
            "llava": "llava",
            "llavajsonl": "llava",
            "sharegpt": "sharegpt",
            "sharegptjson": "sharegpt",
            "sharegptjsonl": "sharegpt",
            "swift": "swift",
            "msswift": "swift",
            "swiftjsonl": "swift",
            "qwenvl": "swift",
            "captionjsonl": "caption_jsonl",
            "imagecaptionjsonl": "caption_jsonl",
        }.get(compact)
        if not target_key:
            return
        radio = self._fmt_radios.get(target_key)
        if radio is not None:
            radio.setChecked(True)
            self._selected_format = target_key

    def _on_export_clicked(self) -> None:
        self.export_requested.emit(self._selected_format)

    def _show_help_dialog(self) -> None:
        from gui.dialogs.llm_format_reference import LlmFormatReferenceDialog
        dlg = LlmFormatReferenceDialog(self.window())
        dlg.exec()

    def retranslate(self) -> None:
        for w, key in self._i18n_refs:
            w.setText(i18n.t(key))
        # The "planned" footer concatenates several keys — rebuild fresh.
        # Mirrors the format used in _build_planned_caption (no
        # 批量生成 entry — that capability has shipped).
        if hasattr(self, "_planned_label"):
            text = "{label}: {a} · {b}".format(
                label=i18n.t("llm.next.label"),
                a=i18n.t("llm.next.import_caption"),
                b=i18n.t("llm.next.import_convs"),
            )
            self._planned_label.setText(text)
        # Re-render data-status counts so the localized template strings
        # ("已显示 X / Y" → "Showing X / Y") swap with the language.
        self._refresh_status_counts()
