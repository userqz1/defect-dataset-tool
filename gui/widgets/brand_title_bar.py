"""Custom FluentWindow title bar — brand D chip + serif name + breadcrumbs.

Subclasses qfluentwidgets' ``FluentTitleBar`` and rewrites its left-side
region (icon + title → brand + crumbs). Window controls on the right
keep the stock Fluent behavior.

Design handoff §1 Title bar:
- Brand mark: 20×20 clay square with italic serif "D" (white fg).
- App name: serif 14px/500 "数据工坊".
- Crumbs: mono 12px, muted fg, last segment is the active dataset name.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPen
from PyQt6.QtWidgets import QFrame, QWidget
from qfluentwidgets import BodyLabel, CaptionLabel
from qfluentwidgets.window.fluent_window import FluentTitleBar

from gui import i18n
from gui.theme import T


class _BrandChip(QWidget):
    """20×20 clay square with italic serif 'D' — hand-painted.

    Drawn in paintEvent rather than a styled QLabel for three reasons:

    - Italic Georgia D rendered via QLabel often sits visually low-left
      because Qt's text-layout centerline doesn't account for the
      italic slant's optical center. Custom paint lets us measure and
      nudge the baseline/x-offset until the glyph looks centered.
    - A subtle top→bottom gradient on the clay fill gives the chip
      dimension without a full drop shadow (matches Claude-web's
      "paper-lift" feel).
    - A 1px highlight along the top edge (alpha white) hints at
      specular glint, helping the 20px chip read as a physical tile
      rather than a flat color block.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("brandChip")
        self.setFixedSize(20, 20)

    def paintEvent(self, _e) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(0, 0, self.width(), self.height())
        # Gradient fill — clay top to slightly darker clay bottom
        top = QColor(T.ACCENT)
        bot = QColor(T.ACCENT)
        bot = bot.darker(115)   # ~15% darker for subtle depth
        grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
        grad.setColorAt(0.0, top)
        grad.setColorAt(1.0, bot)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(grad))
        p.drawRoundedRect(rect, 5.0, 5.0)

        # Top-edge specular highlight — 1px white alpha on the upper
        # 40% of the chip for a soft "lit from above" cue.
        highlight = QColor(255, 255, 255, 32)
        p.setBrush(highlight)
        hr = QRectF(1, 1, rect.width() - 2, rect.height() * 0.45)
        p.drawRoundedRect(hr, 4.0, 4.0)

        # Italic serif 'D'
        font = QFont()
        # Georgia on Windows is the reliable italic-serif; fall back to
        # Songti SC on zh-CN installs that somehow lack Georgia.
        for family in ("Georgia", "Songti SC", "Noto Serif SC", "Times New Roman"):
            font.setFamily(family)
            if QFont(family).exactMatch():
                break
        font.setPointSize(11)
        font.setWeight(QFont.Weight.DemiBold)
        font.setItalic(True)
        p.setFont(font)
        p.setPen(QPen(QColor("#ffffff")))
        # Italic slant leans the glyph right; nudge the draw rect left
        # 1px so optical centering looks balanced.
        text_rect = rect.adjusted(-1, 0, -1, 0)
        p.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, "D")


class BrandTitleBar(FluentTitleBar):
    """FluentWindow title bar themed with a brand chip + breadcrumbs."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setFixedHeight(44)

        # Strip the default icon + title label inherited from FluentTitleBar —
        # we replace the left region with our own brand + crumbs block.
        self.iconLabel.setVisible(False)
        self.titleLabel.setVisible(False)

        # Brand block (chip + name)
        self._chip = _BrandChip()
        self._name = BodyLabel(i18n.t("nav.home") and "数据工坊")
        self._name.setObjectName("brandName")

        # Crumbs block — start with a placeholder; `set_path` fills it.
        self._crumbs = QFrame()
        self._crumbs.setObjectName("crumbsBox")
        from PyQt6.QtWidgets import QHBoxLayout
        self._crumbs_lay = QHBoxLayout(self._crumbs)
        self._crumbs_lay.setContentsMargins(0, 0, 0, 0)
        self._crumbs_lay.setSpacing(4)

        # Insert: brand chip (0), name (1), a 16px gap, crumbs (3)
        # FluentTitleBar keeps the hidden iconLabel at 0 and titleLabel at 1;
        # we prepend our own widgets BEFORE them so visually they come first.
        self.hBoxLayout.insertWidget(
            0, self._chip, 0, Qt.AlignmentFlag.AlignVCenter)
        self.hBoxLayout.insertSpacing(1, 8)
        self.hBoxLayout.insertWidget(
            2, self._name, 0, Qt.AlignmentFlag.AlignVCenter)
        self.hBoxLayout.insertSpacing(3, 16)
        self.hBoxLayout.insertWidget(
            4, self._crumbs, 1, Qt.AlignmentFlag.AlignVCenter)

        # Re-apply text on language change (brand stays zh+CN-styled).
        i18n.bus.language_changed.connect(self._retranslate)

    # ---------- public API ----------

    def set_path(self, path: Path | None) -> None:
        """Render breadcrumbs from a file path. None → clear crumbs."""
        # Wipe previous crumbs
        while self._crumbs_lay.count():
            item = self._crumbs_lay.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                w.deleteLater()

        if path is None:
            return
        parts = [p for p in str(path).replace("\\", "/").split("/") if p]
        # Last segment = active; rest = faded
        for i, seg in enumerate(parts):
            if i > 0:
                sep = CaptionLabel("/")
                sep.setObjectName("crumbSep")
                self._crumbs_lay.addWidget(sep)
            lbl = CaptionLabel(seg)
            lbl.setObjectName("crumbActive" if i == len(parts) - 1
                               else "crumbMuted")
            self._crumbs_lay.addWidget(lbl)
        self._crumbs_lay.addStretch(1)

    # ---------- internals ----------

    def _retranslate(self, _lang: str) -> None:
        # Brand name stays Chinese per design (it's a product name, not a UI
        # string). Nothing to re-apply here; left as a hook.
        pass
