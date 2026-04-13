"""Main window — dataset-browser-first layout.

Navigation:
  TOP    — 首页 (DatasetWelcome)  |  浏览器 (DatasetBrowserView)
  BOTTOM — 管线编辑器 (PipelineView)  |  设置 (SettingsView)

AppState owns the shared Dataset/Project. All views react to its signals.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QWidget
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

        # Scheme state (kept for pipeline compat)
        self._scheme_path: Path | None = None
        self._scheme_active = False
        self._nav_collapse_threshold = 1100

        try:
            self.navigationInterface.panel.returnButton.hide()
        except Exception:
            pass

        self._build_views()

        # Start on home
        self.switchTo(self.home)

    # ---------- Build ----------

    def _build_views(self) -> None:
        from gui.views.dataset_browser_view import DatasetBrowserView
        from gui.views.dataset_welcome import DatasetWelcome
        from gui.views.pipeline_view import PipelineView

        # Home — dataset list
        self.home = DatasetWelcome()
        self.home.open_dataset.connect(self._open_dataset)
        self.home.open_pipeline_template.connect(self._use_template)

        # Browser — top-level dataset browser
        self.browser = DatasetBrowserView(self._state)

        # Pipeline editor
        self.editor = PipelineView()
        self.editor.save_requested.connect(self._save_scheme)

        # Settings
        self.settings_view = SettingsView()
        self.settings_view.theme_changed.connect(self._on_theme_changed)

        # Wire AppState → PipelineView
        self._state.dataset_changed.connect(self._on_dataset_to_pipeline)

        # Nav — TOP
        self.addSubInterface(self.home, FIF.HOME_FILL, "首页",
                             position=NavigationItemPosition.TOP)
        self.addSubInterface(self.browser, FIF.PHOTO, "浏览器",
                             position=NavigationItemPosition.TOP)

        # Nav — BOTTOM
        self.addSubInterface(self.editor, FIF.DEVELOPER_TOOLS, "管线编辑器",
                             position=NavigationItemPosition.BOTTOM)
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

    def _on_dataset_to_pipeline(self, ds) -> None:
        """Push dataset to pipeline workspaces when available."""
        if ds is None:
            return
        self.editor._dataset = ds
        for name_key, (wrapper, _) in self.editor._workspaces.items():
            if name_key != "data_source":
                for child in wrapper.findChildren(QWidget):
                    if hasattr(child, "set_dataset"):
                        child.set_dataset(ds)

    # ---------- Scheme / pipeline operations ----------

    def _new_scheme(self) -> None:
        """Create a blank scheme and enter editor."""
        self._enter_editor("未命名方案", clear=True)

    def _use_template(self, idx: int) -> None:
        """Create scheme from template."""
        from core.scheme import TEMPLATES
        if idx >= len(TEMPLATES):
            return
        tpl = TEMPLATES[idx]
        self._enter_editor(tpl.name, clear=True)
        self.editor._canvas.load_scheme(tpl)

    def _enter_editor(self, name: str, clear: bool = False) -> None:
        """Switch to editor with a named scheme."""
        if clear:
            self.editor._canvas.clear_all()
            self.editor.clear_workspaces()
            self._scheme_path = None
        self._scheme_active = True
        self.editor.set_scheme_name(name)
        self.switchTo(self.editor)

    def _save_scheme(self) -> None:
        """Save current scheme to disk."""
        if not self._scheme_active:
            return
        from core.scheme import save_scheme
        name = self.editor.get_scheme_name() or "未命名方案"
        scheme = self.editor._canvas.to_scheme(name)
        self._scheme_path = save_scheme(scheme, self._scheme_path)
        InfoBar.success("已保存", self._scheme_path.name, parent=self,
                        duration=2000, position=InfoBarPosition.TOP)

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
            pass

    def _on_theme_changed(self, name: str) -> None:
        set_app_theme(name, window=self)
        setTheme(Theme.DARK if name == "dark" else Theme.LIGHT)
        setThemeColor(QColor(T.ACCENT))
        from core.user_settings import save_settings, UserSettings
        save_settings(UserSettings(theme=name))

    def closeEvent(self, e):
        # Save project state
        self._state.close_dataset()
        # Cleanup browser workers
        self.browser.cleanup()
        # Save scheme if active
        if self._scheme_active and self.editor._canvas.get_nodes():
            from qfluentwidgets import MessageBox
            box = MessageBox("保存方案？", "退出前是否保存当前方案？", self)
            box.yesButton.setText("保存并退出")
            box.cancelButton.setText("直接退出")
            if box.exec():
                self._save_scheme()
        super().closeEvent(e)
