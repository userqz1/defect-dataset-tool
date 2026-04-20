"""Distribution mini-chart — 40px bar chart + imbalance caption.

Replicates the design handoff's catalog header card:

- Top row: "分布 · DISTRIBUTION" + "244:1 ⚠" right-aligned.
- 40px bar chart, 12 segments (one per class), descending by count.
  - Largest (hot): accent color.
  - Tail classes (< 50 images): warn @ 0.6 opacity.
  - Middle: muted fg-4.
- Footer: min / max counts in mono.
- Caption: "最大类与最小类相差 244倍…" with warn-colored mono digit.

Sits at the top of BrowserView's category sidebar column, above the
class tree — gives users a zoom-out read of dataset imbalance before
they dive into the per-class list.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import CaptionLabel

from core.models import Dataset
from gui import i18n
from gui.theme import T


_TAIL_THRESHOLD = 50  # classes below this count count as "tail"


class _BarChart(QWidget):
    """Flat 40px bar chart — one bar per class, descending by count."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(40)
        self._counts: list[int] = []

    def set_counts(self, counts: list[int]) -> None:
        self._counts = counts
        self.update()

    def paintEvent(self, _e) -> None:  # type: ignore[override]
        if not self._counts:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        n = len(self._counts)
        gap = 2
        bar_w = max(2, (w - gap * (n - 1)) / n)
        m = max(self._counts)
        accent = QColor(T.ACCENT)
        warn = QColor(T.WARNING)
        warn.setAlphaF(0.6)
        muted = QColor(T.TEXT_3)
        muted.setAlphaF(0.4)

        for i, c in enumerate(self._counts):
            frac = (c / m) if m else 0
            bh = max(2, int(h * frac))
            x = int(i * (bar_w + gap))
            y = h - bh
            if i == 0:
                color = accent
            elif c < _TAIL_THRESHOLD:
                color = warn
            else:
                color = muted
            p.fillRect(int(x), int(y), int(bar_w), int(bh), color)


class DistributionChart(QFrame):
    """Complete distribution card — header + chart + footer + caption."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("distributionChart")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(T.PAD_LG, T.PAD, T.PAD_LG, T.PAD)
        lay.setSpacing(6)

        # Header: "分布 · DISTRIBUTION"  —  "X:1 ⚠"
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(0)
        self._head_label = CaptionLabel(i18n.t("dist.head"))
        self._head_label.setObjectName("distributionHead")
        head.addWidget(self._head_label)
        head.addStretch(1)
        self._ratio_label = CaptionLabel("—")
        self._ratio_label.setObjectName("distributionRatio")
        head.addWidget(self._ratio_label)
        lay.addLayout(head)

        self._chart = _BarChart()
        lay.addWidget(self._chart)

        foot = QHBoxLayout()
        foot.setContentsMargins(0, 0, 0, 0)
        self._min_label = CaptionLabel("min —")
        self._min_label.setObjectName("distributionFoot")
        self._max_label = CaptionLabel("max —")
        self._max_label.setObjectName("distributionFoot")
        foot.addWidget(self._min_label)
        foot.addStretch(1)
        foot.addWidget(self._max_label)
        lay.addLayout(foot)

        self.clear()
        i18n.bus.language_changed.connect(self._retranslate)

    def _retranslate(self, _lang: str) -> None:
        self._head_label.setText(i18n.t("dist.head"))

    def clear(self) -> None:
        self._chart.set_counts([])
        self._ratio_label.setText("—")
        self._min_label.setText("")
        self._max_label.setText("")

    def set_dataset(self, ds: Dataset) -> None:
        counts = sorted((c.image_count for c in ds.categories if c.image_count > 0),
                        reverse=True)
        if not counts:
            self.clear()
            return
        self._chart.set_counts(counts)
        lo, hi = counts[-1], counts[0]
        self._min_label.setText(f"min {lo:,}")
        self._max_label.setText(f"max {hi:,}")
        ratio = hi / lo if lo else 0
        warn = ratio >= 20
        self._ratio_label.setText(f"{ratio:.0f}:1" + (" ⚠" if warn else ""))
        self._ratio_label.setProperty("warn", warn)
        self._ratio_label.style().unpolish(self._ratio_label)
        self._ratio_label.style().polish(self._ratio_label)
