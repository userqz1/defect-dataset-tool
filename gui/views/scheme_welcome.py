"""Welcome page — create new scheme, open recent, use template."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
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


class SchemeWelcome(QWidget):
    """Welcome page for scheme management."""

    new_scheme = pyqtSignal()                    # blank canvas
    open_scheme = pyqtSignal(str)                # path string
    use_template = pyqtSignal(int)               # template index

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("schemeWelcome")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        root = QVBoxLayout(self)
        root.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.setSpacing(T.PAD_2XL)
        root.setContentsMargins(T.PAD_3XL, T.PAD_HERO, T.PAD_3XL, T.PAD_3XL)

        # Title
        title = SubtitleLabel("数据工坊")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(title)

        # Action row: New + Open
        action_row = QHBoxLayout()
        action_row.setSpacing(T.GAP_LG)
        action_row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        new_btn = PrimaryPushButton("新建方案")
        new_btn.setIcon(FIF.ADD)
        new_btn.setFixedSize(140, 40)
        new_btn.clicked.connect(self.new_scheme.emit)
        action_row.addWidget(new_btn)

        root.addLayout(action_row)

        # Two columns: Recent | Templates
        cols = QHBoxLayout()
        cols.setSpacing(T.PAD_2XL)

        # --- Recent schemes ---
        recent_col = QVBoxLayout()
        recent_col.setSpacing(T.GAP)
        recent_col.addWidget(StrongBodyLabel("最近方案"))

        self._recent_list = QListWidget()
        self._recent_list.setObjectName("projectList")
        self._recent_list.setMinimumWidth(280)
        self._recent_list.setMaximumHeight(300)
        self._recent_list.itemDoubleClicked.connect(self._on_recent_click)
        recent_col.addWidget(self._recent_list)
        cols.addLayout(recent_col)

        # --- Templates ---
        tpl_col = QVBoxLayout()
        tpl_col.setSpacing(T.GAP)
        tpl_col.addWidget(StrongBodyLabel("模板"))

        self._tpl_frame = QVBoxLayout()
        self._tpl_frame.setSpacing(T.GAP)
        tpl_col.addLayout(self._tpl_frame)
        tpl_col.addStretch()
        cols.addLayout(tpl_col)

        root.addLayout(cols)
        root.addStretch()

        self._load_content()

    def refresh(self) -> None:
        self._load_content()

    def _load_content(self) -> None:
        # Recent schemes
        self._recent_list.clear()
        from core.scheme import list_recent_schemes
        recents = list_recent_schemes()
        if not recents:
            item = QListWidgetItem("暂无历史方案")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._recent_list.addItem(item)
        else:
            for path, name, modified in recents:
                item = QListWidgetItem(f"{name}  ·  {modified[:10]}")
                item.setData(Qt.ItemDataRole.UserRole, str(path))
                self._recent_list.addItem(item)

        # Templates
        while self._tpl_frame.count():
            w = self._tpl_frame.takeAt(0).widget()
            if w:
                w.deleteLater()

        from core.scheme import TEMPLATES
        for i, tpl in enumerate(TEMPLATES):
            card = self._make_tpl_card(i, tpl.name, f"{len(tpl.nodes)} 节点")
            self._tpl_frame.addWidget(card)

    def _make_tpl_card(self, idx: int, name: str, desc: str) -> QFrame:
        card = QFrame()
        card.setObjectName("formatCard")
        card.setFixedHeight(48)
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QHBoxLayout(card)
        lay.setContentsMargins(T.PAD_LG, T.GAP, T.PAD_LG, T.GAP)
        lay.setSpacing(T.GAP)

        lay.addWidget(BodyLabel(name))
        lay.addStretch()
        lay.addWidget(CaptionLabel(desc))

        card.mousePressEvent = lambda e, i=idx: self.use_template.emit(i)
        return card

    def _on_recent_click(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self.open_scheme.emit(path)
