"""DOTA oriented detection schema."""
from __future__ import annotations

from ..exporter.dota import DotaExportOptions, export_dota
from ..task_types import TaskType
from .base import Schema
from .common_validators import (
    auto_generated_slot,
    classes_slot,
    full_label_coverage_slot,
    images_slot,
    split_pending_slot,
)


DOTA_SCHEMA = Schema(
    key="DOTA",
    display_name="DOTA",
    description="DOTA 旋转框 labelTxt 格式",
    task_types=(TaskType.ORIENTED_DET,),
    slots=(
        images_slot(),
        full_label_coverage_slot(),
        classes_slot(),
        split_pending_slot(),
        auto_generated_slot("classes_txt", "classes.txt"),
    ),
    options_class=DotaExportOptions,
    writer=export_dota,
    directory_preview="images/{split}/ + labelTxt/{split}/ + classes.txt",
    docs_url="https://captain-whu.github.io/DOTA/",
)
