"""Export to JSON Lines format — one JSON object per line, streaming-friendly.

Output: <out>/annotations.jsonl + optionally copied images.
Each line: {"image": "relative/path.jpg", "width": W, "height": H, "category": "...",
            "annotations": [{"label": "...", "bbox": [x1,y1,x2,y2], "points": [...], "shape_type": "..."}]}
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from ..annotation_formats import load_yolo_classes, parse_annotation
from ..models import ImageInfo
from ..splitter import SplitResult


@dataclass
class JsonlExportOptions:
    out_dir: Path
    copy_images: bool = True


@dataclass
class ExportReport:
    written_images: int = 0
    written_labels: int = 0
    skipped: list[tuple[Path, str]] = field(default_factory=list)


def _shape_to_dict(shape) -> dict:
    pts = shape.points
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return {
        "label": shape.label,
        "bbox": [min(xs), min(ys), max(xs), max(ys)],
        "points": [[p[0], p[1]] for p in pts],
        "shape_type": shape.shape_type,
    }


def export_jsonl(
    split: SplitResult,
    opts: JsonlExportOptions,
    progress_cb=None,
) -> ExportReport:
    out = Path(opts.out_dir)
    report = ExportReport()
    splits = {"train": split.train, "val": split.val, "test": split.test}
    total = sum(len(v) for v in splits.values())
    done = 0

    for name, imgs in splits.items():
        if not imgs:
            continue
        jsonl_path = out / f"{name}.jsonl"
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        img_dir = out / "images" / name if opts.copy_images else None
        if img_dir:
            img_dir.mkdir(parents=True, exist_ok=True)

        lines: list[str] = []
        for img in imgs:
            done += 1
            if progress_cb:
                progress_cb(done, total, img.path.name)
            try:
                # Image dimensions
                with Image.open(img.path) as pim:
                    iw, ih = pim.size

                # Copy image
                if img_dir:
                    shutil.copy2(img.path, img_dir / img.path.name)
                    report.written_images += 1
                    rel_path = f"images/{name}/{img.path.name}"
                else:
                    rel_path = str(img.path)

                # Parse annotations
                annots = []
                if img.has_label and img.label_path:
                    classes = (
                        load_yolo_classes(img.label_path.parent)
                        if img.label_path.suffix.lower() == ".txt" else None
                    )
                    r = parse_annotation(img.label_path, img.path, yolo_class_names=classes)
                    if r.ok and r.annotation:
                        annots = [_shape_to_dict(s) for s in r.annotation.shapes]

                record = {
                    "image": rel_path,
                    "width": iw,
                    "height": ih,
                    "category": img.category,
                    "annotations": annots,
                }
                lines.append(json.dumps(record, ensure_ascii=False))
                report.written_labels += 1
            except Exception as e:  # noqa: BLE001
                report.skipped.append((img.path, str(e)))

        jsonl_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if progress_cb:
        progress_cb(total, total, "")
    return report
