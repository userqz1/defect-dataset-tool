"""Image viewer with mouse-wheel zoom, drag-pan, and LabelMe annotation overlay."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, Qt
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

# 一组高对比度但低饱和的标注颜色
PALETTE = [
    "#c96442", "#5a7a3c", "#3a6a7a", "#7a5a8a", "#b8842b",
    "#a85a3a", "#456b9c", "#8a5a4a", "#5a8a8a", "#7a6a3a",
]


def color_for_label(label: str) -> QColor:
    idx = abs(hash(label)) % len(PALETTE)
    return QColor(PALETTE[idx])


class ImageViewer(QGraphicsView):
    def __init__(self) -> None:
        super().__init__()
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setBackgroundBrush(QBrush(QColor("#f3f1ea")))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)

        self._pix_item: QGraphicsPixmapItem | None = None
        self._shape_items: list = []
        self._scale: float = 1.0

    def load_image(self, path: Path) -> None:
        """Load an image, replacing scene contents."""
        self._scene.clear()
        self._shape_items.clear()
        self._pix_item = None

        # 用 QImage 然后转 QPixmap，能更好兼容中文路径
        image = QImage(str(path))
        if image.isNull():
            return
        pix = QPixmap.fromImage(image)
        self._pix_item = self._scene.addPixmap(pix)
        self._scene.setSceneRect(QRectF(pix.rect()))
        self.fit_to_window()

    def set_annotation(self, annotation: Annotation | None) -> None:
        """Draw shapes overlaid on the current image."""
        for it in self._shape_items:
            self._scene.removeItem(it)
        self._shape_items.clear()
        if annotation is None or self._pix_item is None:
            return
        for shape in annotation.shapes:
            item = self._make_shape_item(shape)
            if item is not None:
                self._scene.addItem(item)
                self._shape_items.append(item)

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
            item.setBrush(QBrush(QColor(0, 0, 0, 0)))
            item.setToolTip(shape.label)
            return item
        return None

    def fit_to_window(self) -> None:
        if self._pix_item is None:
            return
        self.resetTransform()
        self.fitInView(self._pix_item, Qt.AspectRatioMode.KeepAspectRatio)
        self._scale = self.transform().m11()

    def reset_view(self) -> None:
        self.fit_to_window()

    def wheelEvent(self, event: QWheelEvent) -> None:  # type: ignore[override]
        if self._pix_item is None:
            return
        factor = 1.18 if event.angleDelta().y() > 0 else 1 / 1.18
        new_scale = self._scale * factor
        if 0.05 < new_scale < 40:
            self.scale(factor, factor)
            self._scale = new_scale
