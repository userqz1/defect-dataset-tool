"""设置 · Settings — Claude-style menu popup.

Looks like a user-menu dropdown rather than a form: each setting is a
row with a leading icon + label, inline seg-buttons (or a plain action
button) on the right, thin horizontal dividers between logical groups,
and a full-row hover highlight.

Window flags: ``Qt.Popup`` so clicking outside auto-hides the panel.
"""
from __future__ import annotations

import logging

from PyQt6.QtCore import QPoint, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QMouseEvent
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    FluentIcon as FIF,
    PushButton,
)

from core.thumbnail_cache import ThumbnailCache
from core.user_settings import load_settings, save_settings
from gui import i18n
from gui.theme import T

logger = logging.getLogger(__name__)


def _human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def _seg_btn(text: str) -> PushButton:
    """Inline segmented button (factory — PushButton subclass breaks on
    qfluentwidgets' singledispatch recursion)."""
    btn = PushButton(text=text)
    btn.setObjectName("tweakSeg")
    btn.setCheckable(True)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    return btn


def _seg_group(*buttons: QWidget) -> QWidget:
    wrap = QWidget()
    lay = QHBoxLayout(wrap)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(2)
    for b in buttons:
        lay.addWidget(b)
    return wrap


class _CloseLabel(QLabel):
    """Tiny click-through × glyph."""

    clicked = pyqtSignal()

    def __init__(self) -> None:
        super().__init__("✕")
        self.setObjectName("tweakClose")
        self.setFixedSize(18, 18)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, e: QMouseEvent) -> None:  # type: ignore[override]
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)


def _divider() -> QFrame:
    """Thin horizontal divider between setting groups."""
    line = QFrame()
    line.setObjectName("tweakDivider")
    line.setFixedHeight(1)
    return line


class SettingsView(QFrame):
    """Claude-style settings popup — menu list with icons + inline controls."""

    theme_changed = pyqtSignal(str)
    catalog_toggled = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("settingsPopup")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setWindowFlags(
            Qt.WindowType.Popup
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setFixedWidth(320)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(40)
        shadow.setOffset(0, 12)
        shadow.setColor(QColor(T.POPUP_SHADOW))
        self.setGraphicsEffect(shadow)

        self._i18n_refs: list[tuple[QWidget, str]] = []

        self._build()
        self._refresh_cache_size()
        i18n.bus.language_changed.connect(self._retranslate)

    # ---------- builder (once) ----------

    def _build(self) -> None:
        body = QVBoxLayout(self)
        body.setContentsMargins(8, 8, 8, 8)
        body.setSpacing(0)

        # Header — small context title + close × on the right.
        head = QHBoxLayout()
        head.setContentsMargins(12, 8, 10, 10)
        head.setSpacing(8)
        self._title = BodyLabel(i18n.t("settings.title"))
        self._title.setObjectName("tweakHead")
        self._i18n_refs.append((self._title, "settings.title"))
        head.addWidget(self._title, 1)
        close_btn = _CloseLabel()
        close_btn.clicked.connect(self.hide)
        head.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        body.addLayout(head)

        settings = load_settings()

        # Group 1: display preferences (theme · language)
        body.addWidget(_divider())

        self._theme_light = _seg_btn("")
        self._theme_dark = _seg_btn("")
        (self._theme_dark if settings.theme == "dark"
         else self._theme_light).setChecked(True)
        g = QButtonGroup(self); g.setExclusive(True)
        g.addButton(self._theme_light); g.addButton(self._theme_dark)
        self._theme_light.clicked.connect(lambda: self._emit_theme("light"))
        self._theme_dark.clicked.connect(lambda: self._emit_theme("dark"))
        body.addWidget(self._row(
            FIF.BRUSH, "settings.theme",
            _seg_group(self._theme_light, self._theme_dark),
        ))
        self._i18n_refs.append((self._theme_light, "settings.theme.light"))
        self._i18n_refs.append((self._theme_dark, "settings.theme.dark"))

        self._lang_zh = _seg_btn("")
        self._lang_en = _seg_btn("")
        (self._lang_en if i18n.lang() == "en" else self._lang_zh).setChecked(True)
        g = QButtonGroup(self); g.setExclusive(True)
        g.addButton(self._lang_zh); g.addButton(self._lang_en)
        self._lang_zh.clicked.connect(lambda: i18n.set_lang("zh"))
        self._lang_en.clicked.connect(lambda: i18n.set_lang("en"))
        body.addWidget(self._row(
            FIF.LANGUAGE, "settings.language",
            _seg_group(self._lang_zh, self._lang_en),
        ))
        self._i18n_refs.append((self._lang_zh, "settings.language.zh"))
        self._i18n_refs.append((self._lang_en, "settings.language.en"))

        # Group 2: layout preferences (catalog visibility)
        body.addWidget(_divider())

        self._cat_show = _seg_btn("")
        self._cat_hide = _seg_btn("")
        self._cat_show.setChecked(True)
        g = QButtonGroup(self); g.setExclusive(True)
        g.addButton(self._cat_show); g.addButton(self._cat_hide)
        self._cat_show.clicked.connect(lambda: self.catalog_toggled.emit(True))
        self._cat_hide.clicked.connect(lambda: self.catalog_toggled.emit(False))
        body.addWidget(self._row(
            FIF.PIE_SINGLE, "settings.catalog",
            _seg_group(self._cat_show, self._cat_hide),
        ))
        self._i18n_refs.append((self._cat_show, "settings.catalog.show"))
        self._i18n_refs.append((self._cat_hide, "settings.catalog.hide"))

        # Project annotation-format migration lives in 项目中心 → 格式中心,
        # not here. Settings is for global preferences only.

        # Group 3: cache (single action — no seg)
        body.addWidget(_divider())

        self._clear_btn = _seg_btn("")
        self._clear_btn.setCheckable(False)
        self._clear_btn.clicked.connect(self._on_clear_cache)
        self._cache_label = BodyLabel("")  # text set by _refresh_cache_size
        self._cache_label.setObjectName("tweakKey")
        # Custom row — cache shows "{label · size}" as the key so we don't use _row
        cache = QFrame()
        cache.setObjectName("tweakRow")
        cl = QHBoxLayout(cache)
        cl.setContentsMargins(12, 8, 10, 8)
        cl.setSpacing(10)
        cache_icon = QLabel()
        cache_icon.setFixedSize(16, 16)
        cache_icon.setPixmap(FIF.BROOM.icon().pixmap(QSize(14, 14)))
        cache_icon.setObjectName("tweakIcon")
        cl.addWidget(cache_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        cl.addWidget(self._cache_label, 1)
        cl.addWidget(self._clear_btn)
        body.addWidget(cache)
        self._i18n_refs.append((self._clear_btn, "settings.cache.clear"))

        self._retranslate("")

    def _row(self, icon: FIF, i18n_key: str, value_widget: QWidget) -> QWidget:
        """Build one menu row: icon + label + right-side control.

        Tracks (label_widget, key) in _i18n_refs so language switch
        re-applies without rebuilding.
        """
        row = QFrame()
        row.setObjectName("tweakRow")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(12, 8, 10, 8)
        lay.setSpacing(10)

        icon_lbl = QLabel()
        icon_lbl.setFixedSize(16, 16)
        icon_lbl.setPixmap(icon.icon().pixmap(QSize(14, 14)))
        icon_lbl.setObjectName("tweakIcon")
        lay.addWidget(icon_lbl, 0, Qt.AlignmentFlag.AlignVCenter)

        key_label = BodyLabel(i18n.t(i18n_key))
        key_label.setObjectName("tweakKey")
        self._i18n_refs.append((key_label, i18n_key))
        lay.addWidget(key_label, 1)

        lay.addWidget(value_widget)
        return row

    # ---------- i18n refresh ----------

    def _retranslate(self, _lang: str) -> None:
        for w, key in self._i18n_refs:
            w.setText(i18n.t(key))
        self._refresh_cache_size()

    # ---------- public API ----------

    def popup_near(self, trigger_global_pos: QPoint) -> None:
        self.adjustSize()
        x = trigger_global_pos.x() + 8
        y = trigger_global_pos.y() - self.height() - 4
        self.move(x, y)
        self.show()
        self.raise_()

    # ---------- internals ----------

    def _emit_theme(self, key: str) -> None:
        self.theme_changed.emit(key)
        s = load_settings()
        s.theme = key
        save_settings(s)

    def _refresh_cache_size(self) -> None:
        try:
            cache = ThumbnailCache()
            n = cache.volume()
            cache.close()
            self._cache_label.setText(f"{i18n.t('settings.cache')} · {_human_bytes(n)}")
        except Exception:  # noqa: BLE001
            logger.exception("reading cache size failed")
            self._cache_label.setText(i18n.t("settings.cache.read_failed"))

    def _on_clear_cache(self) -> None:
        try:
            cache = ThumbnailCache()
            n = cache.clear()
            cache.close()
            self._cache_label.setText(i18n.t("settings.cache.cleared", n=n))
        except Exception:  # noqa: BLE001
            logger.exception("clearing cache failed")
