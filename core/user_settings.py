"""User preferences persisted to ~/.dataforge/settings.json."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

SETTINGS_PATH = Path.home() / ".dataforge" / "settings.json"


@dataclass
class UserSettings:
    theme: str = "light"
    # Write annotation edits straight back to disk instead of waiting for
    # an explicit save. On by default: the annotation loop is edit-heavy
    # and losing a screen of boxes to a forgotten Ctrl+S is the worse
    # failure. Kept switchable because it does write the user's label
    # files without asking.
    autosave: bool = True


def load_settings() -> UserSettings:
    try:
        raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return UserSettings()
    if not isinstance(raw, dict):
        return UserSettings()
    return UserSettings(
        theme=raw.get("theme", "light"),
        # Anything non-bool (missing key, hand-edited file, older
        # settings.json) falls back to the default rather than to a
        # surprising False.
        autosave=(raw["autosave"] if isinstance(raw.get("autosave"), bool)
                  else True),
    )


def save_settings(settings: UserSettings) -> None:
    try:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(
            json.dumps(asdict(settings), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass
