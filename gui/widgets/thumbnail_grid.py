"""Lazy-loading thumbnail grid with pixel dimensions, status badge, multi-select."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from core.models import ImageInfo

THUMB_SIZE = 170
CARD_W = 182
CARD_H = 232

BG = "#ffffff"
BORDER = "#e8e5dc"
TEXT = "#2d2a26"
TEXT_2 = "#6b6760"
TEXT_3 = "#9a958a"
ACCENT = "#c96442"
SUCCESS = "#5a7a3c"
WARNING = "#b8842b"


class ThumbnailCard(QFrame):
    """Single thumbnail card: image + filename + px size + status badge."""

    def __init__(self, img: ImageInfo) -> None:
        super().__init__()
        self.img_info = img
        self.setObjectName("thumbCard")
        self.setFixedSize(CARD_W, CARD_H)
        self._selected = False
        self._apply_style()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 图片区
        self.image_label = QLabel()
        self.image_label.setFixedSize(CARD_W, THUMB_SIZE)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet(
            f"background-color: #f3f1ea; color: {TEXT_3}; font-size: 11px;"
        )
        self.image_label.setText("加载中…")
        layout.addWidget(self.image_label)

        # 状态徽章（悬浮在右上角，通过 parent+位置）
        self.badge = QLabel(self)
        self.badge.setFixedHeight(20)
        self.badge.setStyleSheet(
            f"background-color: {BG}; border: 1px solid {BORDER}; border-radius: 10px;"
            f"padding: 0 8px; font-size: 10px; color: {TEXT_2}; font-weight: 500;"
        )
        self._update_badge()

        # 文件名 + 尺寸
        meta = QWidget()
        meta.setStyleSheet(f"background-color: {BG}; border-top: 1px solid {BORDER};")
        meta_layout = QVBoxLayout(meta)
        meta_layout.setContentsMargins(10, 8, 10, 8)
        meta_layout.setSpacing(3)

        self.name_label = QLabel(img.path.name)
        self.name_label.setStyleSheet(
            f"color: {TEXT}; font-size: 11px; font-family: 'Cascadia Mono', Consolas, monospace;"
        )
        self.name_label.setFixedWidth(CARD_W - 20)

        self.size_label = QLabel("—")
        self.size_label.setStyleSheet(f"color: {TEXT_3}; font-size: 10px;")

        meta_layout.addWidget(self.name_label)
        meta_layout.addWidget(self.size_label)
        layout.addWidget(meta)

    def resizeEvent(self, e):  # type: ignore[override]
        super().resizeEvent(e)
        self.badge.adjustSize()
        self.badge.move(self.width() - self.badge.width() - 8, 8)

    def _apply_style(self) -> None:
        border_color = ACCENT if self._selected else BORDER
        border_width = 2 if self._selected else 1
        self.setStyleSheet(
            f"""
            QFrame#thumbCard {{
                background-color: {BG};
                border: {border_width}px solid {border_color};
                border-radius: 6px;
            }}
            """
        )

    def _update_badge(self) -> None:
        if self.img_info.has_label:
            self.badge.setText("● 有标注")
            self.badge.setStyleSheet(
                f"background-color: {BG}; border: 1px solid {BORDER}; border-radius: 10px;"
                f"padding: 0 8px; font-size: 10px; color: {SUCCESS}; font-weight: 500;"
            )
        else:
            self.badge.setText("● 无标注")
            self.badge.setStyleSheet(
                f"background-color: {BG}; border: 1px solid {BORDER}; border-radius: 10px;"
                f"padding: 0 8px; font-size: 10px; color: {WARNING}; font-weight: 500;"
            )
        self.badge.adjustSize()

    def set_selected(self, selected: bool) -> None:
        if self._selected == selected:
            return
        self._selected = selected
        self._apply_style()

    def set_pixmap(self, pixmap: QPixmap) -> None:
        self.image_label.setText("")
        scaled = pixmap.scaled(
            CARD_W, THUMB_SIZE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_label.setPixmap(scaled)

    def set_dimensions(self, w: int, h: int) -> None:
        if w and h:
            self.size_label.setText(f"{w} × {h} px")


class ThumbnailGrid(QListWidget):
    """Lazy-loading grid of ThumbnailCard widgets using QListWidget for built-in selection."""

    item_activated = pyqtSignal(object)    # ImageInfo (double-click)
    selection_changed = pyqtSignal(list)   # list[ImageInfo]
    request_thumb = pyqtSignal(object)     # Path — main window forwards to worker

    def __init__(self) -> None:
        super().__init__()
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Static)
        self.setSpacing(8)
        self.setUniformItemSizes(True)
        self.setGridSize(QSize(CARD_W + 8, CARD_H + 8))
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet(
            f"""
            QListWidget {{
                background-color: {BG};
                border: none;
                padding: 12px;
            }}
            QListWidget::item {{
                border: none;
                background: transparent;
                padding: 0;
                margin: 0;
            }}
            QListWidget::item:selected {{ background: transparent; }}
            """
        )
        self.itemDoubleClicked.connect(self._on_double_click)
        self.itemSelectionChanged.connect(self._on_selection_changed)

        self._cards: dict[str, ThumbnailCard] = {}  # path_str -> card

    def set_images(self, images: list[ImageInfo]) -> None:
        self.clear()
        self._cards.clear()
        for img in images:
            item = QListWidgetItem()
            item.setSizeHint(QSize(CARD_W, CARD_H))
            item.setData(Qt.ItemDataRole.UserRole, img)
            self.addItem(item)
            card = ThumbnailCard(img)
            self._cards[str(img.path)] = card
            self.setItemWidget(item, card)
            # 请求后台生成缩略图
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
        # 更新每个卡片的选中态边框
        selected_set = {id(it) for it in self.selectedItems()}
        for i in range(self.count()):
            it = self.item(i)
            card = self.itemWidget(it)
            if isinstance(card, ThumbnailCard):
                card.set_selected(id(it) in selected_set)
        self.selection_changed.emit(self.selected_images())
