"""设置：主题切换 / 缩略图缓存 / 最近数据集。"""
from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CheckBox,
    PushButton,
    StrongBodyLabel,
    SubtitleLabel,
)

from core.recent import clear_recent, load_recent
from core.thumbnail_cache import ThumbnailCache
from core.user_settings import load_settings, save_settings
from gui.theme import T

logger = logging.getLogger(__name__)


def _human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


class _ThemeCard(QFrame):
    """A clickable preview card showing a miniature window in a given theme."""

    clicked = pyqtSignal(str)

    def __init__(
        self,
        key: str,
        title: str,
        sidebar: str,
        content: str,
        text: str,
        accent: str,
        border: str,
    ) -> None:
        super().__init__()
        self.key = key
        self._sidebar = sidebar
        self._content = content
        self._text = text
        self._accent = accent
        self._border = border
        self._selected = False

        self.setObjectName("themeCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedSize(180, 140)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._title = title

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self.update()

    def mousePressEvent(self, e):  # type: ignore[override]
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.key)
        super().mousePressEvent(e)

    def paintEvent(self, e):  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 外框
        border_color = QColor(T.ACCENT) if self._selected else QColor(self._border)
        pen = QPen(border_color)
        pen.setWidth(2 if self._selected else 1)
        p.setPen(pen)
        p.setBrush(QColor(self._content))
        p.drawRoundedRect(2, 2, self.width() - 24, self.height() - 28, 8, 8)

        # 侧栏
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(self._sidebar))
        p.drawRoundedRect(6, 6, 36, self.height() - 36, 6, 6)

        # 标题栏文字 (3 条)
        p.setBrush(QColor(self._text))
        for i in range(3):
            p.drawRoundedRect(50, 14 + i * 10, 70 - i * 12, 4, 2, 2)

        # 强调色按钮
        p.setBrush(QColor(self._accent))
        p.drawRoundedRect(self.width() - 38, self.height() - 46, 12, 8, 2, 2)

        # 标签
        p.setPen(QColor(T.TEXT))
        p.drawText(
            0,
            self.height() - 18,
            self.width() - 18,
            18,
            Qt.AlignmentFlag.AlignHCenter,
            self._title,
        )


class SettingsView(QWidget):
    open_recent = pyqtSignal(str)  # 触发打开最近数据集
    theme_changed = pyqtSignal(str)  # "light" / "dark"

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("settingsView")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        root = QVBoxLayout(self)
        root.setContentsMargins(T.PAD_2XL, T.PAD_2XL - 4, T.PAD_2XL, T.PAD_XL)
        root.setSpacing(T.GAP_LG)

        root.addWidget(SubtitleLabel("设置"))

        # 主题
        root.addWidget(StrongBodyLabel("外观"))
        root.addWidget(CaptionLabel("配色"))

        cards_row = QHBoxLayout()
        cards_row.setSpacing(T.GAP_LG)
        # tokens 直接引用 LIGHT/DARK 静态值，确保预览不随当前主题变化
        from gui.theme import LIGHT, DARK
        self.card_light = _ThemeCard(
            "light", "浅色",
            sidebar=LIGHT.SIDEBAR, content=LIGHT.CONTENT,
            text=LIGHT.TEXT_2, accent=LIGHT.ACCENT, border=LIGHT.BORDER,
        )
        self.card_dark = _ThemeCard(
            "dark", "深色",
            sidebar=DARK.SIDEBAR, content=DARK.CONTENT,
            text=DARK.TEXT_2, accent=DARK.ACCENT, border=DARK.BORDER,
        )
        for c in (self.card_light, self.card_dark):
            c.clicked.connect(self._on_theme_card_clicked)
            cards_row.addWidget(c)
        cards_row.addStretch(1)
        root.addLayout(cards_row)
        self._set_selected_card("light")

        # 浏览
        root.addWidget(StrongBodyLabel("浏览"))
        self._keep_filter_chk = CheckBox("切换类别保留筛选")
        self._keep_filter_chk.setChecked(
            load_settings().keep_filter_on_category_switch
        )
        self._keep_filter_chk.toggled.connect(self._on_keep_filter_toggled)
        root.addWidget(self._keep_filter_chk)

        # 缓存
        root.addWidget(StrongBodyLabel("缓存"))
        cache_row = QHBoxLayout()
        self.cache_label = BodyLabel("缩略图缓存：—")
        cache_row.addWidget(self.cache_label, 1)
        self.refresh_btn = PushButton("刷新")
        self.refresh_btn.clicked.connect(self._refresh_cache_size)
        cache_row.addWidget(self.refresh_btn)
        self.clear_cache_btn = PushButton("清空缓存")
        self.clear_cache_btn.clicked.connect(self._on_clear_cache)
        cache_row.addWidget(self.clear_cache_btn)
        root.addLayout(cache_row)

        # 最近数据集
        root.addWidget(StrongBodyLabel("最近打开"))
        self.recent_list = QListWidget()
        self.recent_list.setObjectName("recentList")
        self.recent_list.itemDoubleClicked.connect(self._on_recent_activated)
        root.addWidget(self.recent_list, 1)

        recent_ctrl = QHBoxLayout()
        recent_ctrl.addStretch(1)
        self.clear_recent_btn = PushButton("清空最近列表")
        self.clear_recent_btn.clicked.connect(self._on_clear_recent)
        recent_ctrl.addWidget(self.clear_recent_btn)
        root.addLayout(recent_ctrl)

        self.refresh()

    # 公开接口

    def refresh(self) -> None:
        self._refresh_cache_size()
        self._refresh_recent()

    def set_dataset(self, dataset) -> None:  # 兼容主窗口的统一调用
        self._refresh_recent()

    # 主题

    def _set_selected_card(self, key: str) -> None:
        self.card_light.set_selected(key == "light")
        self.card_dark.set_selected(key == "dark")

    def _on_theme_card_clicked(self, key: str) -> None:
        self._set_selected_card(key)
        self.theme_changed.emit(key)

    # 缓存

    def _refresh_cache_size(self) -> None:
        try:
            cache = ThumbnailCache()
            n = cache.volume()
            cache.close()
            self.cache_label.setText(f"缩略图缓存:{_human_bytes(n)}")
        except Exception as e:  # noqa: BLE001
            logger.exception("reading cache size failed")
            self.cache_label.setText(f"缩略图缓存:读取失败 ({e})")

    def _on_clear_cache(self) -> None:
        try:
            cache = ThumbnailCache()
            n = cache.clear()
            cache.close()
            self.cache_label.setText(f"已清空 {n} 项缓存")
        except Exception as e:  # noqa: BLE001
            logger.exception("clearing cache failed")
            self.cache_label.setText(f"清空失败:{e}")

    # 最近列表

    def _refresh_recent(self) -> None:
        self.recent_list.clear()
        items = load_recent()
        if not items:
            self.recent_list.addItem("(暂无最近打开的数据集)")
            return
        for p in items:
            self.recent_list.addItem(QListWidgetItem(p))

    def _on_recent_activated(self, item: QListWidgetItem) -> None:
        text = item.text()
        if text and not text.startswith("("):
            self.open_recent.emit(text)

    def _on_clear_recent(self) -> None:
        clear_recent()
        self._refresh_recent()

    # 浏览偏好

    def _on_keep_filter_toggled(self, checked: bool) -> None:
        s = load_settings()
        s.keep_filter_on_category_switch = checked
        save_settings(s)
