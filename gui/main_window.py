"""Main window — n8n-style scheme management.

- Home page = scheme manager (list/create/delete/open)
- Editor page = canvas (persists until different scheme opened)
- Tools work from any page: auto-create scheme if needed
- Scheme is a persistent document, not transient state
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

        # Scheme state
        self._scheme_path: Path | None = None  # None = unsaved new scheme
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
        from gui.views.pipeline_view import PipelineView
        from gui.views.scheme_welcome import SchemeWelcome

        self.home = SchemeWelcome()
        self.home.new_scheme.connect(self._new_scheme)
        self.home.open_scheme.connect(self._open_scheme)
        self.home.use_template.connect(self._use_template)

        self.editor = PipelineView()
        self.editor.save_requested.connect(self._save_scheme)

        self.settings_view = SettingsView()
        self.settings_view.theme_changed.connect(self._on_theme_changed)

        # Nav
        self.addSubInterface(self.home, FIF.HOME_FILL, "首页",
                             position=NavigationItemPosition.TOP)
        self.addSubInterface(self.editor, FIF.DEVELOPER_TOOLS, "工作台",
                             position=NavigationItemPosition.TOP)

        # Tools
        self.navigationInterface.addItem(
            routeKey="toolsGroup", icon=FIF.ALBUM, text="工具",
            onClick=lambda: None, selectable=False, tooltip="拖拽或点击添加到画布",
        )
        _icons = {
            "data_source": FIF.FOLDER, "quality_check": FIF.CERTIFICATE,
            "augment": FIF.ADD, "split": FIF.TILES, "export": FIF.SHARE,
        }
        from core.nodes import NODES
        from gui.widgets.toolbox_panel import NodeDragFilter
        self._drag_filters: list = []
        for name, node in NODES.items():
            w = self.navigationInterface.addItem(
                routeKey=f"tool_{name}", icon=_icons.get(name, FIF.TAG),
                text=node.display_name,
                onClick=lambda checked=False, n=name, dn=node.display_name: self._tool_click(n, dn),
                selectable=False, tooltip=node.description, parentRouteKey="toolsGroup",
            )
            if hasattr(w, "itemWidget"):
                filt = NodeDragFilter(name, node.display_name, node.step_type, w.itemWidget)
                w.itemWidget.installEventFilter(filt)
                self._drag_filters.append(filt)

        self.addSubInterface(self.settings_view, FIF.SETTING, "设置",
                             position=NavigationItemPosition.BOTTOM)

    # ---------- Scheme operations ----------

    def _new_scheme(self) -> None:
        """Create a blank scheme and enter editor."""
        self._enter_editor("未命名方案", clear=True)

    def _open_scheme(self, path_str: str) -> None:
        """Open a saved scheme."""
        from core.scheme import load_scheme
        scheme = load_scheme(Path(path_str))
        if not scheme:
            return
        self._enter_editor(scheme.name, clear=True)
        self.editor._canvas.load_scheme(scheme)
        self._scheme_path = Path(path_str)

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

    # ---------- Tool click ----------

    def _tool_click(self, node_name: str, display_name: str) -> None:
        """Click tool in sidebar. Auto-create scheme if none active."""
        if not self._scheme_active:
            self._enter_editor("未命名方案", clear=True)
        else:
            self.switchTo(self.editor)
        self.editor._add_node(node_name, display_name)

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
        if self._scheme_active and self.editor._canvas.get_nodes():
            from qfluentwidgets import MessageBox
            box = MessageBox("保存方案？", "退出前是否保存当前方案？", self)
            box.yesButton.setText("保存并退出")
            box.cancelButton.setText("直接退出")
            if box.exec():
                self._save_scheme()
        super().closeEvent(e)
