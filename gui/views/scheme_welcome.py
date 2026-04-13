"""Scheme manager — list all saved schemes, create, open, delete, duplicate.

This IS the home page. Not a "welcome" — it's a document manager like
n8n's workflow overview or VS Code's recent files.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QMenu,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    FluentIcon as FIF,
    PrimaryPushButton,
    PushButton,
    StrongBodyLabel,
    SubtitleLabel,
)

from gui.theme import T


class _SchemeCard(QFrame):
    """Clickable card representing a saved scheme."""

    clicked = pyqtSignal(str)         # path
    delete_requested = pyqtSignal(str)
    duplicate_requested = pyqtSignal(str)

    def __init__(self, path: str, name: str, modified: str, node_count: int = 0,
                 parent=None) -> None:
        super().__init__(parent)
        self._path = path
        self.setObjectName("formatCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(72)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(T.PAD_LG, T.GAP, T.PAD_LG, T.GAP)
        lay.setSpacing(2)

        top = QHBoxLayout()
        top.addWidget(StrongBodyLabel(name))
        top.addStretch()
        if node_count:
            top.addWidget(CaptionLabel(f"{node_count} 节点"))
        lay.addLayout(top)

        lay.addWidget(CaptionLabel(modified[:16] if modified else ""))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._path)

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        menu.addAction("删除", lambda: self.delete_requested.emit(self._path))
        menu.addAction("复制", lambda: self.duplicate_requested.emit(self._path))
        menu.exec(event.globalPos())


class _TemplateCard(QFrame):
    """Clickable template card."""

    clicked = pyqtSignal(int)

    def __init__(self, idx: int, name: str, node_count: int, parent=None) -> None:
        super().__init__(parent)
        self._idx = idx
        self.setObjectName("formatCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(48)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(T.PAD_LG, T.GAP, T.PAD_LG, T.GAP)
        lay.addWidget(BodyLabel(name))
        lay.addStretch()
        lay.addWidget(CaptionLabel(f"{node_count} 节点"))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._idx)


class SchemeWelcome(QWidget):
    """Scheme manager page — the app's home screen."""

    new_scheme = pyqtSignal()
    open_scheme = pyqtSignal(str)
    use_template = pyqtSignal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("schemeWelcome")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        root = QVBoxLayout(self)
        root.setContentsMargins(T.PAD_3XL, T.PAD_2XL, T.PAD_3XL, T.PAD_2XL)
        root.setSpacing(T.PAD_LG)

        # Header: title + new button
        header = QHBoxLayout()
        header.addWidget(SubtitleLabel("方案"))
        header.addStretch()
        new_btn = PrimaryPushButton("新建方案")
        new_btn.setIcon(FIF.ADD)
        new_btn.setFixedHeight(36)
        new_btn.clicked.connect(self.new_scheme.emit)
        header.addWidget(new_btn)
        root.addLayout(header)

        # Content: schemes grid + templates sidebar
        body = QHBoxLayout()
        body.setSpacing(T.PAD_2XL)

        # Left: saved schemes
        left = QVBoxLayout()
        left.setSpacing(T.GAP)
        self._schemes_label = CaptionLabel("")
        left.addWidget(self._schemes_label)
        self._schemes_grid = QVBoxLayout()
        self._schemes_grid.setSpacing(T.GAP)
        left.addLayout(self._schemes_grid)
        left.addStretch()
        body.addLayout(left, 3)

        # Right: templates
        right = QVBoxLayout()
        right.setSpacing(T.GAP)
        right.addWidget(CaptionLabel("模板"))
        self._tpl_lay = QVBoxLayout()
        self._tpl_lay.setSpacing(T.GAP)
        right.addLayout(self._tpl_lay)
        right.addStretch()
        body.addLayout(right, 1)

        root.addLayout(body, 1)

        self._load()

    def refresh(self) -> None:
        self._load()

    def _load(self) -> None:
        # Clear
        while self._schemes_grid.count():
            w = self._schemes_grid.takeAt(0).widget()
            if w:
                w.deleteLater()
        while self._tpl_lay.count():
            w = self._tpl_lay.takeAt(0).widget()
            if w:
                w.deleteLater()

        # Saved schemes
        from core.scheme import list_recent_schemes
        schemes = list_recent_schemes()
        self._schemes_label.setText(f"{len(schemes)} 个方案" if schemes else "暂无保存的方案")

        for path, name, modified in schemes:
            # Try to read node count
            node_count = 0
            try:
                import json
                data = json.loads(Path(path).read_text(encoding="utf-8"))
                node_count = len(data.get("nodes", []))
            except Exception:
                pass
            card = _SchemeCard(str(path), name, modified, node_count)
            card.clicked.connect(self.open_scheme.emit)
            card.delete_requested.connect(self._on_delete)
            card.duplicate_requested.connect(self._on_duplicate)
            self._schemes_grid.addWidget(card)

        # Templates
        from core.scheme import TEMPLATES
        for i, tpl in enumerate(TEMPLATES):
            card = _TemplateCard(i, tpl.name, len(tpl.nodes))
            card.clicked.connect(self.use_template.emit)
            self._tpl_lay.addWidget(card)

    def _on_delete(self, path_str: str) -> None:
        from qfluentwidgets import MessageBox
        box = MessageBox("删除方案", f"确定删除？此操作不可撤销。", self.window())
        box.yesButton.setText("删除")
        box.cancelButton.setText("取消")
        if box.exec():
            try:
                from send2trash import send2trash
                send2trash(str(Path(path_str)))
            except Exception:
                Path(path_str).unlink(missing_ok=True)
            self._load()

    def _on_duplicate(self, path_str: str) -> None:
        from core.scheme import load_scheme, save_scheme
        scheme = load_scheme(Path(path_str))
        if not scheme:
            return
        scheme.name = scheme.name + " (副本)"
        save_scheme(scheme)  # saves to new file
        self._load()
