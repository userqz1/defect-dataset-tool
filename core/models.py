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
    fingerprint: str = ""  # sha1(scanned_at + top-level mtimes); empty = uncached

    def category_by_name(self, name: str) -> "Category | None":
        """O(1) lookup for a category by name.

        BrowserView's filter / search paths repeatedly ask "give me all
        images in category X" (review #8). A linear scan is fine for 10
        classes and a noticeable drag at 100+. Lazy-build the index on
        first call and cache it on the instance; ``_by_name`` is
        intentionally NOT part of the dataclass fields so it stays out
        of scheme/project serialization.
        """
        idx = getattr(self, "_by_name", None)
        if idx is None or len(idx) != len(self.categories):
            idx = {c.name: c for c in self.categories}
            object.__setattr__(self, "_by_name", idx)
        return idx.get(name)
