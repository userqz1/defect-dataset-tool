"""ms-swift VLM fine-tuning schema (ModelScope).

Qwen-VL / InternVL / GLM-4V 走 ms-swift 训练时使用. v0.1 template-only
backend (same as ShareGPT), 自定义模板 v1.1+.
"""
from __future__ import annotations

from ..exporter.swift import SwiftExportOptions, export_swift
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


def _validate_shapes(dataset: Dataset) -> SlotStatus:
    n_img, n_lbl, _ = _totals(dataset)
    if n_img == 0:
        return SlotStatus(ok=False, current_text="无图片",
                          required_text="≥ 50% 图含标注",
                          action_text="先导入图片")
    coverage = n_lbl / n_img if n_img else 0.0
    ok = coverage >= 0.5
    return SlotStatus(
        ok=ok,
        current_text=f"{n_lbl:,}/{n_img:,} ({coverage:.0%})",
        required_text="≥ 50%",
        action_text="" if ok else "模板 Q&A 质量依赖标注密度",
        fix_command="" if ok else "annotate",
        count=n_lbl,
        target=n_img,
    )


def _validate_qa_template(_: Dataset) -> SlotStatus:
    return SlotStatus(
        ok=True,
        current_text="内置描述模板",
        required_text="template 后端",
    )


def _validate_split(_: Dataset) -> SlotStatus:
    return SlotStatus(
        ok=False,
        current_text="未划分",
        required_text="swift_{split}.jsonl",
        action_text="导出时按比例划分",
        fix_command="split",
    )


SWIFT_SCHEMA = Schema(
    key="Swift",
    display_name="ms-swift",
    description="ModelScope ms-swift VLM 微调格式",
    task_types=(
        TaskType.DETECTION,
        TaskType.ORIENTED_DET,
        TaskType.SEMANTIC_SEG,
        TaskType.INSTANCE_SEG,
        TaskType.CLASSIFICATION,
    ),
    slots=(
        Slot("images", "图片", "images", required=True, validator=_validate_images),
        Slot("shapes", "标注来源", "labels", required=True, validator=_validate_shapes),
        Slot("qa_template", "Q&A 模板", "config", required=True, validator=_validate_qa_template),
        Slot("split", "训练/验证划分", "split", required=True, validator=_validate_split),
    ),
    options_class=SwiftExportOptions,
    writer=export_swift,
    directory_preview="swift_{split}.jsonl + images/{split}/",
    docs_url="https://github.com/modelscope/ms-swift",
)
