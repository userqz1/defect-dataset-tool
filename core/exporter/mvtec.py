"""Export to MVTec AD anomaly-detection layout.

Standard MVTec AD structure::

    <out>/
    ├── train/
    │   └── good/*.png
    └── test/
        ├── good/*.png
        └── <defect_type>/*.png

Conventions (v0.1):
- Requires a "good" category (case-insensitive) on the source dataset.
- All non-good categories are defect types and go entirely to test/.
- The good category is split by ratio between train/good and test/good —
  MVTec conventionally trains on normal-only samples.
- ``ground_truth`` mask dir is out of scope for v0.1.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from ..splitter import SplitResult


@dataclass
class MvtecExportOptions:
    out_dir: Path
    copy_images: bool = True


@dataclass
class ExportReport:
    written_images: int = 0
    skipped: list[tuple[Path, str]] = field(default_factory=list)


def _is_good(category: str) -> bool:
    return (category or "").strip().lower() == "good"


def export_mvtec(
    split: SplitResult,
    opts: MvtecExportOptions,
    progress_cb=None,
) -> ExportReport:
    """Write an MVTec AD-compatible tree.

    The caller's SplitResult is interpreted as follows:
    - ``train`` — good samples used for training (copied into ``train/good``)
    - ``val`` + ``test`` — merged into test/ (val rarely used in MVTec)
        - good samples → ``test/good``
        - any other category → ``test/<category>``

    Defect images in the train split are redirected to test/<category> with a
    warning recorded in ``skipped`` — MVTec's train set is normal-only.
    """
    out = Path(opts.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = ExportReport()

    train_good = [img for img in split.train if _is_good(img.category)]
    misplaced_defects = [img for img in split.train if not _is_good(img.category)]

    # val + test → test/
    test_all = list(split.val) + list(split.test) + misplaced_defects

    total = len(train_good) + len(test_all)
    done = 0

    # train/good
    if train_good:
        dst_dir = out / "train" / "good"
        dst_dir.mkdir(parents=True, exist_ok=True)
        for img in train_good:
            done += 1
            if progress_cb:
                progress_cb(done, total, img.path.name)
            try:
                shutil.copy2(img.path, dst_dir / img.path.name)
                report.written_images += 1
            except Exception as e:  # noqa: BLE001
                report.skipped.append((img.path, str(e)))

    # test/<category>
    for img in test_all:
        done += 1
        if progress_cb:
            progress_cb(done, total, img.path.name)
        try:
            category = (img.category or "").strip()
            if not category:
                report.skipped.append((img.path, "no category"))
                continue
            bucket = "good" if _is_good(category) else category
            dst_dir = out / "test" / bucket
            dst_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(img.path, dst_dir / img.path.name)
            report.written_images += 1
        except Exception as e:  # noqa: BLE001
            report.skipped.append((img.path, str(e)))

    if progress_cb:
        progress_cb(total, total, "")
    return report
