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


# ---------- the per-row class dropdown ----------

def _pane_with_rows(labels: list[str]) -> AnnotationPane:
    pane = AnnotationPane()
    pane.set_class_names(CLASSES)
    pane.refresh_shape_list(Annotation(image_path=None, shapes=[
        Shape(label=lbl, shape_type="rectangle", points=[(0, 0), (9, 9)])
        for lbl in labels
    ]))
    return pane


def _combo(pane: AnnotationPane, row: int):
    from qfluentwidgets import ComboBox
    widget = pane.shape_list.itemWidget(pane.shape_list.item(row))
    return widget.findChild(ComboBox)


def _items(combo) -> list[str]:
    return [combo.itemText(i) for i in range(combo.count())]


def test_every_row_carries_a_class_dropdown(qapp):
    pane = _pane_with_rows(["marked_loose", "marked_normal"])
    assert _combo(pane, 0) is not None
    assert _combo(pane, 1) is not None


def test_dropdown_shows_the_shapes_own_class(qapp):
    pane = _pane_with_rows(["marked_normal", "marked_loose"])
    assert _combo(pane, 0).currentText() == "marked_normal"
    assert _combo(pane, 1).currentText() == "marked_loose"


def test_class_outside_the_project_list_is_still_shown(qapp):
    """Imported data carries these — a "TODO" placeholder, say. Opening
    the dropdown must not silently retarget such a shape."""
    pane = _pane_with_rows(["TODO"])
    combo = _combo(pane, 0)
    assert combo.currentText() == "TODO"
    assert "TODO" in _items(combo)


def test_dropdown_offers_a_way_to_type_a_new_class(qapp):
    """The combo is non-editable (that is the crash fix), so a brand-new
    name needs this entry."""
    from gui.views.panes.annotation_pane import NEW_CLASS_ENTRY
    assert NEW_CLASS_ENTRY in _items(_combo(_pane_with_rows(["TODO"]), 0))


def test_the_dropdown_is_not_an_editable_combo(qapp):
    """Regression guard for the native crash.

    EditableComboBox subclasses QLineEdit and owns a LineEditButton;
    churning those inside the list flooded Qt with "disconnect from
    destroyed signal" and killed the process. Measured: 300 rebuild
    rounds → 1801 warnings with EditableComboBox, 0 with ComboBox.
    """
    from qfluentwidgets import EditableComboBox
    combo = _combo(_pane_with_rows(["marked_loose"]), 0)
    assert not isinstance(combo, EditableComboBox)


def test_same_count_refresh_reuses_rows_instead_of_rebuilding(qapp):
    """The churn fix. refresh_shape_list runs on *every* shape edit; if
    it destroyed and recreated the row widgets each time we would be back
    at the crash."""
    pane = _pane_with_rows(["marked_loose", "marked_normal"])
    built = []
    real = pane._build_row_widget
    pane._build_row_widget = lambda i: (built.append(i), real(i))[1]
    before = [_combo(pane, 0), _combo(pane, 1)]
    pane.refresh_shape_list(Annotation(image_path=None, shapes=[
        Shape(label="unmarked_normal", shape_type="rectangle",
              points=[(0, 0), (9, 9)]),
        Shape(label="marked_loose", shape_type="rectangle",
              points=[(0, 0), (9, 9)]),
    ]))
    assert built == [], "rows were rebuilt for a same-count refresh"
    # Same widget objects, updated in place.
    assert [_combo(pane, 0), _combo(pane, 1)] == before
    assert _combo(pane, 0).currentText() == "unmarked_normal"


def test_row_count_change_does_rebuild(qapp):
    pane = _pane_with_rows(["marked_loose", "marked_normal"])
    pane.refresh_shape_list(Annotation(image_path=None, shapes=[
        Shape(label="marked_loose", shape_type="rectangle",
              points=[(0, 0), (9, 9)]),
    ]))
    assert pane.shape_list.count() == 1
    assert _combo(pane, 0).currentText() == "marked_loose"


def test_refreshing_emits_nothing(qapp):
    """Populating the combos must not read as the user picking classes."""
    pane = _pane_with_rows(["marked_loose"])
    seen = []
    pane.rename_shape_requested.connect(lambda r, c: seen.append((r, c)))
    pane.refresh_shape_list(Annotation(image_path=None, shapes=[
        Shape(label="marked_normal", shape_type="rectangle",
              points=[(0, 0), (9, 9)]),
    ]))
    assert seen == []


def test_picking_a_class_asks_for_the_reclassify(qapp):
    pane = _pane_with_rows(["marked_loose", "marked_normal"])
    seen = []
    pane.rename_shape_requested.connect(lambda r, c: seen.append((r, c)))
    combo = _combo(pane, 1)
    combo.setCurrentText("unmarked_normal")
    pane._on_row_class_picked(1, combo)
    assert seen == [(1, "unmarked_normal")]


def test_picking_the_unchanged_class_is_a_noop(qapp):
    pane = _pane_with_rows(["marked_loose"])
    seen = []
    pane.rename_shape_requested.connect(lambda r, c: seen.append((r, c)))
    pane._on_row_class_picked(0, _combo(pane, 0))
    assert seen == []


# ---------- the dropdown must agree with the shortcuts ----------

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
