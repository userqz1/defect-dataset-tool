"""Category tree with count badges."""
from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QFont, QFontMetrics, QPainter, QPalette
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

from core.models import Dataset

SIDEBAR = "#f5f4ef"
BORDER = "#e8e5dc"
TEXT = "#2d2a26"
TEXT_2 = "#6b6760"
TEXT_3 = "#9a958a"
ACCENT = "#c96442"
ACCENT_SOFT = "#f4e8e2"

ALL_KEY = "__all__"


class _CategoryDelegate(QStyledItemDelegate):
    """Renders 'Name' on the left and 'count' right-aligned in muted color."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:  # type: ignore[override]
        painter.save()
        rect = option.rect.adjusted(12, 0, -12, 0)
        is_selected = bool(option.state & option.state.__class__.State_Selected)
        # 背景由 QSS 处理，这里只画文字
        name = index.data(Qt.ItemDataRole.DisplayRole) or ""
        count = index.data(Qt.ItemDataRole.UserRole + 1) or ""

        font = option.font
        painter.setFont(font)
        if is_selected:
            painter.setPen(QPalette().color(QPalette.ColorRole.HighlightedText))
            painter.setPen(Qt.GlobalColor.transparent)  # placeholder
        # 名称
        from PyQt6.QtGui import QColor
        name_color = QColor(ACCENT) if is_selected else QColor(TEXT)
        count_color = QColor(ACCENT) if is_selected else QColor(TEXT_3)
        painter.setPen(name_color)
        painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, name)
        painter.setPen(count_color)
        painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, count)
        painter.restore()

    def sizeHint(self, option, index) -> QSize:  # type: ignore[override]
        return QSize(0, 32)


class CategoryTree(QListWidget):
    category_selected = pyqtSignal(str)  # "" = all

    def __init__(self) -> None:
        super().__init__()
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet(
            f"""
            QListWidget {{
                background-color: {SIDEBAR};
                border: none;
                border-right: 1px solid {BORDER};
                padding: 6px;
                outline: 0;
                font-size: 13px;
            }}
            QListWidget::item {{
                padding: 8px 10px;
                border-radius: 6px;
                color: {TEXT};
                margin-bottom: 1px;
            }}
            QListWidget::item:hover {{
                background-color: #ede9de;
            }}
            QListWidget::item:selected {{
                background-color: {ACCENT_SOFT};
                color: {ACCENT};
            }}
            """
        )
        self.setItemDelegate(_CategoryDelegate(self))
        self.itemClicked.connect(self._on_item_clicked)

    def load_dataset(self, dataset: Dataset) -> None:
        self.clear()
        # 全部
        all_item = QListWidgetItem("全部")
        all_item.setData(Qt.ItemDataRole.UserRole, ALL_KEY)
        all_item.setData(Qt.ItemDataRole.UserRole + 1, f"{dataset.total_images:,}")
        self.addItem(all_item)
        # 每类
        for cat in sorted(dataset.categories, key=lambda c: c.image_count, reverse=True):
            item = QListWidgetItem(cat.name)
            item.setData(Qt.ItemDataRole.UserRole, cat.name)
            item.setData(Qt.ItemDataRole.UserRole + 1, f"{cat.image_count:,}")
            self.addItem(item)
        self.setCurrentRow(0)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        key = item.data(Qt.ItemDataRole.UserRole)
        self.category_selected.emit("" if key == ALL_KEY else key)
