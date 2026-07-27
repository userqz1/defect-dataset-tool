"""Helpers for oriented bounding boxes.

DataForge stores OBBs as LabelMe-style four-point polygons internally.  These
helpers keep the format-specific import/export code small and deterministic.
Coordinates are pixel-space unless a function explicitly says "normalized".
"""
from __future__ import annotations

import math
from collections.abc import Iterable

from .unified import BBox, Region

Point = tuple[float, float]


def clamp_point(point: Point, image_width: int, image_height: int) -> Point:
    """Clamp *point* into the image bounds."""
    x, y = point
    if image_width > 0:
        x = min(max(float(x), 0.0), float(image_width))
    if image_height > 0:
        y = min(max(float(y), 0.0), float(image_height))
    return x, y


def bbox_to_quad(bbox: BBox) -> list[Point]:
    """Return an axis-aligned four-point polygon for *bbox*."""
    return [
        (bbox.x1, bbox.y1),
        (bbox.x2, bbox.y1),
        (bbox.x2, bbox.y2),
        (bbox.x1, bbox.y2),
    ]


def polygon_area(points: Iterable[Point]) -> float:
    """Return signed shoelace area for *points*."""
    pts = list(points)
    if len(pts) < 3:
        return 0.0
    area = 0.0
    for i, (x1, y1) in enumerate(pts):
        x2, y2 = pts[(i + 1) % len(pts)]
        area += x1 * y2 - x2 * y1
    return area / 2.0


def normalize_quad(
    points: Iterable[Point],
    *,
    image_width: int = 0,
    image_height: int = 0,
    clamp: bool = False,
) -> list[Point] | None:
    """Return a stable top-left-first quad, or None for non-quads.

    The input may be clockwise or counter-clockwise.  Sorting by angle around
    the centroid fixes common click-order drift; rotating the result to start
    at the top-left corner makes exported OBB text deterministic.
    """
    pts = [(float(x), float(y)) for x, y in points]
    if len(pts) != 4:
        return None
    if clamp:
        pts = [clamp_point(p, image_width, image_height) for p in pts]
    if len({(round(x, 6), round(y, 6)) for x, y in pts}) < 4:
        return None

    cx = sum(x for x, _ in pts) / 4.0
    cy = sum(y for _, y in pts) / 4.0
    ordered = sorted(pts, key=lambda p: math.atan2(p[1] - cy, p[0] - cx))
    start = min(
        range(4),
        key=lambda i: (ordered[i][1] + ordered[i][0], ordered[i][1], ordered[i][0]),
    )
    ordered = ordered[start:] + ordered[:start]
    if abs(polygon_area(ordered)) <= 1e-6:
        return None
    return ordered


def region_to_quad(
    region: Region,
    *,
    image_width: int = 0,
    image_height: int = 0,
    clamp: bool = False,
) -> list[Point] | None:
    """Return a quad for *region*.

    Four-point polygons are exported as true OBBs.  Rectangles/bboxes are
    converted to axis-aligned quads.  Other polygons are intentionally skipped
    so segmentation masks are not silently reinterpreted as rotated boxes.
    """
    if region.polygon:
        if len(region.polygon) != 4:
            return None
        return normalize_quad(
            region.polygon,
            image_width=image_width,
            image_height=image_height,
            clamp=clamp,
        )
    bbox = region.ensure_bbox()
    if bbox is None:
        return None
    return normalize_quad(
        bbox_to_quad(bbox),
        image_width=image_width,
        image_height=image_height,
        clamp=clamp,
    )


def normalized_quad_coords(
    quad: Iterable[Point],
    image_width: int,
    image_height: int,
) -> list[float]:
    """Return YOLO-OBB normalized x1 y1 ... x4 y4 coordinates."""
    coords: list[float] = []
    for x, y in quad:
        nx = 0.0 if image_width <= 0 else min(max(x / image_width, 0.0), 1.0)
        ny = 0.0 if image_height <= 0 else min(max(y / image_height, 0.0), 1.0)
        coords.extend([nx, ny])
    return coords


def denormalized_quad_coords(
    coords: Iterable[float],
    image_width: int,
    image_height: int,
) -> list[Point] | None:
    """Convert normalized x1 y1 ... x4 y4 coordinates to a quad."""
    vals = [float(v) for v in coords]
    if len(vals) != 8:
        return None
    pts = [
        (vals[i] * image_width, vals[i + 1] * image_height)
        for i in range(0, 8, 2)
    ]
    return normalize_quad(pts, image_width=image_width, image_height=image_height)
