"""Export to Ultralytics YOLO-OBB via the unified writer."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..splitter import SplitResult


@dataclass
class YoloObbExportOptions:
    out_dir: Path
    copy_images: bool = True


@dataclass
class ExportReport:
    written_images: int = 0
    written_labels: int = 0
    skipped: list[tuple[Path, str]] = field(default_factory=list)


def export_yolo_obb(
    split: SplitResult,
    opts: YoloObbExportOptions,
    progress_cb=None,
) -> ExportReport:
    from ..format_in import load_samples_from_split
    from ..format_out import ExportOptions, export_samples

    ss = load_samples_from_split(split, progress_cb=progress_cb)
    fo = ExportOptions(out_dir=opts.out_dir, copy_images=opts.copy_images)
    result = export_samples(ss, "yolo-obb", fo, progress_cb=progress_cb)
    return ExportReport(
        written_images=result.written_images,
        written_labels=result.written_labels,
        skipped=result.skipped,
    )
