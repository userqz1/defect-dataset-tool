"""Image viewer with mouse-wheel zoom, drag-pan, and LabelMe annotation overlay."""
from __future__ import annotations

import hashlib
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
    QFrame,
    QGraphicsEllipseItem,
    QGraphicsPixmapItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
)
from qfluentwidgets import CaptionLabel, FluentIcon as FIF, TransparentToolButton

from core.models import Annotation, Shape
from gui.theme import T

# 一组高对比度但低饱和的标注颜色（不参与主题切换 — 标注 label 着色独立）
PALETTE = [
    "#c96442", "#5a7a3c", "#3a6a7a", "#7a5a8a", "#b8842b",
    "#a85a3a", "#456b9c", "#8a5a4a", "#5a8a8a", "#7a6a3a",
]


def color_for_label(label: str) -> QColor:
    digest = hashlib.md5(label.encode("utf-8")).hexdigest()
    idx = int(digest[:8], 16) % len(PALETTE)
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
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
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
        self._draw_shape_type: str = "rectangle"  # rectangle | polygon | point | line | circle
        self._annotation: Annotation | None = None
        self._drawing: bool = False
        self._draw_start: QPointF | None = None
        self._temp_rect_item: QGraphicsRectItem | None = None
        self._selected_index: int = -1
        self._handle_items: list[QGraphicsRectItem] = []
        self._resizing: bool = False
        self._resize_handle: str = ""
        self._resize_index: int = -1
        self._resize_origin: QRectF | None = None
        self._resize_changed: bool = False
        self._resize_min_size: float = 3.0
        # Per-vertex node editing (polygon / linestrip / point / circle):
        # index of the point being dragged, or -1 when doing a rect resize.
        self._vertex_index: int = -1
        # 多边形绘制状态
        self._poly_points: list[QPointF] = []
        self._temp_poly_item: QGraphicsPolygonItem | None = None

        # Bottom-corner HUD (zoom controls + cursor coords + pixel value).
        # Cached QImage of the pixmap so per-move pixel sampling is cheap.
        self._hud_image: QImage | None = None
        self._build_hud()
        self.zoom_changed.connect(self._update_hud_zoom)

    # ---------- 底部 HUD（缩放 / 坐标 / 像素值）----------

    def _build_hud(self) -> None:
        """A floating status strip in the bottom-left of the viewport:
        zoom −/+, zoom %, fit / 1:1, then cursor coords + pixel RGB.

        Lives on the viewport so it floats over the image and never steals
        toolbar space (mature editors keep zoom out of the top ribbon)."""
        # Parent to the VIEW, not the viewport: QGraphicsView scrolls its
        # viewport's child widgets when zoom pans the scene, and the viewport
        # also resizes when scrollbars toggle — both would drift the HUD.
        self._hud = QFrame(self)
        self._hud.setObjectName("viewerHud")

        lay = QHBoxLayout(self._hud)
        lay.setContentsMargins(T.GAP, 2, T.GAP, 2)
        lay.setSpacing(2)

        # No +/− buttons (zoom with the wheel); just the % and fit / 1:1.
        self._hud_zoom_lbl = CaptionLabel("100%", self._hud)
        self._hud_zoom_lbl.setObjectName("viewerHudInfo")
        self._hud_zoom_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hud_zoom_lbl.setMinimumWidth(46)
        self._hud_fit = TransparentToolButton(FIF.ZOOM, self._hud)
        self._hud_fit.setToolTip("适应窗口")
        self._hud_fit.clicked.connect(self.reset_view)
        self._hud_actual = TransparentToolButton(FIF.FULL_SCREEN, self._hud)
        self._hud_actual.setToolTip("实际像素 1:1")
        self._hud_actual.clicked.connect(self.zoom_to_actual)

        sep = QFrame(self._hud)
        sep.setObjectName("viewerHudSep")
        sep.setFrameShape(QFrame.Shape.VLine)

        # Letter-labelled so the numbers can't be misread.
        self._hud_coord = CaptionLabel("x: —  y: —", self._hud)
        self._hud_coord.setObjectName("viewerHudInfo")
        self._hud_coord.setMinimumWidth(108)
        self._hud_swatch = QLabel(self._hud)
        self._hud_swatch.setObjectName("viewerHudSwatch")
        self._hud_swatch.setFixedSize(14, 14)
        self._hud_pixel = CaptionLabel("RGB —", self._hud)
        self._hud_pixel.setObjectName("viewerHudInfo")
        self._hud_pixel.setMinimumWidth(116)

        for w in (self._hud_zoom_lbl, self._hud_fit, self._hud_actual, sep,
                  self._hud_coord, self._hud_swatch, self._hud_pixel):
            lay.addWidget(w)
        self._hud.adjustSize()
        self._hud.raise_()

    def _position_hud(self) -> None:
        if not hasattr(self, "_hud"):
            return
        self._hud.adjustSize()
        margin = T.PAD
        # Anchor to the view's own height (constant during zoom/scroll) and
        # reserve the horizontal scrollbar's height so the spot is the same
        # whether or not the scrollbar is currently showing — no drift.
        sb_h = self.horizontalScrollBar().sizeHint().height()
        y = self.height() - self._hud.height() - margin - sb_h
        self._hud.move(margin, max(margin, y))
        self._hud.raise_()

    def _update_hud_zoom(self, scale: float) -> None:
        if hasattr(self, "_hud_zoom_lbl"):
            self._hud_zoom_lbl.setText(f"{scale * 100:.0f}%")

    def _update_hud_readout(self, scene_pos: QPointF) -> None:
        """Update cursor coords + pixel swatch/RGB from a scene position."""
        if not hasattr(self, "_hud_coord"):
            return
        img = self._hud_image
        if img is None:
            self._hud_coord.setText("x: —  y: —")
            self._hud_pixel.setText("RGB —")
            self._hud_swatch.clear()
            return
        x, y = int(scene_pos.x()), int(scene_pos.y())
        if 0 <= x < img.width() and 0 <= y < img.height():
            self._hud_coord.setText(f"x: {x}  y: {y}")
            c = img.pixelColor(x, y)
            # Grayscale pixels naturally read as equal channels (n, n, n).
            self._hud_pixel.setText(f"RGB {c.red()},{c.green()},{c.blue()}")
            sw = QPixmap(14, 14)
            sw.fill(c)
            self._hud_swatch.setPixmap(sw)
        else:
            self._hud_coord.setText("x: —  y: —")
            self._hud_pixel.setText("RGB —")
            self._hud_swatch.clear()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._position_hud()

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
        self._handle_items.clear()
        self._clear_resize_state()
        self._pix_item = None
        self._hud_image = None

        if pix.isNull():
            return
        self._pix_item = self._scene.addPixmap(pix)
        self._scene.setSceneRect(QRectF(pix.rect()))
        # Cache the image once for cheap per-move pixel sampling in the HUD.
        self._hud_image = pix.toImage()
        self.fit_to_window()
        self._position_hud()

    def set_annotation(self, annotation: Annotation | None) -> None:
        """Draw shapes overlaid on the current image."""
        self._clear_handle_items()
        self._clear_resize_state()
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
            self._clear_handle_items()
            self._clear_resize_state()
            self._selected_index = -1
            self.selection_changed.emit(-1)

    def set_draw_label(self, label: str) -> None:
        self._draw_label = label or "object"

    def set_draw_shape_type(self, shape_type: str) -> None:
        if shape_type not in ("rectangle", "polygon", "point", "linestrip",
                              "circle", "ellipse"):
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
        """Commit the in-progress polygon / polyline (Enter key or double-click).

        A polyline (``linestrip``) needs only 2 points and stays open; a polygon
        needs 3+ and closes.  Both accumulate via the same click-to-add path.
        """
        min_pts = 2 if self._draw_shape_type == "linestrip" else 3
        if len(self._poly_points) >= min_pts and self._annotation is not None:
            shape = Shape(
                label=self._draw_label,
                shape_type=self._draw_shape_type,  # polygon | linestrip
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
        self._update_selection_handles()
        self.selection_changed.emit(self._selected_index)

    def _clear_selection_highlight(self) -> None:
        for it in self._shape_items:
            try:
                pen = it.pen()
                pen.setWidthF(2.0)
                it.setPen(pen)
            except Exception:  # noqa: BLE001
                pass
        self._clear_handle_items()

    def set_annotation_visible(self, visible: bool) -> None:
        self._annotation_visible = visible
        for it in self._shape_items:
            it.setVisible(visible)
        for it in self._handle_items:
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
            item.setZValue(10)
            return item
        if st == "rectangle" and len(pts) >= 2:
            (x1, y1), (x2, y2) = pts[0], pts[1]
            r = QRectF(min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1))
            item = QGraphicsRectItem(r)
            item.setPen(pen)
            item.setBrush(brush)
            item.setToolTip(shape.label)
            item.setZValue(10)
            return item
        if st == "circle" and len(pts) >= 2:
            # LabelMe convention: pts = [center, edge]; radius = their distance.
            (cx, cy), (ex, ey) = pts[0], pts[1]
            r = ((ex - cx) ** 2 + (ey - cy) ** 2) ** 0.5
            item = QGraphicsEllipseItem(QRectF(cx - r, cy - r, 2 * r, 2 * r))
            item.setPen(pen)
            item.setBrush(brush)
            item.setToolTip(shape.label)
            item.setZValue(10)
            return item
        if st == "ellipse" and len(pts) >= 2:
            # Stored by bounding box pts = [(x1,y1), (x2,y2)]; the ellipse
            # fits that box (independent width/height, unlike circle).
            (x1, y1), (x2, y2) = pts[0], pts[1]
            r = QRectF(min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1))
            item = QGraphicsEllipseItem(r)
            item.setPen(pen)
            item.setBrush(brush)
            item.setToolTip(shape.label)
            item.setZValue(10)
            return item
        if st == "point" or (st == "circle" and len(pts) == 1):
            x, y = pts[0]
            r = 4.0
            item = QGraphicsEllipseItem(QRectF(x - r, y - r, 2 * r, 2 * r))
            item.setPen(pen)
            item.setBrush(QBrush(color))
            item.setToolTip(shape.label)
            item.setZValue(10)
            return item
        if st in ("linestrip", "line") and len(pts) >= 2:
            poly = QPolygonF([QPointF(x, y) for x, y in pts])
            item = QGraphicsPolygonItem(poly)
            item.setPen(pen)
            item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            item.setToolTip(shape.label)
            item.setZValue(10)
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
        self._update_selection_handles()

    def zoom_to_actual(self) -> None:
        """缩放到 1:1 实际像素。"""
        if self._pix_item is None:
            return
        self.resetTransform()
        self._scale = 1.0
        # 居中到图像中心
        self.centerOn(self._pix_item)
        self.zoom_changed.emit(self._scale)
        self._update_selection_handles()

    def reset_view(self) -> None:
        self.fit_to_window()

    def _apply_zoom(self, factor: float, anchor_pos=None) -> None:
        new_scale = self._scale * factor
        if new_scale < self.MIN_SCALE:
            factor = self.MIN_SCALE / self._scale
            new_scale = self.MIN_SCALE
        elif new_scale > self.MAX_SCALE:
            factor = self.MAX_SCALE / self._scale
            new_scale = self.MAX_SCALE
        if abs(factor - 1.0) < 1e-6:
            return

        if anchor_pos is None:
            anchor_pos = self.viewport().rect().center()
        anchor_scene = self.mapToScene(anchor_pos)

        self.scale(factor, factor)
        self._scale = new_scale
        # Keep the original scene point under the same viewport pixel.
        # Adjusting scrollbars is more stable than transform.translate()
        # after the user has panned or when scrollbars appear mid-zoom.
        anchor_after = self.mapFromScene(anchor_scene)
        delta = anchor_after - anchor_pos
        self.horizontalScrollBar().setValue(
            self.horizontalScrollBar().value() + delta.x())
        self.verticalScrollBar().setValue(
            self.verticalScrollBar().value() + delta.y())
        self.zoom_changed.emit(self._scale)
        self._update_selection_handles()

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
        self._apply_zoom(factor, event.position().toPoint())
        event.accept()

    def leaveEvent(self, event) -> None:
        """Cancel in-progress drawing when mouse leaves the viewport."""
        if self._drawing:
            self._drawing = False
            if self._temp_rect_item is not None:
                self._scene.removeItem(self._temp_rect_item)
                self._temp_rect_item = None
            self._draw_start = None
        super().leaveEvent(event)

    def _clear_resize_state(self) -> None:
        self._resizing = False
        self._resize_handle = ""
        self._resize_index = -1
        self._resize_origin = None
        self._resize_changed = False
        self._vertex_index = -1

    def _handle_size_scene(self) -> float:
        return max(4.0, 9.0 / max(self.current_scale(), 0.001))

    def _handle_hit_tolerance(self) -> float:
        return max(5.0, 9.0 / max(self.current_scale(), 0.001))

    def _shape_rect(self, index: int) -> QRectF | None:
        if self._annotation is None or not (0 <= index < len(self._annotation.shapes)):
            return None
        shape = self._annotation.shapes[index]
        if shape.shape_type not in ("rectangle", "ellipse") or len(shape.points) < 2:
            return None
        (x1, y1), (x2, y2) = shape.points[0], shape.points[1]
        return QRectF(QPointF(x1, y1), QPointF(x2, y2)).normalized()

    def _rect_handle_points(self, rect: QRectF) -> dict[str, QPointF]:
        cx = rect.center().x()
        cy = rect.center().y()
        return {
            "nw": QPointF(rect.left(), rect.top()),
            "n": QPointF(cx, rect.top()),
            "ne": QPointF(rect.right(), rect.top()),
            "e": QPointF(rect.right(), cy),
            "se": QPointF(rect.right(), rect.bottom()),
            "s": QPointF(cx, rect.bottom()),
            "sw": QPointF(rect.left(), rect.bottom()),
            "w": QPointF(rect.left(), cy),
        }

    def _clear_handle_items(self) -> None:
        for it in self._handle_items:
            try:
                self._scene.removeItem(it)
            except RuntimeError:
                pass
        self._handle_items.clear()

    def _selection_handle_points(self, index: int) -> list[QPointF]:
        """Points to draw grab-handles at for the selected shape.

        Rectangle → the 8 bbox handles (corner + edge resize). Every other
        shape → one handle per stored vertex, so its nodes can be dragged.
        """
        if self._annotation is None or not (0 <= index < len(self._annotation.shapes)):
            return []
        shape = self._annotation.shapes[index]
        if shape.shape_type in ("rectangle", "ellipse"):
            rect = self._shape_rect(index)
            if rect is None:
                return []
            return list(self._rect_handle_points(rect).values())
        return [QPointF(x, y) for x, y in shape.points]

    def _update_selection_handles(self) -> None:
        self._clear_handle_items()
        if not self._edit_mode or not self._annotation_visible:
            return
        positions = self._selection_handle_points(self._selected_index)
        if not positions:
            return
        size = self._handle_size_scene()
        half = size / 2
        pen = QPen(QColor(T.ACCENT))
        pen.setWidthF(1.5)
        pen.setCosmetic(True)
        brush = QBrush(QColor(T.CONTENT))
        for pos in positions:
            item = QGraphicsRectItem(
                QRectF(pos.x() - half, pos.y() - half, size, size)
            )
            item.setPen(pen)
            item.setBrush(brush)
            item.setZValue(30)
            item.setVisible(self._annotation_visible)
            self._scene.addItem(item)
            self._handle_items.append(item)

    def _vertex_hit_at(self, scene_pos: QPointF) -> tuple[int, int]:
        """Return (shape_index, vertex_index) if a node handle of the selected
        non-rect shape is under the cursor, else (-1, -1)."""
        idx = self._selected_index
        if self._annotation is None or not (0 <= idx < len(self._annotation.shapes)):
            return -1, -1
        shape = self._annotation.shapes[idx]
        if shape.shape_type in ("rectangle", "ellipse"):
            return -1, -1
        tol = self._handle_hit_tolerance()
        for vi, (x, y) in enumerate(shape.points):
            if abs(scene_pos.x() - x) <= tol and abs(scene_pos.y() - y) <= tol:
                return idx, vi
        return -1, -1

    def _rerender_shape(self, index: int) -> None:
        """Rebuild one shape's graphics item after its points changed."""
        if self._annotation is None or not (0 <= index < len(self._shape_items)):
            return
        try:
            self._scene.removeItem(self._shape_items[index])
        except RuntimeError:
            pass
        item = self._make_shape_item(self._annotation.shapes[index])
        if item is None:
            # Point count is stable during a drag, so this shouldn't fire;
            # keep a zero-area placeholder to preserve index alignment.
            item = QGraphicsRectItem(QRectF(0, 0, 0, 0))
        item.setVisible(self._annotation_visible)
        if index == self._selected_index:
            pen = item.pen()
            pen.setWidthF(3.5)
            item.setPen(pen)
        self._scene.addItem(item)
        self._shape_items[index] = item

    def _apply_vertex_drag(self, scene_pos: QPointF) -> None:
        """Move the dragged node to *scene_pos* (circle center drags the whole
        circle; circle edge changes the radius)."""
        if self._annotation is None:
            return
        if not (0 <= self._resize_index < len(self._annotation.shapes)):
            return
        shape = self._annotation.shapes[self._resize_index]
        pts = list(shape.points)
        i = self._vertex_index
        if not (0 <= i < len(pts)):
            return
        pos = self._clamp_to_scene(scene_pos)
        if shape.shape_type == "circle" and len(pts) >= 2:
            if i == 0:
                # Center node → translate the whole circle (radius unchanged).
                cx, cy = pts[0]
                dx, dy = pos.x() - cx, pos.y() - cy
                pts[0] = (pos.x(), pos.y())
                pts[1] = (pts[1][0] + dx, pts[1][1] + dy)
            else:
                # Edge node → radius follows the cursor, center fixed.
                pts[1] = (pos.x(), pos.y())
        else:
            pts[i] = (pos.x(), pos.y())
        shape.points = pts
        self._rerender_shape(self._resize_index)
        self._resize_changed = True
        self._selected_index = self._resize_index
        self._update_selection_handles()

    def _handle_at_rect(self, rect: QRectF, scene_pos: QPointF) -> str:
        tol = self._handle_hit_tolerance()
        x = scene_pos.x()
        y = scene_pos.y()
        for name in ("nw", "ne", "se", "sw"):
            p = self._rect_handle_points(rect)[name]
            if abs(x - p.x()) <= tol and abs(y - p.y()) <= tol:
                return name
        if abs(y - rect.top()) <= tol and rect.left() - tol <= x <= rect.right() + tol:
            return "n"
        if abs(x - rect.right()) <= tol and rect.top() - tol <= y <= rect.bottom() + tol:
            return "e"
        if abs(y - rect.bottom()) <= tol and rect.left() - tol <= x <= rect.right() + tol:
            return "s"
        if abs(x - rect.left()) <= tol and rect.top() - tol <= y <= rect.bottom() + tol:
            return "w"
        return ""

    def _resize_hit_at(self, scene_pos: QPointF) -> tuple[int, str]:
        rect = self._shape_rect(self._selected_index)
        if rect is not None:
            handle = self._handle_at_rect(rect, scene_pos)
            if handle:
                return self._selected_index, handle
        if self._annotation is None:
            return -1, ""
        for index in range(len(self._annotation.shapes) - 1, -1, -1):
            rect = self._shape_rect(index)
            if rect is None:
                continue
            handle = self._handle_at_rect(rect, scene_pos)
            if handle:
                return index, handle
        return -1, ""

    def _cursor_for_handle(self, handle: str) -> Qt.CursorShape:
        if handle in ("nw", "se"):
            return Qt.CursorShape.SizeFDiagCursor
        if handle in ("ne", "sw"):
            return Qt.CursorShape.SizeBDiagCursor
        if handle in ("e", "w"):
            return Qt.CursorShape.SizeHorCursor
        if handle in ("n", "s"):
            return Qt.CursorShape.SizeVerCursor
        return Qt.CursorShape.CrossCursor

    def _update_hover_cursor(self, scene_pos: QPointF) -> None:
        # A selected non-rect shape's node takes priority so its vertices stay
        # grabbable even when they sit near another shape's bbox handle.
        _, vertex = self._vertex_hit_at(scene_pos)
        if vertex >= 0:
            self.setCursor(Qt.CursorShape.SizeAllCursor)
            return
        _, handle = self._resize_hit_at(scene_pos)
        if handle:
            self.setCursor(self._cursor_for_handle(handle))
        else:
            self.setCursor(Qt.CursorShape.CrossCursor)

    def _bounded_resize_rect(self, scene_pos: QPointF) -> QRectF | None:
        if self._resize_origin is None:
            return None
        rect = QRectF(self._resize_origin)
        bounds = self._scene.sceneRect()
        min_size = self._resize_min_size
        x = min(max(scene_pos.x(), bounds.left()), bounds.right())
        y = min(max(scene_pos.y(), bounds.top()), bounds.bottom())

        if "w" in self._resize_handle:
            rect.setLeft(min(x, rect.right() - min_size))
        if "e" in self._resize_handle:
            rect.setRight(max(x, rect.left() + min_size))
        if "n" in self._resize_handle:
            rect.setTop(min(y, rect.bottom() - min_size))
        if "s" in self._resize_handle:
            rect.setBottom(max(y, rect.top() + min_size))
        return rect.normalized()

    def _clamp_to_scene(self, pos: QPointF) -> QPointF:
        """Clamp a scene-space point into the image (sceneRect) bounds.

        Keeps a freshly-drawn box inside the image edges, matching what
        ``_bounded_resize_rect`` already does for handle drags — so the
        annotation tool itself can never produce an out-of-bounds box.
        """
        b = self._scene.sceneRect()
        return QPointF(
            min(max(pos.x(), b.left()), b.right()),
            min(max(pos.y(), b.top()), b.bottom()),
        )

    def _apply_resize(self, scene_pos: QPointF) -> None:
        if self._vertex_index >= 0:
            self._apply_vertex_drag(scene_pos)
            return
        if self._annotation is None:
            return
        if not (0 <= self._resize_index < len(self._annotation.shapes)):
            return
        rect = self._bounded_resize_rect(scene_pos)
        if rect is None:
            return
        shape = self._annotation.shapes[self._resize_index]
        shape.points = [(rect.left(), rect.top()), (rect.right(), rect.bottom())]
        if 0 <= self._resize_index < len(self._shape_items):
            item = self._shape_items[self._resize_index]
            if isinstance(item, (QGraphicsRectItem, QGraphicsEllipseItem)):
                item.setRect(rect)
        self._resize_changed = True
        self._selected_index = self._resize_index
        self._update_selection_handles()

    # ---------- 编辑事件 ----------

    def mousePressEvent(self, event):  # type: ignore[override]
        if self._edit_mode and event.button() == Qt.MouseButton.RightButton:
            # 右键：取消正在进行的多边形
            if self._temp_poly_item is not None:
                self._cancel_polygon()
                return
        if self._edit_mode and event.button() == Qt.MouseButton.LeftButton and self._pix_item is not None:
            scene_pos = self.mapToScene(event.pos())
            if not (self._draw_shape_type in ("polygon", "linestrip") and self._poly_points):
                # Node drag on the selected polygon / linestrip / point /
                # circle takes priority over bbox handles.
                v_index, v_vertex = self._vertex_hit_at(scene_pos)
                if v_vertex >= 0:
                    self.select_shape(v_index)
                    self._resizing = True
                    self._resize_handle = ""
                    self._resize_index = v_index
                    self._vertex_index = v_vertex
                    self._resize_changed = False
                    self.setCursor(Qt.CursorShape.SizeAllCursor)
                    return
                resize_index, handle = self._resize_hit_at(scene_pos)
                if handle:
                    self.select_shape(resize_index)
                    self._resizing = True
                    self._resize_handle = handle
                    self._resize_index = resize_index
                    self._vertex_index = -1
                    self._resize_origin = self._shape_rect(resize_index)
                    self._resize_changed = False
                    self.setCursor(self._cursor_for_handle(handle))
                    return
            if self._draw_shape_type == "point":
                hit = self._hit_test(scene_pos)
                if hit >= 0:
                    self.select_shape(hit)
                    return
                if self._annotation is not None:
                    shape = Shape(
                        label=self._draw_label,
                        shape_type="point",
                        points=[(scene_pos.x(), scene_pos.y())],
                    )
                    self._annotation.shapes.append(shape)
                    self.set_annotation(self._annotation)
                    self.shapes_changed.emit()
                return
            # 多边形 / 折线模式：每次左键点击添加一个顶点（折线不闭合）
            if self._draw_shape_type in ("polygon", "linestrip"):
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
            # 否则开始绘制新 rect / ellipse（圆走同一套拖拽，temp 用椭圆预览）
            self._drawing = True
            # Clamp the draw origin into the image so a box dragged past the
            # edge is never created out of bounds (matches resize clamping).
            scene_pos = self._clamp_to_scene(scene_pos)
            self._draw_start = scene_pos
            color = color_for_label(self._draw_label)
            pen = QPen(color)
            pen.setWidthF(2.0)
            pen.setCosmetic(True)
            fill = QColor(color); fill.setAlpha(45)
            if self._draw_shape_type in ("circle", "ellipse"):
                self._temp_rect_item = QGraphicsEllipseItem(
                    QRectF(scene_pos, scene_pos))
            else:
                self._temp_rect_item = QGraphicsRectItem(
                    QRectF(scene_pos, scene_pos))
            self._temp_rect_item.setPen(pen)
            self._temp_rect_item.setBrush(QBrush(fill))
            self._scene.addItem(self._temp_rect_item)
            self._clear_selection_highlight()
            self._selected_index = -1
            self.selection_changed.emit(-1)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # type: ignore[override]
        # Always track cursor coords + pixel value in the HUD, whatever the
        # current interaction (drawing / resizing / panning).
        self._update_hud_readout(self.mapToScene(event.pos()))
        if self._resizing:
            self._apply_resize(self.mapToScene(event.pos()))
            return
        if self._drawing and self._temp_rect_item is not None and self._draw_start is not None:
            scene_pos = self._clamp_to_scene(self.mapToScene(event.pos()))
            if self._draw_shape_type == "circle":
                # 中心拖半径：_draw_start 是圆心，鼠标到圆心的距离是半径
                cx, cy = self._draw_start.x(), self._draw_start.y()
                r = ((scene_pos.x() - cx) ** 2 + (scene_pos.y() - cy) ** 2) ** 0.5
                self._temp_rect_item.setRect(QRectF(cx - r, cy - r, 2 * r, 2 * r))
            else:
                rect = QRectF(self._draw_start, scene_pos).normalized()
                self._temp_rect_item.setRect(rect)
            return
        if self._edit_mode and self._draw_shape_type in ("polygon", "linestrip") and self._poly_points:
            # 实时预览：把鼠标当作下一个顶点
            self._update_temp_polygon(self.mapToScene(event.pos()))
            return
        if self._edit_mode and self._pix_item is not None:
            self._update_hover_cursor(self.mapToScene(event.pos()))
        super().mouseMoveEvent(event)

    def mouseDoubleClickEvent(self, event):  # type: ignore[override]
        if self._edit_mode and self._draw_shape_type in ("polygon", "linestrip") and self._poly_points:
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
        if self._resizing:
            self._apply_resize(self.mapToScene(event.pos()))
            changed = self._resize_changed
            selected = self._resize_index
            self._clear_resize_state()
            if selected >= 0:
                self.select_shape(selected)
            if changed:
                self.shapes_changed.emit()
            return
        if self._drawing and self._temp_rect_item is not None and self._draw_start is not None:
            self._drawing = False
            if self._draw_shape_type == "circle":
                # LabelMe circle: points = [center, edge]; center is the press
                # origin, edge is where the drag ended (radius = their distance).
                end = self._clamp_to_scene(self.mapToScene(event.pos()))
                cx, cy = self._draw_start.x(), self._draw_start.y()
                r = ((end.x() - cx) ** 2 + (end.y() - cy) ** 2) ** 0.5
                self._scene.removeItem(self._temp_rect_item)
                self._temp_rect_item = None
                self._draw_start = None
                if r >= 2 and self._annotation is not None:
                    shape = Shape(
                        label=self._draw_label,
                        shape_type="circle",
                        points=[(cx, cy), (end.x(), end.y())],
                    )
                    self._annotation.shapes.append(shape)
                    self.set_annotation(self._annotation)
                    self.shapes_changed.emit()
                return
            rect = self._temp_rect_item.rect()
            self._scene.removeItem(self._temp_rect_item)
            self._temp_rect_item = None
            self._draw_start = None
            if rect.width() >= 3 and rect.height() >= 3 and self._annotation is not None:
                shape = Shape(
                    label=self._draw_label,
                    # Same bbox-drag path as rectangle; only the stored type
                    # (and thus the rendered geometry) differs.
                    shape_type=("ellipse" if self._draw_shape_type == "ellipse"
                                else "rectangle"),
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
