"""Dataset statistics — basic (fast) and extended.

Primary path: ``compute_extended_stats_from_samples(ss)`` — reads from
in-memory SampleSet, no disk I/O, ~100× faster.

Legacy fallback: ``compute_extended_stats(dataset)`` — re-parses
annotation files from disk. Kept only for the rare case where
SampleSet is unavailable (e.g. very early scan phase). Scheduled
for removal once all callers migrate to the SampleSet path.
"""
from __future__ import annotations

import warnings
from collections import Counter
from dataclasses import dataclass, field
from statistics import median
from typing import TYPE_CHECKING

from .models import Dataset

if TYPE_CHECKING:
    from .unified import SampleSet


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


def _parse_one(img):
    """Parse one image's annotation for extended stats.

    Returns ``(objects_count, labels_counter, (w, h) or None)``. Runs off
    the main thread; no shared state mutation. Called from the
    ThreadPoolExecutor inside compute_extended_stats.

    .. deprecated:: Uses legacy annotation_formats; prefer
       ``compute_extended_stats_from_samples`` instead.
    """
    if not img.has_label or img.label_path is None:
        return 0, Counter(), None

    # Lazy import — avoids top-level dependency on annotation_formats
    from .annotation_formats import load_yolo_classes, parse_annotation

    classes = (
        load_yolo_classes(img.label_path.parent)
        if img.label_path.suffix.lower() == ".txt"
        else None
    )
    r = parse_annotation(img.label_path, img.path, yolo_class_names=classes)
    if not (r.ok and r.annotation):
        return 0, Counter(), None

    labels: Counter[str] = Counter()
    for s in r.annotation.shapes:
        labels[s.label] += 1

    # Image size: try PIL's image-header read first (fast: only reads
    # a few KB). Falls back to the LabelMe JSON's embedded dimensions
    # if the image doesn't open. For COCO layouts we previously
    # re-decoded the shared 500MB JSON for every sampled image just to
    # pull imageWidth/imageHeight — a massive waste (review #10).
    size = None
    try:
        from PIL import Image as _PIL
        with _PIL.open(img.path) as im:
            w, h = im.size
            if w > 0 and h > 0:
                size = (w, h)
    except Exception:  # noqa: BLE001
        # Fallback: LabelMe JSON only (COCO JSON has per-image sizes
        # but looking them up requires a whole-file parse we already
        # run once via parse_annotation's COCO cache).
        if img.label_path.suffix.lower() == ".json":
            try:
                import json as _json
                raw = _json.loads(img.label_path.read_text(encoding="utf-8-sig"))
                w = int(raw.get("imageWidth", 0))
                h = int(raw.get("imageHeight", 0))
                if w > 0 and h > 0:
                    size = (w, h)
            except Exception:  # noqa: BLE001
                pass
    return len(r.annotation.shapes), labels, size


def compute_extended_stats(dataset: Dataset, progress_cb=None) -> ExtendedStats:
    """Parse annotation files to compute per-class stats, image sizes, and warnings.

    .. deprecated::
        Use ``compute_extended_stats_from_samples`` with an in-memory
        ``SampleSet`` instead. This function re-parses every annotation
        file from disk — ~100× slower and maintains a parallel parsing
        path that diverges from format_in.

    For datasets > _MAX_PARSE images, samples a random subset and extrapolates.
    Parallelized with ThreadPoolExecutor (Python's json/xml release the GIL
    during I/O) — 4–8× speedup on 2k-sample scans versus the serial loop.
    Call from a worker thread; progress_cb fires on the calling thread.
    """
    warnings.warn(
        "compute_extended_stats() is deprecated; use "
        "compute_extended_stats_from_samples(sample_set) instead",
        DeprecationWarning, stacklevel=2,
    )
    import random as _random
    from concurrent.futures import ThreadPoolExecutor, as_completed

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

    n = len(sample)
    done = 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_parse_one, img): img for img in sample}
        for fut in as_completed(futures):
            done += 1
            if progress_cb and done % 50 == 0:
                progress_cb(done, n, "")
            try:
                n_objs, labels, size = fut.result()
            except Exception:  # noqa: BLE001
                continue
            objects_per_image.append(n_objs)
            class_counter.update(labels)
            if size is not None:
                widths.append(size[0])
                heights.append(size[1])

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


# ────────────────────────────────────────────────────────────────────
# SampleSet-based stats (no disk I/O)
# ────────────────────────────────────────────────────────────────────

def compute_extended_stats_from_samples(
    ss: SampleSet,
    progress_cb=None,
) -> ExtendedStats:
    """Compute extended stats from in-memory SampleSet — no disk I/O.

    Functionally identical to ``compute_extended_stats`` but reads region
    counts, class labels, and image dimensions directly from Sample
    objects. No sampling needed (in-memory iteration is fast).
    """
    class_counter: Counter[str] = Counter()
    objects_per_image: list[int] = []
    widths: list[int] = []
    heights: list[int] = []

    total = len(ss.samples)
    for i, sample in enumerate(ss.samples):
        if progress_cb and i > 0 and i % 200 == 0:
            progress_cb(i, total, "")

        n_objs = len(sample.regions)
        objects_per_image.append(n_objs)

        for r in sample.regions:
            class_counter[r.label] += 1

        if sample.image_width > 0 and sample.image_height > 0:
            widths.append(sample.image_width)
            heights.append(sample.image_height)

    if progress_cb:
        progress_cb(total, total, "")

    # No sampling ⇒ no scale factor
    per_class = sorted(class_counter.items(), key=lambda x: x[1], reverse=True)

    opi_min = min(objects_per_image) if objects_per_image else 0
    opi_max = max(objects_per_image) if objects_per_image else 0
    opi_median = median(objects_per_image) if objects_per_image else 0.0

    size_stats = None
    if widths and heights:
        size_stats = ImageSizeStats(
            min_w=min(widths), min_h=min(heights),
            max_w=max(widths), max_h=max(heights),
            median_w=int(median(widths)), median_h=int(median(heights)),
        )

    counts = [c for _, c in per_class]
    if len(counts) >= 2 and min(counts) > 0:
        imbalance = max(counts) / min(counts)
    else:
        imbalance = 1.0

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

    unlabeled = sum(1 for s in ss.samples if not s.has_label)
    if unlabeled > 0:
        pct = unlabeled / total * 100 if total else 0
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
