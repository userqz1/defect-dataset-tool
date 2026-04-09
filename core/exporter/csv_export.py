"""Export annotations as flat CSV — Pandas-friendly, one row per annotation.

Output: <out>/annotations_{split}.csv + optionally copied images.
Columns: image_path, category, label, x1, y1, x2, y2, shape_type, split
"""
from __future__ import annotations

import csv
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from ..annotation_formats import load_yolo_classes, parse_annotation
from ..models import ImageInfo
from ..splitter import SplitResult


@dataclass
class CsvExportOptions:
    out_dir: Path
    copy_images: bool = True


@dataclass
class ExportReport:
    written_images: int = 0
    written_labels: int = 0
    skipped: list[tuple[Path, str]] = field(default_factory=list)


COLUMNS = ["image_path", "category", "label", "x1", "y1", "x2", "y2", "shape_type", "split"]


def export_csv_dataset(
    split: SplitResult,
    opts: CsvExportOptions,
    progress_cb=None,
) -> ExportReport:
    out = Path(opts.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = ExportReport()
    splits = {"train": split.train, "val": split.val, "test": split.test}
    total = sum(len(v) for v in splits.values())
    done = 0

    csv_path = out / "annotations.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(COLUMNS)

        for name, imgs in splits.items():
            if not imgs:
                continue
            img_dir = out / "images" / name if opts.copy_images else None
            if img_dir:
                img_dir.mkdir(parents=True, exist_ok=True)

            for img in imgs:
                done += 1
                if progress_cb:
                    progress_cb(done, total, img.path.name)
                try:
                    if img_dir:
                        shutil.copy2(img.path, img_dir / img.path.name)
                        report.written_images += 1
                        rel_path = f"images/{name}/{img.path.name}"
                    else:
                        rel_path = str(img.path)

                    # Parse annotations
                    if img.has_label and img.label_path:
                        classes = (
                            load_yolo_classes(img.label_path.parent)
                            if img.label_path.suffix.lower() == ".txt" else None
                        )
                        r = parse_annotation(img.label_path, img.path, yolo_class_names=classes)
                        if r.ok and r.annotation and r.annotation.shapes:
                            for s in r.annotation.shapes:
                                xs = [p[0] for p in s.points]
                                ys = [p[1] for p in s.points]
                                writer.writerow([
                                    rel_path, img.category, s.label,
                                    f"{min(xs):.1f}", f"{min(ys):.1f}",
                                    f"{max(xs):.1f}", f"{max(ys):.1f}",
                                    s.shape_type, name,
                                ])
                            report.written_labels += 1
                            continue
                    # No annotation — still write a row with empty label
                    writer.writerow([rel_path, img.category, "", "", "", "", "", "", name])
                    report.written_labels += 1
                except Exception as e:  # noqa: BLE001
                    report.skipped.append((img.path, str(e)))

    if progress_cb:
        progress_cb(total, total, "")
    return report
