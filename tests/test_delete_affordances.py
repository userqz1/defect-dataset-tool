"""The two deletes in the annotation workbench must not look alike.

One drops a shape and is restorable from the local undo stack; the other
unlinks the image file with no recycle bin, no undo and (today) no audit
record. They previously shared ``ToolButton(FIF.DELETE)`` — same icon,
same size, same shape — with only a tooltip to tell them apart.

Asserted on properties a user actually perceives: does it carry a word,
is it the same icon, is it even the same size of control.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6", reason="GUI test")

from qfluentwidgets import FluentIcon as FIF  # noqa: E402

from gui.views.detail_view import DetailView  # noqa: E402
from gui.views.panes.annotation_pane import AnnotationPane  # noqa: E402


@pytest.fixture
def detail(qapp):
    return DetailView()


@pytest.fixture
def pane(qapp):
    return AnnotationPane()


def test_image_delete_is_labelled(detail):
    """A bare icon is what made the two confusable."""
    assert "图片" in detail.delete_img_btn.text()


def test_shape_delete_stays_icon_only(pane):
    """It is contextual, sitting beside the shape list it acts on."""
    assert pane.delete_btn.text() == ""


def test_the_two_do_not_share_an_icon(detail, pane):
    assert detail.delete_img_btn.icon().cacheKey() != \
        pane.delete_btn.icon().cacheKey()


def test_image_delete_does_not_use_the_shape_delete_icon(detail):
    trash = FIF.DELETE.icon()
    assert detail.delete_img_btn.icon().cacheKey() != trash.cacheKey()


def test_image_delete_is_visibly_wider(detail, pane):
    """Different silhouette, not just different pixels inside the same box."""
    assert detail.delete_img_btn.sizeHint().width() > \
        pane.delete_btn.sizeHint().width() * 2


def test_both_tooltips_name_their_target(detail, pane):
    assert "图片" in detail.delete_img_btn.toolTip()
    assert "标注" in pane.delete_btn.toolTip()


def test_image_delete_tooltip_warns_it_is_permanent(detail):
    tip = detail.delete_img_btn.toolTip()
    assert "永久" in tip and "不可恢复" in tip


def test_image_delete_hides_rather_than_dropping_its_label(detail):
    """Narrow windows must not silently turn it back into a bare icon."""
    detail.resize(900, 700)
    detail._apply_toolbar_compact()
    assert not detail.delete_img_btn.isVisible()
    assert "图片" in detail.delete_img_btn.text()
