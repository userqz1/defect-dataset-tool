"""Pascal VOC schema.

Slot logic mirrors ``core.format_grid._build_voc`` (cf. DataForge-设计方案-v1.2 §5.6).
"""
from __future__ import annotations

from ..exporter.voc import VocExportOptions, export_voc
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
                          required_text="每张图一个 xml",
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


def _validate_split(_: Dataset) -> SlotStatus:
    return SlotStatus(
        ok=False,
        current_text="未划分",
        required_text="ImageSets/Main/{split}.txt",
        action_text="导出时按比例划分",
        fix_command="split",
    )


VOC_SCHEMA = Schema(
    key="VOC",
    display_name="Pascal VOC",
    description="Pascal VOC XML 格式",
    task_types=(TaskType.DETECTION,),
    slots=(
        Slot("images", "图片", "images", required=True, validator=_validate_images),
        Slot("labels", "标注 XML", "labels", required=True, validator=_validate_labels),
        Slot("split", "训练/验证划分", "split", required=True, validator=_validate_split),
    ),
    options_class=VocExportOptions,
    writer=export_voc,
    directory_preview="JPEGImages/ + Annotations/ + ImageSets/Main/",
    docs_url="http://host.robots.ox.ac.uk/pascal/VOC/voc2012/devkit_doc.pdf",
)
