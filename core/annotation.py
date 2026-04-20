"""LabelMe JSON parser. Tolerant of malformed files — failures are recorded, not raised."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .models import Annotation, Shape


@dataclass
class ParseResult:
    annotation: Annotation | None
    error: str | None = None
    # Coordinate space of Shape.points in the returned Annotation.
    # LabelMe / COCO / VOC always emit pixel coords; YOLO needs the image's
    # pixel size to denormalize — callers that invoke parse_yolo without an
    # image_path get "normalized" (0..1) points and must scale themselves.
    # Checking this field on read is a guard against writing the wrong
    # coord space back to disk (review #4).
    coord_space: Literal["pixel", "normalized"] = "pixel"

    @property
    def ok(self) -> bool:
        return self.annotation is not None and self.error is None


def parse_labelme(json_path: Path, image_path: Path | None = None) -> ParseResult:
    """Parse a LabelMe JSON file. Never raises — returns ParseResult with error str on failure."""
    try:
        text = json_path.read_text(encoding="utf-8")
    except OSError as e:
        return ParseResult(None, f"read failed: {e}")

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return ParseResult(None, f"invalid json: {e.msg} at line {e.lineno}")

    if not isinstance(data, dict):
        return ParseResult(None, "root is not an object")

    raw_shapes = data.get("shapes", [])
    if not isinstance(raw_shapes, list):
        return ParseResult(None, "shapes is not a list")

    shapes: list[Shape] = []
    for i, raw in enumerate(raw_shapes):
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label", "")).strip()
        shape_type = str(raw.get("shape_type", "polygon"))
        raw_points = raw.get("points", [])
        if not label or not isinstance(raw_points, list):
            continue
        points: list[tuple[float, float]] = []
        for p in raw_points:
            if isinstance(p, (list, tuple)) and len(p) >= 2:
                try:
                    points.append((float(p[0]), float(p[1])))
                except (TypeError, ValueError):
                    pass
        if not points:
            continue
        shapes.append(Shape(label=label, shape_type=shape_type, points=points))

    img_path = image_path or Path(str(data.get("imagePath", "")))
    return ParseResult(Annotation(image_path=img_path, shapes=shapes))
