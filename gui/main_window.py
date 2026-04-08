"""Main application window."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QFileDialog, QLabel, QStackedWidget, QVBoxLayout, QWidget
from qfluentwidgets import (
    FluentIcon as FIF,
    FluentWindow,
    InfoBar,
    InfoBarPosition,
    NavigationItemPosition,
    PrimaryPushButton,
    setTheme,
    setThemeColor,
    Theme,
)

from gui.views.browser_view import BrowserView
from gui.views.detail_view import DetailView
from gui.views.overview_view import OverviewView
from gui.workers.scan_worker import ScanWorker
from gui.workers.thumbnail_worker import ThumbnailWorker

# Claude 桌面调色板
SIDEBAR = "#f5f4ef"  # 侧栏 / 标题栏：暖米色
CONTENT = "#ffffff"  # 主内容区：白
TEXT = "#2d2a26"
TEXT_2 = "#6b6760"
ACCENT = "#c96442"


class PlaceholderView(QWidget):
    def __init__(self, title: str, subtitle: str, object_name: str) -> None:
        super().__init__()
        self.setObjectName(object_name)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"QWidget#{object_name} {{ background-color: {CONTENT}; }}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title_label = QLabel(title)
        title_label.setStyleSheet(
            f"font-size: 28px; font-weight: 600; color: {TEXT}; letter-spacing: -0.5px;"
        )
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        sub_label = QLabel(subtitle)
        sub_label.setStyleSheet(f"font-size: 13px; color: {TEXT_2}; margin-top: 8px;")
        sub_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(title_label)
        layout.addWidget(sub_label)


class MainWindow(FluentWindow):
    def __init__(self) -> None:
        super().__init__()

        setTheme(Theme.LIGHT)
        setThemeColor(QColor(ACCENT))

        self.setWindowTitle("故障数据集管理工具")
        self.resize(1280, 800)

        self._scan_worker: ScanWorker | None = None

        # 缩略图后台线程，全局一个
        self._thumb_worker = ThumbnailWorker(size=170, parent=self)
        self._thumb_worker.start()

        self.overview = OverviewView()

        # 浏览 + 详情共用一个 stack，作为单个导航项
        self.browser = BrowserView()
        self.detail = DetailView()
        self.browser.thumb_request.connect(self._thumb_worker.request)
        self._thumb_worker.thumb_ready.connect(self.browser.on_thumb_ready)
        self.browser.image_activated.connect(self._on_image_activated)
        self.detail.back_requested.connect(self._on_detail_back)

        self.browser_stack = QStackedWidget()
        self.browser_stack.setObjectName("browserStack")
        self.browser_stack.addWidget(self.browser)
        self.browser_stack.addWidget(self.detail)
        self.quality = PlaceholderView("质检", "数据质量检查（待实现）", "qualityView")
        self.export = PlaceholderView("导出", "格式转换与导出（待实现）", "exportView")

        self.addSubInterface(self.overview, FIF.HOME, "概览")
        self.addSubInterface(self.browser_stack, FIF.PHOTO, "浏览")
        self.addSubInterface(self.quality, FIF.SEARCH, "质检")
        self.addSubInterface(
            self.export, FIF.SHARE, "导出", position=NavigationItemPosition.BOTTOM
        )

        # 「打开数据集」按钮放到导航底部
        self.open_btn = PrimaryPushButton("打开数据集")
        self.open_btn.setIcon(FIF.FOLDER)
        self.open_btn.clicked.connect(self._on_open_clicked)
        self.navigationInterface.addWidget(
            routeKey="openDatasetBtn",
            widget=self.open_btn,
            position=NavigationItemPosition.BOTTOM,
        )

        self._apply_warm_palette()

    def _apply_warm_palette(self) -> None:
        self.setStyleSheet(
            f"""
            FluentWindow {{
                background-color: {SIDEBAR};
            }}
            #stackedWidget, #stackedWidget > QWidget {{
                background-color: {CONTENT};
            }}
            QWidget#overviewView, QWidget#browserView, QWidget#detailView,
            QWidget#qualityView, QWidget#exportView,
            QStackedWidget#browserStack {{
                background-color: {CONTENT};
            }}
            NavigationInterface, NavigationInterface > QWidget {{
                background-color: {SIDEBAR};
                border-right: 1px solid #e8e5dc;
            }}
            TitleBar, TitleBar > QWidget {{
                background-color: {SIDEBAR};
            }}
            """
        )

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
        self._start_scan(Path(directory))

    def _start_scan(self, root: Path) -> None:
        if self._scan_worker and self._scan_worker.isRunning():
            return
        self.open_btn.setEnabled(False)
        self.open_btn.setText("扫描中…")
        InfoBar.info(
            title="开始扫描",
            content=str(root),
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=2000,
            parent=self,
        )

        self._scan_worker = ScanWorker(root, parent=self)
        self._scan_worker.finished_ok.connect(self._on_scan_done)
        self._scan_worker.failed.connect(self._on_scan_failed)
        self._scan_worker.start()

    def _on_scan_done(self, dataset) -> None:
        self.overview.set_dataset(dataset)
        self.browser.load_dataset(dataset)
        self.open_btn.setEnabled(True)
        self.open_btn.setText("打开数据集")
        InfoBar.success(
            title="扫描完成",
            content=f"{dataset.total_images} 张图片 · {len(dataset.categories)} 类",
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=3000,
            parent=self,
        )

    def closeEvent(self, e):  # type: ignore[override]
        try:
            self._thumb_worker.stop()
        except Exception:
            pass
        super().closeEvent(e)

    def _on_scan_failed(self, msg: str) -> None:
        self.open_btn.setEnabled(True)
        self.open_btn.setText("打开数据集")
        InfoBar.error(
            title="扫描失败",
            content=msg,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=5000,
            parent=self,
        )
