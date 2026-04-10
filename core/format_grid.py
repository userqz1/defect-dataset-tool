"""Format grid — defines what each target format needs ("the grid"),
and checks how much of the grid is filled by the current dataset.

Core concept: the output format is KNOWN (the grid shape), the input
is UNKNOWN (messy data). This module tells you what slots exist and
which ones are filled.

Pure Python — no PyQt imports.

Usage::

    from core.format_grid import build_grid

    grid = build_grid("YOLO", dataset)
    for slot in grid.slots:
        print(slot.icon, slot.name, slot.status_text)
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .models import Dataset


@dataclass
class GridSlot:
    """One requirement slot in the target format grid."""
    name: str              # human-readable: "训练集图片"
    category: str          # "images" / "labels" / "split" / "meta" / "export"
    required: bool         # must fill for valid export
    filled: bool           # current state
    count: int = 0         # items in this slot
    target: int = 0        # target count (0 = any)
    fill_node: str = ""    # which node fills this: "import" / "annotate" / "split" / "augment"
    status_text: str = ""  # "1,234 张" / "未导入" / etc.

    @property
    def icon(self) -> str:
        if self.filled:
            return "✓"
        return "✗" if self.required else "–"

    @property
    def progress(self) -> float:
        """0.0 ~ 1.0 fill progress."""
        if self.filled:
            return 1.0
        if self.target > 0 and self.count > 0:
            return min(self.count / self.target, 0.99)
        return 0.0


@dataclass
class FormatGrid:
    """Complete grid for a target format — all slots and their fill state."""
    format_name: str
    slots: list[GridSlot] = field(default_factory=list)

    @property
    def filled_count(self) -> int:
        return sum(1 for s in self.slots if s.filled)

    @property
    def required_count(self) -> int:
        return sum(1 for s in self.slots if s.required)

    @property
    def required_filled(self) -> int:
        return sum(1 for s in self.slots if s.required and s.filled)

    @property
    def ready(self) -> bool:
        return all(s.filled for s in self.slots if s.required)

    @property
    def progress_text(self) -> str:
        return f"{self.required_filled}/{self.required_count}"


# ---------- Grid builders per format ----------

def _common_slots(dataset: Dataset | None) -> dict:
    """Compute common metrics reused by all format builders."""
    if dataset is None:
        return {"n_img": 0, "n_lbl": 0, "n_cat": 0, "n_unlabeled": 0, "cats": []}
    n_img = sum(c.image_count for c in dataset.categories)
    n_lbl = sum(c.label_count for c in dataset.categories)
    n_cat = len(dataset.categories)
    return {
        "n_img": n_img,
        "n_lbl": n_lbl,
        "n_cat": n_cat,
        "n_unlabeled": n_img - n_lbl,
        "cats": [c.name for c in dataset.categories],
    }


def _build_yolo(dataset: Dataset | None) -> FormatGrid:
    m = _common_slots(dataset)
    return FormatGrid(format_name="YOLO", slots=[
        GridSlot("图片", "images", True, m["n_img"] > 0,
                 count=m["n_img"], fill_node="import",
                 status_text=f"{m['n_img']:,} 张" if m["n_img"] else "未导入"),
        GridSlot("标注", "labels", True, m["n_lbl"] > 0,
                 count=m["n_lbl"], target=m["n_img"], fill_node="annotate",
                 status_text=f"{m['n_lbl']:,} 条" if m["n_lbl"] else "未标注"),
        GridSlot("类别定义", "meta", True, m["n_cat"] > 0,
                 count=m["n_cat"], fill_node="",
                 status_text=f"{m['n_cat']} 个类" if m["n_cat"] else "无"),
        GridSlot("训练集/验证集划分", "split", True, False,
                 fill_node="split", status_text="未划分"),
        GridSlot("classes.txt", "meta", True, m["n_cat"] > 0,
                 status_text="自动生成" if m["n_cat"] else "需要类别"),
        GridSlot("data.yaml", "meta", True, m["n_cat"] > 0,
                 status_text="自动生成" if m["n_cat"] else "需要类别"),
    ])


def _build_coco(dataset: Dataset | None) -> FormatGrid:
    m = _common_slots(dataset)
    return FormatGrid(format_name="COCO", slots=[
        GridSlot("图片", "images", True, m["n_img"] > 0,
                 count=m["n_img"], fill_node="import",
                 status_text=f"{m['n_img']:,} 张" if m["n_img"] else "未导入"),
        GridSlot("标注", "labels", True, m["n_lbl"] > 0,
                 count=m["n_lbl"], target=m["n_img"], fill_node="annotate",
                 status_text=f"{m['n_lbl']:,} 条" if m["n_lbl"] else "未标注"),
        GridSlot("类别定义", "meta", True, m["n_cat"] > 0,
                 count=m["n_cat"],
                 status_text=f"{m['n_cat']} 个类" if m["n_cat"] else "无"),
        GridSlot("训练集/验证集划分", "split", True, False,
                 fill_node="split", status_text="未划分"),
        GridSlot("instances_*.json", "meta", True, False,
                 status_text="导出时生成"),
    ])


def _build_voc(dataset: Dataset | None) -> FormatGrid:
    m = _common_slots(dataset)
    return FormatGrid(format_name="Pascal VOC", slots=[
        GridSlot("图片", "images", True, m["n_img"] > 0,
                 count=m["n_img"], fill_node="import",
                 status_text=f"{m['n_img']:,} 张" if m["n_img"] else "未导入"),
        GridSlot("标注 XML", "labels", True, m["n_lbl"] > 0,
                 count=m["n_lbl"], target=m["n_img"], fill_node="annotate",
                 status_text=f"{m['n_lbl']:,} 条" if m["n_lbl"] else "未标注"),
        GridSlot("训练集/验证集划分", "split", True, False,
                 fill_node="split", status_text="未划分"),
    ])


def _build_imagefolder(dataset: Dataset | None) -> FormatGrid:
    m = _common_slots(dataset)
    return FormatGrid(format_name="ImageFolder", slots=[
        GridSlot("图片", "images", True, m["n_img"] > 0,
                 count=m["n_img"], fill_node="import",
                 status_text=f"{m['n_img']:,} 张" if m["n_img"] else "未导入"),
        GridSlot("分类标签", "labels", True, m["n_cat"] >= 2,
                 count=m["n_cat"], fill_node="",
                 status_text=f"{m['n_cat']} 个类" if m["n_cat"] >= 2 else "需要≥2个分类"),
        GridSlot("训练集/验证集划分", "split", True, False,
                 fill_node="split", status_text="未划分"),
    ])


def _build_mvtec(dataset: Dataset | None) -> FormatGrid:
    m = _common_slots(dataset)
    has_good = "good" in [c.lower() for c in m["cats"]] if m["cats"] else False
    return FormatGrid(format_name="MVTec AD", slots=[
        GridSlot("正常样本 (good)", "images", True, has_good,
                 fill_node="import",
                 status_text="已有 good 类" if has_good else "需要 'good' 分类"),
        GridSlot("异常样本", "images", False, m["n_cat"] >= 2,
                 count=m["n_cat"] - (1 if has_good else 0),
                 status_text=f"{m['n_cat'] - 1} 种异常" if m["n_cat"] >= 2 else "可选"),
        GridSlot("训练集/测试集划分", "split", True, False,
                 fill_node="split", status_text="未划分"),
    ])


_BUILDERS = {
    "YOLO": _build_yolo,
    "COCO": _build_coco,
    "Pascal VOC": _build_voc,
    "VOC": _build_voc,
    "ImageFolder": _build_imagefolder,
    "MVTec": _build_mvtec,
    "CSV": lambda ds: FormatGrid("CSV", [
        GridSlot("图片", "images", True, _common_slots(ds)["n_img"] > 0,
                 count=_common_slots(ds)["n_img"], status_text=f"{_common_slots(ds)['n_img']:,} 张"),
    ]),
    "JSON Lines": lambda ds: FormatGrid("JSON Lines", [
        GridSlot("图片", "images", True, _common_slots(ds)["n_img"] > 0,
                 count=_common_slots(ds)["n_img"], status_text=f"{_common_slots(ds)['n_img']:,} 张"),
    ]),
}


def build_grid(format_name: str, dataset: Dataset | None = None) -> FormatGrid:
    """Build a format grid showing what's needed and what's filled."""
    builder = _BUILDERS.get(format_name)
    if builder is None:
        return FormatGrid(format_name, [])
    return builder(dataset)


def available_formats() -> list[str]:
    """All formats that have grid definitions."""
    return list(_BUILDERS.keys())
