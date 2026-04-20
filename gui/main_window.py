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
        is_narrow = self.isCollapsed() or self.displayMode == NavigationDisplayMode.COMPACT
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


class MainWindow(FluentWindow):

    def __init__(self) -> None:
        _install_nav_expand_patch()
        super().__init__()

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
        self.resize(1280, 800)

        # Shared state
        self._state = AppState(parent=self)
        self._nav_collapse_threshold = 1100

        try:
            self.navigationInterface.panel.returnButton.hide()
        except Exception:
            # qfluentwidgets internal layout — best-effort tweak.
            logger.debug("hide returnButton failed", exc_info=True)

        self._build_views()
        self.switchTo(self.home)

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

        # Settings
        self.settings_view = SettingsView()
        self.settings_view.theme_changed.connect(self._on_theme_changed)

        # Nav — TOP
        self.addSubInterface(self.home, FIF.HOME_FILL, "首页",
                             position=NavigationItemPosition.TOP)
        self.addSubInterface(self.organize, FIF.FOLDER_ADD, "整理",
                             position=NavigationItemPosition.TOP)
        self.addSubInterface(self.browser, FIF.PHOTO, "浏览器",
                             position=NavigationItemPosition.TOP)

        # Nav — BOTTOM
        self.addSubInterface(self.settings_view, FIF.SETTING, "设置",
                             position=NavigationItemPosition.BOTTOM)

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

    # ---------- Navigation ----------

    def switchTo(self, interface):
        if interface is self.home:
            self.home.refresh()
        super().switchTo(interface)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        try:
            panel = self.navigationInterface.panel
            if self.width() < self._nav_collapse_threshold and not panel.isCollapsed():
                panel.collapse()
            elif self.width() >= self._nav_collapse_threshold and panel.isCollapsed():
                panel.expand(useAni=False)
        except Exception:
            # qfluentwidgets internal layout — best-effort tweak.
            logger.debug("nav resize patch failed", exc_info=True)

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
