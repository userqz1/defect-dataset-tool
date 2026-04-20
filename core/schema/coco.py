"""COCO detection schema.

Slot logic mirrors ``core.format_grid._build_coco`` (cf. DataForge-设计方案-v1.2 §5.6).
"""
from __future__ import annotations

from ..exporter.coco import CocoExportOptions, export_coco
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
    if n_img == 0:
        return SlotStatus(ok=False, current_text="无图片",
                          required_text="每张图一个 bbox",
                          action_text="先导入图片")
    unlabeled = max(n_img - n_lbl, 0)
    return SlotStatus(
        ok=n_lbl > 0 and n_lbl >= n_img,
        current_text=f"{n_lbl:,}/{n_img:,} 条",
        required_text="100%",
        action_text=f"{unlabeled} 张未标注" if unlabeled else "",
        fix_command="annotate" if unlabeled else "",
        count=n_lbl,
        target=n_img,
    )


def _validate_classes(dataset: Dataset) -> SlotStatus:
    _, _, n_cat = _totals(dataset)
    return SlotStatus(
        ok=n_cat > 0,
        current_text=f"{n_cat} 个类" if n_cat else "无",
        required_text="≥ 1",
        count=n_cat,
    )


def _validate_split(_: Dataset) -> SlotStatus:
    return SlotStatus(
        ok=False,
        current_text="未划分",
        required_text="train/val/test",
        action_text="导出时按比例划分",
        fix_command="split",
    )


def _validate_instances_json(dataset: Dataset) -> SlotStatus:
    _, _, n_cat = _totals(dataset)
    return SlotStatus(
        ok=n_cat > 0,
        current_text="自动生成" if n_cat else "需要类别",
        required_text="导出时写入",
    )


COCO_SCHEMA = Schema(
    key="COCO",
    display_name="COCO",
    description="COCO 检测 JSON 格式",
    task_types=(TaskType.DETECTION,),
    slots=(
        Slot("images", "图片", "images", required=True, validator=_validate_images),
        Slot("labels", "标注", "labels", required=True, validator=_validate_labels),
        Slot("classes", "类别定义", "meta", required=True, validator=_validate_classes),
        Slot("split", "训练/验证划分", "split", required=True, validator=_validate_split),
        Slot("instances_json", "instances_*.json", "meta",
             required=True, validator=_validate_instances_json),
    ),
    options_class=CocoExportOptions,
    writer=export_coco,
    directory_preview="annotations/instances_{split}.json + {split}/",
    docs_url="https://cocodataset.org/#format-data",
)
