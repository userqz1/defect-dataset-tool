"""Thumbnail grid using pure delegate painting — zero child widgets per card.

Layout per design handoff §7 "Image Grid":
- 200×(150 + meta) card, 14px radius, 4:3 thumb on top.
- Badges top-left: warn triangle (issue), DUP (duplicate), "N bbox" (labeled).
- Corner-select top-right on selected.
- Meta bottom: mono filename · mono dimensions · class mini-tag.
- Selected state: 1.5px accent ring.

All rendering happens in _ThumbDelegate.paint(). Orders of magnitude
faster than setItemWidget on large datasets (480 QWidgets → 0).
"""
from __future__ import annotations

from PyQt6.QtCore import QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QListWidget,
    QListWidgetItem,
    QStyledItemDelegate,
    QStyleOptionViewItem,
)

from core.models import ImageInfo
from gui.theme import T
from gui.widgets.category_tree import _color_for  # reuse earthen palette

# Custom data roles
ROLE_IMG = Qt.ItemDataRole.UserRole          # ImageInfo
ROLE_PIX = Qt.ItemDataRole.UserRole + 1      # QPixmap (thumbnail)
ROLE_DIM = Qt.ItemDataRole.UserRole + 2      # (w, h) tuple
ROLE_QUALITY = Qt.ItemDataRole.UserRole + 3  # list[str] of quality issue kinds
ROLE_DUP = Qt.ItemDataRole.UserRole + 4      # bool — part of a dup group


class _ThumbDelegate(QStyledItemDelegate):
    """Paint a thumbnail card entirely in paint() — no widget creation."""

    CARD_W = 200
    THUMB_H = 150   # 4:3 of 200
    META_H = 72
    CARD_H = THUMB_H + META_H
    PAD = 8
    RADIUS = 14

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = option.rect
        is_selected = bool(option.state & option.state.__class__.State_Selected)

        img: ImageInfo | None = index.data(ROLE_IMG)
        if not img:
            painter.restore()
            return

        kinds: list[str] | None = index.data(ROLE_QUALITY)
        has_issue = bool(kinds)

        # ---- Card background ----
        card = QRect(rect.x(), rect.y(), self.CARD_W, self.CARD_H)

        if is_selected:
            border_color = QColor(T.ACCENT)
            border_w = 2
        elif has_issue:
            border_color = QColor(T.WARNING)
            border_w = 1
        else:
            border_color = QColor(T.BORDER)
            border_w = 1
        painter.setPen(QPen(border_color, border_w))
        painter.setBrush(QColor(T.CONTENT))
        painter.drawRoundedRect(card, self.RADIUS, self.RADIUS)

        # Issue stripe — 3px warn color on the left edge (design §7 has-issue)
        if has_issue and not is_selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(T.WARNING))
            painter.drawRect(card.x() + 1, card.y() + 1, 3, card.height() - 2)

        # ---- Thumbnail area (4:3, top, clipped to card radius) ----
        thumb_rect = QRect(
            card.x() + border_w, card.y() + border_w,
            card.width() - 2 * border_w,
            self.THUMB_H - border_w,
        )
        painter.save()
        # Clip so placeholder / image don't paint past rounded top corners
        from PyQt6.QtGui import QPainterPath
        path = QPainterPath()
        r = self.RADIUS - border_w
        path.moveTo(thumb_rect.left(), thumb_rect.bottom())
        path.lineTo(thumb_rect.left(), thumb_rect.top() + r)
        path.quadTo(thumb_rect.left(), thumb_rect.top(),
                    thumb_rect.left() + r, thumb_rect.top())
        path.lineTo(thumb_rect.right() - r, thumb_rect.top())
        path.quadTo(thumb_rect.right(), thumb_rect.top(),
                    thumb_rect.right(), thumb_rect.top() + r)
        path.lineTo(thumb_rect.right(), thumb_rect.bottom())
        path.closeSubpath()
        painter.setClipPath(path)

        pixmap: QPixmap | None = index.data(ROLE_PIX)
        if pixmap and not pixmap.isNull():
            scaled = pixmap.scaled(
                thumb_rect.width(), thumb_rect.height(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            # Center crop
            x = thumb_rect.x() + (thumb_rect.width() - scaled.width()) // 2
            y = thumb_rect.y() + (thumb_rect.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
        else:
            painter.fillRect(thumb_rect, QColor(T.SURFACE_DIM))
            placeholder_font = QFont(painter.font())
            placeholder_font.setFamily("JetBrains Mono, Consolas, Menlo")
            placeholder_font.setPointSize(8)
            painter.setFont(placeholder_font)
            painter.setPen(QColor(T.TEXT_3))
            painter.drawText(thumb_rect, Qt.AlignmentFlag.AlignCenter,
                             img.path.name)
        painter.restore()

        # ---- Badges top-left (stacked horizontally) ----
        badge_font = QFont(painter.font())
        badge_font.setFamily("JetBrains Mono, Consolas, Menlo")
        badge_font.setPointSize(7)
        fm_b = QFontMetrics(badge_font)
        bx = thumb_rect.x() + self.PAD
        by = thumb_rect.y() + self.PAD
        bh = 18

        def draw_badge(text: str, bg: QColor, fg: QColor) -> None:
            nonlocal bx
            w = fm_b.horizontalAdvance(text) + 12
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(bg)
            painter.drawRoundedRect(bx, by, w, bh, 4, 4)
            painter.setPen(fg)
            painter.setFont(badge_font)
            painter.drawText(bx, by, w, bh, Qt.AlignmentFlag.AlignCenter, text)
            bx += w + 3

        # Warn (issue) badge
        if has_issue:
            draw_badge("!", QColor(T.WARNING), QColor("#18181B"))
        # Duplicate badge (ghost style — subtle dark with white text)
        if index.data(ROLE_DUP):
            ghost = QColor(0, 0, 0)
            ghost.setAlphaF(0.55)
            draw_badge("DUP", ghost, QColor("#FFFFFF"))
        # Labeled badge ("N bbox" / "已标" minimal)
        if img.has_label:
            ghost = QColor(0, 0, 0)
            ghost.setAlphaF(0.55)
            draw_badge("已标", ghost, QColor("#FFFFFF"))

        # ---- Corner-select box top-right (only when selected) ----
        if is_selected:
            sel_size = 20
            sx = thumb_rect.right() - sel_size - self.PAD
            sy = thumb_rect.y() + self.PAD
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(T.ACCENT))
            painter.drawRoundedRect(sx, sy, sel_size, sel_size, 6, 6)
            # ✓ mark
            painter.setPen(QPen(QColor("#FFFFFF"), 2))
            painter.drawLine(sx + 5, sy + 10, sx + 9, sy + 14)
            painter.drawLine(sx + 9, sy + 14, sx + 15, sy + 7)

        # ---- Meta area ----
        meta_top = card.y() + self.THUMB_H
        text_x = card.x() + self.PAD + 2
        text_w = card.width() - 2 * self.PAD - 4

        # Filename (mono)
        fn_font = QFont(painter.font())
        fn_font.setFamily("JetBrains Mono, Consolas, Menlo")
        fn_font.setPointSize(8)
        painter.setFont(fn_font)
        painter.setPen(QColor(T.TEXT))
        fm_fn = QFontMetrics(fn_font)
        elided = fm_fn.elidedText(img.path.name, Qt.TextElideMode.ElideMiddle, text_w)
        painter.drawText(text_x, meta_top + 6, text_w, 18,
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         elided)

        # Dimensions (mono, muted)
        dim = index.data(ROLE_DIM)
        dim_font = QFont(painter.font())
        dim_font.setFamily("JetBrains Mono, Consolas, Menlo")
        dim_font.setPointSize(7)
        painter.setFont(dim_font)
        painter.setPen(QColor(T.TEXT_3))
        if dim and dim[0] > 0 and dim[1] > 0:
            painter.drawText(text_x, meta_top + 26, text_w, 16,
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             f"{dim[0]} × {dim[1]} px")

        # Class mini-tag (bottom of meta)
        if img.category:
            tag_color = QColor(_color_for(img.category))
            tag_font = QFont(painter.font())
            tag_font.setPointSize(7)
            tag_font.setWeight(QFont.Weight.Medium)
            painter.setFont(tag_font)
            fm_tag = QFontMetrics(tag_font)
            tag_w = fm_tag.horizontalAdvance(img.category) + 8
            tag_h = 14
            tx = text_x
            ty = meta_top + 46
            soft = QColor(tag_color)
            soft.setAlphaF(0.12)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(soft)
            painter.drawRoundedRect(tx, ty, tag_w, tag_h, 3, 3)
            painter.setPen(tag_color)
            painter.drawText(tx, ty, tag_w, tag_h,
                             Qt.AlignmentFlag.AlignCenter, img.category)

        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        return QSize(self.CARD_W, self.CARD_H)


class ThumbnailGrid(QListWidget):
    """High-performance thumbnail grid using delegate-based painting."""

    item_activated = pyqtSignal(object)    # ImageInfo (double-click)
    selection_changed = pyqtSignal(list)   # list[ImageInfo]
    request_thumb = pyqtSignal(object)     # Path — main window forwards to worker

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("thumbnailGrid")
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Static)
        self.setSpacing(16)
        self.setUniformItemSizes(True)
        self.setGridSize(QSize(_ThumbDelegate.CARD_W + 16,
                                _ThumbDelegate.CARD_H + 16))
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setItemDelegate(_ThumbDelegate(self))
        self.itemDoubleClicked.connect(self._on_double_click)
        self.itemSelectionChanged.connect(self._on_selection_changed)

        # path → item row index for fast thumb_ready lookup
        self._path_to_row: dict[str, int] = {}

        # Debounce selection_changed (review #9) — Ctrl+A over 40 items
        # otherwise fires 40 signals, each triggering a full selected_images()
        # scan on the receiver side. Coalesce to a single emit on the next
        # event loop tick via QTimer.singleShot(0, ...).
        self._sel_pending = False

    def set_images(
        self,
        images: list[ImageInfo],
        quality_map: dict[str, list[str]] | None = None,
    ) -> None:
        """Render given images. quality_map (path str → list of issue kinds)
        is consulted to paint a warn badge + stripe on problematic thumbnails."""
        self.clear()
        self._path_to_row.clear()
        qm = quality_map or {}
        for i, img in enumerate(images):
            item = QListWidgetItem()
            item.setSizeHint(QSize(_ThumbDelegate.CARD_W, _ThumbDelegate.CARD_H))
            item.setData(ROLE_IMG, img)
            kinds = qm.get(str(img.path))
            if kinds:
                item.setData(ROLE_QUALITY, kinds)
            self.addItem(item)
            self._path_to_row[str(img.path)] = i
            self.request_thumb.emit(img.path)

    def on_thumb_ready(self, path: str, jpeg_bytes: bytes, w: int, h: int) -> None:
        row = self._path_to_row.get(path)
        if row is None:
            return
        item = self.item(row)
        if item is None:
            return
        pix = QPixmap()
        pix.loadFromData(jpeg_bytes, "JPEG")
        item.setData(ROLE_PIX, pix)
        item.setData(ROLE_DIM, (w, h))

    def selected_images(self) -> list[ImageInfo]:
        return [
            item.data(ROLE_IMG)
            for item in self.selectedItems()
            if item.data(ROLE_IMG) is not None
        ]

    def _on_double_click(self, item: QListWidgetItem) -> None:
        img = item.data(ROLE_IMG)
        if img:
            self.item_activated.emit(img)

    def _on_selection_changed(self) -> None:
        # Coalesce bursts (Ctrl+A, shift-click range) into a single emit
        # on the next event loop tick.
        if self._sel_pending:
            return
        self._sel_pending = True
        QTimer.singleShot(0, self._flush_selection)

    def _flush_selection(self) -> None:
        self._sel_pending = False
        self.selection_changed.emit(self.selected_images())
