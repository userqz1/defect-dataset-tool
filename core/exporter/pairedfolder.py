"""Export image-pair datasets as split folders plus pairs.csv."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..splitter import SplitResult


@dataclass
class PairedFolderExportOptions:
    out_dir: Path
    copy_images: bool = True


@dataclass
class ExportReport:
    written_images: int = 0
    written_labels: int = 0
    skipped: list[tuple[Path, str]] = field(default_factory=list)


def export_pairedfolder(
    split: SplitResult,
    opts: PairedFolderExportOptions,
    progress_cb=None,
) -> ExportReport:
    from ..format_in import load_samples_from_split
    from ..format_out import ExportOptions, export_samples
    from ..pairing import infer_pairs, unique_pair_samples
    from ..unified import SampleSet

    ss = infer_pairs(load_samples_from_split(split, progress_cb=progress_cb))
    ss = SampleSet(samples=unique_pair_samples(ss.samples))
    fo = ExportOptions(out_dir=opts.out_dir, copy_images=opts.copy_images)
    result = export_samples(ss, "pairedfolder", fo, progress_cb=progress_cb)

    return ExportReport(
        written_images=result.written_images,
        written_labels=result.written_labels,
        skipped=result.skipped,
    )
