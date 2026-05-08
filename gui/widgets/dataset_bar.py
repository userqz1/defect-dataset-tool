"""Dataset bar — serif title + mono path + aggregated stat strip.

Replaces the old thin topbar (path + "N 图片 · M 类" + 选择目录) with a
Claude-web-styled header: pulsing sync dot, serif dataset name, path
underneath in monospace, and a stat strip on the right showing
Images / Classes / Labeled% / Max:Min / Flagged.

See _design/.../README.md §4 "Dataset Bar".
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    Qt,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel,
    FluentIcon as FIF,
    ToolButton,
)

from core.models import Dataset
from core.workflow import WorkflowSummary
from gui import i18n
from gui.theme import T


class _SyncDot(QWidget):
    """6px pulsing dot — pulses between accent bg and fading halo.

    Pure QPainter so color follows the token proxy without hardcoding.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(14, 14)
        self._halo = 0.0  # 0..1, animated
        self._anim = QPropertyAnimation(self, b"halo", self)
        self._anim.setDuration(2000)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setLoopCount(-1)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._anim.start()

    def _get_halo(self) -> float:
        return self._halo

    def _set_halo(self, v: float) -> None:
        self._halo = v
        self.update()

    halo = pyqtProperty(float, fget=_get_halo, fset=_set_halo)

    def paintEvent(self, _e) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        accent = QColor(T.ACCENT)
        # Halo fades out as it expands
        halo_color = QColor(accent)
        halo_color.setAlphaF(max(0.0, 0.35 * (1.0 - self._halo)))
        halo_r = 3 + 4 * self._halo
        cx, cy = self.width() / 2, self.height() / 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(halo_color)
        p.drawEllipse(int(cx - halo_r), int(cy - halo_r),
                       int(halo_r * 2), int(halo_r * 2))
        p.setBrush(accent)
        p.drawEllipse(int(cx - 3), int(cy - 3), 6, 6)


class _Stat(QWidget):
    """One key/value cell in the stat strip.

    - Key: 10px uppercase tracked, fg-3; driven by an i18n key so it
      retranslates on language switch.
    - Value: 15px mono, fg (or warn when flagged as a problem).
    """

    def __init__(self, key_i18n: str, value: str, warn: bool = False) -> None:
        super().__init__()
        self.setObjectName("statCell")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 2, 12, 2)
        lay.setSpacing(2)
        self._key_i18n = key_i18n
        self._key = CaptionLabel(i18n.t(key_i18n).upper())
        self._key.setObjectName("statKey")
        self._val = CaptionLabel(value)
        self._val.setObjectName("statValueWarn" if warn else "statValue")
        lay.addWidget(self._key)
        lay.addWidget(self._val)
        self._sync_min_width()

    def _sync_min_width(self) -> None:
        # Pin a minimum width to the key's measured text so the HBox layout
        # never truncates the cell when the title block competes for space.
        # "FLAGGED" EN is longer than "问题" zh — using whichever is wider.
        from PyQt6.QtGui import QFontMetrics
        fm_key = QFontMetrics(self._key.font())
        fm_val = QFontMetrics(self._val.font())
        key_w = fm_key.horizontalAdvance(self._key.text())
        val_w = fm_val.horizontalAdvance(self._val.text() or "0000")
        self.setMinimumWidth(max(key_w, val_w) + 24)  # 12+12 padding

    def retranslate(self) -> None:
        self._key.setText(i18n.t(self._key_i18n).upper())
        self._sync_min_width()

    def set_value(self, value: str, warn: bool = False) -> None:
        self._val.setText(value)
        self._val.setObjectName("statValueWarn" if warn else "statValue")
        self._val.style().unpolish(self._val)
        self._val.style().polish(self._val)
        self._sync_min_width()


class DatasetBar(QFrame):
    """Serif header + stat strip — sits at the top of DatasetBrowserView.

    Signals mirror the two actions that used to live in the old topbar:

    - ``open_clicked`` — user clicked the primary 选择目录 button.
    - ``catalog_toggled(bool)`` — user toggled the catalog visibility.
      Currently the browser has no separate catalog panel (class tree
      lives in its own column), so the signal is wired but default
      handlers can ignore it.
    """

    open_clicked = pyqtSignal()
    catalog_toggled = pyqtSignal(bool)
    # Global actions — live here after the tool_sidebar retirement.  The
    # controller runs the operation (``refresh`` → session rescan;
    # ``undo`` → ``core.history.try_undo_last`` + rescan).
    refresh_clicked = pyqtSignal()
    undo_clicked = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("datasetBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(T.PAD_LG, T.PAD_LG, T.PAD_LG, T.PAD)
        lay.setSpacing(T.PAD)

        # --- Left: sync dot + (name / path) stacked ---
        title_row = QHBoxLayout()
        title_row.setSpacing(T.GAP)
        title_row.setContentsMargins(0, 0, 0, 0)

        self._dot = _SyncDot()
        title_row.addWidget(self._dot, 0, Qt.AlignmentFlag.AlignVCenter)

        title_box = QVBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(0)
        self._name_label = CaptionLabel(i18n.t("ds.empty"))
        self._name_label.setObjectName("datasetName")
        self._path_label = CaptionLabel("")
        self._path_label.setObjectName("datasetPath")
        self._fmt_label = CaptionLabel("")
        self._fmt_label.setObjectName("datasetFmt")
        self._fmt_label.setVisible(False)
        # Scan-in-progress banner — sits next to the path. Hidden unless
        # AppState.scan_active is True.  A visible text cue lets the user
        # know stat numbers are still settling, complementing the pulsing
        # dot (which alone is too subtle for a "load is happening" signal
        # on a first-open cold scan).
        self._loading_label = CaptionLabel(i18n.t("ds.loading"))
        self._loading_label.setObjectName("datasetLoading")
        self._loading_label.setVisible(False)

        title_box.addWidget(self._name_label)
        # path + format badge + loading banner on one row
        path_row = QHBoxLayout()
        path_row.setContentsMargins(0, 0, 0, 0)
        path_row.setSpacing(T.GAP)
        path_row.addWidget(self._path_label)
        path_row.addWidget(self._fmt_label)
        path_row.addWidget(self._loading_label)
        path_row.addStretch(1)
        title_box.addLayout(path_row)

        title_row.addLayout(title_box)
        lay.addLayout(title_row)

        lay.addStretch(1)

        # --- Middle: stat strip (5 cells) ---
        strip = QFrame()
        strip.setObjectName("statStrip")
        strip_lay = QHBoxLayout(strip)
        strip_lay.setContentsMargins(0, 0, 0, 0)
        strip_lay.setSpacing(0)

        self._stat_images = _Stat("ds.stat.images", "—")
        self._stat_classes = _Stat("ds.stat.classes", "—")
        self._stat_labeled = _Stat("ds.stat.labeled", "—")
        self._stat_ratio = _Stat("ds.stat.ratio", "—")
        self._stat_flagged = _Stat("ds.stat.flagged", "—")
        for w in (self._stat_images, self._stat_classes, self._stat_labeled,
                   self._stat_ratio, self._stat_flagged):
            strip_lay.addWidget(w)

        # Workflow stats — hidden until a workflow is loaded
        self._stat_pending = _Stat("ds.stat.pending", "—")
        self._stat_review = _Stat("ds.stat.review", "—")
        self._stat_ready = _Stat("ds.stat.ready", "—")
        for w in (self._stat_pending, self._stat_review, self._stat_ready):
            w.setVisible(False)
            strip_lay.addWidget(w)

        lay.addWidget(strip)

        # --- Right: global actions + catalog toggle + primary open ---
        # Refresh + Undo are the two "global" actions that used to live
        # at the top of the tool_sidebar.  They stay alongside the
        # catalog toggle / open button so the user has exactly one
        # place to look for toolbar-level commands.
        self._refresh_btn = ToolButton(FIF.SYNC)
        self._refresh_btn.setToolTip(i18n.t("tools.refresh"))
        self._refresh_btn.setEnabled(False)
        self._refresh_btn.clicked.connect(self.refresh_clicked.emit)
        lay.addWidget(self._refresh_btn)

        self._undo_btn = ToolButton(FIF.RETURN)
        self._undo_btn.setToolTip(i18n.t("tools.undo"))
        self._undo_btn.setEnabled(False)
        self._undo_btn.clicked.connect(self.undo_clicked.emit)
        lay.addWidget(self._undo_btn)

        self._catalog_btn = ToolButton(FIF.PIE_SINGLE)
        self._catalog_btn.setCheckable(True)
        self._catalog_btn.setChecked(True)
        self._catalog_btn.toggled.connect(self.catalog_toggled.emit)
        lay.addWidget(self._catalog_btn)

        # "Open another dataset" is a secondary in-workbench action —
        # the primary entry lives on the home page.  Render as a small
        # tool button (icon-only) instead of the v3 PrimaryPushButton.
        self._open_btn = ToolButton(FIF.FOLDER)
        self._open_btn.setToolTip(i18n.t("ds.open_dir"))
        self._open_btn.clicked.connect(self.open_clicked.emit)
        lay.addWidget(self._open_btn)

        i18n.bus.language_changed.connect(self._retranslate)

    def _retranslate(self, _lang: str) -> None:
        # name label only re-applies when cleared (otherwise it shows the
        # dataset name, which is user data — not translatable).
        if self._name_label.text() in ("未选择数据集", "No dataset"):
            self._name_label.setText(i18n.t("ds.empty"))
        for cell in (self._stat_images, self._stat_classes, self._stat_labeled,
                      self._stat_ratio, self._stat_flagged,
                      self._stat_pending, self._stat_review, self._stat_ready):
            cell.retranslate()
        self._open_btn.setToolTip(i18n.t("ds.open_dir"))
        self._loading_label.setText(i18n.t("ds.loading"))
        self._refresh_btn.setToolTip(i18n.t("tools.refresh"))
        # Undo tooltip mixes a translated prefix with a mutable summary
        # (``撤销: <op>`` / ``没有可撤销的操作``) owned by
        # ``set_undo_tooltip``; retranslate only resets the "no-undo"
        # fallback when that's currently shown.
        if not self._undo_btn.isEnabled():
            self._undo_btn.setToolTip(i18n.t("tools.undo.none"))
        else:
            # Preserve the per-entry summary the controller pushed;
            # only the "撤销:" prefix would change across languages,
            # which is negligible against the summary visibility win.
            pass

    # ---------- public setters ----------

    def set_open_enabled(self, enabled: bool) -> None:
        self._open_btn.setEnabled(enabled)

    def set_refresh_enabled(self, enabled: bool) -> None:
        """Gate the refresh button on "dataset loaded"."""
        self._refresh_btn.setEnabled(enabled)

    def set_undo_enabled(self, enabled: bool) -> None:
        """Gate the undo button on "history has an undoable op".

        When disabled, the tooltip resets to the "no undoable op" fallback
        so the user isn't left staring at a stale ``撤销: <op>`` label.
        """
        self._undo_btn.setEnabled(enabled)
        if not enabled:
            self._undo_btn.setToolTip(i18n.t("tools.undo.none"))

    def set_undo_tooltip(self, text: str) -> None:
        """Push a per-entry undo summary (``撤销: <op>``) from the controller."""
        self._undo_btn.setToolTip(text)

    def clear(self) -> None:
        self._name_label.setText(i18n.t("ds.empty"))
        self._path_label.setText("")
        self._fmt_label.setVisible(False)
        for cell in (self._stat_images, self._stat_classes, self._stat_labeled,
                      self._stat_ratio, self._stat_flagged):
            cell.set_value("—")
        self.set_workflow_summary(None)

    def set_dataset(self, ds: Dataset, flagged_count: int = 0) -> None:
        """Populate title + stat strip from a loaded Dataset.

        ``flagged_count`` comes from AppState.quality_issues (the caller
        already has that state; re-plumbing it here would duplicate).
        """
        root = ds.root_path
        self._name_label.setText(root.name if root else ds.name or "数据集")
        self._path_label.setText(self._fmt_path(root))
        # Full path lives in the tooltip — the displayed path is
        # aggressively elided to keep the bar narrow.
        if root is not None:
            self._path_label.setToolTip(str(root))
        else:
            self._path_label.setToolTip("")

        self._stat_images.set_value(f"{ds.total_images:,}")
        self._stat_classes.set_value(str(len(ds.categories)))

        # Labeled %: has_label flags are set during filesystem scan (Phase 1).
        labeled = 0
        for cat in ds.categories:
            labeled += sum(1 for img in cat.images if img.has_label)
        pct = (labeled / ds.total_images * 100) if ds.total_images else 0
        self._stat_labeled.set_value(f"{pct:.0f}%")

        # Imbalance (max:min) — warn when >= 20:1.
        counts = [c.image_count for c in ds.categories if c.image_count > 0]
        if len(counts) >= 2:
            ratio = max(counts) / min(counts)
            self._stat_ratio.set_value(f"{ratio:.0f}:1", warn=ratio >= 20)
        else:
            self._stat_ratio.set_value("—")

        self._stat_flagged.set_value(
            f"{flagged_count}" if flagged_count else "0",
            warn=flagged_count > 0,
        )

    def update_from_sample_set(self, ss) -> None:
        """Refine labeled% from SampleSet (region-aware, more accurate).

        Called when sample_set_changed fires.  SampleSet distinguishes
        "has regions" from "has a label file" — empty label files are
        correctly counted as unlabeled here.
        """
        if ss is None:
            return
        n_annotated = sum(1 for s in ss.samples if s.regions)
        total = len(ss.samples)
        pct = (n_annotated / total * 100) if total else 0
        self._stat_labeled.set_value(f"{pct:.0f}%")

    def set_sample_set_status(self, status_value: str) -> None:
        """Update the sync dot color based on SampleSetStatus.

        - ``ready``       — accent pulse (normal).
        - ``stale``       — orange pulse (data may be outdated).
        - ``unavailable`` — stop pulsing (no unified data).
        """
        from gui.app_state import SampleSetStatus
        status = SampleSetStatus(status_value)
        if status is SampleSetStatus.READY:
            self._dot._anim.resume() if self._dot._anim.state() != self._dot._anim.State.Running else None
            self._dot._anim.start() if self._dot._anim.state() == self._dot._anim.State.Stopped else None
            self._dot.setToolTip("")
        elif status is SampleSetStatus.STALE:
            self._dot.setToolTip("统一模型可能过期 · 正在刷新…")
        else:  # UNAVAILABLE
            self._dot._anim.pause()
            self._dot.setToolTip("统一模型不可用 · 使用磁盘回退")

    def set_flagged_count(self, n: int) -> None:
        """Update just the Flagged stat after a quality-check run."""
        self._stat_flagged.set_value(f"{n}" if n else "0", warn=n > 0)

    def set_loading(self, active: bool) -> None:
        """Show/hide the "model loading" text banner in the title row.

        Bound to ``AppState.scan_active_changed``.  The pulsing sync dot
        already hints at activity, but a visible text cue is what the
        user asked for — the dot alone is too easy to miss on a
        cold-open scan where nothing else on screen has redrawn yet.
        """
        self._loading_label.setVisible(bool(active))

    def set_catalog_open(self, open_: bool) -> None:
        """Sync the catalog toggle button state without re-emitting."""
        self._catalog_btn.blockSignals(True)
        self._catalog_btn.setChecked(open_)
        self._catalog_btn.blockSignals(False)

    def set_catalog_btn_visible(self, visible: bool) -> None:
        """Show/hide the catalog toggle button.

        Catalog only exists on the 标注工作台 stage; on every other
        stage the context panel is force-hidden, so showing this button
        anyway would let the user click a control with no visible effect.
        """
        self._catalog_btn.setVisible(bool(visible))

    def set_annotation_format(self, fmt: str) -> None:
        """Show the project's active annotation format as a badge."""
        if fmt:
            from core.format_convert import FORMATS
            info = FORMATS.get(fmt)
            display = info.display_name if info else fmt.upper()
            self._fmt_label.setText(display)
            self._fmt_label.setVisible(True)
        else:
            self._fmt_label.setVisible(False)

    def set_workflow_summary(self, summary: WorkflowSummary | None) -> None:
        """Show/hide workflow stat cells based on active workflow."""
        active = summary is not None and summary.total > 0
        self._stat_pending.setVisible(active)
        self._stat_review.setVisible(active)
        self._stat_ready.setVisible(active)
        if not active:
            return
        pending = summary.new + summary.prelabeled
        review = summary.review_pending + summary.needs_fix
        ready = summary.ready + summary.exported
        self._stat_pending.set_value(str(pending), warn=pending > 0)
        self._stat_review.set_value(str(review), warn=review > 0)
        self._stat_ready.set_value(str(ready))

    @staticmethod
    def _fmt_path(p: Path | None) -> str:
        if p is None:
            return ""
        text = str(p)
        # Aggressive elision — DatasetBar shares its row with stats and
        # global toolbar buttons; long paths used to push them off-
        # screen. Full path is in the tooltip (see set_dataset).
        if len(text) > 32:
            return text[:10] + "…" + text[-20:]
        return text
