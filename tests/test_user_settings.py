"""User-preference persistence.

``autosave`` writes the user's label files without asking, so the loader
must never turn it on/off by accident: an older settings.json, a
hand-edited one, or a garbage value all have to land on the documented
default rather than on whatever ``bool()`` would say.
"""
from __future__ import annotations

import json

import pytest

from core import user_settings
from core.user_settings import UserSettings, load_settings, save_settings


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(
        user_settings, "SETTINGS_PATH", tmp_path / "settings.json")


def test_defaults_when_no_file():
    s = load_settings()
    assert s.theme == "light"
    assert s.autosave is True


def test_roundtrip():
    save_settings(UserSettings(theme="dark", autosave=False))
    s = load_settings()
    assert s.theme == "dark"
    assert s.autosave is False


def test_older_settings_file_without_the_key_keeps_the_default():
    """A settings.json written before autosave existed."""
    user_settings.SETTINGS_PATH.write_text(
        json.dumps({"theme": "dark"}), encoding="utf-8")
    assert load_settings().autosave is True


@pytest.mark.parametrize("junk", ["true", "no", 0, 1, None, [], {}])
def test_non_bool_autosave_falls_back_to_the_default(junk):
    user_settings.SETTINGS_PATH.write_text(
        json.dumps({"theme": "light", "autosave": junk}), encoding="utf-8")
    assert load_settings().autosave is True


def test_explicit_false_is_honoured():
    """The one case that must NOT be coerced back to the default."""
    user_settings.SETTINGS_PATH.write_text(
        json.dumps({"theme": "light", "autosave": False}), encoding="utf-8")
    assert load_settings().autosave is False


def test_corrupt_file_falls_back_to_defaults():
    user_settings.SETTINGS_PATH.write_text("{not json", encoding="utf-8")
    s = load_settings()
    assert s.theme == "light"
    assert s.autosave is True


def test_non_dict_json_falls_back_to_defaults():
    user_settings.SETTINGS_PATH.write_text("[1, 2, 3]", encoding="utf-8")
    assert load_settings().autosave is True
