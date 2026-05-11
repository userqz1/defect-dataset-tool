"""Export wizard — three-step standalone dialog.

Step 1: Format selection (card grid, filtered by task type)
Step 2: Parameter config (split ratio, copy images, output directory)
Step 3: Preview + Execute (directory tree, summary, start button)

Launched from the browser toolbar — no pipeline dependency.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CheckBox,
    DoubleSpinBox,
    FluentIcon as FIF,
    InfoBar,
    InfoBarPosition,
    MessageBoxBase,
    PrimaryPushButton,
    PushButton,
    RadioButton,
    SpinBox,
    StrongBodyLabel,
    SubtitleLabel,
)

from core.models import Dataset
from core.schema import all_schemas, get as get_schema, schemas_for_task
from core.task_types import TaskType
from gui.theme import T


# ---------- Format definitions (derived from Schema registry) ----------
# v1.2 §5.5: core.schema is the single source of truth for export formats.
# Legacy formats without a Schema (CSV / JSONL / LLaVA / ms-swift) return
# in v0.2 per §14.4 once they're ported to Schema objects.

def _format_cards() -> list[dict]:
    return [
        {"key": s.key, "name": s.display_name, "desc": s.description}
        for s in all_schemas()
    ]


# ---------- Format card ----------

class _FormatCard(QFrame):
    def __init__(self, fmt: dict, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("formatCard")
        self.fmt_key = fmt["key"]
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(72)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(T.PAD_LG, T.PAD, T.PAD_LG, T.PAD)
        layout.setSpacing(2)

        name_row = QHBoxLayout()
        name_row.setSpacing(T.GAP)
        self.name_label = StrongBodyLabel(fmt["name"])
        self.name_label.setObjectName("formatCardName")
        name_row.addWidget(self.name_label)
        name_row.addStretch(1)
        name_row.addWidget(CaptionLabel(fmt["desc"]))
        layout.addLayout(name_row)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        self.name_label.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)
        self.name_label.style().unpolish(self.name_label)
        self.name_label.style().polish(self.name_label)


# ---------- Export Wizard Dialog ----------

class ExportWizardDialog(MessageBoxBase):
    """Three-step export wizard — format → params → preview+execute."""

    def __init__(self, dataset: Dataset, task_type: TaskType | None = None,
                 manual_counts: tuple[int, int, int] = (0, 0, 0),
                 wf_ready_count: int = 0, wf_total_count: int = 0,
                 initial_fmt: str = "",
                 initial_category: str = "",
                 parent=None) -> None:
        super().__init__(parent=parent)
        self._dataset = dataset
        self._task_type = task_type
        self._selected_fmt = "YOLO"
        self._out_dir: Path | None = None
        self._worker = None
        # Counts of paths already bucketed via 右键 → 加入手动划分;
        # used to enable the "manual" radio + show "训练 N · 验证 M · 测试 K".
        self._manual_counts = manual_counts

        # Wider AND taller — content has 3 numbered sections plus
        # per-format cards plus category filter plus preview, easily
        # exceeds MessageBoxBase's default squish-on-overflow height.
        # The QScrollArea below catches anything we still overflow on
        # large dataset configurations (10+ cards · 30+ categories).
        self.widget.setMinimumSize(740, 720)

        # All wizard content lives inside a scrollable container — when
        # the dataset has many categories or the screen is short, the
        # outer dialog box used to silently overlap rows on top of each
        # other.  A scroll area gives Qt a single tall viewport to lay
        # the rows out into and the user just scrolls.
        _content_widget = QWidget()
        self._content_lay = QVBoxLayout(_content_widget)
        self._content_lay.setContentsMargins(0, 0, 0, 0)
        self._content_lay.setSpacing(T.GAP)

        _scroll = QScrollArea()
        _scroll.setObjectName("exportWizardScroll")
        _scroll.setWidgetResizable(True)
        _scroll.setFrameShape(QFrame.Shape.NoFrame)
        _scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        _scroll.setWidget(_content_widget)
        self.viewLayout.addWidget(_scroll)

        # ===== Step 1: Format selection =====
        self._content_lay.addWidget(SubtitleLabel("导出向导"))

        self._content_lay.addWidget(StrongBodyLabel("① 选择导出格式"))

        cards_grid = QGridLayout()
        cards_grid.setSpacing(T.GAP)
        self._format_cards: dict[str, _FormatCard] = {}
        for i, fmt in enumerate(_format_cards()):
            card = _FormatCard(fmt)
            card.mousePressEvent = lambda e, k=fmt["key"]: self._select_format(k)
            self._format_cards[fmt["key"]] = card
            cards_grid.addWidget(card, i // 2, i % 2)
        self._content_lay.addLayout(cards_grid)

        # Filter by task type — Schema-driven (v1.2 §5.5)
        if task_type:
            allowed = {s.key for s in schemas_for_task(task_type)}
            for key, card in self._format_cards.items():
                card.setVisible(key in allowed)

        # ===== Readiness row (Schema-driven, v1.2 §5.4) =====
        # Shows per-slot pills when the selected format has a registered
        # core.schema entry. Other formats fall through silently.
        self._readiness_frame = QFrame()
        self._readiness_frame.setObjectName("chartFrame")
        ready_lay = QVBoxLayout(self._readiness_frame)
        ready_lay.setContentsMargins(T.PAD_LG, T.PAD, T.PAD_LG, T.PAD)
        ready_lay.setSpacing(T.GAP_XS)

        self._readiness_title = BodyLabel("")
        ready_lay.addWidget(self._readiness_title)

        self._readiness_pills_row = QHBoxLayout()
        self._readiness_pills_row.setSpacing(T.GAP_XS)
        self._readiness_pills_row.addStretch(1)
        ready_lay.addLayout(self._readiness_pills_row)

        self._content_lay.addWidget(self._readiness_frame)

        # ===== Step 2: Parameters =====
        self._content_lay.addWidget(StrongBodyLabel("② 配置参数"))

        param_frame = QFrame()
        param_frame.setObjectName("chartFrame")
        p_lay = QVBoxLayout(param_frame)
        p_lay.setContentsMargins(T.PAD_XL, T.PAD_LG, T.PAD_XL, T.PAD_LG)
        p_lay.setSpacing(T.GAP)

        # Category filter — "只导出某几个类目" (e.g. only Loose for VLM
        # grounding training).  Hidden when the dataset has 0 or 1
        # categories because there's nothing meaningful to pick.
        #
        # Layout note: the checkbox grid lives inside an explicit QFrame
        # container (not a bare QGridLayout addLayout'd into p_lay).
        # Bare nested layouts intermittently fail to report their full
        # sizeHint to the parent QVBoxLayout — neighbour rows then
        # render on top of the grid instead of below it.  The QFrame
        # wrapper forces a real geometry contract.  Internal QScrollArea
        # caps the visible height so 30+-category datasets stay usable.
        self._cat_checks: dict[str, CheckBox] = {}
        cat_names = [c.name for c in dataset.categories]
        if len(cat_names) >= 2:
            cat_header_row = QHBoxLayout()
            cat_header_row.setSpacing(T.GAP)
            cat_header_row.addWidget(BodyLabel("类目"))
            cat_header_row.addStretch(1)
            cat_all_btn = PushButton("全选")
            cat_all_btn.setFixedHeight(28)
            cat_all_btn.clicked.connect(lambda: self._set_all_categories(True))
            cat_header_row.addWidget(cat_all_btn)
            cat_none_btn = PushButton("反选")
            cat_none_btn.setFixedHeight(28)
            cat_none_btn.clicked.connect(self._invert_categories)
            cat_header_row.addWidget(cat_none_btn)
            p_lay.addLayout(cat_header_row)

            cat_container = QFrame()
            cat_grid = QGridLayout(cat_container)
            cat_grid.setContentsMargins(0, 0, 0, 0)
            cat_grid.setSpacing(T.GAP)
            cols = 4
            # When the caller passed initial_category="Loose", only
            # that one starts checked — saves the user from clicking
            # 反选 + clicking Loose every single time they came from
            # the catalog tree with Loose already active.  Empty hint
            # falls back to "all checked".
            preselect_one = initial_category if initial_category in cat_names else ""
            for i, name in enumerate(cat_names):
                chk = CheckBox(name)
                chk.setChecked(name == preselect_one if preselect_one else True)
                chk.toggled.connect(self._update_preview)
                self._cat_checks[name] = chk
                cat_grid.addWidget(chk, i // cols, i % cols)

            cat_scroll = QScrollArea()
            cat_scroll.setObjectName("categoryFilterScroll")
            cat_scroll.setWidgetResizable(True)
            cat_scroll.setFrameShape(QFrame.Shape.NoFrame)
            cat_scroll.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            # Cap at ~3 rows of checkboxes; any extra scrolls vertically.
            cat_scroll.setMaximumHeight(108)
            cat_scroll.setWidget(cat_container)
            p_lay.addWidget(cat_scroll)

        # Split mode — ratio (auto) vs manual (right-click 加入手动划分 result)
        mode_row = QHBoxLayout()
        mode_row.setSpacing(T.GAP_LG)
        self._mode_ratio_rb = RadioButton("按比例自动划分")
        self._mode_manual_rb = RadioButton(
            "用手动划分集合 (右键\"加入手动划分\")"
        )
        self._mode_group = QButtonGroup(self)
        self._mode_group.addButton(self._mode_ratio_rb)
        self._mode_group.addButton(self._mode_manual_rb)
        manual_total = sum(self._manual_counts)
        # Manual radio is only meaningful when the user already bucketed
        # something — disable + add a hint otherwise so it doesn't look broken.
        if manual_total > 0:
            self._mode_manual_rb.setText(
                f"用手动划分集合 (训练 {self._manual_counts[0]} · "
                f"验证 {self._manual_counts[1]} · 测试 {self._manual_counts[2]})"
            )
        else:
            self._mode_manual_rb.setEnabled(False)
            self._mode_manual_rb.setToolTip(
                "右键缩略图 → 加入手动划分 后，此选项才可用"
            )
        self._mode_ratio_rb.setChecked(True)
        mode_row.addWidget(self._mode_ratio_rb)
        mode_row.addWidget(self._mode_manual_rb)
        mode_row.addStretch(1)
        p_lay.addLayout(mode_row)

        # Split ratio (only relevant in ratio mode; hidden when manual chosen)
        self._ratio_widget = QFrame()
        ratio_lay = QVBoxLayout(self._ratio_widget)
        ratio_lay.setContentsMargins(0, 0, 0, 0)
        ratio_lay.setSpacing(T.GAP)

        ratio_row = QHBoxLayout()
        ratio_row.setSpacing(T.GAP_LG)
        ratio_row.addWidget(BodyLabel("训练集"))
        self._train = DoubleSpinBox()
        self._train.setRange(0, 1); self._train.setValue(0.8); self._train.setSingleStep(0.05)
        ratio_row.addWidget(self._train)
        ratio_row.addWidget(BodyLabel("验证集"))
        self._val = DoubleSpinBox()
        self._val.setRange(0, 1); self._val.setValue(0.1); self._val.setSingleStep(0.05)
        ratio_row.addWidget(self._val)
        ratio_row.addWidget(BodyLabel("测试集"))
        self._test = DoubleSpinBox()
        self._test.setRange(0, 1); self._test.setValue(0.1); self._test.setSingleStep(0.05)
        ratio_row.addWidget(self._test)
        ratio_row.addStretch(1)
        ratio_lay.addLayout(ratio_row)

        # Seed (review #7) — 0 = random; non-zero = reproducible split.
        # Lets the user re-run the same export and get the same train/val/test,
        # which matters for "上次测试集 87.3%, 这次复测一下" comparisons.
        seed_row = QHBoxLayout()
        seed_row.setSpacing(T.GAP)
        seed_row.addWidget(BodyLabel("随机种子"))
        self._seed = SpinBox()
        self._seed.setRange(0, 2_147_483_647)
        self._seed.setValue(0)
        self._seed.setFixedWidth(140)
        seed_row.addWidget(self._seed)
        seed_row.addWidget(CaptionLabel("(0 = 每次随机)"))
        seed_row.addStretch(1)
        ratio_lay.addLayout(seed_row)

        # Stratified (review #11) — preserve per-category ratios when splitting.
        # Off means pure random; training on imbalanced data usually wants this
        # ON so each split gets proportional class counts.
        self._stratified_chk = CheckBox("按类别分层抽样(推荐)")
        self._stratified_chk.setChecked(True)
        ratio_lay.addWidget(self._stratified_chk)

        p_lay.addWidget(self._ratio_widget)

        self._copy_chk = CheckBox("复制图片到导出目录")
        self._copy_chk.setChecked(True)
        p_lay.addWidget(self._copy_chk)

        # Workflow scope — export all vs ready-only
        self._wf_ready_count = wf_ready_count
        self._wf_total_count = wf_total_count
        scope_row = QHBoxLayout()
        scope_row.setSpacing(T.GAP_LG)
        self._scope_all_rb = RadioButton("导出全部")
        self._scope_ready_rb = RadioButton("仅导出已就绪")
        self._scope_group = QButtonGroup(self)
        self._scope_group.addButton(self._scope_all_rb)
        self._scope_group.addButton(self._scope_ready_rb)
        self._scope_all_rb.setChecked(True)
        scope_row.addWidget(self._scope_all_rb)
        scope_row.addWidget(self._scope_ready_rb)
        if wf_total_count > 0:
            scope_hint = CaptionLabel(
                f"{wf_ready_count} 张就绪 / {wf_total_count} 张总计")
            scope_hint.setObjectName("statValue")
            scope_row.addWidget(scope_hint)
        scope_row.addStretch(1)
        p_lay.addLayout(scope_row)
        # Hide scope row when no workflow is active
        self._scope_all_rb.setVisible(wf_total_count > 0)
        self._scope_ready_rb.setVisible(wf_total_count > 0)

        # Toggle ratio block visibility based on mode selection
        self._mode_ratio_rb.toggled.connect(
            lambda on: (self._ratio_widget.setVisible(on),
                        self._update_preview())
        )

        # VLM question — the user-role text in each training sample
        # (paired with the assistant's grounding/caption answer).
        # Shown only for schemas whose options_class declares a
        # ``question`` field (ShareGPT / LLaVA / Swift); CV formats
        # hide it so the form doesn't balloon.
        self._question_row_widget = QFrame()
        q_row = QHBoxLayout(self._question_row_widget)
        q_row.setContentsMargins(0, 0, 0, 0)
        q_row.setSpacing(T.GAP)
        q_row.addWidget(BodyLabel("用户提问"))
        from qfluentwidgets import LineEdit
        self._question_edit = LineEdit()
        self._question_edit.setPlaceholderText(
            "训练时用户对模型说的话 (留空用默认: 请描述这张图片中的内容。)"
        )
        q_row.addWidget(self._question_edit, 1)
        p_lay.addWidget(self._question_row_widget)
        self._question_row_widget.hide()  # toggled in _update_preview

        # Output directory — promoted to a primary action row.  The
        # "开始导出" button stays disabled until a directory is chosen,
        # so this picker is effectively the gate.  Using
        # PrimaryPushButton + a wider hit area + dedicated row makes
        # the gate visible (review: users were missing the small
        # "选择" button squeezed into a row of mixed controls).
        dir_row = QHBoxLayout()
        dir_row.setSpacing(T.GAP)
        dir_row.addWidget(BodyLabel("输出目录"))
        self._dir_label = CaptionLabel("未选择 — 点右侧选择导出目录")
        dir_row.addWidget(self._dir_label, 1)
        self._dir_btn = PrimaryPushButton("选择导出目录…")
        self._dir_btn.setIcon(FIF.FOLDER)
        self._dir_btn.setMinimumWidth(180)
        self._dir_btn.setFixedHeight(32)
        self._dir_btn.clicked.connect(self._pick_dir)
        dir_row.addWidget(self._dir_btn)
        p_lay.addLayout(dir_row)

        self._content_lay.addWidget(param_frame)

        # ===== Step 3: Preview + Execute =====
        self._content_lay.addWidget(StrongBodyLabel("③ 预览"))

        preview_frame = QFrame()
        preview_frame.setObjectName("chartFrame")
        pv_lay = QVBoxLayout(preview_frame)
        pv_lay.setContentsMargins(T.PAD_XL, T.PAD_LG, T.PAD_XL, T.PAD_LG)
        pv_lay.setSpacing(T.GAP)

        # Summary
        n_images = sum(c.image_count for c in dataset.categories)
        self._summary = BodyLabel(f"共 {n_images:,} 张图片 · {len(dataset.categories)} 个类别")
        pv_lay.addWidget(self._summary)

        # Split preview
        self._split_preview = CaptionLabel("")
        pv_lay.addWidget(self._split_preview)

        # Structure preview
        self._structure = CaptionLabel("")
        self._structure.setWordWrap(True)
        pv_lay.addWidget(self._structure)

        self._content_lay.addWidget(preview_frame)

        # Buttons
        self.yesButton.setText("开始导出")
        self.cancelButton.setText("取消")
        self.yesButton.setEnabled(False)

        # Initial selection — caller-provided hint takes precedence
        # (e.g. LlmDataCard already asked the user to pick ms-swift),
        # otherwise fall back to the first visible card for this task
        # type.  Match is case-insensitive AND aliases the LLM card's
        # short keys (``swift`` → ``Swift``, ``caption_jsonl`` → ``JSONL``).
        initial = self._resolve_format_hint(initial_fmt)
        if not initial:
            initial = next(
                (k for k, c in self._format_cards.items() if c.isVisible()),
                next(iter(self._format_cards), "YOLO"),
            )
        self._select_format(initial)
        self._update_preview()

        # Wire ratio changes to preview update
        self._train.valueChanged.connect(self._update_preview)
        self._val.valueChanged.connect(self._update_preview)
        self._test.valueChanged.connect(self._update_preview)

    # ---------- Format hint ----------

    def _resolve_format_hint(self, hint: str) -> str:
        """Map a caller-supplied format hint to a registered + visible
        Schema key.  Returns ``""`` when no match.

        Accepts case-insensitive aliases so callers like LlmDataCard
        (which speaks ``swift`` / ``llava`` / ``sharegpt`` /
        ``caption_jsonl``) don't have to know the canonical Schema
        keys (``Swift`` / ``LLaVA`` / ``ShareGPT`` / ``JSONL``).
        """
        if not hint:
            return ""
        # caption_jsonl is a use-case alias for the JSONL schema —
        # resolve it before the generic case fold.
        h = hint.strip().lower()
        compact = (
            h.replace(" ", "")
            .replace("-", "")
            .replace("_", "")
            .replace("/", "")
        )
        if compact in {"captionjsonl", "imagecaptionjsonl"}:
            h = "jsonl"
        elif compact in {"llavajsonl"}:
            h = "llava"
        elif compact in {"sharegptjson", "sharegptjsonl"}:
            h = "sharegpt"
        elif compact in {"msswift", "swiftjsonl", "qwenvl"}:
            h = "swift"
        elif compact in {"labelme", "labelmejson"}:
            h = "labelme json"
        elif compact in {"pairedfolder", "pairfolder", "imagepair", "pair"}:
            h = "pairedfolder"
        for key, card in self._format_cards.items():
            if key.lower() == h and card.isVisible():
                return key
        return ""

    # ---------- Category filter ----------

    def _selected_categories(self) -> list[str]:
        """Return names of currently-checked categories.

        Empty list means the row was never built (single-category
        dataset) — callers should treat that as "no filter, export
        all".  When the row exists but the user unchecked everything
        we return the empty list too; the export pipeline guards
        against that with an info bar before starting.
        """
        return [name for name, chk in self._cat_checks.items()
                if chk.isChecked()]

    def _set_all_categories(self, checked: bool) -> None:
        for chk in self._cat_checks.values():
            chk.setChecked(checked)

    def _invert_categories(self) -> None:
        for chk in self._cat_checks.values():
            chk.setChecked(not chk.isChecked())

    # ---------- Format selection ----------

    def _select_format(self, key: str) -> None:
        self._selected_fmt = key
        for k, card in self._format_cards.items():
            card.set_selected(k == key)
        self._update_preview()

    # ---------- Directory ----------

    def _pick_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(
            self, "选择导出目录", str(Path.home()),
        )
        if not d:
            return
        self._out_dir = Path(d)
        text = str(self._out_dir)
        if len(text) > 50:
            text = "..." + text[-47:]
        self._dir_label.setText(text)
        # Once a dir is locked in, the button switches to "更改…" so
        # the row stops shouting "I'm the gate".  The 开始导出 CTA
        # below now becomes the next obvious action.
        self._dir_btn.setText("更改…")
        self.yesButton.setEnabled(True)

    # ---------- Preview ----------

    def _update_preview(self) -> None:
        # Category filter shrinks the working set before split math.
        # Empty selected list (everything unchecked) reads as 0 — the
        # preview just says 0 / 0 / 0 and the export pipeline rejects
        # the run with an info bar.
        sel = set(self._selected_categories())
        if self._cat_checks and sel:
            n_total = sum(c.image_count for c in self._dataset.categories
                          if c.name in sel)
            n_cats = len(sel)
        elif self._cat_checks and not sel:
            n_total = 0
            n_cats = 0
        else:
            n_total = sum(c.image_count for c in self._dataset.categories)
            n_cats = len(self._dataset.categories)

        # Top-line summary mirrors the filter state too — without this
        # the user kept seeing "12 个类别" even after unchecking all but
        # Loose (review feedback).
        self._summary.setText(
            f"共 {n_total:,} 张图片 · {n_cats:,} 个类别"
        )

        if self._mode_manual_rb.isChecked():
            n_tr, n_va, n_te = self._manual_counts
            self._split_preview.setText(
                f"手动 · 训练 {n_tr} · 验证 {n_va} · 测试 {n_te}"
            )
        else:
            tr, va, te = self._train.value(), self._val.value(), self._test.value()
            s = tr + va + te
            if s > 0:
                n_tr = int(round(n_total * tr / s))
                n_va = int(round(n_total * va / s))
                n_te = n_total - n_tr - n_va
            else:
                n_tr, n_va, n_te = n_total, 0, 0
            self._split_preview.setText(
                f"训练 {n_tr} · 验证 {n_va} · 测试 {n_te}"
            )
        schema = get_schema(self._selected_fmt)
        # getattr guard (review #14) — a future Schema that forgets to
        # define directory_preview would otherwise AttributeError here.
        self._structure.setText(getattr(schema, "directory_preview", "") if schema else "")
        # Show Q&A row only when the schema's options support a question.
        supports_q = bool(
            schema and "question" in schema.options_class.__dataclass_fields__
        )
        self._question_row_widget.setVisible(supports_q)
        self._refresh_readiness()

    # ---------- Readiness (Schema-driven) ----------

    def _refresh_readiness(self) -> None:
        """Rebuild per-slot pills from the selected format's Schema.

        Hides the readiness frame entirely if the format has no Schema
        registered (legacy path for formats not yet migrated to core.schema).
        """
        schema = get_schema(self._selected_fmt)
        if schema is None:
            self._readiness_frame.setVisible(False)
            return

        self._readiness_frame.setVisible(True)
        report = schema.validate(self._dataset)
        gaps = [slot.name for slot in report.missing()]
        suffix = "就绪" if report.ready else f"缺:{'、'.join(gaps)}"
        self._readiness_title.setText(
            f"合规状态 · {schema.display_name}  {report.progress_text} {suffix}"
        )

        # Clear previous pills (keep the trailing stretch at index 0 after clear)
        while self._readiness_pills_row.count() > 0:
            item = self._readiness_pills_row.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                w.deleteLater()

        for slot, status in report.results:
            icon = "✓" if status.ok else "✗"
            pill = CaptionLabel(f"{icon} {slot.name}")
            pill.setObjectName("readinessOk" if status.ok else "readinessGap")
            tip_parts = [status.current_text]
            if status.required_text:
                tip_parts.append(f"要求 {status.required_text}")
            if status.action_text:
                tip_parts.append(status.action_text)
            pill.setToolTip(" · ".join(p for p in tip_parts if p))
            self._readiness_pills_row.addWidget(pill)
        self._readiness_pills_row.addStretch(1)

    # ---------- Result ----------

    def export_options(self) -> dict:
        """Return the configured export parameters."""
        seed_val = self._seed.value()
        # Category filter — see ``_selected_categories`` for empty-list
        # semantics.  ``None`` here means "row not built (single-category
        # dataset)" which downstream treats as no-op.  Empty list means
        # "user unchecked everything" which the controller rejects.
        if self._cat_checks:
            categories: list[str] | None = self._selected_categories()
        else:
            categories = None
        return {
            "format": self._selected_fmt,
            "out_dir": self._out_dir,
            "split_mode": "manual" if self._mode_manual_rb.isChecked() else "ratio",
            "train_ratio": self._train.value(),
            "val_ratio": self._val.value(),
            "test_ratio": self._test.value(),
            # 0 = "no fixed seed" (every run is fresh random); non-zero is forwarded
            "seed": seed_val if seed_val > 0 else None,
            "copy_images": self._copy_chk.isChecked(),
            "stratified": self._stratified_chk.isChecked(),
            # question only meaningful for VLM schemas; empty string = use default
            "question": self._question_edit.text().strip(),
            # Workflow scope: "all" or "ready_only"
            "export_scope": "ready_only" if self._scope_ready_rb.isChecked() else "all",
            # None = no filter (single-category dataset); list = filter to those names.
            "categories": categories,
        }
