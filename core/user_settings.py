"""User preferences persisted to ~/.dataforge/settings.json."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

SETTINGS_PATH = Path.home() / ".dataforge" / "settings.json"


@dataclass
class UserSettings:
    theme: str = "light"
    # When True, switching categories preserves the active filter chip
    # (e.g. "未标注"); when False (default), filter resets to "全部".
    # Review #12 — workflow A "过滤未标注 → 遍历每个类别逐个标" wants this on.
    keep_filter_on_category_switch: bool = False


def load_settings() -> UserSettings:
    try:
        raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return UserSettings()
    if not isinstance(raw, dict):
        return UserSettings()
    return UserSettings(
        theme=raw.get("theme", "light"),
        keep_filter_on_category_switch=raw.get(
            "keep_filter_on_category_switch", False
        ),
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
