"""Single-image detail view: large viewer + meta sidebar + A/D navigation."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QKeyEvent
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import FluentIcon as FIF, ToolButton

from core.annotation import parse_labelme
from core.models import Annotation, ImageInfo
from gui.widgets.image_viewer import ImageViewer, color_for_label

BG = "#ffffff"
SIDEBAR = "#f5f4ef"
BORDER = "#e8e5dc"
TEXT = "#2d2a26"
TEXT_2 = "#6b6760"
TEXT_3 = "#9a958a"
ACCENT = "#c96442"


class DetailView(QWidget):
    back_requested = pyqtSignal()  # 用户点返回

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("detailView")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"QWidget#detailView {{ background-color: {BG}; }}")

        self._images: list[ImageInfo] = []
        self._index: int = -1
        self._annotation: Annotation | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 顶部条
        topbar = QFrame()
        topbar.setFixedHeight(48)
        topbar.setStyleSheet(
            f"background-color: {BG}; border-bottom: 1px solid {BORDER};"
        )
        top_layout = QHBoxLayout(topbar)
        top_layout.setContentsMargins(12, 0, 16, 0)
        top_layout.setSpacing(8)

        self.back_btn = ToolButton(FIF.LEFT_ARROW)
        self.back_btn.setToolTip("返回浏览 (Esc)")
        self.back_btn.clicked.connect(self.back_requested.emit)
        top_layout.addWidget(self.back_btn)

        self.crumb_label = QLabel("—")
        self.crumb_label.setStyleSheet(f"color: {TEXT_2}; font-size: 12px;")
        top_layout.addWidget(self.crumb_label)
        top_layout.addStretch(1)

        self.prev_btn = ToolButton(FIF.LEFT_ARROW)
        self.prev_btn.setToolTip("上一张 (A)")
        self.prev_btn.clicked.connect(self.prev_image)
        self.next_btn = ToolButton(FIF.RIGHT_ARROW)
        self.next_btn.setToolTip("下一张 (D)")
        self.next_btn.clicked.connect(self.next_image)
        self.fit_btn = ToolButton(FIF.ZOOM)
        self.fit_btn.setToolTip("适应窗口")
        self.fit_btn.clicked.connect(lambda: self.viewer.reset_view())

        top_layout.addWidget(self.prev_btn)
        top_layout.addWidget(self.next_btn)
        top_layout.addWidget(self.fit_btn)

        root.addWidget(topbar)

        # 主体：viewer + sidebar
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self.viewer = ImageViewer()
        body.addWidget(self.viewer, 1)

        # 右侧元信息
        sidebar = QFrame()
        sidebar.setFixedWidth(280)
        sidebar.setStyleSheet(
            f"background-color: {SIDEBAR}; border-left: 1px solid {BORDER};"
        )
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(20, 20, 20, 20)
        side_layout.setSpacing(14)

        side_layout.addWidget(self._section_label("文件信息"))
        self.info_name = self._meta_value("—")
        self.info_path = self._meta_value("—", small=True)
        self.info_size = self._meta_value("—")
        self.info_dim = self._meta_value("—")
        self.info_cat = self._meta_value("—")
        side_layout.addLayout(self._meta_row("文件名", self.info_name))
        side_layout.addLayout(self._meta_row("路径", self.info_path))
        side_layout.addLayout(self._meta_row("大小", self.info_size))
        side_layout.addLayout(self._meta_row("尺寸", self.info_dim))
        side_layout.addLayout(self._meta_row("类别", self.info_cat))

        side_layout.addSpacing(8)
        side_layout.addWidget(self._section_label("标注列表"))
        self.shape_list = QListWidget()
        self.shape_list.setStyleSheet(
            f"""
            QListWidget {{
                background-color: transparent;
                border: 1px solid {BORDER};
                border-radius: 6px;
                font-size: 12px;
                outline: 0;
            }}
            QListWidget::item {{ padding: 6px 10px; color: {TEXT}; }}
            QListWidget::item:hover {{ background-color: #ede9de; }}
            """
        )
        side_layout.addWidget(self.shape_list, 1)

        body.addWidget(sidebar)
        root.addLayout(body, 1)

    # ---------- 接口 ----------

    def show_image(self, image: ImageInfo, image_list: list[ImageInfo]) -> None:
        self._images = image_list
        try:
            self._index = image_list.index(image)
        except ValueError:
            self._index = 0
            self._images = [image]
        self._load_current()

    def prev_image(self) -> None:
        if not self._images:
            return
        self._index = (self._index - 1) % len(self._images)
        self._load_current()

    def next_image(self) -> None:
        if not self._images:
            return
        self._index = (self._index + 1) % len(self._images)
        self._load_current()

    # ---------- 内部 ----------

    def _load_current(self) -> None:
        if not (0 <= self._index < len(self._images)):
            return
        img = self._images[self._index]
        self.viewer.load_image(img.path)

        # 解析标注
        self._annotation = None
        if img.has_label and img.label_path:
            result = parse_labelme(img.label_path, img.path)
            if result.ok:
                self._annotation = result.annotation
        self.viewer.set_annotation(self._annotation)

        # 元信息
        self.crumb_label.setText(
            f"{img.category}  /  {img.path.name}   "
            f"<span style='color:{TEXT_3}'>{self._index + 1} / {len(self._images)}</span>"
        )
        self.info_name.setText(img.path.name)
        self.info_path.setText(str(img.path.parent))
        try:
            size_kb = img.path.stat().st_size / 1024
            self.info_size.setText(
                f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb / 1024:.2f} MB"
            )
        except OSError:
            self.info_size.setText("—")
        # 尺寸从 viewer 拿
        if self.viewer._pix_item is not None:
            r = self.viewer._pix_item.pixmap()
            self.info_dim.setText(f"{r.width()} × {r.height()} px")
        else:
            self.info_dim.setText("—")
        self.info_cat.setText(img.category)

        # 标注列表
        self.shape_list.clear()
        if self._annotation:
            for shape in self._annotation.shapes:
                item = QListWidgetItem(f"●  {shape.label}   ({shape.shape_type})")
                color = color_for_label(shape.label)
                item.setForeground(color)
                self.shape_list.addItem(item)
        else:
            self.shape_list.addItem(QListWidgetItem("（无标注）"))

    # ---------- 助手 ----------

    def _section_label(self, text: str) -> QLabel:
        lbl = QLabel(text.upper())
        lbl.setStyleSheet(
            f"color: {TEXT_2}; font-size: 11px; font-weight: 600; letter-spacing: 0.6px;"
        )
        return lbl

    def _meta_value(self, text: str, small: bool = False) -> QLabel:
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        size = 10 if small else 12
        lbl.setStyleSheet(f"color: {TEXT}; font-size: {size}px;")
        return lbl

    def _meta_row(self, label: str, value_widget: QLabel) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        key = QLabel(label)
        key.setFixedWidth(48)
        key.setStyleSheet(f"color: {TEXT_3}; font-size: 11px;")
        key.setAlignment(Qt.AlignmentFlag.AlignTop)
        row.addWidget(key)
        row.addWidget(value_widget, 1)
        return row

    # ---------- 快捷键 ----------

    def keyPressEvent(self, e: QKeyEvent) -> None:  # type: ignore[override]
        if e.key() == Qt.Key.Key_A:
            self.prev_image()
        elif e.key() == Qt.Key.Key_D:
            self.next_image()
        elif e.key() == Qt.Key.Key_Escape:
            self.back_requested.emit()
        else:
            super().keyPressEvent(e)
