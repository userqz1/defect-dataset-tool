"""Single-image detail view: large viewer + meta sidebar + A/D navigation."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtGui import QImage, QKeyEvent, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    EditableComboBox,
    FluentIcon as FIF,
    InfoBar,
    InfoBarPosition,
    MessageBox,
    StrongBodyLabel,
    ToolButton,
)

from core.annotation_formats import load_yolo_classes, parse_annotation
from core.annotation_writer import write_annotation
from core.models import Annotation, ImageInfo, Shape
from gui.theme import T
from gui.widgets.image_viewer import ImageViewer, color_for_label


class _ImageLoader(QThread):
    """Load image + parse annotation off the main thread."""
    done = pyqtSignal(object, object, object)  # (QPixmap, Annotation|None, ImageInfo)

    def __init__(self, img: ImageInfo, parent=None):
        super().__init__(parent)
        self._img = img

    def run(self):
        # Load image
        image = QImage(str(self._img.path))
        pix = QPixmap.fromImage(image) if not image.isNull() else QPixmap()

        # Parse annotation
        annotation = None
        if self._img.has_label and self._img.label_path:
            classes = None
            if self._img.label_path.suffix.lower() == ".txt":
                classes = load_yolo_classes(self._img.label_path.parent) or None
            result = parse_annotation(self._img.label_path, self._img.path, yolo_class_names=classes)
            if result.ok:
                annotation = result.annotation

        self.done.emit(pix, annotation, self._img)


class DetailView(QWidget):
    back_requested = pyqtSignal()  # 用户点返回

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("detailView")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._images: list[ImageInfo] = []
        self._index: int = -1
        self._annotation: Annotation | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 顶部条
        topbar = QFrame()
        topbar.setObjectName("detailTopBar")
        topbar.setFixedHeight(48)
        top_layout = QHBoxLayout(topbar)
        top_layout.setContentsMargins(T.GAP_LG, 0, T.PAD_LG, 0)
        top_layout.setSpacing(T.GAP)

        self.back_btn = ToolButton(FIF.LEFT_ARROW)
        self.back_btn.setToolTip("返回浏览 (Esc)")
        self.back_btn.clicked.connect(self._on_back_clicked)
        top_layout.addWidget(self.back_btn)

        self.crumb_label = BodyLabel("—")
        top_layout.addWidget(self.crumb_label)
        top_layout.addStretch(1)

        self.prev_btn = ToolButton(FIF.LEFT_ARROW)
        self.prev_btn.setToolTip("上一张 (A)")
        self.prev_btn.clicked.connect(self.prev_image)
        self.next_btn = ToolButton(FIF.RIGHT_ARROW)
        self.next_btn.setToolTip("下一张 (D)")
        self.next_btn.clicked.connect(self.next_image)
        self.zoom_out_btn = ToolButton(FIF.REMOVE)
        self.zoom_out_btn.setToolTip("缩小")
        self.zoom_out_btn.clicked.connect(lambda: self.viewer.zoom_out())
        self.zoom_in_btn = ToolButton(FIF.ADD)
        self.zoom_in_btn.setToolTip("放大")
        self.zoom_in_btn.clicked.connect(lambda: self.viewer.zoom_in())
        self.fit_btn = ToolButton(FIF.ZOOM)
        self.fit_btn.setToolTip("适应窗口")
        self.fit_btn.clicked.connect(lambda: self.viewer.reset_view())
        self.actual_btn = ToolButton(FIF.FULL_SCREEN)
        self.actual_btn.setToolTip("实际像素 1:1")
        self.actual_btn.clicked.connect(lambda: self.viewer.zoom_to_actual())
        self.toggle_anno_btn = ToolButton(FIF.VIEW)
        self.toggle_anno_btn.setCheckable(True)
        self.toggle_anno_btn.setChecked(True)
        self.toggle_anno_btn.setToolTip("显示 / 隐藏标注 (H)")

        # 编辑模式
        self.edit_btn = ToolButton(FIF.EDIT)
        self.edit_btn.setCheckable(True)
        self.edit_btn.setToolTip("编辑标注 (E) — 拖拽绘制矩形 / 点选删除")
        self.edit_btn.toggled.connect(self._on_edit_toggled)

        self.shape_rect_btn = ToolButton(FIF.LAYOUT)
        self.shape_rect_btn.setCheckable(True)
        self.shape_rect_btn.setChecked(True)
        self.shape_rect_btn.setToolTip("矩形 (R)")
        self.shape_poly_btn = ToolButton(FIF.IOT)
        self.shape_poly_btn.setCheckable(True)
        self.shape_poly_btn.setToolTip("多边形 (P) — 左键加点，双击/回车闭合，右键取消")
        self.shape_rect_btn.clicked.connect(lambda: self._set_shape_type("rectangle"))
        self.shape_poly_btn.clicked.connect(lambda: self._set_shape_type("polygon"))
        self.shape_rect_btn.hide()
        self.shape_poly_btn.hide()

        self.label_combo = EditableComboBox()
        self.label_combo.setMinimumWidth(120)
        self.label_combo.setToolTip("绘制时使用的标签名")
        self.label_combo.currentTextChanged.connect(
            lambda t: self.viewer.set_draw_label(t)
        )
        self.label_combo.hide()

        self.save_btn = ToolButton(FIF.SAVE)
        self.save_btn.setToolTip("保存标注 (Ctrl+S)")
        self.save_btn.clicked.connect(self._on_save)
        self.save_btn.hide()

        self.delete_shape_btn = ToolButton(FIF.DELETE)
        self.delete_shape_btn.setToolTip("删除选中标注 (Del)")
        self.delete_shape_btn.clicked.connect(lambda: self.viewer.delete_selected())
        self.delete_shape_btn.hide()

        self.zoom_label = BodyLabel("100%")
        self.zoom_label.setMinimumWidth(48)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        top_layout.addWidget(self.prev_btn)
        top_layout.addWidget(self.next_btn)
        top_layout.addWidget(self.zoom_out_btn)
        top_layout.addWidget(self.zoom_label)
        top_layout.addWidget(self.zoom_in_btn)
        top_layout.addWidget(self.fit_btn)
        top_layout.addWidget(self.actual_btn)
        top_layout.addWidget(self.toggle_anno_btn)
        top_layout.addWidget(self.edit_btn)
        top_layout.addWidget(self.shape_rect_btn)
        top_layout.addWidget(self.shape_poly_btn)
        top_layout.addWidget(self.label_combo)
        top_layout.addWidget(self.delete_shape_btn)
        top_layout.addWidget(self.save_btn)

        self.help_btn = ToolButton(FIF.HELP)
        self.help_btn.setToolTip("快捷键帮助")
        self.help_btn.clicked.connect(self._show_shortcuts)
        top_layout.addWidget(self.help_btn)

        root.addWidget(topbar)

        # 主体：viewer + sidebar
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self.viewer = ImageViewer()
        self.viewer.zoom_changed.connect(self._on_zoom_changed)
        self.viewer.shapes_changed.connect(self._on_shapes_changed)
        self.viewer.selection_changed.connect(self._on_selection_changed)
        self.toggle_anno_btn.toggled.connect(self.viewer.set_annotation_visible)
        body.addWidget(self.viewer, 1)
        self._dirty: bool = False

        # 右侧元信息
        sidebar = QFrame()
        sidebar.setObjectName("detailSidebar")
        sidebar.setFixedWidth(T.DETAIL_SIDEBAR_WIDTH)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(T.PAD_XL, T.PAD_XL, T.PAD_XL, T.PAD_XL)
        side_layout.setSpacing(T.GAP_LG)

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

        side_layout.addSpacing(T.GAP)
        side_layout.addWidget(self._section_label("标注列表"))
        self.shape_list = QListWidget()
        self.shape_list.setObjectName("shapeList")
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
        if not self._confirm_discard():
            return
        self._index = (self._index - 1) % len(self._images)
        self._load_current()

    def next_image(self) -> None:
        if not self._images:
            return
        if not self._confirm_discard():
            return
        self._index = (self._index + 1) % len(self._images)
        self._load_current()

    def _on_back_clicked(self) -> None:
        if not self._confirm_discard():
            return
        self.back_requested.emit()

    def _confirm_discard(self) -> bool:
        """Return True if it's OK to discard unsaved changes (or none)."""
        if not self._dirty:
            return True
        box = MessageBox(
            "未保存的修改",
            "当前标注有未保存的修改，是否放弃？",
            self.window(),
        )
        box.yesButton.setText("放弃修改")
        box.cancelButton.setText("继续编辑")
        return bool(box.exec())

    # ---------- 内部 ----------

    def _load_current(self) -> None:
        if not (0 <= self._index < len(self._images)):
            return
        img = self._images[self._index]

        # 立即更新面包屑（轻量，不阻塞）
        self.crumb_label.setText(
            f"{img.category}  /  {img.path.name}   "
            f"{self._index + 1} / {len(self._images)}"
        )
        self.info_name.setText(img.path.name)
        self.info_path.setText(str(img.path.parent))

        # 图片 + 标注异步加载
        if hasattr(self, "_loader") and self._loader and self._loader.isRunning():
            self._loader.terminate()
        self._loader = _ImageLoader(img, parent=self)
        self._loader.done.connect(self._on_image_loaded)
        self._loader.start()

    def _on_image_loaded(self, pix: QPixmap, annotation, img: ImageInfo) -> None:
        """Worker 完成后在主线程设置 viewer（轻量操作）。"""
        if not pix.isNull():
            self.viewer.load_pixmap(pix)
        self._annotation = annotation
        self.viewer.set_annotation(self._annotation)
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
        self._refresh_shape_list()
        if self.edit_btn.isChecked():
            self._refresh_label_combo()
        self._dirty = False

    def _show_shortcuts(self) -> None:
        from gui.dialogs.op_dialogs import ShortcutsDialog
        ShortcutsDialog(self.window()).exec()

    def _on_zoom_changed(self, scale: float) -> None:
        self.zoom_label.setText(f"{scale * 100:.0f}%")

    # ---------- 编辑 ----------

    def _on_edit_toggled(self, on: bool) -> None:
        self.viewer.set_edit_mode(on)
        self.label_combo.setVisible(on)
        self.delete_shape_btn.setVisible(on)
        self.save_btn.setVisible(on)
        self.shape_rect_btn.setVisible(on)
        self.shape_poly_btn.setVisible(on)
        if on:
            # 无标注图片 → 自动创建空 Annotation，这样绘制的新 shape 有地方存
            if self._annotation is None and 0 <= self._index < len(self._images):
                img = self._images[self._index]
                self._annotation = Annotation(image_path=img.path, shapes=[])
                self.viewer.set_annotation(self._annotation)
            self._refresh_label_combo()
            self.viewer.set_draw_label(self.label_combo.currentText() or "object")

    def _set_shape_type(self, st: str) -> None:
        self.shape_rect_btn.setChecked(st == "rectangle")
        self.shape_poly_btn.setChecked(st == "polygon")
        self.viewer.set_draw_shape_type(st)

    def _refresh_label_combo(self) -> None:
        existing = sorted({s.label for s in (self._annotation.shapes if self._annotation else [])})
        current = self.label_combo.currentText()
        self.label_combo.blockSignals(True)
        self.label_combo.clear()
        if existing:
            self.label_combo.addItems(existing)
        else:
            self.label_combo.addItem("object")
        if current:
            self.label_combo.setCurrentText(current)
        self.label_combo.blockSignals(False)

    def _on_shapes_changed(self) -> None:
        self._dirty = True
        self._annotation = self.viewer.get_annotation()
        self._refresh_shape_list()
        self._refresh_label_combo()
        self.save_btn.setToolTip("保存标注 (Ctrl+S) — 有未保存修改")

    def _on_selection_changed(self, idx: int) -> None:
        self.shape_list.blockSignals(True)
        if 0 <= idx < self.shape_list.count():
            self.shape_list.setCurrentRow(idx)
        else:
            self.shape_list.clearSelection()
        self.shape_list.blockSignals(False)

    def _refresh_shape_list(self) -> None:
        self.shape_list.clear()
        if self._annotation and self._annotation.shapes:
            for shape in self._annotation.shapes:
                item = QListWidgetItem(f"●  {shape.label}   ({shape.shape_type})")
                color = color_for_label(shape.label)
                item.setForeground(color)
                self.shape_list.addItem(item)
        else:
            self.shape_list.addItem(QListWidgetItem("（无标注）"))

    def _on_save(self) -> None:
        if not (0 <= self._index < len(self._images)):
            return
        img = self._images[self._index]
        if self._annotation is None:
            self._annotation = Annotation(image_path=img.path, shapes=[])
        # 推断 label_path：已有就用原路径；没有则用 LabelMe JSON 旁置
        label_path = img.label_path
        if label_path is None:
            label_path = self._infer_label_path(img.path)
        try:
            write_annotation(self._annotation, label_path, img.path)
        except Exception as e:  # noqa: BLE001
            InfoBar.error(
                title="保存失败", content=str(e),
                isClosable=True, position=InfoBarPosition.TOP,
                duration=4000, parent=self.window(),
            )
            return
        # 更新 ImageInfo 状态
        img.has_label = True
        img.label_path = label_path
        self._dirty = False
        InfoBar.success(
            title="已保存", content=str(label_path.name),
            isClosable=True, position=InfoBarPosition.TOP,
            duration=2000, parent=self.window(),
        )

    def _infer_label_path(self, image_path):
        # 优先 <category>/labels/<stem>.json，否则同目录
        parent = image_path.parent
        if parent.name == "images":
            cand = parent.parent / "labels" / (image_path.stem + ".json")
            cand.parent.mkdir(parents=True, exist_ok=True)
            return cand
        return parent / (image_path.stem + ".json")

    # ---------- 助手 ----------

    def _section_label(self, text: str) -> StrongBodyLabel:
        return StrongBodyLabel(text.upper())

    def _meta_value(self, text: str, small: bool = False):
        lbl = CaptionLabel(text) if small else BodyLabel(text)
        lbl.setWordWrap(True)
        return lbl

    def _meta_row(self, label: str, value_widget) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(T.GAP)
        key = CaptionLabel(label)
        key.setFixedWidth(48)
        key.setAlignment(Qt.AlignmentFlag.AlignTop)
        row.addWidget(key)
        row.addWidget(value_widget, 1)
        return row

    # ---------- 快捷键 ----------

    def keyPressEvent(self, e: QKeyEvent) -> None:  # type: ignore[override]
        if e.key() in (Qt.Key.Key_A, Qt.Key.Key_Left):
            self.prev_image()
        elif e.key() in (Qt.Key.Key_D, Qt.Key.Key_Right):
            self.next_image()
        elif e.key() == Qt.Key.Key_H:
            self.toggle_anno_btn.toggle()
        elif e.key() == Qt.Key.Key_E:
            self.edit_btn.toggle()
        elif e.key() == Qt.Key.Key_R and self.edit_btn.isChecked():
            self._set_shape_type("rectangle")
        elif e.key() == Qt.Key.Key_P and self.edit_btn.isChecked():
            self._set_shape_type("polygon")
        elif e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.edit_btn.isChecked():
            self.viewer.finish_polygon()
        elif e.key() == Qt.Key.Key_Delete and self.edit_btn.isChecked():
            self.viewer.delete_selected()
        elif e.key() == Qt.Key.Key_S and (e.modifiers() & Qt.KeyboardModifier.ControlModifier):
            if self.edit_btn.isChecked():
                self._on_save()
        elif e.key() == Qt.Key.Key_Escape:
            self._on_back_clicked()
        else:
            super().keyPressEvent(e)
