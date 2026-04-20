"""MVTec AD anomaly-detection schema.

Slot logic mirrors ``core.format_grid._build_mvtec`` (cf. DataForge-设计方案-v1.2 §5.6).
"""
from __future__ import annotations

from ..exporter.mvtec import MvtecExportOptions, export_mvtec
from ..models import Dataset
from ..task_types import TaskType
from .base import Schema, Slot, SlotStatus


def _has_good(dataset: Dataset) -> bool:
    return any((c.name or "").strip().lower() == "good" for c in dataset.categories)


def _validate_good(dataset: Dataset) -> SlotStatus:
    has_good = _has_good(dataset)
    if not dataset.categories:
        return SlotStatus(ok=False, current_text="未导入",
                          required_text="需要 'good' 分类",
                          action_text="导入图片并分类")
    return SlotStatus(
        ok=has_good,
        current_text="已有 good 类" if has_good else "缺 good 类",
        required_text="需要 'good' 分类",
        action_text="" if has_good else "将正常样本归入 good 类",
        fix_command="" if has_good else "classify_suggest",
    )


def _validate_defects(dataset: Dataset) -> SlotStatus:
    n_cat = len(dataset.categories)
    has_good = _has_good(dataset)
    n_defect = n_cat - (1 if has_good else 0)
    # Per v1.2 §5.6, defects are *optional* — a good-only dataset is valid
    # for unsupervised anomaly detection (one-class training).
    return SlotStatus(
        ok=True,  # never blocks export
        current_text=f"{n_defect} 种异常" if n_defect > 0 else "仅 good(单类)",
        required_text="可选",
        count=n_defect,
    )


def _validate_split(_: Dataset) -> SlotStatus:
    return SlotStatus(
        ok=False,
        current_text="未划分",
        required_text="train(good)/test(good + defects)",
        action_text="导出时按比例划分",
        fix_command="split",
    )


MVTEC_SCHEMA = Schema(
    key="MVTec",
    display_name="MVTec AD",
    description="MVTec 工业异常检测标准布局",
    task_types=(TaskType.ANOMALY,),
    slots=(
        Slot("good", "正常样本 (good)", "images", required=True, validator=_validate_good),
        Slot("defects", "异常样本", "images", required=False, validator=_validate_defects),
        Slot("split", "训练/测试划分", "split", required=True, validator=_validate_split),
    ),
    options_class=MvtecExportOptions,
    writer=export_mvtec,
    directory_preview="train/good/ + test/{good, defect_type}/",
    docs_url="https://www.mvtec.com/company/research/datasets/mvtec-ad",
)
