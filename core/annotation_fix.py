"""Clamp out-of-bounds annotation geometry back into the image, drop strays.

Complements ``core.quality``'s ``oob`` detection: quality *reports*
out-of-bounds boxes, this *fixes* them — clamp overshoots to the image edge,
and drop boxes that fall entirely outside (collapse to zero area once
clamped).  Pure Python, no GUI; the review-stage handler calls this and
writes the result back via ``annotation_writer``.
"""
from __future__ import annotations

from dataclasses import replace

from .models import Shape

# Only these span an area and can meaningfully "collapse" to nothing; a
# point (and, treated leniently, a line) legitimately spans zero in a
# dimension and must be repositioned rather than dropped.
_AREA_SHAPES = ("rectangle", "polygon")


def clamp_points(
    points: list[tuple[float, float]], width: float, height: float
) -> list[tuple[float, float]]:
    """Clamp each ``(x, y)`` into ``[0, width] x [0, height]``."""
    return [
        (
            min(max(float(x), 0.0), float(width)),
            min(max(float(y), 0.0), float(height)),
        )
        for x, y in points
    ]


def _degenerate(points: list[tuple[float, float]]) -> bool:
    """True if the points span zero width or height (a collapsed box)."""
    if not points:
        return True
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (max(xs) - min(xs) <= 0) or (max(ys) - min(ys) <= 0)


def clamp_shapes(
    shapes: list[Shape], width: float, height: float
) -> tuple[list[Shape], int, int]:
    """Clamp every shape into the image; drop area-shapes that collapse.

    Returns ``(kept_shapes, clamped_count, removed_count)``.  A non-positive
    image size returns the shapes unchanged (no bounds to clamp against).
    Point/line shapes are only repositioned, never dropped for zero span.
    """
    if width <= 0 or height <= 0:
        return list(shapes), 0, 0
    kept: list[Shape] = []
    clamped = 0
    removed = 0
    for s in shapes:
        pts = list(s.points or [])
        new_pts = clamp_points(pts, width, height)
        if s.shape_type in _AREA_SHAPES and _degenerate(new_pts):
            removed += 1
            continue
        if new_pts != pts:
            clamped += 1
            s = replace(s, points=new_pts)
        kept.append(s)
    return kept, clamped, removed
