"""Main application window.

Layout (VS Code-style)：
    ┌──────────────────────────────────────────────────────────┐
    │ icon  Title    [← →] [当前数据集 chip] [关闭项目]  _ □ × │  ← TitleBar
    ├──┬───────────────────────────────────────────────────────┤
    │🏠│                                                        │
    │🖼│                  主内容区 / 欢迎页                     │
    │  │                                                        │
    └──┴───────────────────────────────────────────────────────┘

设计要点：
    - 启动时显示欢迎页（项目列表），选择项目后进入工作区
    - 项目状态持久化到 .dataforge/project.json
    - "关闭项目"回到欢迎页（保存状态后）
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QWidget
from qfluentwidgets import (
    BodyLabel,
    FluentIcon as FIF,
    FluentWindow,
    NavigationItemPosition,
    setTheme,
    setThemeColor,
    Theme,
)

from gui.theme import T, load_qss, set_theme as set_app_theme
from gui.views.settings_view import SettingsView



def _install_nav_expand_patch() -> None:
    """类级别 monkey-patch：narrow 态点击任何 nav 项都展开侧栏，不弹 flyout。"""
    from qfluentwidgets.components.navigation.navigation_panel import (
        NavigationDisplayMode,
        NavigationPanel,
    )

    if getattr(NavigationPanel, "_dataforge_patched", False):
        return

    original = NavigationPanel._onWidgetClicked

    def patched(self):
        widget = self.sender()
        if widget is None:
            return
        is_narrow = (
            self.isCollapsed() or self.displayMode == NavigationDisplayMode.COMPACT
        )
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
        self._user_settings = load_settings()
        if self._user_settings.theme == "dark":
            set_app_theme("dark")
            setTheme(Theme.DARK)
        else:
            setTheme(Theme.LIGHT)
        setThemeColor(QColor(T.ACCENT))
        self.setStyleSheet(load_qss())

        self.setWindowTitle("数据工坊")
        self.resize(1280, 800)

        # 导航历史
        self._nav_history: list[str] = []
        self._nav_cursor: int = -1
        self._nav_navigating: bool = False
        self._nav_collapse_threshold = 1100

        self._build_titlebar()
        self._build_views()

        # 启动 = 欢迎页
        self._current_scheme_path = None
        self.switchTo(self.welcome)

    # ---------- 构建 ----------

    def _build_views(self) -> None:
        from gui.views.pipeline_view import PipelineView
        from gui.views.scheme_welcome import SchemeWelcome

        # Welcome page
        self.welcome = SchemeWelcome()
        self.welcome.new_scheme.connect(self._on_new_scheme)
        self.welcome.open_scheme.connect(self._on_open_scheme)
        self.welcome.use_template.connect(self._on_use_template)

        # Canvas
        self.pipeline_view = PipelineView()
        self.pipeline_view.canvas_save_requested = lambda: self._save_current_scheme()

        self.settings_view = SettingsView()
        self.settings_view.theme_changed.connect(self._on_theme_changed)

        # ---- 分组导航 ----
        # 0) 首页
        self.addSubInterface(
            self.welcome, FIF.HOME_FILL, "首页",
            position=NavigationItemPosition.TOP,
        )

        # 1) 工作台
        self.addSubInterface(
            self.pipeline_view, FIF.DEVELOPER_TOOLS, "工作台",
            position=NavigationItemPosition.TOP,
        )

        # 2) 🧰 工具（拖拽或点击添加节点到画布）
        self.navigationInterface.addItem(
            routeKey="toolsGroup",
            icon=FIF.ALBUM,
            text="工具",
            onClick=lambda: None,
            selectable=False,
            tooltip="拖拽工具到画布，或点击添加",
        )
        _tool_icons = {
            "data_source": FIF.FOLDER,
            "quality_check": FIF.CERTIFICATE,
            "augment": FIF.ADD,
            "split": FIF.TILES,
            "export": FIF.SHARE,
        }
        from core.nodes import NODES
        from gui.widgets.toolbox_panel import NodeDragFilter
        self._drag_filters: list[NodeDragFilter] = []  # prevent GC
        for name, node in NODES.items():
            icon = _tool_icons.get(name, FIF.TAG)
            w = self.navigationInterface.addItem(
                routeKey=f"tool_{name}",
                icon=icon,
                text=node.display_name,
                onClick=lambda checked=False, n=name, dn=node.display_name: self._add_tool_node(n, dn),
                selectable=False,
                tooltip=node.description,
                parentRouteKey="toolsGroup",
            )
            # Install drag filter on the inner button widget
            if hasattr(w, "itemWidget"):
                filt = NodeDragFilter(name, node.display_name, node.step_type, w.itemWidget)
                w.itemWidget.installEventFilter(filt)
                self._drag_filters.append(filt)

        # 4) ⚙ 设置
        self.addSubInterface(
            self.settings_view,
            FIF.SETTING,
            "设置",
            position=NavigationItemPosition.BOTTOM,
        )

    def _build_titlebar(self) -> None:
        from PyQt6.QtWidgets import QSpacerItem, QSizePolicy

        from qfluentwidgets import TransparentToolButton

        self._task_name = BodyLabel("未命名方案")
        self._task_name.setObjectName("taskNameLabel")

        self._save_btn = TransparentToolButton(FIF.SAVE)
        self._save_btn.setFixedSize(32, 30)
        self._save_btn.setToolTip("保存方案")
        self._save_btn.clicked.connect(self._save_current_scheme)

        try:
            self.navigationInterface.panel.returnButton.hide()
        except Exception:  # noqa: BLE001
            pass

        bar_layout = self.titleBar.hBoxLayout
        bar_layout.insertSpacing(2, 12)
        bar_layout.insertWidget(3, self._task_name, 0, Qt.AlignmentFlag.AlignVCenter)
        bar_layout.insertWidget(4, self._save_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        bar_layout.insertSpacerItem(
            5, QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        )

    # ---------- 响应式侧栏 ----------

    def resizeEvent(self, e):  # type: ignore[override]
        super().resizeEvent(e)
        try:
            panel = self.navigationInterface.panel
            should_collapse = self.width() < self._nav_collapse_threshold
            if should_collapse and not panel.isCollapsed():
                panel.collapse()
            elif not should_collapse and panel.isCollapsed():
                panel.expand(useAni=False)
        except Exception:  # noqa: BLE001
            pass

    # ---------- 方案管理 ----------

    def _on_new_scheme(self) -> None:
        self.pipeline_view._canvas.clear_all()
        self._current_scheme_path = None
        self._task_name.setText("未命名方案")
        self.switchTo(self.pipeline_view)

    def _on_open_scheme(self, path_str: str) -> None:
        from pathlib import Path
        from core.scheme import load_scheme
        scheme = load_scheme(Path(path_str))
        if not scheme:
            return
        self.pipeline_view._canvas.clear_all()
        self.pipeline_view._canvas.load_scheme(scheme)
        self._current_scheme_path = Path(path_str)
        self._task_name.setText(scheme.name)
        self.switchTo(self.pipeline_view)

    def _on_use_template(self, idx: int) -> None:
        from core.scheme import TEMPLATES
        if idx >= len(TEMPLATES):
            return
        tpl = TEMPLATES[idx]
        self.pipeline_view._canvas.clear_all()
        self.pipeline_view._canvas.load_scheme(tpl)
        self._current_scheme_path = None
        self._task_name.setText(tpl.name)
        self.switchTo(self.pipeline_view)

    def _save_current_scheme(self) -> None:
        from core.scheme import save_scheme
        name = self._task_name.text() or "未命名方案"
        scheme = self.pipeline_view._canvas.to_scheme(name)
        path = save_scheme(scheme, self._current_scheme_path)
        self._current_scheme_path = path
        from qfluentwidgets import InfoBar, InfoBarPosition
        InfoBar.success("已保存", str(path.name), parent=self,
                        duration=2000, position=InfoBarPosition.TOP)

    # ---------- 工具操作 ----------

    def _add_tool_node(self, node_name: str, display_name: str) -> None:
        """Sidebar tool clicked → add node to canvas."""
        self.switchTo(self.pipeline_view)
        self.pipeline_view._add_node(node_name, display_name)

    def _on_theme_changed(self, name: str) -> None:
        set_app_theme(name, window=self)
        setTheme(Theme.DARK if name == "dark" else Theme.LIGHT)
        setThemeColor(QColor(T.ACCENT))
        from core.user_settings import save_settings, UserSettings
        save_settings(UserSettings(theme=name))
