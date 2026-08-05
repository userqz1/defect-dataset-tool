"""Picking a row in the shape list must point at the box on the canvas.

Two things broke that, and neither showed up in a pane-level test:

1. The row's class dropdown stretches across most of the row. Being a
   real interactive widget it consumed the mouse press, so clicking the
   class name — the obvious target — selected nothing. Only the few-pixel
   colour dot worked, because a plain QLabel ignores the press and lets
   it reach the list viewport.
2. Even once selected, browse mode drew no vertex markers (they were
   gated on edit mode), so the only feedback was the outline going from
   2.0 to 3.5 px — far too quiet to find one box among many.

Clicks here are routed through ``childAt`` on purpose. Sending them
straight to ``shape_list.viewport()`` bypasses the very widget that was
eating them, which makes the broken code look fine.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6", reason="GUI test")

from PyQt6.QtCore import QPoint, Qt  # noqa: E402
from PyQt6.QtGui import QImage, QPixmap  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from core.models import Annotation, Shape  # noqa: E402
from gui.views.panes.annotation_pane import AnnotationPane  # noqa: E402
from gui.widgets.image_viewer import ImageViewer  # noqa: E402


def _shapes() -> list[Shape]:
    return [
        Shape(label="marked_normal", shape_type="rectangle",
              points=[(10, 10), (60, 60)]),
        Shape(label="marked_loose", shape_type="rectangle",
              points=[(70, 70), (120, 120)]),
        Shape(label="TODO", shape_type="polygon",
              points=[(130, 20), (180, 40), (160, 90)]),
    ]


def _pane() -> AnnotationPane:
    pane = AnnotationPane()
    pane.set_class_names(["marked_loose", "marked_normal", "TODO"])
    pane.refresh_shape_list(Annotation(image_path=None, shapes=_shapes()))
    pane.resize(420, 300)
    pane.show()
    QApplication.processEvents()
    return pane


def _click(pane: AnnotationPane, row: int, where: str) -> None:
    """Click a row the way the window system delivers it."""
    lst = pane.shape_list
    w = lst.itemWidget(lst.item(row))
    pt = {
        "class": QPoint(w.width() // 2, w.height() // 2),
        "dot": QPoint(6, w.height() // 2),
        "type": QPoint(w.width() - 25, w.height() // 2),
    }[where]
    target = w.childAt(pt) or w
    QTest.mouseClick(target, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, target.mapFrom(w, pt))
    QApplication.processEvents()


@pytest.mark.parametrize("where", ["class", "dot", "type"])
def test_clicking_anywhere_on_a_row_selects_it(qapp, where):
    pane = _pane()
    seen: list[int] = []
    pane.shape_selected.connect(seen.append)
    try:
        # Start elsewhere so "already selected" can't fake a pass.
        pane.shape_list.setCurrentRow(0)
        seen.clear()
        _click(pane, 2, where)
        assert pane.shape_list.currentRow() == 2, (
            f"clicking the {where!r} part of row 2 did not select it"
        )
        assert seen == [2], f"shape_selected not emitted for {where!r}"
    finally:
        pane.hide()


def test_the_class_dropdown_still_opens(qapp):
    """The click filter must not consume the press it observes."""
    from qfluentwidgets import ComboBox

    pane = _pane()
    try:
        lst = pane.shape_list
        combo = lst.itemWidget(lst.item(1)).findChild(ComboBox)
        assert combo is not None
        assert combo.isEnabled()
        # Its options survive the filter being installed.
        items = [combo.itemText(i) for i in range(combo.count())]
        assert "marked_normal" in items and "TODO" in items
    finally:
        pane.hide()


def _viewer() -> ImageViewer:
    v = ImageViewer()
    img = QImage(240, 200, QImage.Format.Format_RGB32)
    img.fill(0x202020)
    v.load_pixmap(QPixmap.fromImage(img))
    v.set_annotation(Annotation(image_path=None, shapes=_shapes()))
    return v


@pytest.mark.parametrize("index,expected", [(0, 8), (1, 8), (2, 3)])
def test_browse_mode_marks_the_selected_shape_points(qapp, index, expected):
    """Rectangles get their 8 bbox points, a 3-point polygon its 3."""
    v = _viewer()
    assert not v._edit_mode, "this test is about browse mode"
    v.select_shape(index)
    assert len(v._handle_items) == expected


def test_deselecting_clears_the_markers(qapp):
    v = _viewer()
    v.select_shape(1)
    assert v._handle_items
    v.select_shape(-1)
    assert v._handle_items == []


def test_hiding_annotations_hides_the_markers(qapp):
    v = _viewer()
    v.set_annotation_visible(False)
    v.select_shape(1)
    assert v._handle_items == [], "markers drawn while annotations are hidden"


@pytest.mark.parametrize("target", [0, 1])
def test_clicking_a_box_on_the_canvas_selects_it_in_browse_mode(qapp, target):
    """The other direction: canvas → list.

    Shape hit-testing lived entirely inside ``if self._edit_mode``, so a
    left click in browse mode only panned — nothing was selected, and the
    list never highlighted the matching row.
    """
    v = _viewer()
    v.resize(400, 340)
    v.show()
    QApplication.processEvents()
    try:
        assert not v._edit_mode
        (sx, sy), (ex, ey) = _shapes()[target].points[:2]
        pt = v.mapFromScene((sx + ex) / 2, (sy + ey) / 2)
        QTest.mouseClick(v.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, pt)
        QApplication.processEvents()
        assert v._selected_index == target
        assert v._handle_items, "selection drew no markers"
    finally:
        v.hide()


def test_clicking_empty_canvas_clears_the_selection(qapp):
    v = _viewer()
    v.resize(400, 340)
    v.show()
    QApplication.processEvents()
    try:
        v.select_shape(0)
        # Far corner: outside every shape in _shapes().
        QTest.mouseClick(v.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier,
                         v.mapFromScene(5, 195))
        QApplication.processEvents()
        assert v._selected_index == -1
        assert v._handle_items == []
    finally:
        v.hide()


def test_browse_mode_click_does_not_touch_the_annotation(qapp):
    """Selecting must never be an edit — no shape added, moved or dropped."""
    v = _viewer()
    v.resize(400, 340)
    v.show()
    QApplication.processEvents()
    try:
        before = [(s.label, s.shape_type, list(s.points))
                  for s in v._annotation.shapes]
        for x, y in ((45, 45), (5, 195), (95, 95)):
            QTest.mouseClick(v.viewport(), Qt.MouseButton.LeftButton,
                             Qt.KeyboardModifier.NoModifier,
                             v.mapFromScene(x, y))
            QApplication.processEvents()
        after = [(s.label, s.shape_type, list(s.points))
                 for s in v._annotation.shapes]
        assert after == before
    finally:
        v.hide()
