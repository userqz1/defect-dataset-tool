"""Format conversion metadata — field capabilities and loss hints.

Provides a registry of format capabilities so the conversion wizard can
show what fields each format supports, what gets lost in a conversion,
and what field mapping is needed.

Pure Python — no PyQt.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class FieldSupport(Enum):
    """How well a format handles a particular data field."""
    FULL = "full"           # native support, no loss
    PARTIAL = "partial"     # supported with some loss (e.g. polygon → bbox)
    NONE = "none"           # not supported, data is dropped


@dataclass(frozen=True)
class FormatInfo:
    """Describes a single annotation format's capabilities."""
    key: str                           # "labelme", "yolo", etc.
    display_name: str                  # human-readable
    file_ext: str                      # primary extension
    dataset_level: bool = False        # True = one file per dataset (COCO)
    # Field support map
    bbox: FieldSupport = FieldSupport.NONE
    polygon: FieldSupport = FieldSupport.NONE
    keypoints: FieldSupport = FieldSupport.NONE
    classification: FieldSupport = FieldSupport.NONE
    caption: FieldSupport = FieldSupport.NONE
    conversations: FieldSupport = FieldSupport.NONE
    grounding: FieldSupport = FieldSupport.NONE
    image_copy: bool = True            # writer copies images


@dataclass
class ConversionHint:
    """What happens when converting from one format to another."""
    src: str
    dst: str
    preserved: list[str] = field(default_factory=list)
    degraded: list[str] = field(default_factory=list)   # partial
    lost: list[str] = field(default_factory=list)        # dropped entirely
    notes: list[str] = field(default_factory=list)       # extra warnings


# ── Format registry ──────────────────────────────────────────────────

FORMATS: dict[str, FormatInfo] = {}

def _reg(info: FormatInfo) -> None:
    FORMATS[info.key] = info

_reg(FormatInfo(
    key="labelme", display_name="LabelMe JSON", file_ext=".json",
    bbox=FieldSupport.FULL, polygon=FieldSupport.FULL,
    keypoints=FieldSupport.FULL, classification=FieldSupport.PARTIAL,
))
_reg(FormatInfo(
    key="yolo", display_name="YOLO TXT", file_ext=".txt",
    bbox=FieldSupport.FULL, polygon=FieldSupport.PARTIAL,
    classification=FieldSupport.PARTIAL,
))
_reg(FormatInfo(
    key="voc", display_name="Pascal VOC XML", file_ext=".xml",
    bbox=FieldSupport.FULL, classification=FieldSupport.PARTIAL,
))
_reg(FormatInfo(
    key="coco", display_name="COCO JSON", file_ext=".json",
    dataset_level=True,
    bbox=FieldSupport.FULL, polygon=FieldSupport.FULL,
    keypoints=FieldSupport.FULL, classification=FieldSupport.PARTIAL,
))
_reg(FormatInfo(
    key="csv", display_name="CSV", file_ext=".csv",
    bbox=FieldSupport.FULL, classification=FieldSupport.FULL,
))
_reg(FormatInfo(
    key="jsonl", display_name="JSONL", file_ext=".jsonl",
    bbox=FieldSupport.FULL, polygon=FieldSupport.FULL,
    classification=FieldSupport.FULL,
))
_reg(FormatInfo(
    key="imagefolder", display_name="ImageFolder", file_ext="",
    classification=FieldSupport.FULL,
))
_reg(FormatInfo(
    key="mvtec", display_name="MVTec AD", file_ext="",
    classification=FieldSupport.FULL,
))
_reg(FormatInfo(
    key="llava", display_name="LLaVA JSONL", file_ext=".jsonl",
    caption=FieldSupport.FULL, conversations=FieldSupport.FULL,
    grounding=FieldSupport.PARTIAL,
    bbox=FieldSupport.PARTIAL, classification=FieldSupport.PARTIAL,
))
_reg(FormatInfo(
    key="sharegpt", display_name="ShareGPT JSON", file_ext=".json",
    caption=FieldSupport.FULL, conversations=FieldSupport.FULL,
    grounding=FieldSupport.PARTIAL,
    bbox=FieldSupport.PARTIAL, classification=FieldSupport.PARTIAL,
))
_reg(FormatInfo(
    key="swift", display_name="Swift JSONL", file_ext=".jsonl",
    caption=FieldSupport.FULL, conversations=FieldSupport.FULL,
    bbox=FieldSupport.PARTIAL, classification=FieldSupport.PARTIAL,
))
_reg(FormatInfo(
    key="vlm_jsonl", display_name="VLM JSONL (import)", file_ext=".jsonl",
    caption=FieldSupport.FULL, conversations=FieldSupport.FULL,
    grounding=FieldSupport.FULL,
    bbox=FieldSupport.PARTIAL, classification=FieldSupport.PARTIAL,
))


# ── Field names for display ──────────────────────────────────────────

_FIELD_NAMES = {
    "bbox": "边界框",
    "polygon": "多边形",
    "keypoints": "关键点",
    "classification": "分类标签",
    "caption": "文本描述",
    "conversations": "对话数据",
    "grounding": "视觉定位",
}

_CHECKED_FIELDS = [
    "bbox", "polygon", "keypoints", "classification",
    "caption", "conversations", "grounding",
]


# ── Conversion analysis ──────────────────────────────────────────────

def conversion_hints(src_key: str, dst_key: str) -> ConversionHint:
    """Analyse what happens when converting *src* → *dst*.

    Compares per-field support levels; fields that the destination
    supports less well than the source are flagged as degraded or lost.
    """
    src = FORMATS.get(src_key)
    dst = FORMATS.get(dst_key)
    if src is None or dst is None:
        return ConversionHint(src=src_key, dst=dst_key,
                              notes=["unknown format"])

    preserved: list[str] = []
    degraded: list[str] = []
    lost: list[str] = []
    notes: list[str] = []

    for fld in _CHECKED_FIELDS:
        s_support = getattr(src, fld, FieldSupport.NONE)
        d_support = getattr(dst, fld, FieldSupport.NONE)

        if s_support == FieldSupport.NONE:
            continue  # source doesn't have it — nothing to lose

        name = _FIELD_NAMES.get(fld, fld)

        if d_support == FieldSupport.FULL:
            preserved.append(name)
        elif d_support == FieldSupport.PARTIAL:
            degraded.append(name)
        else:
            lost.append(name)

    # Special notes
    if src_key in ("labelme",) and dst_key == "yolo":
        notes.append("多边形将降级为最小外接矩形")
    if src_key == "coco" and dst_key != "coco":
        notes.append("COCO 单文件结构将拆分为每图一个标注文件")
    if dst_key in ("llava", "sharegpt", "swift") and src_key not in (
            "llava", "sharegpt", "swift", "vlm_jsonl"):
        notes.append("目标为 VLM 格式 — 缺少对话数据时将自动生成描述")
    if dst_key == "imagefolder":
        notes.append("仅保留分类信息 — 所有区域级标注将丢失")

    return ConversionHint(
        src=src_key, dst=dst_key,
        preserved=preserved, degraded=degraded,
        lost=lost, notes=notes,
    )


def available_import_formats() -> list[str]:
    """Formats that can be imported (have readers)."""
    return ["labelme", "yolo", "voc", "coco", "classification", "vlm_jsonl"]


def available_export_formats() -> list[str]:
    """Formats that can be exported (have writers)."""
    from .format_out import available_formats
    return available_formats()


def format_display_name(key: str) -> str:
    info = FORMATS.get(key)
    return info.display_name if info else key


def writeback_formats() -> list[str]:
    """Formats that support per-image write-back (in-place annotation save)."""
    from .project import WRITEBACK_FORMATS
    return list(WRITEBACK_FORMATS)
