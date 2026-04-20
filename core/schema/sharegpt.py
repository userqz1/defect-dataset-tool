"""ShareGPT multimodal schema for LLaMA-Factory VLM fine-tuning.

v0.1 only supports the *template* Q&A backend (rule-based answers derived
from shapes/categories — see ``core.exporter.sharegpt._generate_answer``).
Local-LLM / OpenAI-compatible backends and custom Jinja2 templates are
deferred to v1.1+ per DataForge-设计方案-v1.2 §5.7.

Differs from CV schemas: the dataset must carry annotations for the template
backend to produce meaningful Q&A (shapeless samples fall back to a generic
description).
"""
from __future__ import annotations

from ..exporter.sharegpt import ShareGptExportOptions, export_sharegpt
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
        action_text="" if ok else "模板生成的 Q&A 质量依赖标注密度",
        fix_command="" if ok else "annotate",
        count=n_lbl,
        target=n_img,
    )


def _validate_qa_template(_: Dataset) -> SlotStatus:
    # v0.1 hardcodes the "describe" template baked into export_sharegpt.
    # Custom templates arrive in v1.1+.
    return SlotStatus(
        ok=True,
        current_text="内置描述模板",
        required_text="template 后端",
    )


def _validate_split(_: Dataset) -> SlotStatus:
    return SlotStatus(
        ok=False,
        current_text="未划分",
        required_text="train/val/test",
        action_text="导出时按比例划分",
        fix_command="split",
    )


def _validate_dataset_info(dataset: Dataset) -> SlotStatus:
    n_img, _, _ = _totals(dataset)
    return SlotStatus(
        ok=n_img > 0,
        current_text="自动生成" if n_img else "需要图片",
        required_text="LLaMA-Factory 清单",
    )


SHAREGPT_SCHEMA = Schema(
    key="ShareGPT",
    display_name="ShareGPT (LLaMA-Factory)",
    description="LLaMA-Factory 多模态微调 — ShareGPT 对话格式",
    task_types=(TaskType.DETECTION, TaskType.CLASSIFICATION),
    slots=(
        Slot("images", "图片", "images", required=True, validator=_validate_images),
        Slot("shapes", "标注来源", "labels", required=True, validator=_validate_shapes),
        Slot("qa_template", "Q&A 模板", "config", required=True, validator=_validate_qa_template),
        Slot("split", "训练/验证划分", "split", required=True, validator=_validate_split),
        Slot("dataset_info", "dataset_info.json", "meta",
             required=True, validator=_validate_dataset_info),
    ),
    options_class=ShareGptExportOptions,
    writer=export_sharegpt,
    directory_preview="sharegpt_{split}.json + images/{split}/ + dataset_info.json",
    docs_url="https://github.com/hiyouga/LLaMA-Factory/blob/main/data/README.md",
)
