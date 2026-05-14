"""LabelMe JSON export schema for geometry-first annotation tasks."""
from __future__ import annotations

from ..exporter.labelme import LabelMeJsonExportOptions, export_labelme_json
from ..task_types import TaskType
from .base import Schema
from .common_validators import (
    full_label_coverage_slot,
    images_slot,
    split_pending_slot,
)


LABELME_SCHEMA = Schema(
    key="LabelMe JSON",
    display_name="LabelMe JSON",
    description="LabelMe per-image JSON, preserves polygons and keypoints",
    task_types=(
        TaskType.DETECTION,
        TaskType.SEMANTIC_SEG,
        TaskType.INSTANCE_SEG,
        TaskType.KEYPOINT,
    ),
    slots=(
        images_slot(),
        full_label_coverage_slot(name="geometry annotations"),
        split_pending_slot(),
    ),
    options_class=LabelMeJsonExportOptions,
    writer=export_labelme_json,
    directory_preview="images/{split}/ + labels/{split}/*.json",
)
