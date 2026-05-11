"""Three-way split slider — Train / Val / Test.

A horizontal bar with two draggable handles that divide the bar into
three segments using the app's warm clay palette (same hue, three
lightness steps).  Total is always 100%.

Usage::

    slider = SplitSlider()
    slider.ratios_changed.connect(lambda t, v, te: print(t, v, te))
    slider.set_ratios(80, 10, 10)
"""
from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPainterPath
from PyQt6.QtWidgets import QWidget

from gui.theme import T


_BAR_HEIGHT = 28
_HANDLE_W = 6
_HANDLE_H = 36
_LABEL_H = 20
_MIN_PCT = 0


def _segment_colors() -> tuple[QColor, QColor, QColor]:
    """Return (train, val, test) fill colors derived from the theme ACCENT.

    Same hue, three lightness steps so they read as a cohesive set:
    Train = full accent, Val = 55% lightened, Test = 80% lightened.
    """
    base = QColor(T.ACCENT)
    h = base.hueF()
    s = base.saturationF()
    l = base.lightnessF()
    # Train: accent itself
    train = QColor.fromHslF(h, s, l)
    # Val: midtone — push lightness towards 0.65
    val = QColor.fromHslF(h, s * 0.7, min(0.65, l + (1 - l) * 0.45))
    # Test: very light — push lightness towards 0.82
    test = QColor.fromHslF(h, s * 0.45, min(0.82, l + (1 - l) * 0.7))
    return train, val, test


def _text_on(bg: QColor) -> QColor:
    """White on dark segments, dark text on light segments."""
    # Perceived luminance (ITU-R BT.709)
    lum = 0.2126 * bg.redF() + 0.7152 * bg.greenF() + 0.0722 * bg.blueF()
    return QColor(T.BADGE_FG_LIGHT) if lum < 0.55 else QColor(T.TEXT)


class SplitSlider(QWidget):
    """Two-handle slider that splits 100% into Train / Val / Test."""

    ratios_changed = pyqtSignal(int, int, int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._train = 80
        self._val = 10
        self._test = 10
        self._dragging: int = -1   # 0 = left handle, 1 = right handle
        self.setMinimumHeight(_BAR_HEIGHT + _LABEL_H + 8)
        self.setFixedHeight(_BAR_HEIGHT + _LABEL_H + 8)
        self.setMinimumWidth(200)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setMouseTracking(True)

    # ── public API ───────────────────────────────────────────────

    def set_ratios(self, train: int, val: int, test: int) -> None:
        total = train + val + test
        if total <= 0:
            train, val, test = 80, 10, 10
        elif total != 100:
            train = round(train * 100 / total)
            val = round(val * 100 / total)
            test = 100 - train - val
        self._train = max(_MIN_PCT, min(100, train))
        self._val = max(_MIN_PCT, min(100, val))
        self._test = max(_MIN_PCT, min(100, test))
        self.update()

    def ratios(self) -> tuple[int, int, int]:
        return self._train, self._val, self._test

    # ── geometry helpers ─────────────────────────────────────────

    def _bar_rect(self) -> QRectF:
        m = 4
        return QRectF(m, _LABEL_H, self.width() - 2 * m, _BAR_HEIGHT)

    def _pct_to_x(self, pct: int) -> float:
        r = self._bar_rect()
        return r.left() + r.width() * pct / 100.0

    def _x_to_pct(self, x: float) -> int:
        r = self._bar_rect()
        pct = (x - r.left()) / r.width() * 100.0
        return max(0, min(100, round(pct)))

    def _handle_rect(self, which: int) -> QRectF:
        if which == 0:
            cx = self._pct_to_x(self._train)
        else:
            cx = self._pct_to_x(self._train + self._val)
        r = self._bar_rect()
        top = r.top() + (r.height() - _HANDLE_H) / 2
        return QRectF(cx - _HANDLE_W / 2, top, _HANDLE_W, _HANDLE_H)

    # ── painting ─────────────────────────────────────────────────

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        bar = self._bar_rect()
        radius = T.RADIUS
        c_train, c_val, c_test = _segment_colors()

        x_h0 = self._pct_to_x(self._train)
        x_h1 = self._pct_to_x(self._train + self._val)

        # Clip to rounded bar shape
        bar_path = QPainterPath()
        bar_path.addRoundedRect(bar, radius, radius)
        p.setClipPath(bar_path)

        # Three segments
        p.fillRect(QRectF(bar.left(), bar.top(),
                          x_h0 - bar.left(), bar.height()), c_train)
        p.fillRect(QRectF(x_h0, bar.top(),
                          x_h1 - x_h0, bar.height()), c_val)
        p.fillRect(QRectF(x_h1, bar.top(),
                          bar.right() - x_h1, bar.height()), c_test)
        p.setClipping(False)

        # Labels inside segments
        font = QFont()
        font.setPixelSize(11)
        font.setBold(True)
        p.setFont(font)

        for x0, x1, pct, label, bg in (
            (bar.left(), x_h0, self._train, "Train", c_train),
            (x_h0, x_h1, self._val, "Val", c_val),
            (x_h1, bar.right(), self._test, "Test", c_test),
        ):
            seg_w = x1 - x0
            p.setPen(_text_on(bg))
            rect = QRectF(x0, bar.top(), seg_w, bar.height())
            if seg_w > 55:
                p.drawText(rect, Qt.AlignmentFlag.AlignCenter,
                           f"{label} {pct}%")
            elif seg_w > 28:
                p.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"{pct}%")

        # Handles — pill shape, white fill, subtle border
        handle_border = QColor(T.BORDER)
        for i in range(2):
            hr = self._handle_rect(i)
            hp = QPainterPath()
            hp.addRoundedRect(hr, 3, 3)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(T.CONTENT))
            p.drawPath(hp)
            p.setPen(handle_border)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(hp)

        p.end()

    # ── mouse interaction ────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position()
        for i in range(2):
            hr = self._handle_rect(i).adjusted(-4, -4, 4, 4)
            if hr.contains(pos):
                self._dragging = i
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                return
        pct = self._x_to_pct(pos.x())
        h0 = self._train
        h1 = self._train + self._val
        if abs(pct - h0) < abs(pct - h1):
            self._dragging = 0
        else:
            self._dragging = 1
        self._apply_drag(pct)
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position()
        if self._dragging >= 0:
            pct = self._x_to_pct(pos.x())
            self._apply_drag(pct)
        else:
            for i in range(2):
                hr = self._handle_rect(i).adjusted(-4, -4, 4, 4)
                if hr.contains(pos):
                    self.setCursor(Qt.CursorShape.OpenHandCursor)
                    return
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._dragging >= 0:
            self._dragging = -1
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.ratios_changed.emit(self._train, self._val, self._test)

    def _apply_drag(self, pct: int) -> None:
        if self._dragging == 0:
            new_train = max(_MIN_PCT, min(100 - self._test - _MIN_PCT, pct))
            new_val = 100 - new_train - self._test
            if new_val < _MIN_PCT:
                new_val = _MIN_PCT
                new_train = 100 - new_val - self._test
            self._train = new_train
            self._val = new_val
        elif self._dragging == 1:
            new_test = max(_MIN_PCT, 100 - pct)
            new_val = pct - self._train
            if new_val < _MIN_PCT:
                new_val = _MIN_PCT
                new_test = 100 - self._train - new_val
            if new_test < _MIN_PCT:
                new_test = _MIN_PCT
                new_val = 100 - self._train - new_test
            self._val = new_val
            self._test = new_test
        self.update()
        self.ratios_changed.emit(self._train, self._val, self._test)
