"""Drill-out must land the grid on the image DetailView was showing.

The grid is infinite-scroll: only the first CHUNK_SIZE items exist as
widgets. An image the user reached by paging inside DetailView (the
motivating report was the 612th) has no row at all, so "scroll to it" is
not enough — the chunks in between have to be materialized first.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6", reason="grid is a PyQt widget")

from core.models import ImageInfo  # noqa: E402
from gui.app_state import AppState  # noqa: E402
from gui.views.browser_view import CHUNK_SIZE, BrowserView  # noqa: E402


def _images(n: int) -> list[ImageInfo]:
    return [
        ImageInfo(path=Path(f"C:/ds/cat/images/img_{i:05d}.png"),
                  category="cat", width=64, height=64, has_label=False)
        for i in range(n)
    ]


@pytest.fixture
def view(qapp):
    """A BrowserView with 800 images already filtered in.

    ``_filtered`` + ``_show_page`` is the state the grid is in after a
    scan; driving it directly keeps the test off the scan worker.
    """
    v = BrowserView(AppState())
    v._filtered = _images(800)
    v._show_page()
    return v


def test_only_the_first_chunk_starts_materialized(view):
    """Guards the premise — if this changes the rest is testing nothing."""
    assert view.grid.count() == CHUNK_SIZE
    assert view._visible_count == CHUNK_SIZE


def test_reveal_far_image_materializes_and_selects(view):
    target = view._filtered[611]          # the 612th
    assert view.reveal_image(target) is True
    assert view.grid.count() > 611
    assert view._visible_count > 611
    selected = view.grid.selected_images()
    assert [str(i.path) for i in selected] == [str(target.path)]


def test_reveal_does_not_materialize_the_whole_list(view):
    """Walk out to the target, not to the end — 800 rows would be waste."""
    view.reveal_image(view._filtered[611])
    assert view.grid.count() < 800


def test_reveal_image_already_in_first_chunk(view):
    target = view._filtered[3]
    assert view.reveal_image(target) is True
    assert view.grid.count() == CHUNK_SIZE      # nothing extra loaded
    assert view.grid.selected_images()[0].path == target.path


def test_reveal_last_image(view):
    target = view._filtered[-1]
    assert view.reveal_image(target) is True
    assert view._visible_count == 800


def test_reveal_returns_false_for_a_filtered_out_image(view):
    """Category/search changed while in detail, or the image was deleted."""
    stranger = ImageInfo(path=Path("C:/ds/other/images/nope.png"),
                         category="other", width=1, height=1, has_label=False)
    assert view.reveal_image(stranger) is False
    assert view.grid.selected_images() == []


def test_reveal_none_is_a_noop(view):
    assert view.reveal_image(None) is False


def test_reveal_replaces_rather_than_adds_to_the_selection(view):
    view.reveal_image(view._filtered[2])
    view.reveal_image(view._filtered[611])
    assert len(view.grid.selected_images()) == 1
