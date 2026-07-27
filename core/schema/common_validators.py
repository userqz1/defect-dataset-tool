"""Reusable Slot validators — kills the cut-and-paste across schemas.

Per review #3: every schema (YOLO / COCO / VOC / ImageFolder / MVTec /
ShareGPT / LLaVA / Swift / CSV / JSONL) re-defined the same handful of
checks ("at least N images", "labels cover all images", "≥ N classes",
"split pending"). The factories below return ``Slot`` objects bound to
captured thresholds + i18n strings; new schemas just compose them.

Each factory returns a ``Slot``, not a bare validator, so the slot's
human-facing name + display category travel with the predicate. This
keeps the schema definitions declarative.
"""
from __future__ import annotations


from ..models import Dataset
from .base import Slot, SlotStatus


# ---------- shared helpers ----------

def _totals(dataset: Dataset) -> tuple[int, int, int]:
    """Return (n_images, n_labels, n_categories) for the dataset."""
    n_img = sum(c.image_count for c in dataset.categories)
    n_lbl = sum(c.label_count for c in dataset.categories)
    return n_img, n_lbl, len(dataset.categories)


# ---------- factories ----------

def images_slot(min_count: int = 1, *, key: str = "images",
                 name: str = "图片", category: str = "images") -> Slot:
    """Slot that's OK when the dataset has at least *min_count* images."""
    def validate(ds: Dataset) -> SlotStatus:
        n_img, _, _ = _totals(ds)
        return SlotStatus(
            ok=n_img >= min_count,
            current_text=f"{n_img:,} 张" if n_img else "未导入",
            required_text=f"≥ {min_count}" if min_count > 1 else "≥ 1",
            action_text="" if n_img >= min_count else "导入图片",
            fix_command="" if n_img >= min_count else "ingest",
            count=n_img,
        )
    return Slot(key, name, category, required=True, validator=validate)


def full_label_coverage_slot(*, key: str = "labels",
                               name: str = "标注",
                               category: str = "labels") -> Slot:
    """Slot that's OK only when every image has a label file."""
    def validate(ds: Dataset) -> SlotStatus:
        n_img, n_lbl, _ = _totals(ds)
        if n_img == 0:
            return SlotStatus(
                ok=False,
                current_text="无图片",
                required_text="每张图一份标注",
                action_text="先导入图片",
            )
        ok = n_lbl >= n_img
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
    return Slot(key, name, category, required=True, validator=validate)


def classes_slot(min_count: int = 1, *, key: str = "classes",
                  name: str = "类别定义",
                  category: str = "meta") -> Slot:
    """Slot that's OK when the dataset has at least *min_count* categories."""
    def validate(ds: Dataset) -> SlotStatus:
        _, _, n_cat = _totals(ds)
        return SlotStatus(
            ok=n_cat >= min_count,
            current_text=f"{n_cat} 个类" if n_cat else "无",
            required_text=f"≥ {min_count}" if min_count > 1 else "≥ 1",
            action_text=("" if n_cat >= min_count
                         else f"需要至少 {min_count} 个类别"),
            count=n_cat,
        )
    return Slot(key, name, category, required=True, validator=validate)


def split_pending_slot(*, key: str = "split",
                        name: str = "训练/验证划分",
                        category: str = "split") -> Slot:
    """Slot reporting "split decided at export time" (always pending)."""
    def validate(_ds: Dataset) -> SlotStatus:
        return SlotStatus(
            ok=False,
            current_text="未划分",
            required_text="train/val/test",
            action_text="导出时按比例划分",
            fix_command="split",
        )
    return Slot(key, name, category, required=True, validator=validate)


def auto_generated_slot(slot_key: str, slot_label: str, *,
                         category: str = "meta",
                         needs_classes: bool = True) -> Slot:
    """Slot for files the writer auto-generates at export time.

    OK iff prerequisite (default: "≥1 category") is satisfied. Used for
    things like ``classes.txt``, ``data.yaml``, ``categories.json``.
    """
    def validate(ds: Dataset) -> SlotStatus:
        if needs_classes:
            _, _, n_cat = _totals(ds)
            ready = n_cat > 0
            current = "自动生成" if ready else "需要类别"
        else:
            ready = True
            current = "自动生成"
        return SlotStatus(
            ok=ready,
            current_text=current,
            required_text="导出时写入",
        )
    return Slot(slot_key, slot_label, category, required=True, validator=validate)
