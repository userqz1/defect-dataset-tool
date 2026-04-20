"""Export to torchvision ImageFolder layout.

Layout::

    <out>/
    ├── train/
    │   ├── <class_a>/*.jpg
    │   └── <class_b>/*.jpg
    ├── val/
    │   └── <class_a>/*.jpg
    └── test/
        └── <class_b>/*.jpg

Class = image's category (no separate label files). Images with no category
are skipped.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from ..splitter import SplitResult


@dataclass
class ImageFolderExportOptions:
    out_dir: Path
    copy_images: bool = True  # False → create symlinks / move; v0.1 only supports copy


@dataclass
class ExportReport:
    written_images: int = 0
    skipped: list[tuple[Path, str]] = field(default_factory=list)


def export_imagefolder(
    split: SplitResult,
    opts: ImageFolderExportOptions,
    progress_cb=None,
) -> ExportReport:
    out = Path(opts.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = ExportReport()

    splits = {"train": split.train, "val": split.val, "test": split.test}
    total = sum(len(v) for v in splits.values())
    done = 0
    for name, imgs in splits.items():
        if not imgs:
            continue
        for img in imgs:
            done += 1
            if progress_cb:
                progress_cb(done, total, img.path.name)
            try:
                category = (img.category or "").strip()
                if not category:
                    report.skipped.append((img.path, "no category"))
                    continue
                class_dir = out / name / category
                class_dir.mkdir(parents=True, exist_ok=True)
                dst = class_dir / img.path.name
                if opts.copy_images:
                    shutil.copy2(img.path, dst)
                else:
                    # Fallback to copy if move not requested — v0.1 keeps safe default.
                    shutil.copy2(img.path, dst)
                report.written_images += 1
            except Exception as e:  # noqa: BLE001
                report.skipped.append((img.path, str(e)))

    if progress_cb:
        progress_cb(total, total, "")
    return report
