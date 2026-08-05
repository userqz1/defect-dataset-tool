"""Reclassifying a box must not require retyping its class name.

Before this, the only way to move a box to another class was an inline
rename — typing the whole name, per box. Two faster paths now exist and
they must agree: the 1-9 shortcuts and the right-click "改为类别" list
index into the *same* ordered vocabulary, or "press 3" and the menu's
"3" would be different classes.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6", reason="GUI test")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtGui import QImage, QKeyEvent, QPixmap  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from core.models import Annotation, Shape  # noqa: E402
from gui.views.detail_view import DetailView  # noqa: E402
from gui.views.panes.annotation_pane import AnnotationPane  # noqa: E402

CLASSES = ["marked_loose", "marked_normal", "unmarked_normal"]


def _annotation() -> Annotation:
    return Annotation(image_path=None, shapes=[
        Shape(label="marked_loose", shape_type="rectangle",
              points=[(10, 10), (50, 50)]),
        Shape(label="marked_normal", shape_type="rectangle",
              points=[(60, 60), (90, 90)]),
    ])


@pytest.fixture
def view(qapp, monkeypatch):
    v = DetailView()
    img = QImage(200, 200, QImage.Format.Format_RGB32)
    img.fill(0x202020)
    v.viewer.load_pixmap(QPixmap.fromImage(img))
    v._annotation = _annotation()
    v.viewer.set_annotation(v._annotation)
    # Build the vocabulary the way production does, so the pane gets it
    # through the real sync path rather than by assignment here.
    v._project_class_names = list(CLASSES)
    v._refresh_label_combo()
    # Write gate + autosave are exercised elsewhere; keep this about the
    # reclassify logic.
    monkeypatch.setattr(v, "_block_write_if_scanning", lambda: False)
    monkeypatch.setattr(v, "_mark_dirty", lambda: None)
    return v


def _press(widget, key) -> None:
    QApplication.sendEvent(
        widget,
        QKeyEvent(QKeyEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier),
    )


def test_number_key_reassigns_the_selected_shape(view):
    view.viewer.select_shape(0)
    _press(view, Qt.Key.Key_3)
    assert view._annotation.shapes[0].label == "unmarked_normal"


def test_other_shapes_are_untouched(view):
    view.viewer.select_shape(0)
    _press(view, Qt.Key.Key_3)
    assert view._annotation.shapes[1].label == "marked_normal"


def test_selection_survives_so_a_mistake_can_be_corrected(view):
    """The whole point of a shortcut is chaining; 3 then 2 must both land."""
    view.viewer.select_shape(1)
    _press(view, Qt.Key.Key_3)
    assert view.viewer.selected_index() == 1
    _press(view, Qt.Key.Key_1)
    assert view._annotation.shapes[1].label == "marked_loose"


def test_number_key_with_nothing_selected_is_ignored(view):
    view.viewer.select_shape(-1)
    before = [s.label for s in view._annotation.shapes]
    _press(view, Qt.Key.Key_2)
    assert [s.label for s in view._annotation.shapes] == before


def test_slot_beyond_the_class_list_is_ignored(view):
    view.viewer.select_shape(0)
    _press(view, Qt.Key.Key_9)          # only 3 classes exist
    assert view._annotation.shapes[0].label == "marked_loose"


def test_reclassify_is_undoable(view):
    view.viewer.select_shape(0)
    _press(view, Qt.Key.Key_2)
    assert view._annotation.shapes[0].label == "marked_normal"
    assert view._undo_stack, "no snapshot pushed — Ctrl+Z would lose the edit"


def test_digit_zero_is_not_bound(view):
    """Slots are 1-based; 0 must not silently mean class 1."""
    view.viewer.select_shape(0)
    _press(view, Qt.Key.Key_0)
    assert view._annotation.shapes[0].label == "marked_loose"


# ---------- the menu must agree with the shortcuts ----------

def test_pane_offers_the_classes_it_was_given(qapp):
    pane = AnnotationPane()
    pane.set_class_names(CLASSES)
    assert pane._class_names == CLASSES


def test_pane_drops_empty_names(qapp):
    pane = AnnotationPane()
    pane.set_class_names(["a", "", "b"])
    assert pane._class_names == ["a", "b"]


def test_view_pushes_its_vocabulary_to_the_pane(view):
    """Same list object contents → menu numbering matches the shortcuts."""
    if view._annotation_pane is None:
        pytest.skip("spec for this task type has no annotation pane")
    assert view._annotation_pane._class_names == view._quick_labels
