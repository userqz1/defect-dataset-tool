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
    PrimaryPushButton,
    ToolButton,
)

from core.models import Dataset
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
        title_box.addWidget(self._name_label)
        title_box.addWidget(self._path_label)

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

        lay.addWidget(strip)

        # --- Right: catalog toggle + primary open button ---
        self._catalog_btn = ToolButton(FIF.PIE_SINGLE)
        self._catalog_btn.setCheckable(True)
        self._catalog_btn.setChecked(True)
        self._catalog_btn.toggled.connect(self.catalog_toggled.emit)
        lay.addWidget(self._catalog_btn)

        self._open_btn = PrimaryPushButton(i18n.t("ds.open_dir"))
        self._open_btn.setIcon(FIF.FOLDER)
        # Width expands to fit "Open dataset" (EN) without truncation; zh
        # "选择目录" is narrower and just gets extra padding, which is fine.
        self._open_btn.setMinimumWidth(140)
        self._open_btn.clicked.connect(self.open_clicked.emit)
        lay.addWidget(self._open_btn)

        i18n.bus.language_changed.connect(self._retranslate)

    def _retranslate(self, _lang: str) -> None:
        # name label only re-applies when cleared (otherwise it shows the
        # dataset name, which is user data — not translatable).
        if self._name_label.text() in ("未选择数据集", "No dataset"):
            self._name_label.setText(i18n.t("ds.empty"))
        for cell in (self._stat_images, self._stat_classes, self._stat_labeled,
                      self._stat_ratio, self._stat_flagged):
            cell.retranslate()
        self._open_btn.setText(i18n.t("ds.open_dir"))

    # ---------- public setters ----------

    def set_open_enabled(self, enabled: bool) -> None:
        self._open_btn.setEnabled(enabled)

    def clear(self) -> None:
        self._name_label.setText(i18n.t("ds.empty"))
        self._path_label.setText("")
        for cell in (self._stat_images, self._stat_classes, self._stat_labeled,
                      self._stat_ratio, self._stat_flagged):
            cell.set_value("—")

    def set_dataset(self, ds: Dataset, flagged_count: int = 0) -> None:
        """Populate title + stat strip from a loaded Dataset.

        ``flagged_count`` comes from AppState.quality_issues (the caller
        already has that state; re-plumbing it here would duplicate).
        """
        root = ds.root_path
        self._name_label.setText(root.name if root else ds.name or "数据集")
        self._path_label.setText(self._fmt_path(root))

        self._stat_images.set_value(f"{ds.total_images:,}")
        self._stat_classes.set_value(str(len(ds.categories)))

        # Labeled %: rely on has_label flags from count_annotations phase.
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

    def set_flagged_count(self, n: int) -> None:
        """Update just the Flagged stat after a quality-check run."""
        self._stat_flagged.set_value(f"{n}" if n else "0", warn=n > 0)

    @staticmethod
    def _fmt_path(p: Path | None) -> str:
        if p is None:
            return ""
        text = str(p)
        # Keep path compact so the header fits narrower windows without
        # overflow. Middle-elide once past ~46 chars.
        if len(text) > 46:
            return text[:16] + "…" + text[-28:]
        return text
