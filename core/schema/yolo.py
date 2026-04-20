"""YOLO (Ultralytics) schema — reference implementation.

Declares what a dataset must fill to export to Ultralytics YOLO format,
and wires existing ``core.exporter.yolo`` as the writer.

Slot validators come from :mod:`core.schema.common_validators` (review
#3) — every schema previously hand-rolled the same "≥1 image", "labels
cover all images", "≥1 class", "split pending" predicates. New schemas
should follow this pattern and reuse the factories instead of pasting
the same closure each time.
"""
from __future__ import annotations

from ..exporter.yolo import YoloExportOptions, export_yolo
from ..task_types import TaskType
from .base import Schema
from .common_validators import (
    auto_generated_slot,
    classes_slot,
    full_label_coverage_slot,
    images_slot,
    split_pending_slot,
)


YOLO_SCHEMA = Schema(
    key="YOLO",
    display_name="YOLO (Ultralytics)",
    description="Ultralytics YOLO 检测/分割格式",
    task_types=(TaskType.DETECTION,),
    slots=(
        images_slot(),
        full_label_coverage_slot(),
        classes_slot(),
        split_pending_slot(),
        auto_generated_slot("classes_txt", "classes.txt"),
        auto_generated_slot("data_yaml", "data.yaml"),
    ),
    options_class=YoloExportOptions,
    writer=export_yolo,
    directory_preview="images/{split}/ + labels/{split}/ + classes.txt + data.yaml",
    docs_url="https://docs.ultralytics.com/datasets/detect/",
)
