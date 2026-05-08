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

from PyQt6.QtCore import QEvent, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QFontDatabase, QLinearGradient, QPainter, QPen,
)
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QWidget
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

        # Top-edge specular highlight — on-accent foreground with low
        # alpha for a soft "lit from above" cue. Tracks the theme token
        # rather than a hard-coded white.
        highlight = QColor(T.ON_ACCENT)
        highlight.setAlpha(32)
        p.setBrush(highlight)
        hr = QRectF(1, 1, rect.width() - 2, rect.height() * 0.45)
        p.drawRoundedRect(hr, 4.0, 4.0)

        # Italic serif 'D'. Walk the fallback stack via QFontDatabase —
        # ``QFont(family).exactMatch()`` returns False in most Qt builds
        # when no point size is set, which makes the old probe always
        # fall through to the last entry (review #12). Checking
        # ``families()`` membership is the reliable way.
        font = QFont()
        installed = set(QFontDatabase.families())
        for family in ("Georgia", "Songti SC", "Noto Serif SC", "Times New Roman"):
            if family in installed:
                font.setFamily(family)
                break
        else:
            font.setFamily("serif")
        font.setPointSize(11)
        font.setWeight(QFont.Weight.DemiBold)
        font.setItalic(True)
        p.setFont(font)
        p.setPen(QPen(QColor(T.ON_ACCENT)))
        # Italic slant leans the glyph right; nudge the draw rect left
        # 1px so optical centering looks balanced.
        text_rect = rect.adjusted(-1, 0, -1, 0)
        p.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, "D")


class BrandTitleBar(FluentTitleBar):
    """FluentWindow title bar themed with a brand chip + breadcrumbs.

    Clicking the brand block (chip + name) emits ``home_clicked`` —
    the shell wires it to ``switchTo(self.home)`` so the launchpad is
    a one-click return from anywhere.
    """

    home_clicked = pyqtSignal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setFixedHeight(44)

        # Strip the default icon + title label inherited from FluentTitleBar —
        # we replace the left region with our own brand + crumbs block.
        self.iconLabel.setVisible(False)
        self.titleLabel.setVisible(False)

        # Brand block — single clickable QFrame wrapping chip + name so
        # both share the click target.  Cursor + tooltip make the
        # affordance explicit; the rest of the title bar still drags
        # the window normally.
        self._brand_area = QFrame(self)
        self._brand_area.setObjectName("brandHomeArea")
        brand_lay = QHBoxLayout(self._brand_area)
        brand_lay.setContentsMargins(0, 0, 0, 0)
        brand_lay.setSpacing(8)
        self._chip = _BrandChip()
        brand_lay.addWidget(self._chip)
        self._name = BodyLabel("数据工坊")
        self._name.setObjectName("brandName")
        brand_lay.addWidget(self._name)
        self._brand_area.setCursor(Qt.CursorShape.PointingHandCursor)
        self._brand_area.installEventFilter(self)

        # Crumbs block — start with a placeholder; `set_path` fills it.
        self._crumbs = QFrame()
        self._crumbs.setObjectName("crumbsBox")
        self._crumbs_lay = QHBoxLayout(self._crumbs)
        self._crumbs_lay.setContentsMargins(0, 0, 0, 0)
        self._crumbs_lay.setSpacing(4)

        # Insert: brand area (0), 16px gap, crumbs (2).  FluentTitleBar
        # keeps the hidden iconLabel + titleLabel at the original 0/1
        # positions; we prepend our own widgets BEFORE them so visually
        # they come first.
        self.hBoxLayout.insertWidget(
            0, self._brand_area, 0, Qt.AlignmentFlag.AlignVCenter)
        self.hBoxLayout.insertSpacing(1, 16)
        self.hBoxLayout.insertWidget(
            2, self._crumbs, 1, Qt.AlignmentFlag.AlignVCenter)

        # No language_changed subscription: the brand name is a product
        # name that stays in Chinese, and breadcrumb segments are file-path
        # segments not subject to translation — there is literally nothing
        # to re-apply on language switch, so we skip the wire rather than
        # keep an empty hook.

    def eventFilter(self, obj, event):  # type: ignore[override]
        """Catch left-clicks on the brand area → emit ``home_clicked``.

        We use an event filter (rather than overriding mousePressEvent
        on the wrapper) so the window's drag-by-title-bar behaviour
        stays intact for every region *outside* the brand block.
        """
        if obj is self._brand_area and event.type() == QEvent.Type.MouseButtonRelease:
            if event.button() == Qt.MouseButton.LeftButton:
                self.home_clicked.emit()
                return True
        return super().eventFilter(obj, event)

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

