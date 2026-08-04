"""The viewer status strip must never sit on top of the image.

It used to float over the bottom-left corner of the viewport, hiding
pixels the user may need to inspect or annotate. It now gets a reserved
strip via ``setViewportMargins``.

These tests assert the geometric consequence — the strip and the viewport
do not overlap — rather than the mechanism, so a future re-implementation
that keeps the promise still passes.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6", reason="viewer is a PyQt widget")

from PyQt6.QtGui import QImage, QPixmap  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from gui.widgets.image_viewer import ImageViewer  # noqa: E402


def _viewer(qapp, w=900, h=600) -> ImageViewer:
    v = ImageViewer()
    v.resize(w, h)
    v.show()          # without this the resize never reaches the viewport
    QApplication.processEvents()
    return v


@pytest.mark.parametrize(("w", "h"), [(1400, 900), (900, 600), (420, 300)])
def test_strip_never_overlaps_the_viewport(qapp, w, h):
    v = _viewer(qapp, w, h)
    assert not v.viewport().geometry().intersects(v._hud.geometry()), (
        "status strip overlaps the image area"
    )


def test_strip_sits_below_the_viewport(qapp):
    v = _viewer(qapp)
    assert v._hud.geometry().top() >= v.viewport().geometry().bottom()


def test_viewport_is_shorter_than_the_view_by_the_strip(qapp):
    """The strip is carved out of the scroll area, not painted over it."""
    v = _viewer(qapp)
    assert v.viewportMargins().bottom() == v._hud.sizeHint().height()
    assert v.viewport().height() < v.height()


def test_still_no_overlap_after_zooming_in(qapp):
    """Zoom changes the scene transform, not the reservation."""
    v = _viewer(qapp)
    img = QImage(2000, 1500, QImage.Format.Format_RGB32)
    img.fill(0x3366AA)
    v.load_pixmap(QPixmap.fromImage(img))
    QApplication.processEvents()
    for _ in range(6):
        v._apply_zoom(1.18)
    QApplication.processEvents()
    assert not v.viewport().geometry().intersects(v._hud.geometry())


def test_strip_spans_the_viewport_width(qapp):
    v = _viewer(qapp, 1200, 700)
    assert v._hud.geometry().width() == v.viewport().geometry().width()
