"""Design tokens & theme switching — single source of truth.

商业三层 GUI 样式架构：

1. **tokens (本文件)**            原子常量 + 主题集合 (Light / Dark)
2. **semantic widgets**           qfluentwidgets 的 BodyLabel/CaptionLabel/...
                                  + 本项目封装的 widgets (FilterChip, ToolSidebar, ...)
3. **gui/styles/app.qss**         一份 QSS, 用 $TOKEN 占位由 dataclass 注入
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
    ERROR: str = "#c0392b"
    # Text/glyph color that reads against ACCENT (e.g. brand chip "D",
    # button-on-accent labels). Override per theme if ACCENT shifts hue.
    ON_ACCENT: str = "#ffffff"

    # Drop shadow used by the floating Settings popup. Warm-brown on
    # light, black-with-alpha on dark — set per theme.
    POPUP_SHADOW: str = "#2d2a2640"

    # Badge overlays (thumbnail "已标" / "DUP" / "!") — ghost background
    # is a semi-transparent overlay; FG is the text color on that.
    BADGE_GHOST_BG: str = "#00000088"   # black @ 55% alpha
    BADGE_FG_LIGHT: str = "#ffffff"
    BADGE_FG_DARK: str = "#18181b"

    # Workflow-status identity colors (used by the batch list's progress
    # strip). Modeled the same way as the category-identity palette in
    # ``image_viewer.PALETTE`` / ``category_tree._EARTHEN`` — values are
    # expected to read against both themes, so LIGHT and DARK can reuse
    # the same hex. Keeping them as tokens (rather than widget-local
    # literals) so style-cop stays green and future themes can override.
    STATUS_NEW: str = "#6b7280"
    STATUS_PRELABELED: str = "#8b5cf6"
    STATUS_ANNOTATING: str = "#3b82f6"
    STATUS_REVIEW_PENDING: str = "#f59e0b"
    STATUS_NEEDS_FIX: str = "#ef4444"
    STATUS_READY: str = "#22c55e"
    STATUS_EXPORTED: str = "#06b6d4"

    # ---- Node editor ----
    NODE_CAT_CLEAN: str = ""
    NODE_CAT_AUGMENT: str = ""
    NODE_CAT_SPLIT: str = ""
    NODE_CAT_EXPORT: str = ""
    NODE_CAT_INPUT: str = ""
    NODE_BG: str = ""
    NODE_BG_HEADER: str = ""
    NODE_SHADOW: str = ""

    # ---- Geometry ----
    # RADIUS: small pills / chips (= design --r-xs 6)
    # RADIUS_LG: cards / panels (= design --r-lg 14); softer Claude-web look.
    RADIUS: int = 6
    RADIUS_LG: int = 14
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
    # Card dimensions for the thumbnail grid (delegate uses these to
    # paint; grid uses them for the layout pitch). Values match the
    # 200×222 card that ships in thumbnail_grid.py.
    CARD_WIDTH: int = 200
    CARD_HEIGHT: int = 222
    THUMB_H: int = 150
    CARD_META_H: int = 72
    CARD_PAD: int = 8
    # Common 32px control height used by PushButton / ToolButton /
    # LineEdit across the filter bar + delete button + search box.
    CONTROL_HEIGHT: int = 32


# ---------- 主题登记表 ----------

LIGHT = Tokens(
    # Palette aligned to Claude-web (design handoff): warm ivory canvas,
    # clay/crimson accent, near-black foreground for tighter contrast.
    SIDEBAR="#faf9f5",
    CONTENT="#ffffff",
    BORDER="#ebe7db",        # ≈ rgba(60,40,20,0.08) on ivory
    HOVER="#f7f5ee",         # ≈ rgba(60,40,20,0.04)
    HOVER_STRONG="#efece1",  # ≈ rgba(60,40,20,0.14) hover border tint
    SURFACE_DIM="#f0eee6",   # shared with search / chip-group / thumb placeholder
    TEXT="#141413",
    TEXT_2="#605a52",
    TEXT_3="#8c857a",
    ACCENT="#c96442",
    ACCENT_SOFT="#f4e8e2",
    SUCCESS="#5a7a3c",
    WARNING="#ce8a2c",
    ERROR="#b5453c",
    ON_ACCENT="#ffffff",
    POPUP_SHADOW="#3c28143c",  # warm brown @ 24% alpha — ivory-friendly
    BADGE_GHOST_BG="#00000088",
    BADGE_FG_LIGHT="#ffffff",
    BADGE_FG_DARK="#18181b",
    NODE_CAT_CLEAN="#4a9a8a",
    NODE_CAT_AUGMENT="#8a6ac0",
    NODE_CAT_SPLIT="#c09840",
    NODE_CAT_EXPORT="#5a8a3c",
    NODE_CAT_INPUT="#5a7acf",
    NODE_BG="#ffffff",
    NODE_BG_HEADER="#f7f5f0",
    NODE_SHADOW="#2d2a2640",
)

DARK = Tokens(
    # Dark palette aligned to Claude-web (design handoff).
    SIDEBAR="#262624",
    CONTENT="#1f1e1d",
    BORDER="#343230",
    HOVER="#2e2c2a",
    HOVER_STRONG="#3c3a37",
    SURFACE_DIM="#30302e",
    TEXT="#f5f4ee",
    TEXT_2="#bfb9ae",
    TEXT_3="#8c8578",
    ACCENT="#d97757",
    ACCENT_SOFT="#3d2a22",
    SUCCESS="#7a9a4c",
    WARNING="#e0a84a",
    ERROR="#d26a60",
    ON_ACCENT="#ffffff",
    POPUP_SHADOW="#00000080",
    BADGE_GHOST_BG="#00000099",
    BADGE_FG_LIGHT="#ffffff",
    BADGE_FG_DARK="#18181b",
    NODE_CAT_CLEAN="#5abaa0",
    NODE_CAT_AUGMENT="#a080e0",
    NODE_CAT_SPLIT="#d0a850",
    NODE_CAT_EXPORT="#70a050",
    NODE_CAT_INPUT="#6a8adf",
    NODE_BG="#2d2a26",
    NODE_BG_HEADER="#332f2b",
    NODE_SHADOW="#00000060",
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
    """Read styles/app.qss and substitute $TOKEN placeholders with active theme values."""
    from string import Template
    qss_path = Path(__file__).parent / "styles" / "app.qss"
    raw = qss_path.read_text(encoding="utf-8")
    return Template(raw).substitute(
        **{f.name: getattr(_active, f.name) for f in fields(Tokens)}
    )


def set_theme(name: str, window: QWidget | None = None) -> None:
    """Swap the active theme. Pass `window` to re-apply QSS immediately."""
    global _active
    if name not in THEMES:
        raise ValueError(f"unknown theme: {name!r} (known: {list(THEMES)})")
    _active = THEMES[name]
    if window is not None:
        window.setStyleSheet(load_qss())
