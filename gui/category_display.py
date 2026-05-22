"""Display helpers for directory-derived image categories."""
from __future__ import annotations

from core.dataset import UNCATEGORIZED


def display_category_name(name: str, *, fallback: str = "无图片分组") -> str:
    """Return a user-facing name for an image directory category.

    ``UNCATEGORIZED`` is an internal bucket used for ``root/images`` +
    ``root/labels`` detection datasets. Showing it as "未分类" makes users
    think object labels are missing, so the UI calls it an image grouping.
    """
    return fallback if name == UNCATEGORIZED else (name or fallback)


def has_semantic_category(name: str) -> bool:
    """Whether *name* is a real user category rather than the neutral bucket."""
    return bool(name and name != UNCATEGORIZED)
