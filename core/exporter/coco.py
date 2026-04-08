"""Export to COCO detection format (single annotations.json + images dir)."""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from ..annotation_formats import load_yolo_classes, parse_annotation
from ..splitter import SplitResult


@dataclass
class CocoExportOptions:
    out_dir: Path
    copy_images: bool = True


@dataclass
class ExportReport:
    written_images: int = 0
    written_annotations: int = 0
    skipped: list[tuple[Path, str]] = field(default_factory=list)


def _build_split(split_name: str, imgs, out: Path, opts: CocoExportOptions, report):
    img_dir = out / split_name
    if opts.copy_images:
        img_dir.mkdir(parents=True, exist_ok=True)

    images_json = []
    annotations_json = []
    cat_idx: dict[str, int] = {}
    next_img_id = 1
    next_ann_id = 1

    for img in imgs:
        try:
            with Image.open(img.path) as pim:
                iw, ih = pim.size
            if opts.copy_images:
                shutil.copy2(img.path, img_dir / img.path.name)
                report.written_images += 1
            images_json.append({
                "id": next_img_id,
                "file_name": img.path.name,
                "width": iw,
                "height": ih,
            })
            if img.has_label and img.label_path is not None:
                classes = (
                    load_yolo_classes(img.label_path.parent)
                    if img.label_path.suffix.lower() == ".txt"
                    else None
                )
                r = parse_annotation(img.label_path, img.path, yolo_class_names=classes)
                if r.ok and r.annotation:
                    for s in r.annotation.shapes:
                        if s.label not in cat_idx:
                            cat_idx[s.label] = len(cat_idx) + 1
                        xs = [p[0] for p in s.points]
                        ys = [p[1] for p in s.points]
                        x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
                        w, h = x2 - x1, y2 - y1
                        if w <= 0 or h <= 0:
                            continue
                        annotations_json.append({
                            "id": next_ann_id,
                            "image_id": next_img_id,
                            "category_id": cat_idx[s.label],
                            "bbox": [x1, y1, w, h],
                            "area": w * h,
                            "iscrowd": 0,
                        })
                        next_ann_id += 1
                        report.written_annotations += 1
            next_img_id += 1
        except Exception as e:  # noqa: BLE001
            report.skipped.append((img.path, str(e)))

    categories_json = [
        {"id": cid, "name": name} for name, cid in sorted(cat_idx.items(), key=lambda x: x[1])
    ]
    return {
        "images": images_json,
        "annotations": annotations_json,
        "categories": categories_json,
    }


def export_coco(
    split: SplitResult,
    opts: CocoExportOptions,
    progress_cb=None,
) -> ExportReport:
    out = Path(opts.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = ExportReport()
    ann_dir = out / "annotations"
    ann_dir.mkdir(parents=True, exist_ok=True)

    splits = {"train": split.train, "val": split.val, "test": split.test}
    total = sum(len(v) for v in splits.values())
    done = 0
    for name, imgs in splits.items():
        if not imgs:
            continue
        if progress_cb:
            progress_cb(done, total, name)
        coco = _build_split(name, imgs, out, opts, report)
        (ann_dir / f"instances_{name}.json").write_text(
            json.dumps(coco, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        done += len(imgs)
        if progress_cb:
            progress_cb(done, total, name)

    if progress_cb:
        progress_cb(total, total, "")
    return report
