"""Dataset welcome page — the app's home screen.

Shows recent datasets and provides quick entry points:
- Open a dataset directory
- Pick from recent datasets
- Access pipeline templates (small entry at bottom)
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QMenu,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CaptionLabel,
    FluentIcon as FIF,
    PrimaryPushButton,
    StrongBodyLabel,
    SubtitleLabel,
)

from gui.theme import T


class _DatasetCard(QFrame):
    """Clickable card representing a recent dataset."""

    clicked = pyqtSignal(str)           # root_path
    remove_requested = pyqtSignal(str)  # root_path

    def __init__(self, root_path: str, name: str, updated_at: str,
                 exists: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._root = root_path
        self.setObjectName("formatCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(72)
        self.setEnabled(exists)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(T.PAD_LG, T.GAP, T.PAD_LG, T.GAP)
        lay.setSpacing(2)

        top = QHBoxLayout()
        top.addWidget(StrongBodyLabel(name))
        top.addStretch()
        if not exists:
            gone = CaptionLabel("目录不存在")
            gone.setObjectName("hintWarn")
            top.addWidget(gone)
        lay.addLayout(top)

        # Path + timestamp
        info = QHBoxLayout()
        path_text = root_path
        if len(path_text) > 60:
            path_text = "..." + path_text[-57:]
        info.addWidget(CaptionLabel(path_text))
        info.addStretch()
        if updated_at:
            info.addWidget(CaptionLabel(updated_at[:16]))
        lay.addLayout(info)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self.clicked.emit(self._root)

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        menu.addAction("从列表移除", lambda: self.remove_requested.emit(self._root))
        menu.exec(event.globalPos())


class DatasetWelcome(QWidget):
    """Dataset-centric home page."""

    open_dataset = pyqtSignal(str)          # root_path

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("datasetWelcome")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        root = QVBoxLayout(self)
        root.setContentsMargins(T.PAD_3XL, T.PAD_2XL, T.PAD_3XL, T.PAD_2XL)
        root.setSpacing(T.PAD_LG)

        # Header: title + open button
        header = QHBoxLayout()
        header.addWidget(SubtitleLabel("数据集"))
        header.addStretch()
        open_btn = PrimaryPushButton("打开数据集目录")
        open_btn.setIcon(FIF.FOLDER)
        open_btn.setFixedHeight(36)
        open_btn.clicked.connect(self._on_open_dir)
        header.addWidget(open_btn)
        root.addLayout(header)

        # Recent datasets list
        self._list_label = CaptionLabel("")
        root.addWidget(self._list_label)

        self._list_lay = QVBoxLayout()
        self._list_lay.setSpacing(T.GAP)
        root.addLayout(self._list_lay)

        root.addStretch()
        self._load()

    # -- Public --

    def refresh(self) -> None:
        self._load()

    # -- Private --

    def _load(self) -> None:
        # Clear datasets
        while self._list_lay.count():
            w = self._list_lay.takeAt(0).widget()
            if w:
                w.deleteLater()

        # Recent datasets
        from core.project import list_known_projects
        projects = list_known_projects()
        if projects:
            self._list_label.setText(f"{len(projects)} 个最近数据集")
        else:
            self._list_label.setText("暂无最近数据集，点击上方按钮打开目录")

        for ps in projects:
            card = _DatasetCard(
                str(ps.root_path), ps.name, ps.updated_at, ps.exists,
            )
            card.clicked.connect(self.open_dataset.emit)
            card.remove_requested.connect(self._on_remove)
            self._list_lay.addWidget(card)

    def _on_open_dir(self) -> None:
        from PyQt6.QtWidgets import QFileDialog
        d = QFileDialog.getExistingDirectory(self, "选择数据集目录", str(Path.home()))
        if d:
            self.open_dataset.emit(d)

    def _on_remove(self, path_str: str) -> None:
        """Remove from recent list (does not delete files)."""
        import json
        from core.recent import RECENT_PATH, load_recent
        recent = [p for p in load_recent() if p != path_str]
        try:
            RECENT_PATH.write_text(
                json.dumps(recent, ensure_ascii=False, indent=2), encoding="utf-8",
            )
        except OSError:
            pass
        self._load()
