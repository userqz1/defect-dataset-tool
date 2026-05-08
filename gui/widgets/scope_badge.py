"""Scope badge — single source of truth for "what does this affect" markers.

Every action in the app needs to answer: *what data does this touch,
and is it destructive?*  P1.5 promotes that signal from ad-hoc strings
into one widget with a small set of named visual variants so the user
reads a consistent language across pages.

Three variants::

    Scope.NEUTRAL   — informational scope tags
                       当前图 / 已选 N 张 / 当前筛选 N 张 / 整库 N 张
                       Visual: ghost grey background, secondary text.
    Scope.READONLY  — produces output without mutating the project
                       只读导出 / 不修改项目
                       Visual: warm tan (ACCENT_SOFT) — "safe to click".
    Scope.WRITES    — mutates project files / images / annotations
                       会修改项目 / 会修改图片 / 会写入标注
                       Visual: amber (WARNING_SOFT) + bold weight —
                       "this is the moment to read carefully".

A single ``ScopeBadge`` instance can flip variant + text together via
:meth:`set_scope_text`, useful for live-updating selection counts.

Usage::

    from gui.widgets.scope_badge import Scope, ScopeBadge

    badge = ScopeBadge("当前图", Scope.NEUTRAL)
    # later, on selection change:
    badge.set_scope_text(f"已选 {n} 张", Scope.NEUTRAL)
    # or for a dangerous CTA:
    badge = ScopeBadge("会修改项目", Scope.WRITES)

QSS lives in ``gui/styles/app.qss`` — drives the three variants off
the dynamic ``scope`` property.
"""
from __future__ import annotations

from enum import Enum

from PyQt6.QtWidgets import QWidget
from qfluentwidgets import CaptionLabel


class Scope(str, Enum):
    """Visual variant for a :class:`ScopeBadge`."""

    NEUTRAL = "neutral"     # informational — current image / selection / filter
    READONLY = "readonly"   # produces output, doesn't touch the project
    WRITES = "writes"       # mutates project / images / labels


class ScopeBadge(CaptionLabel):
    """Compact pill that names what an action acts on.

    Subclasses :class:`qfluentwidgets.CaptionLabel` so it inherits the
    small typography that matches our other badge widgets — only the
    background + foreground + corner radius come from the ``[scope=...]``
    QSS rule.
    """

    def __init__(
        self,
        text: str = "",
        scope: Scope = Scope.NEUTRAL,
        parent: QWidget | None = None,
    ) -> None:
        # qfluentwidgets' CaptionLabel uses ``@singledispatchmethod`` for
        # its overloaded ``__init__`` — passing ``(text, parent)``
        # positionally trips the recursive dispatch and crashes with
        # "takes 1 to 2 args but 3 were given". Construct with just the
        # parent and apply the text via ``setText``.
        super().__init__(parent)
        if text:
            self.setText(text)
        self.setObjectName("scopeBadge")
        # Setting the property here (before any reapply) is fine — the
        # initial polish picks it up.  Subsequent flips via set_scope
        # need an explicit unpolish/polish cycle.
        self.setProperty("scope", scope.value)
        self._scope = scope

    # ---- Public API ----

    def set_scope(self, scope: Scope) -> None:
        if scope == self._scope:
            return
        self._scope = scope
        self.setProperty("scope", scope.value)
        self.style().unpolish(self)
        self.style().polish(self)

    def set_scope_text(self, text: str, scope: Scope) -> None:
        """Set both the displayed text and the visual variant in one call."""
        self.setText(text)
        self.set_scope(scope)

    @property
    def scope(self) -> Scope:
        return self._scope
