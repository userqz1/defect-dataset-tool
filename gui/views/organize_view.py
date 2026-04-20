"""Organize view — batch import → classify → land.

Per DataForge-设计方案-v1.2 §9.3:
  "整理台 (拖入原始数据 → 分类建议 → 调整 → 落地)"

Layout:
  ┌──────────────────────────────────────┐
  │ ① 选择源目录          [选择]        │
  │    /path/to/raw   → 404 张图片      │
  ├──────────────────────────────────────┤
  │ ② 分类规则   [▼ by_filename_prefix] │
  │    [预览分类]                        │
  ├──────────────────────────────────────┤
  │ ③ 分类预览                          │
  │    crack     │ 120                   │
  │    good      │ 284                   │
  │    未分类     │   0                   │
  ├──────────────────────────────────────┤
  │ ④ 目标目录          [选择]          │
  │    /datasets/project1               │
  │                                      │
  │        [ 开始导入 ]                  │
  └──────────────────────────────────────┘

After import, emits ``import_done(path_str)`` so MainWindow can
open the dataset in the browser view.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CheckBox,
    ComboBox,
    FluentIcon as FIF,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    PushButton,
    StrongBodyLabel,
    SubtitleLabel,
)

from gui.theme import T


class OrganizeView(QWidget):
    """Batch import → classify → land workflow."""

    import_done = pyqtSignal(str)  # target_root path after successful import

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("organizeView")

        self._source_dir: Path | None = None
        self._target_dir: Path | None = None
        self._discovered: list[Path] = []
        self._preview = None  # IngestPreview | None

        root = QVBoxLayout(self)
        root.setContentsMargins(T.PAD_2XL, T.PAD_XL, T.PAD_2XL, T.PAD_XL)
        root.setSpacing(T.GAP_LG)

        root.addWidget(SubtitleLabel("整理台"))

        # ===== ① Source directory =====
        src_frame = self._card()
        src_lay = QVBoxLayout(src_frame)
        src_lay.setContentsMargins(T.PAD_XL, T.PAD_LG, T.PAD_XL, T.PAD_LG)
        src_lay.setSpacing(T.GAP)

        src_row = QHBoxLayout()
        src_row.addWidget(StrongBodyLabel("① 选择源目录"))
        src_row.addStretch(1)
        src_btn = PushButton("选择")
        src_btn.setIcon(FIF.FOLDER)
        src_btn.setFixedWidth(80)
        src_btn.clicked.connect(self._pick_source)
        src_row.addWidget(src_btn)
        src_lay.addLayout(src_row)

        self._src_label = CaptionLabel("未选择")
        src_lay.addWidget(self._src_label)
        root.addWidget(src_frame)

        # ===== ② Classification rule =====
        rule_frame = self._card()
        rule_lay = QVBoxLayout(rule_frame)
        rule_lay.setContentsMargins(T.PAD_XL, T.PAD_LG, T.PAD_XL, T.PAD_LG)
        rule_lay.setSpacing(T.GAP)

        rule_row = QHBoxLayout()
        rule_row.addWidget(StrongBodyLabel("② 分类规则"))
        rule_row.addStretch(1)
        self._rule_combo = ComboBox()
        self._rule_combo.addItems([
            "文件名前缀 (crack_001 → crack)",
            "子目录名 (data/scratch/ → scratch)",
            "拍摄日期 (EXIF → 2024-03)",
            "手动分类 (全部 → 未分类)",
        ])
        self._rule_combo.setFixedWidth(300)
        rule_row.addWidget(self._rule_combo)
        rule_lay.addLayout(rule_row)

        preview_btn = PushButton("预览分类")
        preview_btn.setIcon(FIF.VIEW)
        preview_btn.setFixedWidth(120)
        preview_btn.clicked.connect(self._run_preview)
        rule_lay.addWidget(preview_btn)
        root.addWidget(rule_frame)

        # ===== ③ Preview table =====
        preview_frame = self._card()
        pv_lay = QVBoxLayout(preview_frame)
        pv_lay.setContentsMargins(T.PAD_XL, T.PAD_LG, T.PAD_XL, T.PAD_LG)
        pv_lay.setSpacing(T.GAP)
        pv_lay.addWidget(StrongBodyLabel("③ 分类预览"))

        self._pv_summary = CaptionLabel("")
        pv_lay.addWidget(self._pv_summary)

        self._pv_table = QTableWidget(0, 2)
        self._pv_table.setHorizontalHeaderLabels(["类别", "数量"])
        self._pv_table.horizontalHeader().setStretchLastSection(True)
        self._pv_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self._pv_table.verticalHeader().setVisible(False)
        self._pv_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._pv_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._pv_table.setMaximumHeight(240)
        pv_lay.addWidget(self._pv_table)
        root.addWidget(preview_frame)

        # ===== ④ Target directory + Execute =====
        exec_frame = self._card()
        exec_lay = QVBoxLayout(exec_frame)
        exec_lay.setContentsMargins(T.PAD_XL, T.PAD_LG, T.PAD_XL, T.PAD_LG)
        exec_lay.setSpacing(T.GAP)

        tgt_row = QHBoxLayout()
        tgt_row.addWidget(StrongBodyLabel("④ 目标目录"))
        tgt_row.addStretch(1)
        tgt_btn = PushButton("选择")
        tgt_btn.setIcon(FIF.FOLDER)
        tgt_btn.setFixedWidth(80)
        tgt_btn.clicked.connect(self._pick_target)
        tgt_row.addWidget(tgt_btn)
        exec_lay.addLayout(tgt_row)

        self._tgt_label = CaptionLabel("未选择")
        exec_lay.addWidget(self._tgt_label)

        # Post-ingest checks (§6.4)
        checks_row = QHBoxLayout()
        checks_row.setSpacing(T.GAP_LG)
        self._run_quality_chk = CheckBox("导入后质检")
        self._run_quality_chk.setChecked(True)
        self._run_dedup_chk = CheckBox("导入后去重")
        self._run_dedup_chk.setChecked(True)
        checks_row.addWidget(self._run_quality_chk)
        checks_row.addWidget(self._run_dedup_chk)
        checks_row.addStretch(1)
        exec_lay.addLayout(checks_row)

        self._import_btn = PrimaryPushButton("开始导入")
        self._import_btn.setIcon(FIF.DOWNLOAD)
        self._import_btn.setEnabled(False)
        self._import_btn.clicked.connect(self._run_import)
        exec_lay.addWidget(self._import_btn, alignment=Qt.AlignmentFlag.AlignRight)
        root.addWidget(exec_frame)

        root.addStretch(1)

    # ---------- Helpers ----------

    @staticmethod
    def _card() -> QFrame:
        f = QFrame()
        f.setObjectName("chartFrame")
        return f

    def _rule_key(self) -> str:
        idx = self._rule_combo.currentIndex()
        return ["by_filename_prefix", "by_subdir", "by_exif_date", "manual"][idx]

    def _short_path(self, p: Path, max_len: int = 60) -> str:
        s = str(p)
        return ("..." + s[-(max_len - 3):]) if len(s) > max_len else s

    # ---------- Source ----------

    def _pick_source(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择源目录", str(Path.home()))
        if not d:
            return
        self._source_dir = Path(d)

        from core.ingest import discover
        self._discovered = discover([self._source_dir])
        self._src_label.setText(
            f"{self._short_path(self._source_dir)}  →  {len(self._discovered):,} 张图片"
        )
        # Clear stale preview
        self._preview = None
        self._pv_table.setRowCount(0)
        self._pv_summary.setText("")
        self._update_import_btn()

    # ---------- Preview ----------

    def _run_preview(self) -> None:
        if not self._discovered:
            InfoBar.warning("", "请先选择源目录",
                            parent=self.window(), duration=2000,
                            position=InfoBarPosition.TOP)
            return

        from core.ingest import RULES, preview
        rule = RULES[self._rule_key()]
        self._preview = preview(self._discovered, rule)

        # Fill table
        cats = self._preview.categories
        self._pv_table.setRowCount(len(cats))
        for row, (cat, imgs) in enumerate(
            sorted(cats.items(), key=lambda kv: -len(kv[1]))
        ):
            self._pv_table.setItem(row, 0, QTableWidgetItem(cat))
            count_item = QTableWidgetItem(f"{len(imgs):,}")
            count_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._pv_table.setItem(row, 1, count_item)

        self._pv_summary.setText(
            f"{self._preview.placed_count:,} 张 → {self._preview.category_count} 个类别"
            + (f"  ·  {len(self._preview.skipped)} 跳过" if self._preview.skipped else "")
        )
        self._update_import_btn()

    # ---------- Target ----------

    def _pick_target(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择目标目录", str(Path.home()))
        if not d:
            return
        self._target_dir = Path(d)
        self._tgt_label.setText(self._short_path(self._target_dir))
        self._update_import_btn()

    # ---------- Import ----------

    def _update_import_btn(self) -> None:
        ok = (self._preview is not None
              and self._preview.placed_count > 0
              and self._target_dir is not None)
        self._import_btn.setEnabled(ok)

    def _run_import(self) -> None:
        if self._preview is None or self._target_dir is None:
            return

        from core.ingest import execute_with_checks
        pv = self._preview
        tgt = self._target_dir
        do_quality = self._run_quality_chk.isChecked()
        do_dedup = self._run_dedup_chk.isChecked()

        def task(progress_cb):
            return execute_with_checks(
                pv, tgt,
                run_quality=do_quality,
                run_dedup=do_dedup,
                progress_cb=progress_cb,
            )

        from gui.workers.batch_runner import BatchRunner
        runner = BatchRunner(self.window(), "导入数据集")
        runner.run(
            task,
            on_done=lambda result: self._on_import_done(result, tgt),
        )

    def _on_import_done(self, result, target: Path) -> None:
        parts = [f"{result.copied:,} 张图片已导入"]
        if result.quality_issues is not None:
            parts.append(f"质检异常 {len(result.quality_issues)}")
        if result.duplicate_groups is not None:
            n_dup = sum(g.size - 1 for g in result.duplicate_groups if g.size > 1)
            parts.append(f"重复 {n_dup}")
        InfoBar.success(
            "导入完成",
            " · ".join(parts) + f"  →  {self._short_path(target)}",
            parent=self.window(), duration=6000,
            position=InfoBarPosition.TOP,
        )
        self.import_done.emit(str(target))
