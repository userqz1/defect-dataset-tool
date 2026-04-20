"""YOLO (Ultralytics) schema — reference implementation.

Declares what a dataset must fill to export to Ultralytics YOLO format,
and wires existing ``core.exporter.yolo`` as the writer.

Slot logic mirrors ``core.format_grid._build_yolo`` one-to-one (the older
format_grid module stays around during the v1.2 migration; this file is
the canonical definition going forward).
"""
from __future__ import annotations

from ..exporter.yolo import YoloExportOptions, export_yolo
from ..models import Dataset
from ..task_types import TaskType
from .base import Schema, Slot, SlotStatus


# ---------- slot validators ----------

def _totals(dataset: Dataset) -> tuple[int, int, int]:
    """(n_images, n_labels, n_categories)."""
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
    ok = n_lbl > 0 and n_lbl >= n_img  # all images annotated
    if n_img == 0:
        return SlotStatus(
            ok=False,
            current_text="无图片",
            required_text="每张图一个 txt",
            action_text="先导入图片",
        )
    unlabeled = max(n_img - n_lbl, 0)
    return SlotStatus(
        ok=ok,
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
        action_text="" if n_cat else "需要至少一个类别",
        count=n_cat,
    )


def _validate_split(dataset: Dataset) -> SlotStatus:
    # v0.1: split is decided at export time (ratio in wizard), not stored on
    # the dataset. Always report "pending — chosen at export" rather than ok.
    return SlotStatus(
        ok=False,
        current_text="未划分",
        required_text="train/val/test",
        action_text="导出时按比例划分",
        fix_command="split",
    )


def _validate_classes_txt(dataset: Dataset) -> SlotStatus:
    _, _, n_cat = _totals(dataset)
    return SlotStatus(
        ok=n_cat > 0,
        current_text="自动生成" if n_cat else "需要类别",
        required_text="导出时写入",
    )


def _validate_data_yaml(dataset: Dataset) -> SlotStatus:
    _, _, n_cat = _totals(dataset)
    return SlotStatus(
        ok=n_cat > 0,
        current_text="自动生成" if n_cat else "需要类别",
        required_text="导出时写入",
    )


# ---------- schema instance ----------

YOLO_SCHEMA = Schema(
    key="YOLO",
    display_name="YOLO (Ultralytics)",
    description="Ultralytics YOLO 检测/分割格式",
    task_types=(TaskType.DETECTION,),
    slots=(
        Slot("images", "图片", "images", required=True, validator=_validate_images),
        Slot("labels", "标注", "labels", required=True, validator=_validate_labels),
        Slot("classes", "类别定义", "meta", required=True, validator=_validate_classes),
        Slot("split", "训练/验证划分", "split", required=True, validator=_validate_split),
        Slot("classes_txt", "classes.txt", "meta", required=True, validator=_validate_classes_txt),
        Slot("data_yaml", "data.yaml", "meta", required=True, validator=_validate_data_yaml),
    ),
    options_class=YoloExportOptions,
    writer=export_yolo,
    directory_preview="images/{split}/ + labels/{split}/ + classes.txt + data.yaml",
    docs_url="https://docs.ultralytics.com/datasets/detect/",
)
