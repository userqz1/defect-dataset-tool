"""LLaVA VLM fine-tuning schema (alternative to ShareGPT).

Conversations with position descriptions — v0.1 ships a template-based
backend; custom templates / LLM Q&A arrive in v1.1+. Primarily detection
(positions depend on bbox centers).
"""
from __future__ import annotations

from ..exporter.llava import LlavaExportOptions, export_llava
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
        current_text="内置位置描述模板",
        required_text="template 后端",
    )


def _validate_split(_: Dataset) -> SlotStatus:
    return SlotStatus(
        ok=False,
        current_text="未划分",
        required_text="llava_{split}.jsonl",
        action_text="导出时按比例划分",
        fix_command="split",
    )


LLAVA_SCHEMA = Schema(
    key="LLaVA",
    display_name="LLaVA",
    description="LLaVA 多模态微调 JSONL, 带位置描述",
    task_types=(TaskType.DETECTION,),
    slots=(
        Slot("images", "图片", "images", required=True, validator=_validate_images),
        Slot("shapes", "标注来源", "labels", required=True, validator=_validate_shapes),
        Slot("qa_template", "Q&A 模板", "config", required=True, validator=_validate_qa_template),
        Slot("split", "训练/验证划分", "split", required=True, validator=_validate_split),
    ),
    options_class=LlavaExportOptions,
    writer=export_llava,
    directory_preview="llava_{split}.jsonl + images/{split}/",
    docs_url="https://github.com/haotian-liu/LLaVA",
)
