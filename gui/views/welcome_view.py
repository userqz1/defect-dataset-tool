"""Welcome page — project list shown on startup (IDE-style)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QSizePolicy,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    LargeTitleLabel,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
)

from core.project import ProjectSummary, list_known_projects
from core.recent import load_recent
from gui.theme import T


class _ProjectCardDelegate(QStyledItemDelegate):
    """Paints a project card: name (bold), path, and updated time."""

    CARD_HEIGHT = 80

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = option.rect.adjusted(4, 4, -4, -4)
        is_hovered = bool(option.state & option.state.__class__.State_MouseOver)
        is_selected = bool(option.state & option.state.__class__.State_Selected)

        # Background
        if is_selected:
            painter.setBrush(QColor(T.ACCENT_SOFT))
            painter.setPen(QColor(T.ACCENT))
        elif is_hovered:
            painter.setBrush(QColor(T.HOVER))
            painter.setPen(QColor(T.BORDER))
        else:
            painter.setBrush(QColor(T.CONTENT))
            painter.setPen(QColor(T.BORDER))
        painter.drawRoundedRect(rect, T.RADIUS_LG, T.RADIUS_LG)

        inner = rect.adjusted(T.PAD_XL + 4, T.PAD_LG + 2, -T.PAD_XL - 4, -T.PAD_LG - 2)
        summary: ProjectSummary | None = index.data(Qt.ItemDataRole.UserRole)
        if not summary:
            painter.restore()
            return

        # Name
        name_color = QColor(T.ACCENT) if is_selected else QColor(T.TEXT)
        painter.setPen(name_color)
        font = painter.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 1)
        painter.setFont(font)
        painter.drawText(inner, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft, summary.name)

        # Path
        font.setBold(False)
        font.setPointSize(font.pointSize() - 1)
        painter.setFont(font)
        painter.setPen(QColor(T.TEXT_3))
        path_str = str(summary.root_path)
        if len(path_str) > 70:
            path_str = path_str[:30] + "…" + path_str[-36:]
        path_rect = inner.adjusted(0, 28, 0, 0)
        painter.drawText(path_rect, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft, path_str)

        # Updated time (right side)
        if summary.updated_at:
            ts = summary.updated_at[:10]  # just the date
            painter.drawText(inner, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight, ts)

        # Exists indicator
        if not summary.exists:
            painter.setPen(QColor(T.WARNING))
            warn_rect = inner.adjusted(0, 28, 0, 0)
            painter.drawText(warn_rect, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight, "目录不存在")

        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        return QSize(0, self.CARD_HEIGHT)


class WelcomeView(QWidget):
    """Startup welcome page with project list."""

    open_project = pyqtSignal(Path)     # user selected a project to open
    open_folder = pyqtSignal()          # user wants to pick a new folder

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("welcomeView")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        root = QVBoxLayout(self)
        root.setContentsMargins(60, 48, 60, 32)
        root.setSpacing(T.GAP_XL)

        # Header
        header = QVBoxLayout()
        header.setSpacing(T.GAP)
        title = LargeTitleLabel("数据坊")
        title.setObjectName("welcomeTitle")
        header.addWidget(title)
        subtitle = CaptionLabel("缺陷数据集管理工具 — 选择一个项目开始")
        header.addWidget(subtitle)
        root.addLayout(header)

        # Action buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(T.GAP_LG)
        open_btn = PrimaryPushButton("打开数据集目录")
        open_btn.setFixedHeight(40)
        open_btn.clicked.connect(self._on_open_folder)
        btn_row.addWidget(open_btn)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

        # Recent projects section
        section_label = SubtitleLabel("最近项目")
        root.addWidget(section_label)

        self.project_list = QListWidget()
        self.project_list.setObjectName("projectList")
        self.project_list.setFrameShape(QFrame.Shape.NoFrame)
        self.project_list.setItemDelegate(_ProjectCardDelegate(self))
        self.project_list.setMouseTracking(True)
        self.project_list.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.project_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.project_list.customContextMenuRequested.connect(self._on_context_menu)
        root.addWidget(self.project_list, 1)

        # Empty hint
        self.empty_label = CaptionLabel("还没有打开过数据集，点击上方按钮开始。")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.empty_label)

        self.refresh()

    def refresh(self) -> None:
        """Reload the project list from recent history."""
        self.project_list.clear()
        summaries = list_known_projects()

        if not summaries:
            self.project_list.hide()
            self.empty_label.show()
            return

        self.empty_label.hide()
        self.project_list.show()

        for s in summaries:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, s)
            item.setSizeHint(QSize(0, _ProjectCardDelegate.CARD_HEIGHT))
            self.project_list.addItem(item)

    def _on_open_folder(self) -> None:
        self.open_folder.emit()

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        summary: ProjectSummary | None = item.data(Qt.ItemDataRole.UserRole)
        if summary and summary.exists:
            self.open_project.emit(summary.root_path)

    def _on_context_menu(self, pos) -> None:
        item = self.project_list.itemAt(pos)
        if not item:
            return
        summary: ProjectSummary | None = item.data(Qt.ItemDataRole.UserRole)
        if not summary:
            return

        menu = QMenu(self)
        if summary.exists:
            menu.addAction("打开项目", lambda: self.open_project.emit(summary.root_path))
            menu.addAction("打开文件夹位置", lambda: self._reveal_in_explorer(summary.root_path))
        menu.addSeparator()
        menu.addAction("从列表移除", lambda: self._remove_from_recent(summary.root_path))
        menu.exec(self.project_list.viewport().mapToGlobal(pos))

    def _reveal_in_explorer(self, path: Path) -> None:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(path)])

    def _remove_from_recent(self, path: Path) -> None:
        from core.recent import load_recent, RECENT_PATH
        items = load_recent()
        items = [x for x in items if x != str(path)]
        try:
            RECENT_PATH.parent.mkdir(parents=True, exist_ok=True)
            import json
            RECENT_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass
        self.refresh()
