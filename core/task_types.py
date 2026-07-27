"""Task type registry — defines what annotation form, export formats,
and augmentation behavior apply to each CV task type.

Usage::

    from core.task_types import TaskType, TASK_REGISTRY

    info = TASK_REGISTRY[TaskType.DETECTION]
    print(info.display_name)        # "目标检测"
    print(info.export_formats)      # ("YOLO", "COCO", "VOC", ...)
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TaskType(str, Enum):
    """Image dataset task type. Stored in project config."""

    # Image-level
    CLASSIFICATION = "classification"
    MULTI_LABEL = "multi_label"
    ANOMALY = "anomaly_detection"

    # Region-level
    DETECTION = "object_detection"
    ORIENTED_DET = "oriented_detection"

    # Pixel-level
    SEMANTIC_SEG = "semantic_segmentation"
    INSTANCE_SEG = "instance_segmentation"

    # Point-level
    KEYPOINT = "keypoint_detection"

    # Pair
    IMAGE_PAIR = "image_pair"


@dataclass(frozen=True)
class TaskTypeInfo:
    """Metadata for a task type — drives UI, export, and augmentation logic."""

    task_type: TaskType
    display_name: str
    annotation_level: str          # "image" | "region" | "pixel" | "point" | "pair"
    needs_shapes: bool             # requires bbox / polygon / point annotations
    needs_image_label: bool        # requires image-level class label
    valid_shape_types: tuple[str, ...]
    export_formats: tuple[str, ...]
    augment_updates_shapes: bool   # geometric augment must update annotation coords


TASK_REGISTRY: dict[TaskType, TaskTypeInfo] = {
    TaskType.CLASSIFICATION: TaskTypeInfo(
        task_type=TaskType.CLASSIFICATION,
        display_name="图像分类",
        annotation_level="image",
        needs_shapes=False,
        needs_image_label=True,
        valid_shape_types=(),
        export_formats=("ImageFolder", "CSV", "JSONL"),
        augment_updates_shapes=False,
    ),
    TaskType.MULTI_LABEL: TaskTypeInfo(
        task_type=TaskType.MULTI_LABEL,
        display_name="多标签分类",
        annotation_level="image",
        needs_shapes=False,
        needs_image_label=True,
        valid_shape_types=(),
        export_formats=("CSV", "JSONL"),
        augment_updates_shapes=False,
    ),
    TaskType.ANOMALY: TaskTypeInfo(
        task_type=TaskType.ANOMALY,
        display_name="异常检测",
        annotation_level="image",
        needs_shapes=False,
        needs_image_label=True,
        valid_shape_types=(),
        export_formats=("MVTec", "ImageFolder"),
        augment_updates_shapes=False,
    ),
    TaskType.DETECTION: TaskTypeInfo(
        task_type=TaskType.DETECTION,
        display_name="目标检测",
        annotation_level="region",
        needs_shapes=True,
        needs_image_label=False,
        valid_shape_types=("rectangle", "polygon"),
        export_formats=("YOLO", "COCO", "VOC", "CSV", "JSONL", "LLaVA", "ShareGPT", "Swift"),
        augment_updates_shapes=True,
    ),
    TaskType.ORIENTED_DET: TaskTypeInfo(
        task_type=TaskType.ORIENTED_DET,
        display_name="旋转框检测",
        annotation_level="region",
        needs_shapes=True,
        needs_image_label=False,
        valid_shape_types=("polygon",),
        export_formats=("YOLO-OBB", "DOTA", "LabelMe JSON", "JSONL", "LLaVA", "ShareGPT", "Swift"),
        augment_updates_shapes=True,
    ),
    TaskType.SEMANTIC_SEG: TaskTypeInfo(
        task_type=TaskType.SEMANTIC_SEG,
        display_name="语义分割",
        annotation_level="pixel",
        needs_shapes=True,
        needs_image_label=False,
        valid_shape_types=("polygon",),
        export_formats=("JSONL", "LabelMe JSON", "LLaVA", "ShareGPT", "Swift"),
        augment_updates_shapes=True,
    ),
    TaskType.INSTANCE_SEG: TaskTypeInfo(
        task_type=TaskType.INSTANCE_SEG,
        display_name="实例分割",
        annotation_level="pixel",
        needs_shapes=True,
        needs_image_label=False,
        valid_shape_types=("polygon",),
        export_formats=("JSONL", "LabelMe JSON", "LLaVA", "ShareGPT", "Swift"),
        augment_updates_shapes=True,
    ),
    TaskType.KEYPOINT: TaskTypeInfo(
        task_type=TaskType.KEYPOINT,
        display_name="关键点检测",
        annotation_level="point",
        needs_shapes=True,
        needs_image_label=False,
        valid_shape_types=("point", "rectangle"),
        export_formats=("LabelMe JSON",),
        augment_updates_shapes=True,
    ),
    TaskType.IMAGE_PAIR: TaskTypeInfo(
        task_type=TaskType.IMAGE_PAIR,
        display_name="图像对",
        annotation_level="pair",
        needs_shapes=False,
        needs_image_label=False,
        valid_shape_types=(),
        export_formats=("PairedFolder",),
        augment_updates_shapes=False,
    ),
}


def get_task_info(task_type: TaskType) -> TaskTypeInfo:
    """Lookup task type metadata. Raises KeyError for unknown types."""
    return TASK_REGISTRY[task_type]
