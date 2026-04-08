"""Core domain models. Pure Python — no PyQt imports allowed."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Shape:
    label: str
    shape_type: str  # polygon / rectangle / point / line / circle
    points: list[tuple[float, float]]


@dataclass
class Annotation:
    image_path: Path
    shapes: list[Shape] = field(default_factory=list)


@dataclass
class ImageInfo:
    path: Path
    category: str
    width: int = 0
    height: int = 0
    has_label: bool = False
    label_path: Path | None = None


@dataclass
class Category:
    name: str
    image_count: int = 0
    label_count: int = 0
    images: list[ImageInfo] = field(default_factory=list)


@dataclass
class Dataset:
    name: str
    root_path: Path
    categories: list[Category] = field(default_factory=list)
    total_images: int = 0
    total_annotations: int = 0
    layout: str = "standard"  # standard / flat / single / recursive / empty
