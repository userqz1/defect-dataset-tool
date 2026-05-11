"""JSON Lines streaming annotation schema.

One JSON object per line — suits large datasets (streamable, append-able)
and data pipelines (Spark / pandas.read_json lines=True).
"""
from __future__ import annotations

from ..exporter.jsonl import JsonlExportOptions, export_jsonl
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
        required_text="{split}.jsonl",
        action_text="导出时按比例划分",
        fix_command="split",
    )


JSONL_SCHEMA = Schema(
    key="JSONL",
    display_name="JSON Lines",
    description="流式 JSON Lines, 每行一个图像条目",
    task_types=(
        TaskType.DETECTION,
        TaskType.ORIENTED_DET,
        TaskType.SEMANTIC_SEG,
        TaskType.INSTANCE_SEG,
        TaskType.CLASSIFICATION,
        TaskType.MULTI_LABEL,
    ),
    slots=(
        Slot("images", "图片", "images", required=True, validator=_validate_images),
        Slot("labels", "标注", "labels", required=False, validator=_validate_labels),
        Slot("split", "训练/验证划分", "split", required=True, validator=_validate_split),
    ),
    options_class=JsonlExportOptions,
    writer=export_jsonl,
    directory_preview="{split}.jsonl + images/{split}/",
)
