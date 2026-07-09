"""Core domain models. Pure Python — no PyQt imports allowed."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .labels import normalize_label


@dataclass
class Shape:
    label: str
    shape_type: str  # polygon / rectangle / point / linestrip / circle
    points: list[tuple[float, float]]
    text: str = ""   # per-region caption / referring expression

    def __post_init__(self) -> None:
        self.label = normalize_label(self.label)


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

    def remove_images(
        self,
        paths: set[str],
        *,
        regions_by_path: dict[str, int] | None = None,
    ) -> int:
        """Remove images from the in-memory Dataset by path string.

        Updates ``total_images`` and per-category ``image_count`` /
        ``label_count``.  Returns the number of images removed.
        Invalidates the ``_by_name`` index.

        ``total_annotations`` is the count of **annotation regions/shapes**
        across the dataset (the same semantic filled in by the scan
        worker from ``SampleSet.total_regions``).  Because ``ImageInfo``
        only knows whether a label *file* exists — not how many regions
        it contained — this method subtracts region counts only when the
        caller passes ``regions_by_path`` (typically derived from the
        live SampleSet).  Without it, ``total_annotations`` is left
        untouched so we don't silently replace the region count with a
        "labeled-image" count.  Callers that need it accurate should
        resync from SampleSet after calling this.
        """
        ann_delta = 0
        removed = 0
        for cat in self.categories:
            before = len(cat.images)
            kept: list[ImageInfo] = []
            for img in cat.images:
                if str(img.path) in paths:
                    if regions_by_path is not None:
                        ann_delta += regions_by_path.get(str(img.path), 0)
                else:
                    kept.append(img)
            cat.images = kept
            delta = before - len(cat.images)
            if delta:
                cat.image_count = len(cat.images)
                cat.label_count = sum(1 for i in cat.images if i.has_label)
                removed += delta
        self.total_images -= removed
        if regions_by_path is not None:
            # Caller supplied authoritative per-image region counts — safe
            # to decrement.  Clamp to 0 in case the caller's bookkeeping
            # drifted from the in-memory dataset.
            self.total_annotations = max(0, self.total_annotations - ann_delta)
        # Invalidate cached lookup
        if hasattr(self, "_by_name"):
            object.__delattr__(self, "_by_name")
        return removed
