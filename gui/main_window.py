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

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QFileDialog, QStackedWidget, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    FluentIcon as FIF,
    FluentWindow,
    InfoBar,
    InfoBarPosition,
    NavigationItemPosition,
    TransparentToolButton,
    setTheme,
    setThemeColor,
    Theme,
)

from core.models import Dataset
from core.project import Project, create_project, load_project, save_project
from core.recent import add_recent
from gui.theme import T, load_qss, set_theme as set_app_theme
from gui.views.augment_view import AugmentView
from gui.views.browser_view import BrowserView
from gui.views.cleaning_view import CleaningView
from gui.views.detail_view import DetailView
from gui.views.overview_view import OverviewView
from gui.views.export_view import ExportView
from gui.views.placeholder_view import PlaceholderView
from gui.views.predict_view import PredictView
from gui.views.settings_view import SettingsView
from gui.views.split_view import SplitView
from gui.views.standards_view import StandardsView
from gui.views.welcome_view import WelcomeView
from gui.workers.scan_worker import ScanWorker
from gui.workers.thumbnail_worker import ThumbnailWorker


class _DatasetChip(QWidget):
    """标题栏里显示项目名（短），hover 显示完整路径。固定最大宽度防止拉伸。"""

    MAX_NAME_LEN = 20

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("datasetChip")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMaximumWidth(300)
        from PyQt6.QtWidgets import QHBoxLayout
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(0)
        self.hide()
        self.name_label = BodyLabel("")
        self.name_label.setObjectName("datasetChipName")
        layout.addWidget(self.name_label)

    def set_project(self, name: str, path: Path) -> None:
        display = name if len(name) <= self.MAX_NAME_LEN else name[:self.MAX_NAME_LEN - 1] + "…"
        self.name_label.setText(display)
        self.setToolTip(str(path))
        self.show()

    def clear(self) -> None:
        self.name_label.setText("")
        self.setToolTip("")
        self.hide()


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

        self._scan_worker: ScanWorker | None = None
        self._scan_progress = None
        self._dataset_root: Path | None = None
        self._project: Project | None = None

        # 导航历史
        self._nav_history: list[str] = []
        self._nav_cursor: int = -1
        self._nav_navigating: bool = False
        self._nav_collapse_threshold = 1100

        # 缩略图后台线程
        self._thumb_worker = ThumbnailWorker(size=170, parent=self)
        self._thumb_worker.start()

        self._build_titlebar()
        self._build_views()

        # 启动时显示欢迎页
        self.switchTo(self.welcome_view)

    # ---------- 构建 ----------

    def _build_views(self) -> None:
        # 欢迎页
        self.welcome_view = WelcomeView()
        self.welcome_view.open_project.connect(self._open_project)
        self.welcome_view.open_folder.connect(self._on_open_clicked)
        self.welcome_view.new_task.connect(self._on_new_task)

        # 核心视图
        self.overview = OverviewView()

        self.browser = BrowserView()
        self.detail = DetailView()
        self.browser.thumb_request.connect(self._thumb_worker.request)
        self.browser.clear_thumb_queue.connect(self._thumb_worker.clear_queue)
        self._thumb_worker.thumb_ready.connect(self.browser.on_thumb_ready)
        self.browser.image_activated.connect(self._on_image_activated)
        self.browser.dataset_changed.connect(self._on_dataset_changed)
        self.detail.back_requested.connect(self._on_detail_back)

        self.browser_stack = QStackedWidget()
        self.browser_stack.setObjectName("browserStack")
        self.browser_stack.addWidget(self.browser)
        self.browser_stack.addWidget(self.detail)

        from gui.views.pipeline_view import PipelineView
        self.pipeline_view = PipelineView()

        self.cleaning_view = CleaningView()
        self.augment_view = AugmentView()
        self.predict_view = PredictView()
        self.split_view = SplitView()
        self.browser.add_to_split.connect(self._on_add_to_split)
        self.split_view.go_export.connect(lambda: self.switchTo(self.export_view))
        self.augment_view.set_selection_provider(self.browser.get_selected_images)
        self.export_view = ExportView()
        self.standards_view = StandardsView()
        self.settings_view = SettingsView()
        self.settings_view.open_recent.connect(lambda p: self._open_project(Path(p)))
        self.settings_view.theme_changed.connect(self._on_theme_changed)

        # ---- 分组导航 ----
        # 0) 欢迎页（首页入口）
        self.addSubInterface(
            self.welcome_view, FIF.HOME_FILL, "首页",
            position=NavigationItemPosition.TOP,
        )

        # 1) 浏览
        self.addSubInterface(self.browser_stack, FIF.PHOTO, "浏览")

        # 2) 工作台（节点画布）
        self.addSubInterface(self.pipeline_view, FIF.DEVELOPER_TOOLS, "工作台")

        # 3) 节点工具箱 — 点击添加到画布
        self.navigationInterface.addSeparator()

        _TOOL_ICONS = {
            "data_source": FIF.FOLDER,
            "quality_check": FIF.CERTIFICATE,
            "dedup": FIF.COPY,
            "augment": FIF.ADD,
            "split": FIF.TILES,
            "export": FIF.SEND,
        }
        from core.nodes import NODE_REGISTRY
        import functools
        for nid, spec in NODE_REGISTRY.items():
            icon = _TOOL_ICONS.get(nid, FIF.TAG)
            self.navigationInterface.addItem(
                routeKey=f"tool_{nid}",
                icon=icon,
                text=spec.label,
                onClick=functools.partial(self._add_tool_node, nid),
                selectable=False,
                tooltip=spec.label,
            )

        self.navigationInterface.addSeparator()

        # 4) ⚙ 设置
        self.addSubInterface(
            self.settings_view,
            FIF.SETTING,
            "设置",
            position=NavigationItemPosition.BOTTOM,
        )

    def _build_titlebar(self) -> None:
        from PyQt6.QtWidgets import QSpacerItem, QSizePolicy

        self.dataset_chip = _DatasetChip()

        # 导航 ← →
        self.back_btn = TransparentToolButton(FIF.LEFT_ARROW)
        self.back_btn.setToolTip("后退")
        self.back_btn.setFixedSize(34, 30)
        self.back_btn.clicked.connect(self._nav_go_back)
        self.fwd_btn = TransparentToolButton(FIF.RIGHT_ARROW)
        self.fwd_btn.setToolTip("前进")
        self.fwd_btn.setFixedSize(34, 30)
        self.fwd_btn.clicked.connect(self._nav_go_forward)
        self.back_btn.setEnabled(False)
        self.fwd_btn.setEnabled(False)

        # 关闭项目按钮（带文字更醒目）
        from qfluentwidgets import HyperlinkButton
        self.close_project_btn = HyperlinkButton("", "关闭项目")
        self.close_project_btn.setFixedHeight(30)
        self.close_project_btn.clicked.connect(self._close_project)
        self.close_project_btn.hide()

        try:
            self.navigationInterface.panel.returnButton.hide()
        except Exception:  # noqa: BLE001
            pass

        bar_layout = self.titleBar.hBoxLayout
        bar_layout.insertWidget(2, self.back_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        bar_layout.insertWidget(3, self.fwd_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        bar_layout.insertSpacing(4, 12)
        bar_layout.insertWidget(5, self.dataset_chip, 0, Qt.AlignmentFlag.AlignVCenter)
        bar_layout.insertWidget(6, self.close_project_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        bar_layout.insertSpacerItem(
            7, QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        )

    # ---------- 项目生命周期 ----------

    def _open_project(self, root: Path) -> None:
        """Open or create a project, then scan."""
        if self._scan_worker and self._scan_worker.isRunning():
            return
        # Save current project first
        self._save_current_project()

        project = load_project(root)
        if project is None:
            project = create_project(root)
        self._project = project

        # 立刻显示进度弹窗，用户第一时间看到反馈
        from gui.dialogs.op_dialogs import ProgressDialog
        self._scan_progress = ProgressDialog("打开项目", parent=self)
        self._scan_progress.label.setText(str(root))
        self._scan_progress.show()

        self._start_scan(root)

    def _close_project(self) -> None:
        """Save state and return to welcome page."""
        # 检查 detail view 是否有未保存修改
        if hasattr(self, 'detail') and getattr(self.detail, '_dirty', False):
            from qfluentwidgets import MessageBox
            box = MessageBox(
                "未保存的修改",
                "当前图片有未保存的标注修改，关闭项目将丢失这些修改。确定关闭？",
                self,
            )
            box.yesButton.setText("关闭项目")
            box.cancelButton.setText("返回编辑")
            if not box.exec():
                return
        self._save_current_project()
        self._project = None
        self._dataset_root = None
        self.dataset_chip.clear()
        self.close_project_btn.hide()
        self.welcome_view.refresh()
        self.switchTo(self.welcome_view)

    def _save_current_project(self) -> None:
        """Collect state from all views and persist."""
        if self._project is None:
            return
        # Collect browse state
        self._project.browse_state = self.browser.save_state()
        # Collect export config
        self._project.export_config = self.export_view.save_state()
        # Collect split state
        self._project.split_state = self.split_view.save_state()
        # Collect data standard
        self._project.data_standard = self.standards_view.get_standard().to_dict()
        save_project(self._project)

    # ---------- 导航历史 ----------

    def switchTo(self, interface):  # type: ignore[override]
        super().switchTo(interface)
        if self._nav_navigating:
            return
        key = interface.objectName()
        if not key:
            return
        if self._nav_cursor < len(self._nav_history) - 1:
            self._nav_history = self._nav_history[: self._nav_cursor + 1]
        if not self._nav_history or self._nav_history[-1] != key:
            self._nav_history.append(key)
            self._nav_cursor = len(self._nav_history) - 1
        self._update_nav_buttons()

    def _switch_to_key(self, key: str) -> None:
        for i in range(self.stackedWidget.count()):
            w = self.stackedWidget.widget(i)
            if w.objectName() == key:
                self._nav_navigating = True
                try:
                    super().switchTo(w)
                    self.navigationInterface.setCurrentItem(key)
                finally:
                    self._nav_navigating = False
                return

    def _nav_go_back(self) -> None:
        if self._nav_cursor <= 0:
            return
        self._nav_cursor -= 1
        self._switch_to_key(self._nav_history[self._nav_cursor])
        self._update_nav_buttons()

    def _nav_go_forward(self) -> None:
        if self._nav_cursor >= len(self._nav_history) - 1:
            return
        self._nav_cursor += 1
        self._switch_to_key(self._nav_history[self._nav_cursor])
        self._update_nav_buttons()

    def _update_nav_buttons(self) -> None:
        self.back_btn.setEnabled(self._nav_cursor > 0)
        self.fwd_btn.setEnabled(self._nav_cursor < len(self._nav_history) - 1)

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

    # ---------- 浏览/详情切换 ----------

    def _on_image_activated(self, image, image_list) -> None:
        self.detail.show_image(image, image_list)
        self.browser_stack.setCurrentWidget(self.detail)
        self.detail.setFocus()

    def _on_detail_back(self) -> None:
        self.browser_stack.setCurrentWidget(self.browser)

    def _on_new_task(self) -> None:
        """Create a blank canvas — new task/方案."""
        self.pipeline_view.clear()
        self.switchTo(self.pipeline_view)

    def _add_tool_node(self, node_id: str) -> None:
        """Sidebar tool clicked → switch to workspace + add node."""
        self.switchTo(self.pipeline_view)
        self.pipeline_view.add_node(node_id)

    # ---------- 打开数据集 ----------

    def _on_open_clicked(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, "选择数据集根目录", str(Path.home())
        )
        if not directory:
            return
        self._open_project(Path(directory))

    def _start_scan(self, root: Path) -> None:
        if self._scan_worker and self._scan_worker.isRunning():
            return
        # 进度弹窗已在 _open_project 中创建并显示
        # 这里只需要确保存在（dataset_changed 重扫描时也需要）
        if self._scan_progress is None:
            from gui.dialogs.op_dialogs import ProgressDialog
            self._scan_progress = ProgressDialog("扫描数据集", parent=self)
            self._scan_progress.label.setText(str(root))
            self._scan_progress.show()

        self._scan_worker = ScanWorker(root, parent=self)
        self._scan_worker.progress.connect(self._on_scan_progress)
        self._scan_worker.phase.connect(self._on_scan_phase)
        self._scan_worker.finished_ok.connect(self._on_scan_done)
        self._scan_worker.failed.connect(self._on_scan_failed)
        self._scan_worker.start()

    def _on_scan_phase(self, phase: str) -> None:
        if self._scan_progress is None:
            return
        labels = {
            "scan": "扫描数据集 · 索引文件",
            "annotate": "扫描数据集 · 解析标注",
            "analyze": "扫描数据集 · 分析统计",
        }
        self._scan_progress.titleLabel.setText(labels.get(phase, phase))

    def _on_scan_progress(self, done: int, total: int, name: str) -> None:
        if self._scan_progress is None:
            return
        self._scan_progress.set_progress(done, total, name)

    def _close_scan_progress(self) -> None:
        if self._scan_progress is not None:
            self._scan_progress.accept()
            self._scan_progress = None

    def _on_theme_changed(self, name: str) -> None:
        set_app_theme(name, window=self)
        setTheme(Theme.DARK if name == "dark" else Theme.LIGHT)
        setThemeColor(QColor(T.ACCENT))
        from core.user_settings import save_settings, UserSettings
        save_settings(UserSettings(theme=name))

    def _on_dataset_changed(self) -> None:
        if self._dataset_root:
            self._start_scan(self._dataset_root)

    def _on_add_to_split(self, bucket: str, images) -> None:
        self.split_view.add_to_manual_bucket(bucket, images)
        self.switchTo(self.split_view)

    def _on_scan_done(self, result) -> None:
        # result 是 ScanResult — 所有耗时操作已在 Worker 线程完成
        from gui.workers.scan_worker import ScanResult
        if isinstance(result, ScanResult):
            dataset = result.dataset
            ext_stats = result.ext_stats
        else:
            dataset = result
            ext_stats = None

        self._dataset_root = dataset.root_path
        add_recent(dataset.root_path)

        # 设置视图（轻量赋值，不阻塞主线程）
        self.overview.set_dataset(dataset)
        if ext_stats:
            self.overview._on_extended_stats(ext_stats)
        self.browser.load_dataset(dataset)
        self.settings_view.refresh()
        for v in (
            self.cleaning_view,
            self.augment_view,
            self.predict_view,
            self.split_view,
            self.export_view,
            self.standards_view,
        ):
            v.set_dataset(dataset)

        # 恢复项目状态
        if self._project:
            self.browser.restore_state(self._project.browse_state)
            self.export_view.restore_state(self._project.export_config)
            self.split_view.restore_state(self._project.split_state)
            if self._project.data_standard:
                from core.standards import DataStandard
                self.standards_view.set_standard(
                    DataStandard.from_dict(self._project.data_standard)
                )

        # 一切就绪，关闭弹窗 → 用户直接看到完整的工作区
        self._close_scan_progress()

        proj_name = self._project.name if self._project else dataset.name
        self.dataset_chip.set_project(proj_name, dataset.root_path)
        self.close_project_btn.show()
        # 用户打开项目是为了操作图片 → 默认落在浏览页
        self.switchTo(self.browser_stack)

        InfoBar.success(
            title="项目已就绪",
            content=f"{dataset.total_images} 张图片 · {len(dataset.categories)} 类",
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=3000,
            parent=self,
        )

    def _on_scan_failed(self, msg: str) -> None:
        self._close_scan_progress()
        InfoBar.error(
            title="扫描失败",
            content=msg,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=5000,
            parent=self,
        )

    def closeEvent(self, e):  # type: ignore[override]
        # 检查未保存修改
        if hasattr(self, 'detail') and getattr(self.detail, '_dirty', False):
            from qfluentwidgets import MessageBox
            box = MessageBox(
                "未保存的修改",
                "当前图片有未保存的标注修改，退出将丢失。确定退出？",
                self,
            )
            box.yesButton.setText("退出")
            box.cancelButton.setText("取消")
            if not box.exec():
                e.ignore()
                return
        self._save_current_project()
        try:
            self._thumb_worker.stop()
        except Exception:
            pass
        super().closeEvent(e)
