"""Centralized exporter registry — single source of truth for format dispatch.

Eliminates duplicated if/elif chains in ExportNode, DatasetBrowserView, and
ExportWizardDialog. To add a new export format, register it here once.

Usage::

    from core.exporter.registry import EXPORTERS, run_export

    report = run_export("YOLO", split, out_dir, copy_images=True, progress_cb=cb)
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class ExporterEntry:
    """Metadata + factory for one export format."""
    key: str               # machine key: "YOLO", "COCO", etc.
    display_name: str      # UI label
    description: str       # one-liner for tooltips
    module: str            # e.g. "core.exporter.yolo"
    opts_class: str        # e.g. "YoloExportOptions"
    export_fn: str         # e.g. "export_yolo"
    supports_copy_images: bool = True
    structure: str = ""    # output directory tree preview for wizard


def _lazy_import(module: str, name: str) -> Any:
    import importlib
    mod = importlib.import_module(module)
    return getattr(mod, name)


# ---- Registry ----

EXPORTERS: dict[str, ExporterEntry] = {}


def _register(entry: ExporterEntry) -> None:
    EXPORTERS[entry.key] = entry


_register(ExporterEntry(
    key="YOLO",
    display_name="YOLO",
    description="Ultralytics YOLO 检测/分割格式",
    module="core.exporter.yolo",
    opts_class="YoloExportOptions",
    export_fn="export_yolo",
    structure="images/{split}/ + labels/{split}/ + data.yaml",
))

_register(ExporterEntry(
    key="COCO",
    display_name="COCO",
    description="COCO 检测 JSON 格式",
    module="core.exporter.coco",
    opts_class="CocoExportOptions",
    export_fn="export_coco",
    structure="annotations/instances_{split}.json + {split}/",
))

_register(ExporterEntry(
    key="VOC",
    display_name="Pascal VOC",
    description="Pascal VOC XML 格式",
    module="core.exporter.voc",
    opts_class="VocExportOptions",
    export_fn="export_voc",
    structure="JPEGImages/ + Annotations/ + ImageSets/Main/",
))

_register(ExporterEntry(
    key="CSV",
    display_name="CSV",
    description="Pandas 友好的平面 CSV 标注",
    module="core.exporter.csv_export",
    opts_class="CsvExportOptions",
    export_fn="export_csv_dataset",
    structure="annotations.csv + images/{split}/",
))

_register(ExporterEntry(
    key="JSONL",
    display_name="JSON Lines",
    description="流式 JSON Lines 标注",
    module="core.exporter.jsonl",
    opts_class="JsonlExportOptions",
    export_fn="export_jsonl",
    structure="{split}.jsonl + images/{split}/",
))

_register(ExporterEntry(
    key="LLaVA",
    display_name="LLaVA",
    description="LLaVA 多模态微调 JSONL",
    module="core.exporter.llava",
    opts_class="LlavaExportOptions",
    export_fn="export_llava",
    structure="llava_{split}.jsonl + images/{split}/",
))

_register(ExporterEntry(
    key="ShareGPT",
    display_name="ShareGPT",
    description="LLaMA-Factory ShareGPT 多模态格式",
    module="core.exporter.sharegpt",
    opts_class="ShareGptExportOptions",
    export_fn="export_sharegpt",
    structure="sharegpt_{split}.json + images/ + dataset_info.json",
))

_register(ExporterEntry(
    key="Swift",
    display_name="ms-swift",
    description="ModelScope ms-swift VLM 微调格式",
    module="core.exporter.swift",
    opts_class="SwiftExportOptions",
    export_fn="export_swift",
    structure="swift_{split}.jsonl + images/{split}/",
))

_register(ExporterEntry(
    key="ImageFolder",
    display_name="ImageFolder",
    description="torchvision ImageFolder 分类布局",
    module="core.exporter.imagefolder",
    opts_class="ImageFolderExportOptions",
    export_fn="export_imagefolder",
    structure="{split}/{class}/*.jpg",
))

_register(ExporterEntry(
    key="MVTec",
    display_name="MVTec AD",
    description="MVTec 工业异常检测标准布局",
    module="core.exporter.mvtec",
    opts_class="MvtecExportOptions",
    export_fn="export_mvtec",
    structure="train/good/ + test/{good, defect_type}/",
))


# ---- Dispatch ----

def run_export(
    fmt: str,
    split,
    out_dir: Path,
    copy_images: bool = True,
    progress_cb: Callable | None = None,
):
    """Run an export by format key. Returns the exporter's report object.

    Raises ValueError for unknown formats.
    """
    entry = EXPORTERS.get(fmt)
    if entry is None:
        raise ValueError(f"未知导出格式: {fmt}")

    OptsCls = _lazy_import(entry.module, entry.opts_class)
    fn = _lazy_import(entry.module, entry.export_fn)

    # Build options — only pass copy_images if the Options class accepts it
    kwargs: dict[str, Any] = {"out_dir": out_dir}
    if entry.supports_copy_images and hasattr(OptsCls, "__dataclass_fields__"):
        if "copy_images" in OptsCls.__dataclass_fields__:
            kwargs["copy_images"] = copy_images

    opts = OptsCls(**kwargs)
    return fn(split, opts, progress_cb=progress_cb)
