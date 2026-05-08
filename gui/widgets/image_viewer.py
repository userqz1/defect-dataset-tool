"""Image viewer with mouse-wheel zoom, drag-pan, and LabelMe annotation overlay."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QImage,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
    QWheelEvent,
)
from PyQt6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsPixmapItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
)

from core.models import Annotation, Shape
from gui.theme import T

# 一组高对比度但低饱和的标注颜色（不参与主题切换 — 标注 label 着色独立）
PALETTE = [
    "#c96442", "#5a7a3c", "#3a6a7a", "#7a5a8a", "#b8842b",
    "#a85a3a", "#456b9c", "#8a5a4a", "#5a8a8a", "#7a6a3a",
]


def color_for_label(label: str) -> QColor:
    idx = abs(hash(label)) % len(PALETTE)
    return QColor(PALETTE[idx])


class ImageViewer(QGraphicsView):
    zoom_changed = pyqtSignal(float)  # 绝对缩放系数（1.0 = 1:1 像素）
    shapes_changed = pyqtSignal()     # 标注被编辑（增/删/改）
    selection_changed = pyqtSignal(int)  # 选中第几个 shape；-1 = 无选中

    MIN_SCALE = 0.02
    MAX_SCALE = 64.0

    def __init__(self) -> None:
        super().__init__()
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setBackgroundBrush(QBrush(QColor(T.SURFACE_DIM)))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)

        self._pix_item: QGraphicsPixmapItem | None = None
        self._shape_items: list = []
        self._scale: float = 1.0
        self._annotation_visible: bool = True

        # 编辑模式
        self._edit_mode: bool = False
        self._draw_label: str = "object"
        self._draw_shape_type: str = "rectangle"  # rectangle | polygon
        self._annotation: Annotation | None = None
        self._drawing: bool = False
        self._draw_start: QPointF | None = None
        self._temp_rect_item: QGraphicsRectItem | None = None
        self._selected_index: int = -1
        # 多边形绘制状态
        self._poly_points: list[QPointF] = []
        self._temp_poly_item: QGraphicsPolygonItem | None = None

    def load_image(self, path: Path) -> None:
        """Load an image from file, replacing scene contents."""
        image = QImage(str(path))
        if image.isNull():
            return
        self.load_pixmap(QPixmap.fromImage(image))

    def load_pixmap(self, pix: QPixmap) -> None:
        """Set a pre-loaded pixmap, replacing scene contents."""
        self._scene.clear()
        self._shape_items.clear()
        self._pix_item = None

        if pix.isNull():
            return
        self._pix_item = self._scene.addPixmap(pix)
        self._scene.setSceneRect(QRectF(pix.rect()))
        self.fit_to_window()

    def set_annotation(self, annotation: Annotation | None) -> None:
        """Draw shapes overlaid on the current image."""
        for it in self._shape_items:
            self._scene.removeItem(it)
        self._shape_items.clear()
        self._selected_index = -1
        self._annotation = annotation
        if annotation is None or self._pix_item is None:
            return
        for shape in annotation.shapes:
            item = self._make_shape_item(shape)
            if item is not None:
                item.setVisible(self._annotation_visible)
                self._scene.addItem(item)
                self._shape_items.append(item)

    def get_annotation(self) -> Annotation | None:
        return self._annotation

    # ---------- 编辑模式 ----------

    def set_edit_mode(self, on: bool) -> None:
        self._edit_mode = on
        if on:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self.unsetCursor()
            self._clear_selection_highlight()
            self._selected_index = -1
            self.selection_changed.emit(-1)

    def set_draw_label(self, label: str) -> None:
        self._draw_label = label or "object"

    def set_draw_shape_type(self, shape_type: str) -> None:
        if shape_type not in ("rectangle", "polygon"):
            return
        # 切换形状时取消正在进行的多边形
        self._cancel_polygon()
        self._draw_shape_type = shape_type

    def _cancel_polygon(self) -> None:
        if self._temp_poly_item is not None:
            self._scene.removeItem(self._temp_poly_item)
            self._temp_poly_item = None
        self._poly_points = []

    def finish_polygon(self) -> None:
        """Commit the in-progress polygon (called by Enter key or double-click)."""
        if len(self._poly_points) >= 3 and self._annotation is not None:
            shape = Shape(
                label=self._draw_label,
                shape_type="polygon",
                points=[(p.x(), p.y()) for p in self._poly_points],
            )
            self._annotation.shapes.append(shape)
            self._cancel_polygon()
            self.set_annotation(self._annotation)
            self.shapes_changed.emit()
        else:
            self._cancel_polygon()

    def has_selection(self) -> bool:
        """True when a shape is currently selected on the canvas.

        Lets callers (DetailView) decide *before* calling
        :meth:`delete_selected` whether to push an undo snapshot.
        """
        return (self._annotation is not None
                and 0 <= self._selected_index < len(self._annotation.shapes))

    def delete_selected(self) -> bool:
        if self._annotation is None or self._selected_index < 0:
            return False
        return self.delete_shape_at(self._selected_index)

    def delete_shape_at(self, index: int) -> bool:
        """Delete the shape at *index* without requiring it to be selected.

        Used by the AnnotationPane's right-click "删除此标注" entry —
        the user can delete any list row directly without first
        clicking it on the canvas. Mirrors the post-delete contract of
        :meth:`delete_selected`: shapes_changed fires, selection
        clears, and the annotation buffer is rewritten.
        """
        if self._annotation is None:
            return False
        if not (0 <= index < len(self._annotation.shapes)):
            return False
        del self._annotation.shapes[index]
        self.set_annotation(self._annotation)
        self.shapes_changed.emit()
        self.selection_changed.emit(-1)
        return True

    def select_shape(self, index: int) -> None:
        self._clear_selection_highlight()
        self._selected_index = index
        if 0 <= index < len(self._shape_items):
            it = self._shape_items[index]
            pen = it.pen()
            pen.setWidthF(3.5)
            it.setPen(pen)
        self.selection_changed.emit(self._selected_index)

    def _clear_selection_highlight(self) -> None:
        for it in self._shape_items:
            try:
                pen = it.pen()
                pen.setWidthF(2.0)
                it.setPen(pen)
            except Exception:  # noqa: BLE001
                pass

    def set_annotation_visible(self, visible: bool) -> None:
        self._annotation_visible = visible
        for it in self._shape_items:
            it.setVisible(visible)

    def is_annotation_visible(self) -> bool:
        return self._annotation_visible

    def _make_shape_item(self, shape: Shape):
        color = color_for_label(shape.label)
        pen = QPen(color)
        pen.setWidthF(2.0)
        pen.setCosmetic(True)  # 缩放时线宽保持
        fill = QColor(color)
        fill.setAlpha(45)
        brush = QBrush(fill)

        st = shape.shape_type
        pts = shape.points
        if st == "polygon" and len(pts) >= 3:
            poly = QPolygonF([QPointF(x, y) for x, y in pts])
            item = QGraphicsPolygonItem(poly)
            item.setPen(pen)
            item.setBrush(brush)
            item.setToolTip(shape.label)
            return item
        if st == "rectangle" and len(pts) >= 2:
            (x1, y1), (x2, y2) = pts[0], pts[1]
            r = QRectF(min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1))
            item = QGraphicsRectItem(r)
            item.setPen(pen)
            item.setBrush(brush)
            item.setToolTip(shape.label)
            return item
        if st in ("point", "circle") and len(pts) >= 1:
            x, y = pts[0]
            r = 4.0
            item = QGraphicsEllipseItem(QRectF(x - r, y - r, 2 * r, 2 * r))
            item.setPen(pen)
            item.setBrush(QBrush(color))
            item.setToolTip(shape.label)
            return item
        if st == "line" and len(pts) >= 2:
            poly = QPolygonF([QPointF(x, y) for x, y in pts])
            item = QGraphicsPolygonItem(poly)
            item.setPen(pen)
            item.setBrush(Qt.BrushStyle.NoBrush)
            item.setToolTip(shape.label)
            return item
        return None

    def current_scale(self) -> float:
        return self.transform().m11()

    def fit_to_window(self) -> None:
        if self._pix_item is None:
            return
        self.resetTransform()
        self.fitInView(self._pix_item, Qt.AspectRatioMode.KeepAspectRatio)
        self._scale = self.current_scale()
        self.zoom_changed.emit(self._scale)

    def zoom_to_actual(self) -> None:
        """缩放到 1:1 实际像素。"""
        if self._pix_item is None:
            return
        self.resetTransform()
        self._scale = 1.0
        # 居中到图像中心
        self.centerOn(self._pix_item)
        self.zoom_changed.emit(self._scale)

    def reset_view(self) -> None:
        self.fit_to_window()

    def _apply_zoom(self, factor: float) -> None:
        new_scale = self._scale * factor
        if new_scale < self.MIN_SCALE:
            factor = self.MIN_SCALE / self._scale
            new_scale = self.MIN_SCALE
        elif new_scale > self.MAX_SCALE:
            factor = self.MAX_SCALE / self._scale
            new_scale = self.MAX_SCALE
        if abs(factor - 1.0) < 1e-6:
            return
        self.scale(factor, factor)
        self._scale = new_scale
        self.zoom_changed.emit(self._scale)

    def zoom_in(self) -> None:
        if self._pix_item is not None:
            self._apply_zoom(1.25)

    def zoom_out(self) -> None:
        if self._pix_item is not None:
            self._apply_zoom(1 / 1.25)

    def wheelEvent(self, event: QWheelEvent) -> None:  # type: ignore[override]
        if self._pix_item is None:
            return
        factor = 1.18 if event.angleDelta().y() > 0 else 1 / 1.18
        self._apply_zoom(factor)

    def leaveEvent(self, event) -> None:
        """Cancel in-progress drawing when mouse leaves the viewport."""
        if self._drawing:
            self._drawing = False
            if self._temp_rect_item is not None:
                self._scene.removeItem(self._temp_rect_item)
                self._temp_rect_item = None
            self._draw_start = None
        super().leaveEvent(event)

    # ---------- 编辑事件 ----------

    def mousePressEvent(self, event):  # type: ignore[override]
        if self._edit_mode and event.button() == Qt.MouseButton.RightButton:
            # 右键：取消正在进行的多边形
            if self._temp_poly_item is not None:
                self._cancel_polygon()
                return
        if self._edit_mode and event.button() == Qt.MouseButton.LeftButton and self._pix_item is not None:
            scene_pos = self.mapToScene(event.pos())
            # 多边形模式：每次左键点击添加一个顶点
            if self._draw_shape_type == "polygon":
                # 第一个点之前优先点选已有 shape
                if not self._poly_points:
                    hit = self._hit_test(scene_pos)
                    if hit >= 0:
                        self.select_shape(hit)
                        return
                self._poly_points.append(scene_pos)
                self._update_temp_polygon(scene_pos)
                self._clear_selection_highlight()
                self._selected_index = -1
                self.selection_changed.emit(-1)
                return
            # 矩形模式：优先点选已有 shape
            hit = self._hit_test(scene_pos)
            if hit >= 0:
                self.select_shape(hit)
                return
            # 否则开始绘制新 rect
            self._drawing = True
            self._draw_start = scene_pos
            color = color_for_label(self._draw_label)
            pen = QPen(color)
            pen.setWidthF(2.0)
            pen.setCosmetic(True)
            fill = QColor(color); fill.setAlpha(45)
            self._temp_rect_item = QGraphicsRectItem(QRectF(scene_pos, scene_pos))
            self._temp_rect_item.setPen(pen)
            self._temp_rect_item.setBrush(QBrush(fill))
            self._scene.addItem(self._temp_rect_item)
            self._clear_selection_highlight()
            self._selected_index = -1
            self.selection_changed.emit(-1)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # type: ignore[override]
        if self._drawing and self._temp_rect_item is not None and self._draw_start is not None:
            scene_pos = self.mapToScene(event.pos())
            rect = QRectF(self._draw_start, scene_pos).normalized()
            self._temp_rect_item.setRect(rect)
            return
        if self._edit_mode and self._draw_shape_type == "polygon" and self._poly_points:
            # 实时预览：把鼠标当作下一个顶点
            self._update_temp_polygon(self.mapToScene(event.pos()))
            return
        super().mouseMoveEvent(event)

    def mouseDoubleClickEvent(self, event):  # type: ignore[override]
        if self._edit_mode and self._draw_shape_type == "polygon" and self._poly_points:
            self.finish_polygon()
            return
        super().mouseDoubleClickEvent(event)

    def _update_temp_polygon(self, hover_pos: QPointF) -> None:
        if not self._poly_points:
            return
        pts = list(self._poly_points) + [hover_pos]
        poly = QPolygonF(pts)
        if self._temp_poly_item is None:
            color = color_for_label(self._draw_label)
            pen = QPen(color)
            pen.setWidthF(2.0)
            pen.setCosmetic(True)
            pen.setStyle(Qt.PenStyle.DashLine)
            fill = QColor(color); fill.setAlpha(45)
            self._temp_poly_item = QGraphicsPolygonItem(poly)
            self._temp_poly_item.setPen(pen)
            self._temp_poly_item.setBrush(QBrush(fill))
            self._scene.addItem(self._temp_poly_item)
        else:
            self._temp_poly_item.setPolygon(poly)

    def mouseReleaseEvent(self, event):  # type: ignore[override]
        if self._drawing and self._temp_rect_item is not None and self._draw_start is not None:
            self._drawing = False
            rect = self._temp_rect_item.rect()
            self._scene.removeItem(self._temp_rect_item)
            self._temp_rect_item = None
            self._draw_start = None
            if rect.width() >= 3 and rect.height() >= 3 and self._annotation is not None:
                shape = Shape(
                    label=self._draw_label,
                    shape_type="rectangle",
                    points=[(rect.left(), rect.top()), (rect.right(), rect.bottom())],
                )
                self._annotation.shapes.append(shape)
                self.set_annotation(self._annotation)
                self.shapes_changed.emit()
            return
        super().mouseReleaseEvent(event)

    def _hit_test(self, scene_pos: QPointF) -> int:
        for i, it in enumerate(self._shape_items):
            try:
                if it.contains(it.mapFromScene(scene_pos)):
                    return i
            except Exception:  # noqa: BLE001
                pass
        return -1
