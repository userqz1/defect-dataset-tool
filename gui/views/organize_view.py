"""Organize view — batch import → classify → land.

Two modes:
  1. **Standalone** — no active project. User picks source dir → classify →
     pick target dir → import.  Emits ``import_done(path_str)``.
  2. **Inbox** — an active project is set.  Images land in
     ``<root>/_inbox/<batch>/images/``.  Target directory is the project
     root (read-only). After import the workflow tracks each image.

After import, emits ``import_done(path_str)`` so MainWindow can
open the dataset in the browser view.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    from gui.app_state import AppState
    from gui.controllers.workflow_controller import WorkflowController


class OrganizeView(QWidget):
    """Batch import → classify → land workflow."""

    import_done = pyqtSignal(str)  # target_root path after successful import

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("organizeView")

        self._state: AppState | None = None
        self._wf_ctrl: WorkflowController | None = None
        self._source_dir: Path | None = None
        self._target_dir: Path | None = None
        self._discovered: list[Path] = []
        self._preview = None  # IngestPreview | None

        root = QVBoxLayout(self)
        root.setContentsMargins(T.PAD_2XL, T.PAD_XL, T.PAD_2XL, T.PAD_XL)
        root.setSpacing(T.GAP_LG)

        self._title = SubtitleLabel("整理台")
        root.addWidget(self._title)

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
        self._exec_frame = self._card()
        exec_lay = QVBoxLayout(self._exec_frame)
        exec_lay.setContentsMargins(T.PAD_XL, T.PAD_LG, T.PAD_XL, T.PAD_LG)
        exec_lay.setSpacing(T.GAP)

        tgt_row = QHBoxLayout()
        self._tgt_title = StrongBodyLabel("④ 目标目录")
        tgt_row.addWidget(self._tgt_title)
        tgt_row.addStretch(1)
        self._tgt_btn = PushButton("选择")
        self._tgt_btn.setIcon(FIF.FOLDER)
        self._tgt_btn.setFixedWidth(80)
        self._tgt_btn.clicked.connect(self._pick_target)
        tgt_row.addWidget(self._tgt_btn)
        exec_lay.addLayout(tgt_row)

        self._tgt_label = CaptionLabel("未选择")
        exec_lay.addWidget(self._tgt_label)

        # Post-ingest checks (§6.4)
        self._checks_row_widget = QWidget()
        checks_row = QHBoxLayout(self._checks_row_widget)
        checks_row.setContentsMargins(0, 0, 0, 0)
        checks_row.setSpacing(T.GAP_LG)
        self._run_quality_chk = CheckBox("导入后质检")
        self._run_quality_chk.setChecked(True)
        self._run_dedup_chk = CheckBox("导入后去重")
        self._run_dedup_chk.setChecked(True)
        checks_row.addWidget(self._run_quality_chk)
        checks_row.addWidget(self._run_dedup_chk)
        checks_row.addStretch(1)
        exec_lay.addWidget(self._checks_row_widget)

        self._import_btn = PrimaryPushButton("开始导入")
        self._import_btn.setIcon(FIF.DOWNLOAD)
        self._import_btn.setEnabled(False)
        self._import_btn.clicked.connect(self._run_import)
        exec_lay.addWidget(self._import_btn, alignment=Qt.AlignmentFlag.AlignRight)
        root.addWidget(self._exec_frame)

        root.addStretch(1)

    # ---------- Public ----------

    def set_state(self, state: AppState,
                  wf_ctrl: WorkflowController) -> None:
        """Inject shared state.  Call once from MainWindow after creation."""
        self._state = state
        self._wf_ctrl = wf_ctrl
        state.project_changed.connect(self._sync_inbox_mode)

    @property
    def _inbox_mode(self) -> bool:
        return (self._state is not None
                and self._state.project is not None)

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

    def _sync_inbox_mode(self, project) -> None:
        """Toggle between inbox mode and standalone mode."""
        inbox = project is not None
        # In inbox mode: target = project root, hide target picker + checks
        self._tgt_btn.setVisible(not inbox)
        self._checks_row_widget.setVisible(not inbox)
        if inbox:
            self._title.setText(f"整理台 — {project.name}")
            self._tgt_title.setText("④ 导入到项目")
            self._tgt_label.setText(self._short_path(project.root_path))
            self._target_dir = project.root_path
            self._import_btn.setText("导入到收件箱")
        else:
            self._title.setText("整理台")
            self._tgt_title.setText("④ 目标目录")
            self._tgt_label.setText("未选择")
            self._target_dir = None
            self._import_btn.setText("开始导入")
        self._update_import_btn()

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

        # Review #23: the default RULES["by_subdir"] is a module-level
        # singleton with source_root=None, which made images directly
        # under the user's picked root look like they belonged to a
        # category named after the root directory itself. Build a fresh
        # rule instance so source_root points at the real selection.
        from core.ingest import BySubdirRule, RULES, preview
        rule_key = self._rule_key()
        if rule_key == "by_subdir":
            rule = BySubdirRule(source_root=self._source_dir)
        else:
            rule = RULES[rule_key]
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
        if self._inbox_mode:
            # inbox mode: only need source images discovered
            ok = len(self._discovered) > 0
        else:
            # standalone: need preview + target
            ok = (self._preview is not None
                  and self._preview.placed_count > 0
                  and self._target_dir is not None)
        self._import_btn.setEnabled(ok)

    def _run_import(self) -> None:
        if self._inbox_mode:
            self._run_inbox_import()
        else:
            self._run_standalone_import()

    # -- Inbox import (into project's _inbox) --

    def _run_inbox_import(self) -> None:
        if not self._source_dir or not self._wf_ctrl:
            return
        src = self._source_dir

        def task(progress_cb):
            return self._wf_ctrl.import_to_inbox(
                [src], progress_cb=progress_cb,
            )

        from gui.workers.batch_runner import BatchRunner
        runner = BatchRunner(self.window(), "导入到收件箱")
        runner.run(task, on_done=self._on_inbox_done)

    def _on_inbox_done(self, count: int) -> None:
        project = self._state.project if self._state else None
        name = project.name if project else ""
        InfoBar.success(
            "导入完成",
            f"{count:,} 张图片已导入收件箱 — {name}",
            parent=self.window(), duration=6000,
            position=InfoBarPosition.TOP,
        )
        if project:
            self.import_done.emit(str(project.root_path))

    # -- Standalone import (classify → target dir) --

    def _run_standalone_import(self) -> None:
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
            on_done=lambda result: self._on_standalone_done(result, tgt),
        )

    def _on_standalone_done(self, result, target: Path) -> None:
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
        # Create WorkItems for newly imported images so they enter the
        # production queue immediately (not just on next scan).
        self._create_work_items_for_import(result, target)
        self.import_done.emit(str(target))

    def _create_work_items_for_import(self, result, target: Path) -> None:
        """Register imported images in the workflow as NEW items."""
        if self._state is None or self._state.project is None:
            return
        root = self._state.project.root_path
        wf = self._state.workflow
        if wf is None:
            return
        from core.workflow import WorkItem, WorkStatus, make_id, _now_iso
        now = _now_iso()
        existing_paths = {item.relative_path for item in wf.items}
        new_items = []
        for dest in getattr(result, "destinations", []):
            try:
                rel = Path(dest).relative_to(root).as_posix()
            except (ValueError, TypeError):
                continue
            if rel not in existing_paths:
                new_items.append(WorkItem(
                    item_id=make_id(),
                    relative_path=rel,
                    status=WorkStatus.NEW,
                    updated_at=now,
                ))
        if new_items:
            wf.items.extend(new_items)
            from core import workflow_store
            workflow_store.save(root, wf)
            self._state.refresh_workflow_summary()
