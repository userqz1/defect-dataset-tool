"""Organize view — import images into the current project.

Progressive-disclosure layout:
  1. **Drop zone** — drag folder or click to select (always visible)
  2. **Rules**     — classification rule radio buttons (after source selected)
  3. **Preview**   — category distribution table (after preview runs)
  4. **Import**    — target info + execute button (after source selected)

Two modes:
  - **Inbox** — active project → images land in ``<root>/_inbox/<batch>/``.
  - **Standalone** — no project → user picks target dir.

Emits ``import_done(path_str)`` so MainWindow can reopen the dataset.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QDragEnterEvent, QDropEvent, QPainter, QPen
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QRadioButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CaptionLabel,
    CheckBox,
    FluentIcon as FIF,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    PushButton,
    StrongBodyLabel,
)

from gui.i18n import t
from gui.theme import T

if TYPE_CHECKING:
    from gui.app_state import AppState
    from gui.controllers.workflow_controller import WorkflowController


# ── Drop zone (source selector) ──────────────────────────────────

class _SourceZone(QFrame):
    """Large drag-and-drop area for selecting the source image folder.

    Two visual states:
      - **Empty** — big dashed outline, icon + title + button + note.
      - **Filled** — compact summary of source path + file count,
        with a "change" button.  Drop zone shrinks.
    """

    button_clicked = pyqtSignal()
    folder_dropped = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAcceptDrops(True)
        self.setMinimumHeight(160)

        self._hovering = False
        self._has_source = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(T.PAD_2XL, T.PAD_3XL, T.PAD_2XL, T.PAD_3XL)
        lay.setSpacing(T.GAP_LG)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # ── Empty state widgets ──
        self._empty_container = QWidget()
        e_lay = QVBoxLayout(self._empty_container)
        e_lay.setContentsMargins(0, 0, 0, 0)
        e_lay.setSpacing(T.GAP_LG)
        e_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = StrongBodyLabel(t("org.drop.title"))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        e_lay.addWidget(title)

        btn = PrimaryPushButton(t("org.drop.btn"))
        btn.setIcon(FIF.FOLDER_ADD)
        btn.setFixedHeight(T.CONTROL_HEIGHT)
        btn.clicked.connect(self.button_clicked.emit)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(btn)
        btn_row.addStretch(1)
        e_lay.addLayout(btn_row)

        note = CaptionLabel(t("org.drop.note"))
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        e_lay.addWidget(note)

        lay.addWidget(self._empty_container)

        # ── Filled state widgets (initially hidden) ──
        self._filled_container = QWidget()
        f_lay = QVBoxLayout(self._filled_container)
        f_lay.setContentsMargins(0, 0, 0, 0)
        f_lay.setSpacing(T.GAP)

        info_row = QHBoxLayout()
        self._source_lbl = StrongBodyLabel("")
        info_row.addWidget(self._source_lbl, 1)
        change_btn = PushButton(t("org.drop.change"))
        change_btn.setIcon(FIF.FOLDER)
        change_btn.setFixedHeight(28)
        change_btn.clicked.connect(self.button_clicked.emit)
        info_row.addWidget(change_btn)
        f_lay.addLayout(info_row)

        self._count_lbl = CaptionLabel("")
        f_lay.addWidget(self._count_lbl)

        self._filled_container.hide()
        lay.addWidget(self._filled_container)

    def set_source(self, path: Path, count: int) -> None:
        """Switch to the filled state showing source info."""
        self._has_source = True
        short = str(path)
        if len(short) > 55:
            short = "…" + short[-52:]
        self._source_lbl.setText(t("org.drop.source", path=short))
        self._count_lbl.setText(t("org.drop.count", n=count))

        self._empty_container.hide()
        self._filled_container.show()
        self.setMinimumHeight(0)  # shrink
        self.update()

    def clear_source(self) -> None:
        """Reset to empty state."""
        self._has_source = False
        self._filled_container.hide()
        self._empty_container.show()
        self.setMinimumHeight(160)
        self.update()

    # ── Drag-and-drop ─────────────────────────────────────────────

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        mime = event.mimeData()
        if mime and mime.hasUrls():
            event.acceptProposedAction()
            self._hovering = True
            self.update()

    def dragLeaveEvent(self, event) -> None:
        self._hovering = False
        self.update()

    def dropEvent(self, event: QDropEvent) -> None:
        self._hovering = False
        self.update()
        mime = event.mimeData()
        if not mime:
            return
        for url in mime.urls():
            path = url.toLocalFile()
            if path:
                self.folder_dropped.emit(path)
                return

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        # Dashed border only in empty state or while hovering
        if not self._has_source or self._hovering:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            color = QColor(T.ACCENT) if self._hovering else QColor(T.BORDER)
            width = 2.5 if self._hovering else 1.5
            pen = QPen(color, width, Qt.PenStyle.DashLine)
            p.setPen(pen)
            margin = width / 2 + 1
            rect = QRectF(margin, margin,
                          self.width() - 2 * margin,
                          self.height() - 2 * margin)
            p.drawRoundedRect(rect, T.RADIUS_LG, T.RADIUS_LG)
            p.end()


# ── Main view ─────────────────────────────────────────────────────

class OrganizeView(QWidget):
    """Import images → classify → land workflow."""

    import_done = pyqtSignal(str)
    back_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("organizeView")

        self._state: AppState | None = None
        self._wf_ctrl: WorkflowController | None = None
        self._source_dir: Path | None = None
        self._target_dir: Path | None = None
        self._discovered: list[Path] = []
        self._preview = None  # IngestPreview | None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Scroll wrapper
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        body = QWidget()
        root = QVBoxLayout(body)
        root.setContentsMargins(T.PAD_2XL, T.PAD_XL, T.PAD_2XL, T.PAD_XL)
        root.setSpacing(T.GAP_XL)

        # ── Back + title ──
        title_row = QHBoxLayout()
        back_btn = PushButton(t("org.back"))
        back_btn.setIcon(FIF.LEFT_ARROW)
        back_btn.setFixedHeight(T.CONTROL_HEIGHT)
        back_btn.clicked.connect(self.back_requested.emit)
        title_row.addWidget(back_btn)
        self._title = StrongBodyLabel(t("org.title"))
        f = self._title.font()
        f.setPointSize(14)
        self._title.setFont(f)
        title_row.addWidget(self._title)
        title_row.addStretch(1)
        root.addLayout(title_row)

        # ── Block 1: Drop zone ──
        self._source_zone = _SourceZone()
        self._source_zone.button_clicked.connect(self._pick_source)
        self._source_zone.folder_dropped.connect(
            lambda p: self._apply_source(Path(p)))
        root.addWidget(self._source_zone)

        # ── Block 2: Classification rules (hidden until source) ──
        self._rules_section = QWidget()
        rules_lay = QHBoxLayout(self._rules_section)
        rules_lay.setContentsMargins(0, 0, 0, 0)
        rules_lay.setSpacing(T.GAP_LG)

        rules_lay.addWidget(StrongBodyLabel(t("org.rule.label")))

        self._radio_subdir = QRadioButton(t("org.rule.subdir"))
        self._radio_prefix = QRadioButton(t("org.rule.prefix"))
        self._radio_single = QRadioButton(t("org.rule.single"))

        self._radio_subdir.setChecked(True)

        rules_lay.addWidget(self._radio_subdir)
        rules_lay.addWidget(self._radio_prefix)
        rules_lay.addWidget(self._radio_single)
        rules_lay.addStretch(1)

        self._preview_btn = PushButton(t("org.preview"))
        self._preview_btn.setIcon(FIF.VIEW)
        self._preview_btn.setFixedHeight(28)
        self._preview_btn.clicked.connect(self._run_preview)
        rules_lay.addWidget(self._preview_btn)

        self._rules_section.hide()
        root.addWidget(self._rules_section)

        # ── Block 3: Preview table (hidden until preview runs) ──
        self._preview_section = QFrame()
        self._preview_section.setObjectName("chartFrame")
        self._preview_section.setAttribute(
            Qt.WidgetAttribute.WA_StyledBackground, True)
        pv_lay = QVBoxLayout(self._preview_section)
        pv_lay.setContentsMargins(T.PAD_XL, T.PAD_LG, T.PAD_XL, T.PAD_LG)
        pv_lay.setSpacing(T.GAP)

        pv_header = QHBoxLayout()
        pv_header.addWidget(StrongBodyLabel(t("org.preview")))
        self._pv_summary = CaptionLabel("")
        pv_header.addStretch(1)
        pv_header.addWidget(self._pv_summary)
        pv_lay.addLayout(pv_header)

        self._pv_table = QTableWidget(0, 2)
        self._pv_table.setHorizontalHeaderLabels(
            [t("org.preview.col_class"), t("org.preview.col_count")])
        self._pv_table.horizontalHeader().setStretchLastSection(True)
        self._pv_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self._pv_table.verticalHeader().setVisible(False)
        self._pv_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._pv_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._pv_table.setMaximumHeight(280)
        pv_lay.addWidget(self._pv_table)

        self._preview_section.hide()
        root.addWidget(self._preview_section)

        # ── Block 4: Target + Import (hidden until source) ──
        self._import_section = QWidget()
        imp_lay = QVBoxLayout(self._import_section)
        imp_lay.setContentsMargins(0, 0, 0, 0)
        imp_lay.setSpacing(T.GAP)

        # Target info line
        tgt_row = QHBoxLayout()
        tgt_row.setSpacing(T.GAP)
        self._tgt_title = StrongBodyLabel(t("org.target"))
        tgt_row.addWidget(self._tgt_title)
        self._tgt_label = CaptionLabel(t("org.target.none"))
        tgt_row.addWidget(self._tgt_label, 1)
        self._tgt_btn = PushButton(t("org.target.select"))
        self._tgt_btn.setIcon(FIF.FOLDER)
        self._tgt_btn.setFixedHeight(28)
        self._tgt_btn.clicked.connect(self._pick_target)
        tgt_row.addWidget(self._tgt_btn)
        imp_lay.addLayout(tgt_row)

        # Post-ingest checks (standalone mode only)
        self._checks_row = QWidget()
        checks_lay = QHBoxLayout(self._checks_row)
        checks_lay.setContentsMargins(0, 0, 0, 0)
        checks_lay.setSpacing(T.GAP_LG)
        self._run_quality_chk = CheckBox(t("org.check.quality"))
        self._run_quality_chk.setChecked(True)
        self._run_dedup_chk = CheckBox(t("org.check.dedup"))
        self._run_dedup_chk.setChecked(True)
        checks_lay.addWidget(self._run_quality_chk)
        checks_lay.addWidget(self._run_dedup_chk)
        checks_lay.addStretch(1)
        imp_lay.addWidget(self._checks_row)

        # Import row: safety note + button
        import_row = QHBoxLayout()
        import_row.setSpacing(T.GAP_LG)
        self._safety_note = CaptionLabel(t("org.safety_note"))
        import_row.addWidget(self._safety_note)
        import_row.addStretch(1)
        self._import_btn = PrimaryPushButton(t("org.import"))
        self._import_btn.setIcon(FIF.DOWNLOAD)
        self._import_btn.setFixedHeight(T.CONTROL_HEIGHT)
        self._import_btn.setEnabled(False)
        self._import_btn.clicked.connect(self._run_import)
        import_row.addWidget(self._import_btn)
        imp_lay.addLayout(import_row)

        self._import_section.hide()
        root.addWidget(self._import_section)

        root.addStretch(1)
        scroll.setWidget(body)
        outer.addWidget(scroll)

    # ── Public API ────────────────────────────────────────────────

    def set_state(self, state: AppState,
                  wf_ctrl: WorkflowController) -> None:
        """Inject shared state.  Call once from MainWindow after creation."""
        self._state = state
        self._wf_ctrl = wf_ctrl
        state.project_changed.connect(self._sync_inbox_mode)

    def set_source_path(self, path: str | Path) -> None:
        """Pre-fill the source directory (e.g. from drag-and-drop).

        Runs discovery immediately so the user sees the file count and
        can proceed to preview / import without an extra click.
        """
        self._apply_source(Path(path))

    @property
    def _inbox_mode(self) -> bool:
        return (self._state is not None
                and self._state.project is not None)

    # ── Helpers ───────────────────────────────────────────────────

    @staticmethod
    def _short_path(p: Path, max_len: int = 55) -> str:
        s = str(p)
        return ("…" + s[-(max_len - 1):]) if len(s) > max_len else s

    def _rule_key(self) -> str:
        if self._radio_subdir.isChecked():
            return "by_subdir"
        if self._radio_prefix.isChecked():
            return "by_filename_prefix"
        return "manual"

    def _sync_inbox_mode(self, project) -> None:
        """Toggle between inbox mode and standalone mode."""
        inbox = project is not None
        self._tgt_btn.setVisible(not inbox)
        self._checks_row.setVisible(not inbox)
        if inbox:
            self._title.setText(t("org.title_project", name=project.name))
            self._tgt_title.setText(t("org.target"))
            self._tgt_label.setText(
                t("org.target.inbox", name=project.name))
            self._target_dir = project.root_path
            self._import_btn.setText(t("org.import"))
            self._safety_note.setText(t("org.safety_note"))
        else:
            self._title.setText(t("org.title"))
            self._tgt_title.setText(t("org.target"))
            self._tgt_label.setText(t("org.target.none"))
            self._target_dir = None
            self._import_btn.setText(t("org.import"))
            self._safety_note.setText("")
        self._sync_mode_visibility()
        self._update_import_btn()

    # ── Source selection ──────────────────────────────────────────

    def _pick_source(self) -> None:
        d = QFileDialog.getExistingDirectory(
            self, t("org.dlg.pick_source"), str(Path.home()))
        if not d:
            return
        self._apply_source(Path(d))

    def _apply_source(self, source: Path) -> None:
        """Common logic after source folder is known (pick or drop)."""
        if not source.is_dir():
            InfoBar.warning("", t("org.warn.not_folder"),
                            parent=self.window(), duration=2000,
                            position=InfoBarPosition.TOP)
            return
        self._source_dir = source

        from core.ingest import discover
        self._discovered = discover([self._source_dir])
        if not self._discovered:
            InfoBar.warning("", t("org.warn.empty"),
                            parent=self.window(), duration=2500,
                            position=InfoBarPosition.TOP)

        # Update drop zone to filled state
        self._source_zone.set_source(source, len(self._discovered))

        # Clear stale preview
        self._preview = None
        self._pv_table.setRowCount(0)
        self._pv_summary.setText("")
        self._preview_section.hide()

        # Show downstream blocks (progressive disclosure). In project
        # inbox mode, classification happens after the batch lands, so
        # do not show a preview UI that the importer will not apply.
        self._sync_mode_visibility()
        self._import_section.show()
        self._update_import_btn()

    # ── Preview ───────────────────────────────────────────────────

    def _run_preview(self) -> None:
        if self._inbox_mode:
            InfoBar.info("", t("org.info.inbox_hint"),
                         parent=self.window(), duration=2500,
                         position=InfoBarPosition.TOP)
            return
        if not self._discovered:
            InfoBar.warning("", t("org.warn.no_source"),
                            parent=self.window(), duration=2000,
                            position=InfoBarPosition.TOP)
            return

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

        summary = t("org.preview.summary",
                    placed=self._preview.placed_count,
                    cats=self._preview.category_count)
        if self._preview.skipped:
            summary += "  ·  " + t("org.preview.skipped",
                                   n=len(self._preview.skipped))
        self._pv_summary.setText(summary)
        self._preview_section.show()
        self._update_import_btn()

    # ── Target ────────────────────────────────────────────────────

    def _pick_target(self) -> None:
        d = QFileDialog.getExistingDirectory(
            self, t("org.dlg.pick_target"), str(Path.home()))
        if not d:
            return
        self._target_dir = Path(d)
        self._tgt_label.setText(self._short_path(self._target_dir))
        self._update_import_btn()

    # ── Import ────────────────────────────────────────────────────

    def _update_import_btn(self) -> None:
        if self._inbox_mode:
            ok = len(self._discovered) > 0
        else:
            ok = (self._preview is not None
                  and self._preview.placed_count > 0
                  and self._target_dir is not None)
        self._import_btn.setEnabled(ok)

    def _sync_mode_visibility(self) -> None:
        """Keep the page honest about what the current mode can apply."""
        has_source = self._source_dir is not None
        if self._inbox_mode:
            self._rules_section.hide()
            self._preview_section.hide()
        else:
            self._rules_section.setVisible(has_source)

    def _run_import(self) -> None:
        if self._inbox_mode:
            self._run_inbox_import()
        else:
            self._run_standalone_import()

    # -- Inbox import --

    def _run_inbox_import(self) -> None:
        if not self._source_dir or not self._wf_ctrl:
            return
        src = self._source_dir

        def task(progress_cb):
            return self._wf_ctrl.import_to_inbox(
                [src], progress_cb=progress_cb,
            )

        from gui.workers.batch_runner import BatchRunner
        runner = BatchRunner(self.window(), t("org.progress.inbox"))
        runner.run(task, on_done=self._on_inbox_done)

    def _on_inbox_done(self, count: int) -> None:
        project = self._state.project if self._state else None
        name = project.name if project else ""
        InfoBar.success(
            t("org.done.title"),
            t("org.done.inbox", n=count, name=name),
            parent=self.window(), duration=4000,
            position=InfoBarPosition.TOP,
        )
        # Refresh workflow so the inbox batch list picks up the new batch
        if self._state:
            self._state.refresh_workflow_summary()
        # Return to inbox page — the new batch card appears automatically
        self.back_requested.emit()

    # -- Standalone import --

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
        runner = BatchRunner(self.window(), t("org.progress.standalone"))
        runner.run(
            task,
            on_done=lambda result: self._on_standalone_done(result, tgt),
        )

    def _on_standalone_done(self, result, target: Path) -> None:
        parts = [t("org.done.standalone", n=result.copied)]
        if result.quality_issues is not None:
            parts.append(t("org.done.quality",
                           n=len(result.quality_issues)))
        if result.duplicate_groups is not None:
            n_dup = sum(
                g.size - 1 for g in result.duplicate_groups if g.size > 1)
            parts.append(t("org.done.dedup", n=n_dup))
        InfoBar.success(
            t("org.done.title"),
            " · ".join(parts) + f"  →  {self._short_path(target)}",
            parent=self.window(), duration=6000,
            position=InfoBarPosition.TOP,
        )
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
