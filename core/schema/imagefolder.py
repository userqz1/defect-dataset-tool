"""torchvision ImageFolder schema.

No per-image annotations — class is inferred from the containing directory.
Fits CLASSIFICATION / ANOMALY tasks (cf. DataForge-设计方案-v1.2 §5.6).
"""
from __future__ import annotations

from ..exporter.imagefolder import ImageFolderExportOptions, export_imagefolder
from ..models import Dataset
from ..task_types import TaskType
from .base import Schema, Slot, SlotStatus


def _totals(dataset: Dataset) -> tuple[int, int]:
    n_img = sum(c.image_count for c in dataset.categories)
    return n_img, len(dataset.categories)


def _validate_images(dataset: Dataset) -> SlotStatus:
    n_img, _ = _totals(dataset)
    return SlotStatus(
        ok=n_img > 0,
        current_text=f"{n_img:,} 张" if n_img else "未导入",
        required_text="≥ 1",
        action_text="" if n_img else "导入图片",
        fix_command="" if n_img else "ingest",
        count=n_img,
    )


def _validate_classes(dataset: Dataset) -> SlotStatus:
    _, n_cat = _totals(dataset)
    ok = n_cat >= 2
    return SlotStatus(
        ok=ok,
        current_text=f"{n_cat} 个类" if n_cat else "无",
        required_text="≥ 2",
        action_text="" if ok else "分类任务需要至少两个类别",
        fix_command="" if ok else "classify_suggest",
        count=n_cat,
        target=2,
    )


def _validate_split(_: Dataset) -> SlotStatus:
    return SlotStatus(
        ok=False,
        current_text="未划分",
        required_text="train/val/test",
        action_text="导出时按比例划分",
        fix_command="split",
    )


IMAGEFOLDER_SCHEMA = Schema(
    key="ImageFolder",
    display_name="ImageFolder",
    description="torchvision ImageFolder 分类布局",
    task_types=(TaskType.CLASSIFICATION, TaskType.ANOMALY),
    slots=(
        Slot("images", "图片", "images", required=True, validator=_validate_images),
        Slot("classes", "分类标签", "labels", required=True, validator=_validate_classes),
        Slot("split", "训练/验证划分", "split", required=True, validator=_validate_split),
    ),
    options_class=ImageFolderExportOptions,
    writer=export_imagefolder,
    directory_preview="{split}/{class}/*.jpg",
    docs_url="https://pytorch.org/vision/stable/generated/torchvision.datasets.ImageFolder.html",
)
