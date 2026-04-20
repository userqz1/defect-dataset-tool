"""Main window — dataset-browser-first layout.

Navigation:
  TOP    — 首页 (DatasetWelcome)  |  浏览器 (DatasetBrowserView)
  BOTTOM — 设置 (SettingsView)

AppState owns the shared Dataset/Project. All views react to its signals.
"""
from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtGui import QColor
from qfluentwidgets import (
    FluentIcon as FIF,
    FluentWindow,
    InfoBar,
    InfoBarPosition,
    NavigationItemPosition,
    setTheme,
    setThemeColor,
    Theme,
)

from gui.app_state import AppState
from gui.theme import T, load_qss, set_theme as set_app_theme
from gui.views.settings_view import SettingsView

logger = logging.getLogger(__name__)


def _install_nav_expand_patch() -> None:
    """Monkey-patch qfluentwidgets.NavigationPanel so clicks in collapsed mode
    expand the sidebar before (or instead of) switching interfaces.

    Why this exists (review #8): default NavigationPanel behavior in
    narrow/COMPACT mode is to switch interface silently on click — users hit
    a nav icon, the page switches, but they don't see labels to know what
    they picked. The patched version expands the panel first on a collapsed
    click so labels become visible, preserving click-to-switch on already-
    expanded panels.

    Tested against: qfluentwidgets 1.11 (see requirements.txt pin). The
    patched symbol ``_onWidgetClicked`` is a private attribute; upstream
    rename / signature change will break the patch, so we wrap everything
    in try/except and fall through cleanly — the app still works, just
    without the expand-before-switch behavior.
    """
    try:
        from qfluentwidgets.components.navigation.navigation_panel import (
            NavigationDisplayMode, NavigationPanel,
        )
        if getattr(NavigationPanel, "_dataforge_patched", False):
            return
        original = NavigationPanel._onWidgetClicked

        def patched(self):
            widget = self.sender()
            if widget is None:
                return
            is_narrow = (self.isCollapsed()
                         or self.displayMode == NavigationDisplayMode.COMPACT)
            if not widget.isSelectable:
                if is_narrow:
                    self.expand(useAni=True)
                    return
                return original(self)
            if is_narrow:
                self.expand(useAni=True)
            return original(self)

        NavigationPanel._onWidgetClicked = patched
        NavigationPanel._dataforge_patched = True
    except Exception:
        # qfluentwidgets upstream changed — log once so a maintainer notices
        # the nav UX regressed, but don't crash the app on startup.
        logger.warning(
            "nav expand patch failed — qfluentwidgets API may have changed; "
            "collapsed nav clicks will switch without auto-expanding",
            exc_info=True,
        )


class MainWindow(FluentWindow):

    def __init__(self) -> None:
        _install_nav_expand_patch()
        super().__init__()

        # Install brand title bar BEFORE theme/qss so stylesheet applies
        # to it on first paint. Design §1: brand D chip + serif name +
        # breadcrumb path.
        from gui.widgets.brand_title_bar import BrandTitleBar
        self._brand_bar = BrandTitleBar(self)
        self.setTitleBar(self._brand_bar)

        from core.user_settings import load_settings
        s = load_settings()
        if s.theme == "dark":
            set_app_theme("dark")
            setTheme(Theme.DARK)
        else:
            setTheme(Theme.LIGHT)
        setThemeColor(QColor(T.ACCENT))
        self.setStyleSheet(load_qss())

        self.setWindowTitle("数据工坊")
        # Screen-aware initial size — target 1360×820 but cap at 90% of the
        # available screen so small laptops don't get a too-big window
        # (or a window that overflows the taskbar). Minimum width 1080
        # keeps the 3-column body (248 tools + 560 viewer + 272 catalog min)
        # from horizontal-overflowing; users can close the catalog for
        # narrower screens.
        from PyQt6.QtGui import QGuiApplication
        geom = QGuiApplication.primaryScreen().availableGeometry()
        w = min(1360, int(geom.width() * 0.9))
        h = min(820, int(geom.height() * 0.9))
        self.resize(w, h)
        self.setMinimumSize(1080, 680)
        # Center on the primary screen — without this, Qt leaves the window
        # at whatever the window manager picked (usually top-left on Windows),
        # which felt wrong on first launch.
        self.move(
            geom.x() + (geom.width() - w) // 2,
            geom.y() + (geom.height() - h) // 2,
        )

        # Shared state
        self._state = AppState(parent=self)
        # Title-bar breadcrumbs follow the active dataset.
        self._state.dataset_changed.connect(
            lambda ds: self._brand_bar.set_path(ds.root_path if ds else None)
        )

        try:
            self.navigationInterface.panel.returnButton.hide()
        except Exception:
            # qfluentwidgets internal layout — best-effort tweak.
            logger.debug("hide returnButton failed", exc_info=True)

        self._build_views()
        self.switchTo(self.home)

        # Design §NavRail is a 60px icon-only rail — *never* auto-expand.
        # qfluentwidgets otherwise re-expands on menu-button click, nav-item
        # click (selectable), or hover. We lock it in three ways:
        #   1. Collapse now, so the first paint is narrow.
        #   2. Hide the ☰ menu button so users can't toggle it manually.
        #   3. Monkey-patch panel.expand() to a no-op so nothing else can
        #      sneak an expand past us (e.g. internal item-click handler).
        try:
            panel = self.navigationInterface.panel
            panel.collapse()
            panel.menuButton.hide()
            panel.expand = lambda *a, **kw: None  # type: ignore[assignment]
        except Exception:
            logger.debug("nav rail lockdown failed", exc_info=True)

    # ---------- Build ----------

    def _build_views(self) -> None:
        from gui.views.dataset_browser_view import DatasetBrowserView
        from gui.views.dataset_welcome import DatasetWelcome
        from gui.views.organize_view import OrganizeView

        # Home — dataset list
        self.home = DatasetWelcome()
        self.home.open_dataset.connect(self._open_dataset)

        # Organize — batch import → classify → land (v1.2 §9.3)
        self.organize = OrganizeView()
        self.organize.import_done.connect(self._open_dataset)

        # Browser — top-level dataset browser
        self.browser = DatasetBrowserView(self._state)

        # Settings lives as a floating popup (design handoff §Tweaks) —
        # NOT a routable subInterface. It's parented to MainWindow so popup
        # geometry + Qt.Popup click-outside handling work.
        self.settings_view = SettingsView(self)
        self.settings_view.theme_changed.connect(self._on_theme_changed)
        # The catalog toggle from the popup drives the DatasetBrowserView's
        # own catalog-visibility signal — DatasetBrowserView already handles
        # the in-window visibility state.
        self.settings_view.catalog_toggled.connect(
            lambda on: self.browser._set_catalog_open(on)
        )

        # Nav — TOP (labels via gui.i18n.t — live-updated on language switch)
        from gui import i18n
        self.addSubInterface(self.home, FIF.HOME_FILL, i18n.t("nav.home"),
                             position=NavigationItemPosition.TOP)
        self.addSubInterface(self.organize, FIF.FOLDER_ADD, i18n.t("nav.organize"),
                             position=NavigationItemPosition.TOP)
        self.addSubInterface(self.browser, FIF.PHOTO, i18n.t("nav.browser"),
                             position=NavigationItemPosition.TOP)

        # Nav — BOTTOM: gear button opens the floating Tweaks panel.
        # selectable=False keeps it an action (no route highlight on click).
        self.navigationInterface.addItem(
            routeKey="settings-trigger",
            icon=FIF.SETTING,
            text=i18n.t("nav.settings"),
            onClick=self._open_settings_popup,
            selectable=False,
            position=NavigationItemPosition.BOTTOM,
        )
        # Re-label nav items when the language flips. qfluentwidgets stores
        # the display text inside each NavigationTreeWidget item; reach into
        # the widget map to update in place.
        i18n.bus.language_changed.connect(self._relabel_nav)

    # ---------- Dataset operations ----------

    def _open_dataset(self, path_str: str) -> None:
        """Open a dataset directory — show task type dialog if new."""
        root = Path(path_str)
        if not root.is_dir():
            InfoBar.warning("", "目录不存在", parent=self,
                            duration=2000, position=InfoBarPosition.TOP)
            return

        from core.project import load_project

        project = load_project(root)
        if project:
            task_type = project.task_type
        else:
            from gui.dialogs.task_type_dialog import TaskTypeDialog
            dlg = TaskTypeDialog(self)
            if not dlg.exec():
                return
            task_type = dlg.selected_task_type()
            if task_type is None:
                return

        self._state.open_dataset(root, task_type)
        self.browser.open_directory(root)
        self.switchTo(self.browser)

    # ---------- i18n ----------

    def _relabel_nav(self, _lang: str) -> None:
        """Re-apply translated labels on the nav panel.

        qfluentwidgets' NavigationPanel stores ``{routeKey: NavigationItem}``
        in ``panel.items``; each NavigationItem wraps the actual button
        widget under ``.widget``. The button has a ``setText`` method.
        """
        from gui import i18n
        panel = self.navigationInterface.panel
        mapping = {
            self.home.objectName(): i18n.t("nav.home"),
            self.organize.objectName(): i18n.t("nav.organize"),
            self.browser.objectName(): i18n.t("nav.browser"),
            "settings-trigger": i18n.t("nav.settings"),
        }
        for key, label in mapping.items():
            item = panel.items.get(key)
            w = getattr(item, "widget", None) if item else None
            if w is not None and hasattr(w, "setText"):
                try:
                    w.setText(label)
                except Exception:
                    logger.debug("relabel failed for %s", key, exc_info=True)

    # ---------- Settings popup ----------

    def _open_settings_popup(self) -> None:
        """Show the settings popup at window-bottom-left, right of the rail.

        Design §Tweaks positions the panel at ``left: 68px; bottom: 16px``
        of the viewport. We follow that literally using the main window's
        own geometry so it doesn't matter whether the nav panel is using
        its icon-only or (long-deprecated) expanded width.
        """
        self.settings_view.adjustSize()
        mw_tl_global = self.mapToGlobal(self.rect().topLeft())
        x = mw_tl_global.x() + 68
        y = mw_tl_global.y() + self.height() - self.settings_view.height() - 16
        self.settings_view.move(x, y)
        self.settings_view.show()
        self.settings_view.raise_()

    # ---------- Navigation ----------

    def switchTo(self, interface):
        if interface is self.home:
            self.home.refresh()
        super().switchTo(interface)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # Force collapse on every resize — qfluentwidgets' internal logic
        # otherwise re-expands the panel at wider widths. Design §NavRail
        # mandates a constant 60px icon-only rail.
        try:
            panel = self.navigationInterface.panel
            if not panel.isCollapsed():
                panel.collapse()
        except Exception:
            logger.debug("nav resize collapse failed", exc_info=True)

    def _on_theme_changed(self, name: str) -> None:
        set_app_theme(name, window=self)
        setTheme(Theme.DARK if name == "dark" else Theme.LIGHT)
        setThemeColor(QColor(T.ACCENT))
        from core.user_settings import save_settings, UserSettings
        save_settings(UserSettings(theme=name))

    def closeEvent(self, e):
        self._state.close_dataset()
        self.browser.cleanup()
        super().closeEvent(e)
