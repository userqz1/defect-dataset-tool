"""Ultralytics YOLO-OBB schema."""
from __future__ import annotations

from ..exporter.yolo_obb import YoloObbExportOptions, export_yolo_obb
from ..task_types import TaskType
from .base import Schema
from .common_validators import (
    auto_generated_slot,
    classes_slot,
    full_label_coverage_slot,
    images_slot,
    split_pending_slot,
)


YOLO_OBB_SCHEMA = Schema(
    key="YOLO-OBB",
    display_name="YOLO-OBB (Ultralytics)",
    description="Ultralytics 旋转框检测格式",
    task_types=(TaskType.ORIENTED_DET,),
    slots=(
        images_slot(),
        full_label_coverage_slot(),
        classes_slot(),
        split_pending_slot(),
        auto_generated_slot("classes_txt", "classes.txt"),
        auto_generated_slot("data_yaml", "data.yaml"),
    ),
    options_class=YoloObbExportOptions,
    writer=export_yolo_obb,
    directory_preview="images/{split}/ + labels/{split}/ + classes.txt + data.yaml",
    docs_url="https://docs.ultralytics.com/datasets/obb/",
)
