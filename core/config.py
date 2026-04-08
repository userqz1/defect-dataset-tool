"""Lightweight config loader. Pure Python — no PyQt.

Reads `config/default_config.yaml` once and exposes typed accessors. Callers
should go through the helpers below rather than re-parsing the YAML.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "default_config.yaml"

_FALLBACK_IMAGE_EXTS: set[str] = {
    ".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff",
}


@lru_cache(maxsize=1)
def load() -> dict:
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}
    return data if isinstance(data, dict) else {}


def image_extensions() -> set[str]:
    """Normalized set of lowercased image extensions (with leading dot)."""
    scan = load().get("scan") or {}
    exts = scan.get("image_exts")
    if not isinstance(exts, (list, tuple)) or not exts:
        return set(_FALLBACK_IMAGE_EXTS)
    out: set[str] = set()
    for e in exts:
        if not isinstance(e, str):
            continue
        e = e.lower().strip()
        if not e.startswith("."):
            e = "." + e
        out.add(e)
    return out or set(_FALLBACK_IMAGE_EXTS)
