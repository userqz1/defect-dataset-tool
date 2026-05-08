"""Export to ShareGPT multimodal format — thin wrapper delegating to ``format_out``."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..splitter import SplitResult


@dataclass
class ShareGptExportOptions:
    out_dir: Path
    copy_images: bool = True
    question: str = "请描述这张图片中的内容。"


@dataclass
class ExportReport:
    written_images: int = 0
    written_labels: int = 0
    skipped: list[tuple[Path, str]] = field(default_factory=list)
    grounding_fallback_count: int = 0
    grounding_dropped_no_bbox: int = 0


def export_sharegpt(
    split: SplitResult,
    opts: ShareGptExportOptions,
    progress_cb=None,
) -> ExportReport:
    from ..format_in import load_samples_from_split
    from ..format_out import ExportOptions, export_samples

    ss = load_samples_from_split(split, progress_cb=progress_cb)
    fo = ExportOptions(
        out_dir=opts.out_dir,
        copy_images=opts.copy_images,
        question=opts.question,
    )
    result = export_samples(ss, "sharegpt", fo, progress_cb=progress_cb)

    return ExportReport(
        written_images=result.written_images,
        written_labels=result.written_labels,
        skipped=result.skipped,
        grounding_fallback_count=result.grounding_fallback_count,
        grounding_dropped_no_bbox=result.grounding_dropped_no_bbox,
    )
