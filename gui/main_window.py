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

        # 启动 = 空白画布
        self.switchTo(self.pipeline_view)

    # ---------- 构建 ----------

    def _build_views(self) -> None:
        from gui.views.pipeline_view import PipelineView
        self.pipeline_view = PipelineView()

        self.settings_view = SettingsView()
        self.settings_view.theme_changed.connect(self._on_theme_changed)

        # ---- 分组导航 ----
        # 1) 🔧 工作台（节点画布 — 主视图）
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
            "dedup": FIF.COPY,
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

        # 方案名称（标题栏显示）
        self._task_name = BodyLabel("未命名方案")
        self._task_name.setObjectName("taskNameLabel")

        try:
            self.navigationInterface.panel.returnButton.hide()
        except Exception:  # noqa: BLE001
            pass

        bar_layout = self.titleBar.hBoxLayout
        bar_layout.insertSpacing(2, 12)
        bar_layout.insertWidget(3, self._task_name, 0, Qt.AlignmentFlag.AlignVCenter)
        bar_layout.insertSpacerItem(
            4, QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
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
