"""Deleting must not throw the user back to the first image.

Any delete mutates the dataset, which re-runs the filter and calls
``_show_page`` — that resets to the first chunk and scrolls to the top.
The fix is a one-shot "land here after the next render" request, armed
*before* the delete while the victims' neighbours are still known.

Also covers DetailView's advance-after-delete, which has to leave the
viewer on the following image rather than reloading the deleted one.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6", reason="GUI test")

from core.models import ImageInfo  # noqa: E402
from gui.app_state import AppState  # noqa: E402
from gui.views.browser_view import CHUNK_SIZE, BrowserView  # noqa: E402
from gui.views.detail_view import DetailView  # noqa: E402


def _images(n: int) -> list[ImageInfo]:
    return [
        ImageInfo(path=Path(f"C:/ds/cat/images/img_{i:05d}.png"),
                  category="cat", width=64, height=64, has_label=False)
        for i in range(n)
    ]


@pytest.fixture
def view(qapp):
    v = BrowserView(AppState())
    v._filtered = _images(300)
    v._show_page()
    return v


# ---------- choosing where to land ----------

def test_neighbour_is_the_image_after_the_victim(view):
    doomed = [view._filtered[10]]
    assert view.neighbour_after_removing(doomed) == str(
        view._filtered[11].path)


def test_neighbour_skips_a_contiguous_block(view):
    doomed = view._filtered[10:15]
    assert view.neighbour_after_removing(doomed) == str(
        view._filtered[15].path)


def test_neighbour_of_the_last_image_falls_back_to_the_previous(view):
    doomed = [view._filtered[-1]]
    assert view.neighbour_after_removing(doomed) == str(
        view._filtered[-2].path)


def test_neighbour_is_none_when_everything_goes(view):
    assert view.neighbour_after_removing(list(view._filtered)) is None


# ---------- surviving the re-render ----------

def test_render_after_delete_lands_on_the_neighbour_not_image_one(view):
    """The actual reported bug."""
    doomed = view._filtered[199]
    survivor = view.neighbour_after_removing([doomed])
    view.request_reveal_after_render(survivor)

    # What a delete does: image disappears, filter re-runs, page resets.
    view._filtered = [i for i in view._filtered if str(i.path) != str(doomed.path)]
    view._show_page()

    selected = view.grid.selected_images()
    assert [str(i.path) for i in selected] == [survivor]
    assert view.grid.count() > CHUNK_SIZE      # walked out to it


def test_request_is_consumed_once(view):
    view.request_reveal_after_render(str(view._filtered[150].path))
    view._show_page()
    assert view.grid.selected_images()
    view._show_page()                          # an unrelated later render
    assert view.grid.selected_images() == []


def test_a_target_that_vanished_is_dropped_quietly(view):
    view.request_reveal_after_render("C:/ds/cat/images/gone.png")
    view._show_page()
    assert view.grid.selected_images() == []
    assert view._reveal_after_render is None


def test_none_target_disarms(view):
    view.request_reveal_after_render(None)
    assert view._reveal_after_render is None


# ---------- DetailView advance ----------

@pytest.fixture
def detail(qapp, monkeypatch):
    d = DetailView()
    monkeypatch.setattr(d, "_load_current", lambda: None)
    return d


def test_advance_lands_on_the_following_image(detail):
    imgs = _images(5)
    detail._images = list(imgs)
    detail._index = 2
    assert detail.drop_current_and_advance() is True
    assert len(detail._images) == 4
    assert detail.current_image().path == imgs[3].path


def test_advance_from_the_last_image_steps_back(detail):
    imgs = _images(3)
    detail._images = list(imgs)
    detail._index = 2
    assert detail.drop_current_and_advance() is True
    assert detail.current_image().path == imgs[1].path


def test_advance_on_the_only_image_goes_back_to_the_grid(detail):
    seen = []
    detail.back_requested.connect(lambda: seen.append(1))
    detail._images = _images(1)
    detail._index = 0
    assert detail.drop_current_and_advance() is False
    assert seen == [1]
    assert detail._images == []


def test_advance_with_no_image_is_a_noop(detail):
    detail._images = []
    detail._index = -1
    assert detail.drop_current_and_advance() is False
