"""Category tree with count badges. All visual styling lives in app.qss."""
from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (
    QFrame,
    QListWidget,
    QListWidgetItem,
    QStyledItemDelegate,
    QStyleOptionViewItem,
)

from core.models import Dataset
from gui.theme import T

ALL_KEY = "__all__"


class _CategoryDelegate(QStyledItemDelegate):
    """Renders 'name' on the left and 'count' right-aligned in muted color.

    Background colors come from QSS via QListWidget#categoryTree::item, so we
    only paint text here.
    """

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:  # type: ignore[override]
        painter.save()
        rect = option.rect.adjusted(12, 0, -12, 0)
        is_selected = bool(option.state & option.state.__class__.State_Selected)
        name = index.data(Qt.ItemDataRole.DisplayRole) or ""
        count = index.data(Qt.ItemDataRole.UserRole + 1) or ""

        painter.setFont(option.font)
        name_color = QColor(T.ACCENT) if is_selected else QColor(T.TEXT)
        count_color = QColor(T.ACCENT) if is_selected else QColor(T.TEXT_3)

        painter.setPen(name_color)
        painter.drawText(
            rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, name
        )
        painter.setPen(count_color)
        painter.drawText(
            rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, count
        )
        painter.restore()

    def sizeHint(self, option, index) -> QSize:  # type: ignore[override]
        return QSize(0, 32)


class CategoryTree(QListWidget):
    category_selected = pyqtSignal(str)  # "" = all

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("categoryTree")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setItemDelegate(_CategoryDelegate(self))
        self.itemClicked.connect(self._on_item_clicked)

    def load_dataset(self, dataset: Dataset) -> None:
        self.clear()
        all_item = QListWidgetItem("全部")
        all_item.setData(Qt.ItemDataRole.UserRole, ALL_KEY)
        all_item.setData(Qt.ItemDataRole.UserRole + 1, f"{dataset.total_images:,}")
        self.addItem(all_item)
        for cat in sorted(dataset.categories, key=lambda c: c.image_count, reverse=True):
            item = QListWidgetItem(cat.name)
            item.setData(Qt.ItemDataRole.UserRole, cat.name)
            item.setData(Qt.ItemDataRole.UserRole + 1, f"{cat.image_count:,}")
            self.addItem(item)
        self.setCurrentRow(0)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        key = item.data(Qt.ItemDataRole.UserRole)
        self.category_selected.emit("" if key == ALL_KEY else key)
