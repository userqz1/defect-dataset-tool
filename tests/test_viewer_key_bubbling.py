"""ImageViewer must not swallow the prev/next-image arrow keys.

``ImageViewer`` extends ``QGraphicsView``, which claims Left/Right to
scroll its viewport. Because annotating means clicking the image, focus
lives on the viewer, so those keys stopped reaching
``DetailView.keyPressEvent`` and prev/next-image silently did nothing —
while ``A``/``D`` kept working, because QGraphicsView does not handle
*those* and Qt bubbles unhandled keys to the parent.

These tests pin the bubbling, not the implementation: they assert the
parent actually receives the key.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6", reason="viewer is a PyQt widget")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtGui import QKeyEvent  # noqa: E402
from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

from gui.widgets.image_viewer import ImageViewer  # noqa: E402


class _Catcher(QWidget):
    """Stands in for DetailView: records keys that bubble up to it."""

    def __init__(self):
        super().__init__()
        self.seen: list[int] = []

    def keyPressEvent(self, e):  # noqa: N802 - Qt override
        self.seen.append(e.key())


def _child_viewer(parent: QWidget) -> ImageViewer:
    """ImageViewer takes no parent arg; reparent so keys have somewhere to go."""
    viewer = ImageViewer()
    viewer.setParent(parent)
    return viewer


def _press(widget, key: int) -> QKeyEvent:
    ev = QKeyEvent(QKeyEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, ev)
    return ev


@pytest.mark.parametrize("key", [Qt.Key.Key_Left, Qt.Key.Key_Right])
def test_arrow_keys_bubble_to_the_parent(qapp, key):
    parent = _Catcher()
    viewer = _child_viewer(parent)
    _press(viewer, key)
    assert parent.seen == [key], "arrow key was swallowed by the viewer"


@pytest.mark.parametrize("key", [Qt.Key.Key_A, Qt.Key.Key_D])
def test_letter_shortcuts_still_bubble(qapp, key):
    """The path that already worked must keep working."""
    parent = _Catcher()
    viewer = _child_viewer(parent)
    _press(viewer, key)
    assert parent.seen == [key]


@pytest.mark.parametrize("key", [Qt.Key.Key_Up, Qt.Key.Key_Down])
def test_vertical_arrows_are_left_to_the_viewer(qapp, key):
    """Only Left/Right are image navigation; Up/Down stay the viewer's."""
    parent = _Catcher()
    viewer = _child_viewer(parent)
    _press(viewer, key)
    assert parent.seen == []
