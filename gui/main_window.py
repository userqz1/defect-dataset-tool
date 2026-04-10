"""Main application window — scheme-centric workflow.

Scheme persists across navigation. Going to 首页 does NOT close the scheme.
Only explicit "关闭方案" action closes it.
Scheme name lives in the canvas top bar, not the title bar.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QWidget
from qfluentwidgets import (
    BodyLabel,
    FluentIcon as FIF,
    FluentWindow,
    InfoBar,
    InfoBarPosition,
    NavigationItemPosition,
    setTheme,
    setThemeColor,
    Theme,
)

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

        self._scheme_active = False
        self._scheme_dirty = False
        self._current_scheme_path = None
        self._nav_collapse_threshold = 1100

        try:
            self.navigationInterface.panel.returnButton.hide()
        except Exception:
            pass

        self._build_views()
        self.switchTo(self.welcome)

    # ---------- Build ----------

    def _build_views(self) -> None:
        from gui.views.pipeline_view import PipelineView
        from gui.views.scheme_welcome import SchemeWelcome

        self.welcome = SchemeWelcome()
        self.welcome.new_scheme.connect(self._on_new_scheme)
        self.welcome.open_scheme.connect(self._on_open_scheme)
        self.welcome.use_template.connect(self._on_use_template)

        self.pipeline_view = PipelineView()

        self.settings_view = SettingsView()
        self.settings_view.theme_changed.connect(self._on_theme_changed)

        # Navigation
        self.addSubInterface(self.welcome, FIF.HOME_FILL, "首页",
                             position=NavigationItemPosition.TOP)
        self.addSubInterface(self.pipeline_view, FIF.DEVELOPER_TOOLS, "工作台",
                             position=NavigationItemPosition.TOP)

        # Tools
        self.navigationInterface.addItem(
            routeKey="toolsGroup", icon=FIF.ALBUM, text="工具",
            onClick=lambda: None, selectable=False, tooltip="拖拽到画布或点击添加",
        )
        _icons = {
            "data_source": FIF.FOLDER, "quality_check": FIF.CERTIFICATE,
            "augment": FIF.ADD, "split": FIF.TILES, "export": FIF.SHARE,
        }
        from core.nodes import NODES
        from gui.widgets.toolbox_panel import NodeDragFilter
        self._drag_filters: list[NodeDragFilter] = []
        for name, node in NODES.items():
            w = self.navigationInterface.addItem(
                routeKey=f"tool_{name}", icon=_icons.get(name, FIF.TAG),
                text=node.display_name,
                onClick=lambda checked=False, n=name, dn=node.display_name: self._add_tool_node(n, dn),
                selectable=False, tooltip=node.description, parentRouteKey="toolsGroup",
            )
            if hasattr(w, "itemWidget"):
                filt = NodeDragFilter(name, node.display_name, node.step_type, w.itemWidget)
                w.itemWidget.installEventFilter(filt)
                self._drag_filters.append(filt)

        self.addSubInterface(self.settings_view, FIF.SETTING, "设置",
                             position=NavigationItemPosition.BOTTOM)

    # ---------- Scheme lifecycle ----------

    def _enter_scheme(self, name: str) -> None:
        """Activate a scheme and go to canvas."""
        self._scheme_active = True
        self._scheme_dirty = False
        self.pipeline_view.set_scheme_name(name)
        self.switchTo(self.pipeline_view)

    def _on_new_scheme(self) -> None:
        if not self._confirm_discard():
            return
        self.pipeline_view._canvas.clear_all()
        self._current_scheme_path = None
        self.pipeline_view.clear_workspaces()
        self._enter_scheme("未命名方案")

    def _on_open_scheme(self, path_str: str) -> None:
        if not self._confirm_discard():
            return
        from pathlib import Path
        from core.scheme import load_scheme
        scheme = load_scheme(Path(path_str))
        if not scheme:
            return
        self.pipeline_view._canvas.clear_all()
        self.pipeline_view._canvas.load_scheme(scheme)
        self.pipeline_view.clear_workspaces()
        self._current_scheme_path = Path(path_str)
        self._enter_scheme(scheme.name)

    def _on_use_template(self, idx: int) -> None:
        if not self._confirm_discard():
            return
        from core.scheme import TEMPLATES
        if idx >= len(TEMPLATES):
            return
        tpl = TEMPLATES[idx]
        self.pipeline_view._canvas.clear_all()
        self.pipeline_view._canvas.load_scheme(tpl)
        self.pipeline_view.clear_workspaces()
        self._current_scheme_path = None
        self._enter_scheme(tpl.name)

    def _save_scheme(self) -> None:
        if not self._scheme_active:
            return
        from core.scheme import save_scheme
        name = self.pipeline_view.get_scheme_name() or "未命名方案"
        scheme = self.pipeline_view._canvas.to_scheme(name)
        path = save_scheme(scheme, self._current_scheme_path)
        self._current_scheme_path = path
        self._scheme_dirty = False
        InfoBar.success("已保存", path.name, parent=self,
                        duration=2000, position=InfoBarPosition.TOP)

    def _confirm_discard(self) -> bool:
        """Ask to save if dirty. Returns True = proceed, False = cancel."""
        if not self._scheme_active or not self._scheme_dirty:
            return True
        if not self.pipeline_view._canvas.get_nodes():
            return True
        from qfluentwidgets import MessageBox
        box = MessageBox("保存方案？", "当前方案有未保存的修改。", self)
        box.yesButton.setText("保存")
        box.cancelButton.setText("不保存")
        if box.exec():
            self._save_scheme()
        return True

    # ---------- Tool click ----------

    def _add_tool_node(self, node_name: str, display_name: str) -> None:
        if not self._scheme_active:
            InfoBar.info("", "请先创建或打开一个方案", parent=self,
                         duration=2000, position=InfoBarPosition.TOP)
            return
        self.switchTo(self.pipeline_view)
        self.pipeline_view._add_node(node_name, display_name)
        self._scheme_dirty = True

    # ---------- Responsive sidebar ----------

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

    # ---------- Close ----------

    def closeEvent(self, e):
        if self._scheme_active and self._scheme_dirty and self.pipeline_view._canvas.get_nodes():
            from qfluentwidgets import MessageBox
            box = MessageBox("保存方案？", "退出前是否保存？", self)
            box.yesButton.setText("保存并退出")
            box.cancelButton.setText("直接退出")
            if box.exec():
                self._save_scheme()
        super().closeEvent(e)
