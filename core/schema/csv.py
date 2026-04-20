"""CSV (Pandas-friendly flat annotation) schema.

One row per annotation, columns:
  image_path, category, label, x1, y1, x2, y2, shape_type, split

Suits detection / classification / multi-label — any task whose truth
can be tabulated.
"""
from __future__ import annotations

from ..exporter.csv_export import CsvExportOptions, export_csv_dataset
from ..models import Dataset
from ..task_types import TaskType
from .base import Schema, Slot, SlotStatus


def _totals(dataset: Dataset) -> tuple[int, int, int]:
    n_img = sum(c.image_count for c in dataset.categories)
    n_lbl = sum(c.label_count for c in dataset.categories)
    return n_img, n_lbl, len(dataset.categories)


def _validate_images(dataset: Dataset) -> SlotStatus:
    n_img, _, _ = _totals(dataset)
    return SlotStatus(
        ok=n_img > 0,
        current_text=f"{n_img:,} 张" if n_img else "未导入",
        required_text="≥ 1",
        action_text="" if n_img else "导入图片",
        fix_command="" if n_img else "ingest",
        count=n_img,
    )


def _validate_labels(dataset: Dataset) -> SlotStatus:
    n_img, n_lbl, _ = _totals(dataset)
    # CSV tolerates missing annotations — rows without shapes are valid too.
    return SlotStatus(
        ok=True,
        current_text=f"{n_lbl:,}/{n_img:,} 条" if n_img else "无图片",
        required_text="可选",
        count=n_lbl,
        target=n_img,
    )


def _validate_split(_: Dataset) -> SlotStatus:
    return SlotStatus(
        ok=False,
        current_text="未划分",
        required_text="annotations_{split}.csv",
        action_text="导出时按比例划分",
        fix_command="split",
    )


CSV_SCHEMA = Schema(
    key="CSV",
    display_name="CSV (Pandas)",
    description="扁平 CSV 标注, 每行一个标注",
    task_types=(TaskType.DETECTION, TaskType.CLASSIFICATION, TaskType.MULTI_LABEL),
    slots=(
        Slot("images", "图片", "images", required=True, validator=_validate_images),
        Slot("labels", "标注", "labels", required=False, validator=_validate_labels),
        Slot("split", "训练/验证划分", "split", required=True, validator=_validate_split),
    ),
    options_class=CsvExportOptions,
    writer=export_csv_dataset,
    directory_preview="annotations_{split}.csv + images/{split}/",
)
