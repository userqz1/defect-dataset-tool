"""导出 hub — output-only task cards.

This page only produces deliverables: training-dataset export, VLM-data
export, and copy-based annotation conversion. Operations that rewrite the
project live under ProjectManageHub so users can distinguish "export a
copy" from "mutate my project".
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
    PrimaryPushButton,
    PushButton,
    StrongBodyLabel,
)

from gui import i18n
from gui.theme import T
from gui.widgets.llm_data_card import LlmDataCard
from gui.widgets.scope_badge import Scope, ScopeBadge


class _TaskCard(QFrame):
    """One task card — title + (scope, input, output) rows + main CTA.

    Constructed declaratively from i18n key-stems plus a CTA handler.
    Optional ``danger=True`` flips the scope badge to the warning color.
    Optional ``inline_widget`` is dropped between the field rows and the
    CTA.
    """

    def __init__(self,
                 title_key: str,
                 scope_key: str,
                 input_key: str,
                 output_key: str,
                 cta_key: str,
                 *,
                 danger: bool = False,
                 writes_label_key: str = "scope.writes_project",
                 inline_widget: QWidget | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("taskCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        root = QVBoxLayout(self)
        root.setContentsMargins(T.PAD_XL, T.PAD_LG, T.PAD_XL, T.PAD_LG)
        root.setSpacing(T.GAP)

        self._i18n_refs: list[tuple[QWidget, str]] = []

        # Header row: title + scope badge (read-only vs writes-* variant)
        head = QHBoxLayout()
        title = StrongBodyLabel(i18n.t(title_key))
        title.setObjectName("taskCardTitle")
        head.addWidget(title)
        self._i18n_refs.append((title, title_key))
        head.addStretch(1)
        if danger:
            badge = ScopeBadge(i18n.t(writes_label_key), Scope.WRITES)
            self._i18n_refs.append((badge, writes_label_key))
        else:
            badge = ScopeBadge(i18n.t("scope.readonly"), Scope.READONLY)
            self._i18n_refs.append((badge, "scope.readonly"))
        head.addWidget(badge)
        root.addLayout(head)

        # Three field rows (作用范围 / 输入 / 产出).  Each row has a
        # muted key column + a body value column.
        for key_i18n, val_i18n in (
            ("task.scope",  scope_key),
            ("task.input",  input_key),
            ("task.output", output_key),
        ):
            row = QHBoxLayout()
            row.setSpacing(T.GAP)
            k = CaptionLabel(i18n.t(key_i18n))
            k.setObjectName("taskCardKey")
            k.setFixedWidth(72)
            row.addWidget(k, 0, Qt.AlignmentFlag.AlignTop)
            v = CaptionLabel(i18n.t(val_i18n))
            v.setObjectName("taskCardValue")
            v.setWordWrap(True)
            row.addWidget(v, 1)
            self._i18n_refs.append((k, key_i18n))
            self._i18n_refs.append((v, val_i18n))
            root.addLayout(row)

        # Optional inline widget (capabilities / process buttons) — sits
        # between the field rows and the CTA.
        if inline_widget is not None:
            root.addSpacing(T.GAP)
            root.addWidget(inline_widget)

        # CTA row
        cta_row = QHBoxLayout()
        cta_row.addStretch(1)
        self._cta = PrimaryPushButton(i18n.t(cta_key))
        self._cta.setFixedHeight(32)
        self._cta.setEnabled(False)   # gated by set_actions_enabled
        cta_row.addWidget(self._cta)
        self._i18n_refs.append((self._cta, cta_key))
        root.addLayout(cta_row)

    @property
    def cta(self) -> PrimaryPushButton:
        return self._cta

    def retranslate(self) -> None:
        for w, key in self._i18n_refs:
            w.setText(i18n.t(key))


class DeliveryHub(QFrame):
    """导出 stage body — task cards for output-producing actions."""

    # Copy/export format action
    convert_annot_requested = pyqtSignal()
    # Export
    # Payload: format hint key (e.g. "swift", "llava", "yolo", "coco")
    # OR empty string when the trigger doesn't pin a format (the
    # generic 数据集导出 card CTA).  The wizard preselects when the hint
    # matches a registered Schema; empty falls back to the first
    # visible card for the current task type.
    export_requested = pyqtSignal(str)
    # 大模型标注向导 — bubbled up from the LLM-data card's launcher.
    # Shell opens VlmStartDialog, applies caps, switches to ANNOTATE,
    # filters category, drills into first incomplete image.
    start_vlm_workflow_requested = pyqtSignal()

    # 批量填入区域文本 — bubbled up from the LLM-data card's launcher.
    # Shell opens BulkRegionTextDialog, runs core.grounding_bulk in a
    # worker, then notifies AppState so per-region counts refresh.
    bulk_fill_region_text_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("deliveryHub")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root.addWidget(scroll)

        inner = QWidget()
        inner_lay = QVBoxLayout(inner)
        inner_lay.setContentsMargins(
            T.PAD_2XL, T.PAD_XL, T.PAD_2XL, T.PAD_XL)
        inner_lay.setSpacing(T.GAP_LG)

        # Track every CTA so set_actions_enabled can gate the whole
        # surface in one pass.
        self._cards: list[_TaskCard] = []
        self._action_buttons: list[PushButton | PrimaryPushButton] = []
        # Project ref cached so retranslate can repaint without
        # round-tripping AppState.
        self._project_ref = None

        # ── Card 1: 导出训练数据 ────────────────────────────────────
        export_card = _TaskCard(
            "delivery.export.title",
            "delivery.export.scope",
            "delivery.export.input",
            "delivery.export.output",
            "delivery.export.cta",
            danger=False,
        )
        # Generic dataset-export card has no format hint — empty string
        # tells the wizard to fall back to "first visible card".
        export_card.cta.clicked.connect(
            lambda: self.export_requested.emit(""))
        self._add_card(export_card, inner_lay)

        # ── Card 2: 标注格式转换 (副本) ─────────────────────────────
        convert_card = _TaskCard(
            "delivery.convert.title",
            "delivery.convert.scope",
            "delivery.convert.input",
            "delivery.convert.output",
            "delivery.convert.cta",
            danger=False,
        )
        convert_card.cta.clicked.connect(self.convert_annot_requested.emit)
        self._add_card(convert_card, inner_lay)

        # ── Card 3: 大模型数据 ──────────────────────────────────────
        # Specialized card — drops the generic _TaskCard scope/input/
        # output rows in favor of a real data-status block, format
        # picker, format-reference help link, and VLM workflow helpers.
        self._llm_card = LlmDataCard()
        self._llm_card.export_requested.connect(self._on_llm_export)
        self._llm_card.start_vlm_workflow_requested.connect(
            self.start_vlm_workflow_requested.emit)
        self._llm_card.bulk_fill_region_text_requested.connect(
            self.bulk_fill_region_text_requested.emit)
        inner_lay.addWidget(self._llm_card)
        # Track its export button so set_actions_enabled can gate it
        # alongside the other CTAs in one pass.
        self._action_buttons.append(self._llm_card._export_btn)

        inner_lay.addStretch(1)
        scroll.setWidget(inner)

        i18n.bus.language_changed.connect(self._retranslate)

    # -- Public API --

    def set_actions_enabled(self, enabled: bool) -> None:
        """Gate every task-card CTA."""
        for btn in self._action_buttons:
            btn.setEnabled(enabled)
        self._llm_card.set_actions_enabled(enabled)

    def set_project(self, project) -> None:
        """Forward the active project into the LLM-data card.

        The card decides whether to show its empty state (no caps
        enabled) or the full editor.  Capability toggles themselves
        moved to :class:`ProjectManageHub` in P1.4.
        """
        self._project_ref = project
        self._llm_card.set_project(project)

    def set_sample_set(self, sample_set) -> None:
        """Push the live SampleSet into the LLM-data card for status counts.

        Wired from ``AppState.sample_set_changed`` so caption /
        conversations / grounding counts update as users edit.
        """
        self._llm_card.set_sample_set(sample_set)

    # -- Internals --

    def _add_card(self, card: _TaskCard, container: QVBoxLayout) -> None:
        container.addWidget(card)
        self._cards.append(card)
        self._action_buttons.append(card.cta)

    def _on_llm_export(self, format_key: str) -> None:
        """Forward the LLM-card's export click with the chosen format.

        ``format_key`` is one of ``llava`` / ``sharegpt`` / ``swift`` /
        ``caption_jsonl``.  Forwarded verbatim so the wizard preselects
        the matching card — users no longer have to "pick the format
        twice" (once on the card, again in the wizard).
        """
        self.export_requested.emit(format_key)

    def _retranslate(self, _lang: str) -> None:
        for card in self._cards:
            card.retranslate()
        # The LLM-data card has its own retranslate hook; trigger it
        # so all status / format / footer copy refreshes against the
        # active language.
        self._llm_card.retranslate()
