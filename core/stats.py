"""Dataset statistics — basic (fast) and extended (parses all annotations)."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from statistics import median

from .annotation_formats import load_yolo_classes, parse_annotation
from .models import Dataset


@dataclass
class DatasetStats:
    total_images: int
    total_annotations: int
    category_count: int
    unlabeled_count: int
    avg_annotations_per_image: float
    label_completion_rate: float  # 0..1
    category_distribution: list[tuple[str, int]]  # [(name, image_count)] 已按数量降序


@dataclass
class ImageSizeStats:
    min_w: int
    min_h: int
    max_w: int
    max_h: int
    median_w: int
    median_h: int


@dataclass
class ExtendedStats:
    """Extended stats computed by parsing all annotation files."""

    per_class_annotations: list[tuple[str, int]]  # [(label, count)] 降序
    objects_per_image_min: int = 0
    objects_per_image_max: int = 0
    objects_per_image_median: float = 0.0
    image_sizes: ImageSizeStats | None = None
    imbalance_ratio: float = 1.0  # max / min (1.0 = 完美平衡)
    warnings: list[str] = field(default_factory=list)


def compute_stats(dataset: Dataset) -> DatasetStats:
    total_images = dataset.total_images
    total_annotations = dataset.total_annotations
    labeled = sum(c.label_count for c in dataset.categories)
    unlabeled = total_images - labeled

    distribution = sorted(
        ((c.name, c.image_count) for c in dataset.categories),
        key=lambda x: x[1],
        reverse=True,
    )

    return DatasetStats(
        total_images=total_images,
        total_annotations=total_annotations,
        category_count=len(dataset.categories),
        unlabeled_count=unlabeled,
        avg_annotations_per_image=(total_annotations / total_images) if total_images else 0.0,
        label_completion_rate=(labeled / total_images) if total_images else 0.0,
        category_distribution=distribution,
    )


ProgressCb = type(lambda done, total, name: None)


_MAX_PARSE = 2000  # 超过此数量抽样，避免大数据集卡顿


def compute_extended_stats(dataset: Dataset, progress_cb=None) -> ExtendedStats:
    """Parse annotation files to compute per-class stats, image sizes, and warnings.

    For datasets > _MAX_PARSE images, samples a random subset and extrapolates.
    Call from a worker thread.
    """
    import random as _random

    class_counter: Counter[str] = Counter()
    objects_per_image: list[int] = []
    widths: list[int] = []
    heights: list[int] = []

    all_images = [img for cat in dataset.categories for img in cat.images]
    total = len(all_images)

    # For large datasets, sample to keep things responsive
    if total > _MAX_PARSE:
        sample = _random.sample(all_images, _MAX_PARSE)
        scale_factor = total / _MAX_PARSE
    else:
        sample = all_images
        scale_factor = 1.0

    for i, img in enumerate(sample):
        if progress_cb and i % 50 == 0:
            progress_cb(i + 1, len(sample), img.path.name)

        if not img.has_label or img.label_path is None:
            objects_per_image.append(0)
            continue

        classes = (
            load_yolo_classes(img.label_path.parent)
            if img.label_path.suffix.lower() == ".txt"
            else None
        )
        r = parse_annotation(img.label_path, img.path, yolo_class_names=classes)
        if not (r.ok and r.annotation):
            objects_per_image.append(0)
            continue

        shapes = r.annotation.shapes
        objects_per_image.append(len(shapes))
        for s in shapes:
            class_counter[s.label] += 1

        # Image dimensions from LabelMe JSON
        if img.label_path.suffix.lower() == ".json":
            try:
                import json as _json
                raw = _json.loads(img.label_path.read_text(encoding="utf-8"))
                w = raw.get("imageWidth", 0)
                h = raw.get("imageHeight", 0)
                if w > 0 and h > 0:
                    widths.append(int(w))
                    heights.append(int(h))
            except Exception:  # noqa: BLE001
                pass

    # Per-class annotations (scale up if sampled)
    if scale_factor > 1.0:
        per_class = sorted(
            ((label, int(count * scale_factor)) for label, count in class_counter.items()),
            key=lambda x: x[1], reverse=True,
        )
    else:
        per_class = sorted(class_counter.items(), key=lambda x: x[1], reverse=True)

    # Objects per image stats
    opi_min = min(objects_per_image) if objects_per_image else 0
    opi_max = max(objects_per_image) if objects_per_image else 0
    opi_median = median(objects_per_image) if objects_per_image else 0.0

    # Image size stats
    size_stats = None
    if widths and heights:
        size_stats = ImageSizeStats(
            min_w=min(widths), min_h=min(heights),
            max_w=max(widths), max_h=max(heights),
            median_w=int(median(widths)), median_h=int(median(heights)),
        )

    # Imbalance ratio
    counts = [c for _, c in per_class]
    if len(counts) >= 2 and min(counts) > 0:
        imbalance = max(counts) / min(counts)
    else:
        imbalance = 1.0

    # Warnings
    warnings: list[str] = []
    if not per_class:
        warnings.append("未检测到任何标注类别")
    else:
        for label, count in per_class:
            if count < 10:
                warnings.append(f"类别 \"{label}\" 仅有 {count} 个标注，可能不足以训练")
        if imbalance > 5:
            most, least = per_class[0], per_class[-1]
            warnings.append(
                f"类别严重不平衡：\"{most[0]}\"({most[1]}) vs \"{least[0]}\"({least[1]})，"
                f"比例 {imbalance:.1f}:1"
            )

    unlabeled = sum(1 for img in all_images if not img.has_label)
    if unlabeled > 0:
        pct = unlabeled / len(all_images) * 100
        warnings.append(f"{unlabeled} 张图片未标注（{pct:.1f}%）")

    return ExtendedStats(
        per_class_annotations=per_class,
        objects_per_image_min=opi_min,
        objects_per_image_max=opi_max,
        objects_per_image_median=opi_median,
        image_sizes=size_stats,
        imbalance_ratio=imbalance,
        warnings=warnings,
    )
