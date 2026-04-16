"""Thumbnail grid using pure delegate painting — zero child widgets per card.

All rendering happens in _ThumbDelegate.paint(). This is orders of magnitude
faster than the previous setItemWidget approach (480 QWidgets → 0).
"""
from __future__ import annotations

from PyQt6.QtCore import QRect, QSize, Qt, pyqtSignal
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

# Custom data roles
ROLE_IMG = Qt.ItemDataRole.UserRole          # ImageInfo
ROLE_PIX = Qt.ItemDataRole.UserRole + 1      # QPixmap (thumbnail)
ROLE_DIM = Qt.ItemDataRole.UserRole + 2      # (w, h) tuple
ROLE_QUALITY = Qt.ItemDataRole.UserRole + 3  # list[str] of quality issue kinds

# Map quality kinds → 1-char Chinese badge code
_QUALITY_CHAR = {
    "blur": "模",
    "blank": "空",
    "over": "曝",
    "under": "暗",
    "corrupt": "损",
}


class _ThumbDelegate(QStyledItemDelegate):
    """Paint a thumbnail card entirely in paint() — no widget creation."""

    CARD_W = T.CARD_WIDTH
    CARD_H = T.CARD_HEIGHT
    THUMB_H = T.THUMB_SIZE
    META_H = CARD_H - THUMB_H
    PAD = T.PAD
    GAP = T.GAP
    RADIUS = T.RADIUS_LG

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = option.rect
        is_selected = bool(option.state & option.state.__class__.State_Selected)

        img: ImageInfo | None = index.data(ROLE_IMG)
        if not img:
            painter.restore()
            return

        # ---- Card background ----
        border = 2 if is_selected else 1
        card = QRect(rect.x(), rect.y(), self.CARD_W, self.CARD_H)
        painter.setPen(QPen(QColor(T.ACCENT if is_selected else T.BORDER), border))
        painter.setBrush(QColor(T.CONTENT))
        painter.drawRoundedRect(card, self.RADIUS, self.RADIUS)

        # Inner content area (inset from border + round corners)
        inset = border + 3
        inner = card.adjusted(inset, inset, -inset, -inset)

        # ---- Thumbnail area ----
        thumb_rect = QRect(inner.x(), inner.y(),
                           inner.width(), self.THUMB_H - 2 * inset)
        pixmap: QPixmap | None = index.data(ROLE_PIX)
        if pixmap and not pixmap.isNull():
            # Center the thumbnail
            scaled = pixmap.scaled(
                thumb_rect.width(), thumb_rect.height(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = thumb_rect.x() + (thumb_rect.width() - scaled.width()) // 2
            y = thumb_rect.y() + (thumb_rect.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
        else:
            # Placeholder
            painter.fillRect(thumb_rect, QColor(T.SURFACE_DIM))
            painter.setPen(QColor(T.TEXT_3))
            painter.drawText(thumb_rect, Qt.AlignmentFlag.AlignCenter, "加载中…")

        # ---- Badge (top-right) — silent when OK, only show warnings ----
        # Labeled is the expected "good" state; showing "● 有标注" on every
        # thumbnail in a fully-annotated dataset is pure noise. Only flag
        # the actionable state ("无标注") here.
        badge_font = QFont(painter.font())
        badge_font.setPointSize(badge_font.pointSize() - 1)
        bh = 20
        if not img.has_label:
            painter.setFont(badge_font)
            badge_text = "● 无标注"
            badge_color = QColor(T.WARNING)
            fm = QFontMetrics(badge_font)
            bw = fm.horizontalAdvance(badge_text) + 16
            badge_rect = QRect(inner.right() - bw, inner.y(), bw, bh)
            painter.setPen(QPen(QColor(T.BORDER), 1))
            painter.setBrush(QColor(T.CONTENT))
            painter.drawRoundedRect(badge_rect, 10, 10)
            painter.setPen(badge_color)
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, badge_text)

        # ---- Quality badge (top-left) ----
        kinds: list[str] | None = index.data(ROLE_QUALITY)
        if kinds:
            chars = "".join(_QUALITY_CHAR.get(k, "?") for k in kinds)
            qfm = QFontMetrics(badge_font)
            qw = qfm.horizontalAdvance(chars) + 14
            q_rect = QRect(inner.x(), inner.y(), qw, bh)
            painter.setPen(QPen(QColor(T.ERROR), 1))
            painter.setBrush(QColor(T.ERROR))
            painter.drawRoundedRect(q_rect, 10, 10)
            painter.setPen(QColor(T.CONTENT))
            painter.drawText(q_rect, Qt.AlignmentFlag.AlignCenter, chars)

        # ---- Meta area (bottom: separator + name + dimensions) ----
        meta_top = card.y() + self.THUMB_H
        # Separator line
        painter.setPen(QPen(QColor(T.BORDER), 1))
        painter.drawLine(inner.x(), meta_top, inner.right(), meta_top)

        text_x = inner.x() + self.PAD
        text_w = inner.width() - 2 * self.PAD

        # Filename
        name_font = QFont(painter.font())
        painter.setFont(name_font)
        painter.setPen(QColor(T.TEXT))
        name = img.path.name
        fm_name = QFontMetrics(name_font)
        elided = fm_name.elidedText(name, Qt.TextElideMode.ElideMiddle, text_w)
        painter.drawText(text_x, meta_top + 8, text_w, 20,
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         elided)

        # Dimensions
        dim = index.data(ROLE_DIM)
        if dim and dim[0] > 0 and dim[1] > 0:
            dim_font = QFont(painter.font())
            dim_font.setPointSize(dim_font.pointSize() - 1)
            painter.setFont(dim_font)
            painter.setPen(QColor(T.TEXT_3))
            painter.drawText(text_x, meta_top + 28, text_w, 18,
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             f"{dim[0]} × {dim[1]} px")

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
        self.setSpacing(T.GAP)
        self.setUniformItemSizes(True)
        self.setGridSize(QSize(T.CARD_WIDTH + T.GAP, T.CARD_HEIGHT + T.GAP))
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setItemDelegate(_ThumbDelegate(self))
        self.itemDoubleClicked.connect(self._on_double_click)
        self.itemSelectionChanged.connect(self._on_selection_changed)

        # path → item row index for fast thumb_ready lookup
        self._path_to_row: dict[str, int] = {}

    def set_images(
        self,
        images: list[ImageInfo],
        quality_map: dict[str, list[str]] | None = None,
    ) -> None:
        """Render given images. quality_map (path str → list of issue kinds)
        is consulted to paint a red badge on problematic thumbnails."""
        self.clear()
        self._path_to_row.clear()
        qm = quality_map or {}
        for i, img in enumerate(images):
            item = QListWidgetItem()
            item.setSizeHint(QSize(T.CARD_WIDTH, T.CARD_HEIGHT))
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
        # No need to call update() — setData triggers repaint automatically

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
        self.selection_changed.emit(self.selected_images())
