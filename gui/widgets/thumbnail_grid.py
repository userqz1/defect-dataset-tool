"""Lazy-loading thumbnail grid with pixel dimensions, status badge, multi-select.

All visual styling lives in gui/styles/app.qss; this file only sets object
names and dynamic properties so the QSS can target them.
"""
from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import BodyLabel, CaptionLabel

from core.models import ImageInfo
from gui.theme import T


def _refresh(widget: QWidget) -> None:
    """Force QSS to re-evaluate after a dynamic property change."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class ThumbnailCard(QFrame):
    """Single thumbnail card. Selection state set via dynamic property `selected`."""

    def __init__(self, img: ImageInfo) -> None:
        super().__init__()
        self.img_info = img
        self.setObjectName("thumbCard")
        self.setProperty("selected", "false")
        self.setFixedSize(T.CARD_WIDTH, T.CARD_HEIGHT)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 图片区
        self.image_label = CaptionLabel("加载中…")
        self.image_label.setObjectName("thumbImage")
        self.image_label.setFixedSize(T.CARD_WIDTH, T.THUMB_SIZE)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.image_label)

        # 状态徽章（绝对定位在右上角）
        self.badge = CaptionLabel(self)
        self.badge.setObjectName("thumbBadge")
        self.badge.setFixedHeight(20)
        self._update_badge()

        # 文件名 + 尺寸
        meta = QWidget()
        meta.setObjectName("thumbMeta")
        meta_layout = QVBoxLayout(meta)
        meta_layout.setContentsMargins(T.PAD, T.GAP, T.PAD, T.GAP)
        meta_layout.setSpacing(3)

        self.name_label = BodyLabel(img.path.name)
        self.name_label.setFixedWidth(T.CARD_WIDTH - 2 * T.PAD)
        self.size_label = CaptionLabel("")

        meta_layout.addWidget(self.name_label)
        meta_layout.addWidget(self.size_label)
        layout.addWidget(meta)

    def resizeEvent(self, e):  # type: ignore[override]
        super().resizeEvent(e)
        self.badge.adjustSize()
        self.badge.move(self.width() - self.badge.width() - T.GAP, T.GAP)

    def _update_badge(self) -> None:
        if self.img_info.has_label:
            self.badge.setText("● 有标注")
            self.badge.setProperty("state", "labeled")
        else:
            self.badge.setText("● 无标注")
            self.badge.setProperty("state", "unlabeled")
        _refresh(self.badge)
        self.badge.adjustSize()

    def set_selected(self, selected: bool) -> None:
        flag = "true" if selected else "false"
        if self.property("selected") == flag:
            return
        self.setProperty("selected", flag)
        _refresh(self)

    def set_pixmap(self, pixmap: QPixmap) -> None:
        self.image_label.setText("")
        scaled = pixmap.scaled(
            T.CARD_WIDTH, T.THUMB_SIZE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_label.setPixmap(scaled)

    def set_dimensions(self, w: int, h: int) -> None:
        if w and h:
            self.size_label.setText(f"{w} × {h} px")


class ThumbnailGrid(QListWidget):
    """Lazy-loading grid of ThumbnailCard widgets backed by QListWidget selection."""

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
        self.itemDoubleClicked.connect(self._on_double_click)
        self.itemSelectionChanged.connect(self._on_selection_changed)

        self._cards: dict[str, ThumbnailCard] = {}

    def set_images(self, images: list[ImageInfo]) -> None:
        self.clear()
        self._cards.clear()
        for img in images:
            item = QListWidgetItem()
            item.setSizeHint(QSize(T.CARD_WIDTH, T.CARD_HEIGHT))
            item.setData(Qt.ItemDataRole.UserRole, img)
            self.addItem(item)
            card = ThumbnailCard(img)
            self._cards[str(img.path)] = card
            self.setItemWidget(item, card)
            self.request_thumb.emit(img.path)

    def on_thumb_ready(self, path: str, jpeg_bytes: bytes, w: int, h: int) -> None:
        card = self._cards.get(path)
        if card is None:
            return
        pix = QPixmap()
        pix.loadFromData(jpeg_bytes, "JPEG")
        card.set_pixmap(pix)
        card.set_dimensions(w, h)

    def selected_images(self) -> list[ImageInfo]:
        return [
            item.data(Qt.ItemDataRole.UserRole)
            for item in self.selectedItems()
        ]

    def _on_double_click(self, item: QListWidgetItem) -> None:
        img: ImageInfo = item.data(Qt.ItemDataRole.UserRole)
        self.item_activated.emit(img)

    def _on_selection_changed(self) -> None:
        selected_set = {id(it) for it in self.selectedItems()}
        for i in range(self.count()):
            it = self.item(i)
            card = self.itemWidget(it)
            if isinstance(card, ThumbnailCard):
                card.set_selected(id(it) in selected_set)
        self.selection_changed.emit(self.selected_images())
