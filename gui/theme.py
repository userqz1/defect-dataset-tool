"""Design tokens & theme switching — single source of truth.

商业三层 GUI 样式架构：

1. **tokens (本文件)**            原子常量 + 主题集合 (Light / Dark)
2. **semantic widgets**           qfluentwidgets 的 BodyLabel/CaptionLabel/...
                                  + 本项目封装的 widgets (FilterChip, GhostButton, ...)
3. **gui/styles/app.qss**         一份 QSS, 用 {TOKEN} 占位由 dataclass 注入
                                  只放 "无法靠组件 API 解决" 的容器/复合选择器

任何视图都不应再 `setStyleSheet(f"color:#xxx")`. 写颜色字面量违反 layer 1.
新增主题只需新建一个 dataclass 实例并在 set_theme() 里登记.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QWidget


@dataclass(frozen=True)
class Tokens:
    """A complete visual theme. Override every field for a new theme."""

    # ---- Surface colors ----
    SIDEBAR: str
    CONTENT: str
    BORDER: str
    HOVER: str
    HOVER_STRONG: str
    SURFACE_DIM: str          # 缩略图占位 / 弱化背景

    # ---- Text ----
    TEXT: str
    TEXT_2: str
    TEXT_3: str

    # ---- Brand / state ----
    ACCENT: str
    ACCENT_SOFT: str
    SUCCESS: str
    WARNING: str

    # ---- Geometry ----
    RADIUS: int = 6
    RADIUS_LG: int = 8
    GAP_XS: int = 4
    GAP: int = 8
    GAP_LG: int = 12
    GAP_XL: int = 16
    PAD: int = 10
    PAD_LG: int = 16
    PAD_XL: int = 20
    PAD_2XL: int = 32
    PAD_3XL: int = 48
    PAD_HERO: int = 60

    # ---- Sizes ----
    SIDEBAR_WIDTH: int = 240
    DETAIL_SIDEBAR_WIDTH: int = 280
    THUMB_SIZE: int = 170
    CARD_WIDTH: int = 182
    CARD_HEIGHT: int = 232


# ---------- 主题登记表 ----------

LIGHT = Tokens(
    SIDEBAR="#f5f4ef",
    CONTENT="#ffffff",
    BORDER="#e8e5dc",
    HOVER="#faf9f7",
    HOVER_STRONG="#ede9de",
    SURFACE_DIM="#f3f1ea",
    TEXT="#2d2a26",
    TEXT_2="#6b6760",
    TEXT_3="#9a958a",
    ACCENT="#c96442",
    ACCENT_SOFT="#f4e8e2",
    SUCCESS="#5a7a3c",
    WARNING="#b8842b",
)

DARK = Tokens(
    SIDEBAR="#2a2825",
    CONTENT="#1f1d1b",
    BORDER="#3a3733",
    HOVER="#332f2b",
    HOVER_STRONG="#3d3935",
    SURFACE_DIM="#262420",
    TEXT="#ece7df",
    TEXT_2="#a8a29a",
    TEXT_3="#7a7570",
    ACCENT="#e0805a",
    ACCENT_SOFT="#3d2a22",
    SUCCESS="#7a9a4c",
    WARNING="#d09a3a",
)

THEMES = {"light": LIGHT, "dark": DARK}


# ---------- Mutable proxy ----------

class _TokenProxy:
    """Module-level proxy so `from gui.theme import T` always returns current values."""

    def __getattr__(self, name: str):
        return getattr(_active, name)


_active: Tokens = LIGHT
T: Tokens = _TokenProxy()  # type: ignore[assignment]


# ---------- Public API ----------

def load_qss() -> str:
    """Read styles/app.qss and substitute the active theme tokens."""
    qss_path = Path(__file__).parent / "styles" / "app.qss"
    raw = qss_path.read_text(encoding="utf-8")
    return raw.format(**{f.name: getattr(_active, f.name) for f in fields(Tokens)})


def set_theme(name: str, window: QWidget | None = None) -> None:
    """Swap the active theme. Pass `window` to re-apply QSS immediately."""
    global _active
    if name not in THEMES:
        raise ValueError(f"unknown theme: {name!r} (known: {list(THEMES)})")
    _active = THEMES[name]
    if window is not None:
        window.setStyleSheet(load_qss())
