"""Dataset statistics."""
from __future__ import annotations

from dataclasses import dataclass

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
