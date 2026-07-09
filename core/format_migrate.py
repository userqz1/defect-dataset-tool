"""In-place annotation format migration for a project.

Converts all label files from one format to another **within** the
project directory, then updates ``Project.annotation_format``. This
is not an export — it replaces the on-disk labels.

Safety: old label files are renamed to ``<stem>.<ext>.bak`` before the
new ones are written, so a crash mid-migration doesn't lose data.

Pure Python — no PyQt.
"""
from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .annotation_writer import write_annotation_as
from .format_in import load_sample, _load_yolo_classes
from .models import Annotation, Dataset, ImageInfo, Shape
from .unified import Region, Sample

logger = logging.getLogger(__name__)


@dataclass
class MigrateResult:
    converted: int = 0
    skipped: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)  # (name, error)
    backup_dir: Path | None = None


def migrate_annotation_format(
    dataset: Dataset,
    target_fmt: str,
    *,
    progress_cb: Callable[[int, int, str], None] | None = None,
) -> MigrateResult:
    """Convert all label files to *target_fmt* in-place.

    Steps per image:
      1. Load existing annotation via ``format_in.load_sample``.
      2. Back up the old label file (``*.bak``).
      3. Write new label in *target_fmt* via ``write_annotation_as``.
      4. Delete the backup on success (or keep on failure).

    Does **not** update ``Project.annotation_format`` — the caller
    should do that after verifying the result.
    """
    result = MigrateResult()
    all_images: list[ImageInfo] = []
    for cat in dataset.categories:
        all_images.extend(cat.images)

    total = len(all_images)
    if total == 0:
        return result

    # Pre-load YOLO class names so labels survive the round-trip.
    # Each category may have its own classes.txt in its labels/ dir.
    _yolo_cache: dict[Path, list[str]] = {}

    def _yolo_classes_for(label_path: Path) -> list[str] | None:
        lbl_dir = label_path.parent
        if lbl_dir not in _yolo_cache:
            _yolo_cache[lbl_dir] = _load_yolo_classes(lbl_dir)
        return _yolo_cache[lbl_dir] or None

    for i, img in enumerate(all_images):
        if progress_cb:
            progress_cb(i, total, img.path.name)

        if not img.has_label or img.label_path is None:
            result.skipped += 1
            continue

        try:
            # Phase 1: Load into unified model — supply YOLO class names
            # so numeric indices are resolved to string labels.
            yolo_names = None
            if img.label_path.suffix.lower() == ".txt":
                yolo_names = _yolo_classes_for(img.label_path)
            sample = load_sample(img, yolo_class_names=yolo_names)
            if not sample.regions:
                # Classification-only — no annotation file to convert
                result.skipped += 1
                continue

            # Phase 2: Build legacy Annotation for writer
            ann = _sample_to_annotation(sample)

            # Phase 3: Back up old label
            old_label = img.label_path
            backup = old_label.with_suffix(old_label.suffix + ".bak")
            shutil.copy2(str(old_label), str(backup))

            # Phase 4: Write in target format
            new_label = write_annotation_as(ann, img.path, target_fmt)

            # Phase 5: Remove old file if different path, then remove backup
            if new_label != old_label and old_label.exists():
                old_label.unlink()
            if backup.exists():
                backup.unlink()

            result.converted += 1

        except Exception as e:
            logger.debug("migrate failed for %s: %s", img.path.name, e)
            result.failed.append((img.path.name, str(e)))
            # Restore from backup if it exists
            if img.label_path is not None:
                bak = img.label_path.with_suffix(img.label_path.suffix + ".bak")
                if bak.exists() and not img.label_path.exists():
                    shutil.copy2(str(bak), str(img.label_path))
                if bak.exists():
                    bak.unlink()

    if progress_cb:
        progress_cb(total, total, "")
    return result


def _sample_to_annotation(sample: Sample) -> Annotation:
    """Bridge unified Sample → legacy Annotation for the writer."""
    shapes = []
    for r in sample.regions:
        pts = _region_to_points(r)
        if pts:
            # LabelMe has no ellipse → emit the bbox points as a polygon.
            st = "polygon" if r.shape_type == "ellipse" else r.shape_type
            shapes.append(Shape(
                label=r.label,
                shape_type=st,
                points=pts,
                text=r.text,
            ))
    return Annotation(image_path=sample.image_path, shapes=shapes)


def _region_to_points(r: Region) -> list[tuple[float, float]]:
    """Extract point list from a Region for the legacy writer.

    Mirrors ``format_out._region_points``: circle → ``[center, edge]`` and
    point → a single coordinate, so migrating LabelMe→LabelMe doesn't turn a
    circle/point into a 4-corner polygon that still claims to be a circle.
    """
    st = r.shape_type
    if st == "circle" and r.bbox:
        bb = r.bbox
        cx, cy = (bb.x1 + bb.x2) / 2.0, (bb.y1 + bb.y2) / 2.0
        rad = (bb.x2 - bb.x1) / 2.0
        return [(cx, cy), (cx + rad, cy)]
    if st == "point":
        if r.keypoints:
            x, y, _v = r.keypoints[0]
            return [(x, y)]
        if r.bbox:
            bb = r.bbox
            return [((bb.x1 + bb.x2) / 2.0, (bb.y1 + bb.y2) / 2.0)]
        return []
    if r.polygon:
        return list(r.polygon)
    if r.bbox:
        if st == "rectangle":
            return [(r.bbox.x1, r.bbox.y1), (r.bbox.x2, r.bbox.y2)]
        return [(r.bbox.x1, r.bbox.y1), (r.bbox.x2, r.bbox.y1),
                (r.bbox.x2, r.bbox.y2), (r.bbox.x1, r.bbox.y2)]
    if r.keypoints:
        return [(x, y) for x, y, _v in r.keypoints]
    return []
