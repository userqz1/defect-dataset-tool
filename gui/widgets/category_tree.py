"""Category list with swatch + progress bar + mono count.

Visual per the design handoff §9 "Catalog Panel → Class rows":

  [swatch 8×8]  name · en-hint     [count]
                ▬▬▬▬▬░░░░░░░░░░░░
                progress bar (pct = count / max)

- Swatch uses an earthen palette keyed on category name hash so the
  same class always gets the same color across scans.
- Tail classes (count < 50) render their count in warn color; rest use
  neutral fg-2.
- "全部" appears first (ALL_KEY) with a muted fg swatch + full-width bar.

All rendering lives in ``_CategoryDelegate.paint`` — zero widgets per row
so a 100-class dataset still scrolls at 60fps.
"""
from __future__ import annotations

import hashlib

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QFont, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import (
    QFrame,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QStyledItemDelegate,
    QStyleOptionViewItem,
)

from core.models import Dataset
from gui import i18n
from gui.theme import T

ALL_KEY = "__all__"

# Earthen palette from the design handoff (README §Class colors).
# Hash-mapped so the same name always gets the same color.
_EARTHEN = [
    "#8B6B4A", "#5A7B8C", "#B5453C", "#A3743A", "#876A8E",
    "#5E8892", "#A0513E", "#8C6B3E", "#5E8A7A", "#8A5E7A",
    "#6A6F8A", "#6B8A5E",
]

# A few well-known Chinese fault names get explicit slots for
# consistency with the design mockup.
_NAMED: dict[str, str] = {
    "松动": "#8B6B4A", "Loose": "#8B6B4A",
    "缺失": "#5A7B8C", "Lose": "#5A7B8C",
    "裂纹": "#B5453C", "Crack": "#B5453C",
    "锈蚀": "#A3743A", "Rust": "#A3743A",
    "磨损": "#876A8E", "Wear": "#876A8E",
    "变形": "#5E8892", "Bent": "#5E8892", "Deformation": "#5E8892",
    "烧蚀": "#A0513E", "Burn": "#A0513E",
    "渗油": "#8C6B3E", "Oilleak": "#8C6B3E", "Oil leak": "#8C6B3E",
    "凹陷": "#5E8A7A", "Dent": "#5E8A7A",
    "划痕": "#8A5E7A", "Scratch": "#8A5E7A",
    "噪声": "#6A6F8A", "Noise": "#6A6F8A",
    "正常": "#6B8A5E", "Normal": "#6B8A5E",
}

_TAIL_THRESHOLD = 50


def _color_for(name: str) -> str:
    if name in _NAMED:
        return _NAMED[name]
    h = int(hashlib.md5(name.encode()).hexdigest()[:6], 16)
    return _EARTHEN[h % len(_EARTHEN)]


class _CategoryDelegate(QStyledItemDelegate):
    """Paints: swatch · name · progress bar · count. ALL row is special."""

    ROW_H = 46
    PAD_L = 12
    PAD_R = 12
    SWATCH = 8
    BAR_H = 3

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:  # type: ignore[override]
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = option.rect.adjusted(6, 2, -6, -2)
        is_selected = bool(option.state & option.state.__class__.State_Selected)

        if is_selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(T.HOVER_STRONG))
            painter.drawRoundedRect(rect, 8, 8)

        # Data
        name = index.data(Qt.ItemDataRole.DisplayRole) or ""
        count_text = index.data(Qt.ItemDataRole.UserRole + 1) or ""
        count_val = int(index.data(Qt.ItemDataRole.UserRole + 2) or 0)
        max_val = int(index.data(Qt.ItemDataRole.UserRole + 3) or 1) or 1
        key = index.data(Qt.ItemDataRole.UserRole) or ""

        # --- Swatch ---
        swatch_x = rect.x() + self.PAD_L
        swatch_y = rect.y() + 10
        swatch_color = QColor(T.TEXT) if key == ALL_KEY else QColor(_color_for(name))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(swatch_color)
        painter.drawRoundedRect(swatch_x, swatch_y, self.SWATCH, self.SWATCH, 2, 2)

        # --- Info column (name + bar) ---
        info_x = swatch_x + self.SWATCH + 10
        count_font = QFont(painter.font())
        count_font.setFamily("JetBrains Mono, Consolas, Menlo")
        fm_count = QFontMetrics(count_font)
        count_w = fm_count.horizontalAdvance(count_text) + 8

        info_w = rect.right() - info_x - count_w - self.PAD_R

        # Name
        name_font = QFont(painter.font())
        name_font.setPointSize(max(9, name_font.pointSize()))
        name_font.setWeight(QFont.Weight.Medium if is_selected else QFont.Weight.Normal)
        painter.setFont(name_font)
        painter.setPen(QColor(T.TEXT))
        fm_name = QFontMetrics(name_font)
        elided = fm_name.elidedText(name, Qt.TextElideMode.ElideMiddle, info_w)
        painter.drawText(
            info_x, rect.y() + 6, info_w, 18,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            elided,
        )

        # Progress bar
        bar_y = rect.y() + 28
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(T.SURFACE_DIM))
        painter.drawRoundedRect(info_x, bar_y, info_w, self.BAR_H, 2, 2)
        pct = count_val / max_val if max_val else 0
        fill_w = int(info_w * pct)
        if fill_w > 0:
            fill_color = QColor(T.TEXT_3) if key == ALL_KEY else QColor(_color_for(name))
            painter.setBrush(fill_color)
            painter.drawRoundedRect(info_x, bar_y, fill_w, self.BAR_H, 2, 2)

        # --- Count (right-aligned, mono) ---
        painter.setFont(count_font)
        is_tail = count_val > 0 and count_val < _TAIL_THRESHOLD and key != ALL_KEY
        painter.setPen(QColor(T.WARNING) if is_tail else QColor(T.TEXT_2))
        painter.drawText(
            rect.right() - count_w - self.PAD_R, rect.y(),
            count_w, rect.height(),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            count_text,
        )

        painter.restore()

    def sizeHint(self, option, index) -> QSize:  # type: ignore[override]
        return QSize(0, self.ROW_H)


class CategoryTree(QListWidget):
    """Rich class list — swatch + name + progress bar + mono count."""

    category_selected = pyqtSignal(str)  # "" = all
    rename_requested = pyqtSignal(str)
    merge_requested = pyqtSignal(str)
    split_requested = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("categoryTree")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setItemDelegate(_CategoryDelegate(self))
        self.itemClicked.connect(self._on_item_clicked)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)

    def load_dataset(self, dataset: Dataset) -> None:
        self.clear()
        counts = [c.image_count for c in dataset.categories]
        max_val = max(counts) if counts else 1

        all_item = QListWidgetItem(i18n.t("catalog.all"))
        all_item.setData(Qt.ItemDataRole.UserRole, ALL_KEY)
        all_item.setData(Qt.ItemDataRole.UserRole + 1, f"{dataset.total_images:,}")
        all_item.setData(Qt.ItemDataRole.UserRole + 2, dataset.total_images)
        all_item.setData(Qt.ItemDataRole.UserRole + 3, dataset.total_images or 1)
        self.addItem(all_item)

        for cat in dataset.categories:
            item = QListWidgetItem(cat.name)
            item.setData(Qt.ItemDataRole.UserRole, cat.name)
            item.setData(Qt.ItemDataRole.UserRole + 1, f"{cat.image_count:,}")
            item.setData(Qt.ItemDataRole.UserRole + 2, cat.image_count)
            item.setData(Qt.ItemDataRole.UserRole + 3, max_val)
            self.addItem(item)
        self.setCurrentRow(0)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        key = item.data(Qt.ItemDataRole.UserRole)
        self.category_selected.emit("" if key == ALL_KEY else key)

    def _on_context_menu(self, pos) -> None:
        item = self.itemAt(pos)
        if not item:
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        if key == ALL_KEY:
            return

        menu = QMenu(self)
        rename_act = QAction("重命名类别…", self)
        rename_act.triggered.connect(lambda: self.rename_requested.emit(key))
        menu.addAction(rename_act)

        merge_act = QAction("合并类别…", self)
        merge_act.triggered.connect(lambda: self.merge_requested.emit(key))
        menu.addAction(merge_act)

        split_act = QAction("拆分类别…", self)
        split_act.triggered.connect(lambda: self.split_requested.emit(key))
        menu.addAction(split_act)

        menu.exec(self.mapToGlobal(pos))

    def get_category_names(self) -> list[str]:
        """Return all category names (excluding '全部')."""
        names = []
        for i in range(self.count()):
            key = self.item(i).data(Qt.ItemDataRole.UserRole)
            if key != ALL_KEY:
                names.append(key)
        return names
