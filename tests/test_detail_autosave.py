"""Autosave state machine in DetailView.

Exercises the real preference path (a temp settings.json) rather than
stubbing ``_autosave_enabled``, so a regression in the loader shows up
here too. ``_on_save`` itself is replaced by a counter — what matters is
*when* a save is triggered, not the writer, which has its own tests.
"""
from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6", reason="DetailView is a PyQt widget")

from core import user_settings  # noqa: E402
from gui.views.detail_view import DetailView  # noqa: E402


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    monkeypatch.setattr(user_settings, "SETTINGS_PATH", path)
    return path


def _set_autosave(path, on: bool) -> None:
    path.write_text(json.dumps({"theme": "light", "autosave": on}),
                    encoding="utf-8")


@pytest.fixture
def view(qapp, settings_file, monkeypatch):
    v = DetailView()
    v.saves: list[int] = []
    monkeypatch.setattr(v, "_on_save", lambda: v.saves.append(1))
    return v


# ---------- autosave ON ----------

def test_mark_dirty_arms_the_timer(view, settings_file):
    _set_autosave(settings_file, True)
    view._mark_dirty()
    assert view._dirty is True
    assert view._autosave_timer.isActive()


def test_burst_of_edits_coalesces_into_one_save(view, settings_file):
    """Debounce contract: rapid edits must not mean rapid writes."""
    _set_autosave(settings_file, True)
    for _ in range(5):
        view._mark_dirty()
    assert view._autosave_timer.isActive()
    assert view.saves == []          # nothing written yet
    view._flush_autosave()
    assert view.saves == [1]         # exactly one


def test_flush_writes_and_disarms(view, settings_file):
    _set_autosave(settings_file, True)
    view._mark_dirty()
    view._flush_autosave()
    assert view.saves == [1]
    assert not view._autosave_timer.isActive()


def test_flush_is_a_noop_when_clean(view, settings_file):
    _set_autosave(settings_file, True)
    view._flush_autosave()
    assert view.saves == []


def test_navigating_flushes_instead_of_prompting(view, settings_file):
    """_confirm_discard is the funnel every navigation path goes through."""
    _set_autosave(settings_file, True)
    view._mark_dirty()
    assert view._confirm_discard() is True   # no modal, no blocking
    assert view.saves == [1]


def test_hiding_the_view_flushes(view, settings_file):
    """Leaving the stage / closing the window hides the view.

    ``show()`` first because Qt only delivers hideEvent to a widget that
    is actually visible — in the app DetailView always is, sitting in the
    workbench's page stack.
    """
    _set_autosave(settings_file, True)
    view.show()
    view._mark_dirty()
    view.hide()
    assert view.saves == [1]


def test_loading_an_image_disarms_a_pending_timer(view, settings_file):
    """A timer left armed would fire against the newly loaded image."""
    _set_autosave(settings_file, True)
    view._mark_dirty()
    assert view._autosave_timer.isActive()
    view._autosave_timer.stop()      # what _load_current does
    view._dirty = False
    view._autosave_fire()
    assert view.saves == []


# ---------- autosave OFF ----------

def test_disabled_marks_dirty_without_arming(view, settings_file):
    _set_autosave(settings_file, False)
    view._mark_dirty()
    assert view._dirty is True
    assert not view._autosave_timer.isActive()
    assert view.saves == []


def test_disabled_flush_writes_nothing(view, settings_file):
    _set_autosave(settings_file, False)
    view._mark_dirty()
    view._flush_autosave()
    assert view.saves == []


def test_timer_firing_after_disabling_writes_nothing(view, settings_file):
    """Toggle is read per call, so an in-flight timer respects the change."""
    _set_autosave(settings_file, True)
    view._mark_dirty()
    _set_autosave(settings_file, False)
    view._autosave_fire()
    assert view.saves == []
