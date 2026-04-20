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
                 parent=None) -> None:
        super().__init__(parent=parent)
        self._dataset = dataset
        self._task_type = task_type
        self._selected_fmt = "YOLO"
        self._out_dir: Path | None = None
        self._worker = None

        self.widget.setMinimumWidth(680)

        # ===== Step 1: Format selection =====
        self.viewLayout.addWidget(SubtitleLabel("导出向导"))

        self.viewLayout.addWidget(StrongBodyLabel("① 选择导出格式"))

        cards_grid = QGridLayout()
        cards_grid.setSpacing(T.GAP)
        self._format_cards: dict[str, _FormatCard] = {}
        for i, fmt in enumerate(_format_cards()):
            card = _FormatCard(fmt)
            card.mousePressEvent = lambda e, k=fmt["key"]: self._select_format(k)
            self._format_cards[fmt["key"]] = card
            cards_grid.addWidget(card, i // 2, i % 2)
        self.viewLayout.addLayout(cards_grid)

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

        self.viewLayout.addWidget(self._readiness_frame)

        # ===== Step 2: Parameters =====
        self.viewLayout.addWidget(StrongBodyLabel("② 配置参数"))

        param_frame = QFrame()
        param_frame.setObjectName("chartFrame")
        p_lay = QVBoxLayout(param_frame)
        p_lay.setContentsMargins(T.PAD_XL, T.PAD_LG, T.PAD_XL, T.PAD_LG)
        p_lay.setSpacing(T.GAP)

        # Split ratio
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
        p_lay.addLayout(ratio_row)

        self._copy_chk = CheckBox("复制图片到导出目录")
        self._copy_chk.setChecked(True)
        p_lay.addWidget(self._copy_chk)

        # Output directory
        dir_row = QHBoxLayout()
        dir_row.setSpacing(T.GAP)
        dir_row.addWidget(BodyLabel("输出目录"))
        self._dir_label = CaptionLabel("未选择")
        dir_row.addWidget(self._dir_label, 1)
        dir_btn = PushButton("选择")
        dir_btn.setIcon(FIF.FOLDER)
        dir_btn.setFixedWidth(80)
        dir_btn.clicked.connect(self._pick_dir)
        dir_row.addWidget(dir_btn)
        p_lay.addLayout(dir_row)

        self.viewLayout.addWidget(param_frame)

        # ===== Step 3: Preview + Execute =====
        self.viewLayout.addWidget(StrongBodyLabel("③ 预览"))

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

        self.viewLayout.addWidget(preview_frame)

        # Buttons
        self.yesButton.setText("开始导出")
        self.cancelButton.setText("取消")
        self.yesButton.setEnabled(False)

        # Initial selection — first visible schema (task_type may hide YOLO)
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
        self.yesButton.setEnabled(True)

    # ---------- Preview ----------

    def _update_preview(self) -> None:
        n = sum(c.image_count for c in self._dataset.categories)
        tr, va, te = self._train.value(), self._val.value(), self._test.value()
        s = tr + va + te
        if s > 0:
            n_tr = int(round(n * tr / s))
            n_va = int(round(n * va / s))
            n_te = n - n_tr - n_va
        else:
            n_tr, n_va, n_te = n, 0, 0
        self._split_preview.setText(
            f"训练 {n_tr} · 验证 {n_va} · 测试 {n_te}"
        )
        schema = get_schema(self._selected_fmt)
        self._structure.setText(schema.directory_preview if schema else "")
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
        return {
            "format": self._selected_fmt,
            "out_dir": self._out_dir,
            "train_ratio": self._train.value(),
            "val_ratio": self._val.value(),
            "test_ratio": self._test.value(),
            "copy_images": self._copy_chk.isChecked(),
        }
