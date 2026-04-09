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
from gui.views.detail_view import DetailView
from gui.views.overview_view import OverviewView
from gui.views.dedup_view import DedupView
from gui.views.export_view import ExportView
from gui.views.placeholder_view import PlaceholderView
from gui.views.predict_view import PredictView
from gui.views.quality_view import QualityView
from gui.views.settings_view import SettingsView
from gui.views.split_view import SplitView
from gui.views.transform_view import TransformView
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

        self.setWindowTitle("数据坊")
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

        self.quality_view = QualityView()
        self.dedup_view = DedupView()
        self.transform_view = TransformView()
        self.augment_view = AugmentView()
        self.predict_view = PredictView()
        self.split_view = SplitView()
        self.browser.add_to_split.connect(self._on_add_to_split)
        self.transform_view.set_selection_provider(self.browser.get_selected_images)
        self.augment_view.set_selection_provider(self.browser.get_selected_images)
        self.export_view = ExportView()
        self.settings_view = SettingsView()
        self.settings_view.open_recent.connect(lambda p: self._open_project(Path(p)))
        self.settings_view.theme_changed.connect(self._on_theme_changed)

        # ---- 分组导航 ----
        # 0) 欢迎页（首页入口）
        self.addSubInterface(
            self.welcome_view, FIF.HOME_FILL, "首页",
            position=NavigationItemPosition.TOP,
        )

        # 1) 📂 数据集
        self.navigationInterface.addItem(
            routeKey="datasetGroup",
            icon=FIF.FOLDER,
            text="数据集",
            onClick=lambda: None,
            selectable=False,
            tooltip="数据集",
        )
        self.navigationInterface.addItem(
            routeKey="openDatasetItem",
            icon=FIF.FOLDER_ADD,
            text="打开…",
            onClick=self._on_open_clicked,
            selectable=False,
            tooltip="打开数据集",
            parentRouteKey="datasetGroup",
        )
        self.addSubInterface(
            self.overview, FIF.HOME, "概览", parent="datasetGroup"
        )
        self.addSubInterface(
            self.browser_stack, FIF.PHOTO, "浏览", parent="datasetGroup"
        )

        # 2) 🔧 数据处理
        self.navigationInterface.addItem(
            routeKey="processGroup",
            icon=FIF.DEVELOPER_TOOLS,
            text="数据处理",
            onClick=lambda: None,
            selectable=False,
            tooltip="数据处理",
        )
        self.addSubInterface(
            self.quality_view, FIF.CERTIFICATE, "质量检查", parent="processGroup"
        )
        self.addSubInterface(
            self.dedup_view, FIF.COPY, "重复检测", parent="processGroup"
        )
        self.addSubInterface(
            self.predict_view, FIF.ROBOT, "AI 预标注", parent="processGroup"
        )
        self.addSubInterface(
            self.transform_view, FIF.BRUSH, "批量变换", parent="processGroup"
        )
        self.addSubInterface(
            self.augment_view, FIF.ALBUM, "数据增强", parent="processGroup"
        )
        self.addSubInterface(
            self.split_view, FIF.TILES, "数据集划分", parent="processGroup"
        )

        # 3) 📤 导出
        self.navigationInterface.addItem(
            routeKey="exportGroup",
            icon=FIF.SHARE,
            text="导出",
            onClick=lambda: None,
            selectable=False,
            tooltip="导出",
        )
        self.addSubInterface(
            self.export_view, FIF.SEND, "导出向导", parent="exportGroup"
        )

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
        # Save current project first
        self._save_current_project()

        project = load_project(root)
        if project is None:
            project = create_project(root)
        self._project = project
        self._start_scan(root)

    def _close_project(self) -> None:
        """Save state and return to welcome page."""
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
        from gui.dialogs.op_dialogs import ProgressDialog
        self._scan_progress = ProgressDialog("扫描数据集", parent=self)
        self._scan_progress.label.setText(str(root))

        self._scan_worker = ScanWorker(root, parent=self)
        self._scan_worker.progress.connect(self._on_scan_progress)
        self._scan_worker.phase.connect(self._on_scan_phase)
        self._scan_worker.finished_ok.connect(self._on_scan_done)
        self._scan_worker.failed.connect(self._on_scan_failed)
        self._scan_worker.start()
        self._scan_progress.show()

    def _on_scan_phase(self, phase: str) -> None:
        if self._scan_progress is None:
            return
        if phase == "scan":
            self._scan_progress.titleLabel.setText("扫描数据集 · 索引文件")
        elif phase == "annotate":
            self._scan_progress.titleLabel.setText("扫描数据集 · 解析标注")

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

    def _on_scan_done(self, dataset) -> None:
        # 扫描弹窗还在显示 → 在弹窗背后把所有视图初始化完毕
        # 这样关闭弹窗后用户立刻看到就绪的工作区
        if self._scan_progress:
            self._scan_progress.titleLabel.setText("正在准备工作区…")

        self._dataset_root = dataset.root_path
        add_recent(dataset.root_path)

        # 初始化所有视图（弹窗挡住，用户看不到中间状态）
        self.overview.set_dataset(dataset)
        self.browser.load_dataset(dataset)
        self.settings_view.refresh()
        for v in (
            self.quality_view,
            self.dedup_view,
            self.transform_view,
            self.augment_view,
            self.predict_view,
            self.split_view,
            self.export_view,
        ):
            v.set_dataset(dataset)

        # 恢复项目状态
        if self._project:
            self.browser.restore_state(self._project.browse_state)
            self.export_view.restore_state(self._project.export_config)
            self.split_view.restore_state(self._project.split_state)

        # 一切就绪，关闭弹窗 → 用户直接看到完整的工作区
        self._close_scan_progress()

        proj_name = self._project.name if self._project else dataset.name
        self.dataset_chip.set_project(proj_name, dataset.root_path)
        self.close_project_btn.show()
        self.switchTo(self.overview)

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
        self._save_current_project()
        try:
            self._thumb_worker.stop()
        except Exception:
            pass
        super().closeEvent(e)
