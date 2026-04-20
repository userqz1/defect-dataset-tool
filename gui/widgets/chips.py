"""Reusable chip-style buttons. Visual styling lives in styles/app.qss."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QPushButton


class FilterChip(QPushButton):
    """Toggleable pill-shaped filter, styled by QPushButton#filterChip in app.qss."""

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.setObjectName("filterChip")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
