"""Unified internal annotation model — the format-neutral hub.

Every external format (LabelMe / YOLO / VOC / COCO / classification-by-dir)
is imported into this model first. All internal operations (quality check,
dedup, transform, augment, convert) work on it. Export to any target format
reads from it — no re-parsing from disk.

Design invariants:
  - All coordinates are **pixel-space** (float). Never normalized.
  - ``Region.bbox`` is always ``(x1, y1, x2, y2)`` — top-left / bottom-right.
  - Polygons are closed loops of ``(x, y)`` pairs.
  - Keypoints are ``(x, y, visibility)`` triples (COCO convention: 0=missing,
    1=occluded, 2=visible).

Pure Python — no PyQt.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .labels import normalize_label


# ---------- Geometry primitives ----------

@dataclass(slots=True)
class BBox:
    """Axis-aligned bounding box in pixel coordinates."""
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def width(self) -> float:
        return max(0.0, self.x2 - self.x1)

    @property
    def height(self) -> float:
        return max(0.0, self.y2 - self.y1)

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2)

    def to_xywh(self) -> tuple[float, float, float, float]:
        """COCO-style ``(x, y, w, h)`` where ``(x, y)`` is top-left."""
        return (self.x1, self.y1, self.width, self.height)

    def to_yolo(self, img_w: int, img_h: int) -> tuple[float, float, float, float]:
        """Normalized ``(cx, cy, w, h)`` for YOLO."""
        cx, cy = self.center
        return (cx / img_w, cy / img_h, self.width / img_w, self.height / img_h)

    @classmethod
    def from_xywh(cls, x: float, y: float, w: float, h: float) -> BBox:
        return cls(x, y, x + w, y + h)

    @classmethod
    def from_yolo(cls, cx: float, cy: float, w: float, h: float,
                  img_w: int, img_h: int) -> BBox:
        pw, ph = w * img_w, h * img_h
        pcx, pcy = cx * img_w, cy * img_h
        return cls(pcx - pw / 2, pcy - ph / 2, pcx + pw / 2, pcy + ph / 2)

    @classmethod
    def from_points(cls, points: list[tuple[float, float]]) -> BBox:
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return cls(min(xs), min(ys), max(xs), max(ys))


# ---------- Region (one annotated object) ----------

@dataclass
class Region:
    """One annotated object / region on an image.

    At minimum, ``label`` and one geometry field (``bbox``, ``polygon``,
    or ``keypoints``) should be populated. Exporters pick whichever
    geometry they need and ignore the rest.
    """
    label: str
    bbox: BBox | None = None
    polygon: list[tuple[float, float]] | None = None
    keypoints: list[tuple[float, float, int]] | None = None  # (x, y, vis)
    shape_type: str = "rectangle"     # rectangle / polygon / point / linestrip / circle
    text: str = ""                   # per-region caption / referring expression
    confidence: float = 1.0
    difficult: bool = False
    truncated: bool = False
    iscrowd: bool = False
    attributes: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.label = normalize_label(self.label)

    def ensure_bbox(self) -> BBox | None:
        """Return ``bbox``, deriving from polygon/keypoints if absent."""
        if self.bbox is not None:
            return self.bbox
        pts = self.polygon or [(x, y) for x, y, _v in (self.keypoints or [])]
        if pts:
            self.bbox = BBox.from_points(pts)
            return self.bbox
        return None


# ---------- Sample (one image + all its annotations) ----------

@dataclass
class Sample:
    """One image plus all its annotations — the universal internal unit.

    Covers every task type:
    - **Classification / anomaly**: ``image_labels`` + ``category``.
    - **Detection**: ``regions`` with ``bbox``.
    - **Segmentation**: ``regions`` with ``polygon``.
    - **Keypoint**: ``regions`` with ``keypoints``.
    - **Image pair**: ``pair_path`` points to the second image.
    """
    # -- Identity --
    image_path: Path
    image_width: int = 0
    image_height: int = 0

    # -- Image-level --
    category: str = ""                        # directory-derived category
    image_labels: list[str] = field(default_factory=list)  # classification tags

    # -- Region-level --
    regions: list[Region] = field(default_factory=list)

    # -- Dataset bookkeeping --
    split: str = ""                           # "train" / "val" / "test" / ""
    has_label: bool = False                   # was a label file found?
    label_path: Path | None = None            # original label file on disk
    source_format: str = ""                   # "labelme" / "yolo" / "voc" / "coco" / ""

    # -- Workflow --
    work_status: str = ""                     # WorkStatus.value or "" (untracked)

    # -- VLM / multimodal --
    caption: str = ""                         # free-text image caption
    conversations: list[dict[str, str]] = field(default_factory=list)
    # Each entry: {"from": "human"|"gpt", "value": "..."}
    grounding: list[dict[str, Any]] = field(default_factory=list)
    # Each entry: {"label": "...", "bbox": [x1,y1,x2,y2], "text": "..."}

    # -- Extension slot --
    pair_path: Path | None = None             # for image-pair tasks
    metadata: dict[str, Any] = field(default_factory=dict)

    # -- Derived helpers --

    @property
    def class_names(self) -> list[str]:
        """Unique sorted labels across all regions + image_labels."""
        names: set[str] = {
            label for label in (normalize_label(v) for v in self.image_labels)
            if label
        }
        for r in self.regions:
            label = normalize_label(r.label)
            if label:
                names.add(label)
        return sorted(names)

    @property
    def region_count(self) -> int:
        return len(self.regions)


# ---------- SampleSet (a whole dataset in unified form) ----------

@dataclass
class SampleSet:
    """Ordered collection of Samples — the internal representation of a
    full dataset ready for inspection, processing, and export."""
    samples: list[Sample] = field(default_factory=list)

    # -- Class registry --

    @property
    def class_names(self) -> list[str]:
        """Globally sorted unique class list."""
        names: set[str] = set()
        for s in self.samples:
            names.update(s.class_names)
        return sorted(names)

    @property
    def class_to_index(self) -> dict[str, int]:
        return {n: i for i, n in enumerate(self.class_names)}

    # -- Split views --

    @property
    def train(self) -> list[Sample]:
        return [s for s in self.samples if s.split == "train"]

    @property
    def val(self) -> list[Sample]:
        return [s for s in self.samples if s.split == "val"]

    @property
    def test(self) -> list[Sample]:
        return [s for s in self.samples if s.split == "test"]

    @property
    def unsplit(self) -> list[Sample]:
        return [s for s in self.samples if not s.split]

    # -- Stats --

    @property
    def total_regions(self) -> int:
        return sum(s.region_count for s in self.samples)

    @property
    def labeled_count(self) -> int:
        return sum(1 for s in self.samples if s.has_label)

    def by_category(self) -> dict[str, list[Sample]]:
        out: dict[str, list[Sample]] = {}
        for s in self.samples:
            out.setdefault(s.category or "", []).append(s)
        return out

    # -- Workflow views --

    def by_work_status(self, status: str) -> list[Sample]:
        """Samples matching a single work_status value."""
        return [s for s in self.samples if s.work_status == status]

    @property
    def work_status_counts(self) -> dict[str, int]:
        """Counter of work_status → number of samples."""
        counts: dict[str, int] = {}
        for s in self.samples:
            k = s.work_status or ""
            counts[k] = counts.get(k, 0) + 1
        return counts

    # -- VLM views --

    @property
    def captioned_count(self) -> int:
        return sum(1 for s in self.samples if s.caption)

    @property
    def conversational_count(self) -> int:
        return sum(1 for s in self.samples if s.conversations)

    # -- Incremental mutations --

    def _build_index(self) -> dict[str, int]:
        """Build path → list-index lookup (lazy, rebuilt on demand)."""
        return {str(s.image_path): i for i, s in enumerate(self.samples)}

    def find(self, image_path: Path | str) -> Sample | None:
        """Look up a sample by image path. O(n) scan — fine for
        single-image interactive use, not for batch."""
        key = str(image_path)
        for s in self.samples:
            if str(s.image_path) == key:
                return s
        return None

    def remove_by_path(self, image_path: Path | str) -> bool:
        """Remove a single sample by path. Returns True if found."""
        key = str(image_path)
        for i, s in enumerate(self.samples):
            if str(s.image_path) == key:
                self.samples.pop(i)
                return True
        return False

    def remove_by_paths(self, paths: set[str]) -> int:
        """Bulk-remove samples whose ``str(image_path)`` is in *paths*.

        Returns the number of samples removed. More efficient than
        calling ``remove_by_path`` in a loop (single pass).
        """
        before = len(self.samples)
        self.samples = [s for s in self.samples
                        if str(s.image_path) not in paths]
        return before - len(self.samples)

    def update_sample(self, image_path: Path | str,
                      **fields) -> bool:
        """Update fields on a single sample in-place. Returns True if
        the sample was found. Only provided kwargs are set.

        Example::

            ss.update_sample(img.path, category="scratch",
                             work_status="annotating")
        """
        s = self.find(image_path)
        if s is None:
            return False
        for k, v in fields.items():
            if hasattr(s, k):
                setattr(s, k, v)
        return True
