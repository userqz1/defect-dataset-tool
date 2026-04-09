"""Export to YOLO format.

Layout:
    <out>/
        images/{train,val,test}/*.jpg
        labels/{train,val,test}/*.txt
        classes.txt
        data.yaml
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from ..annotation_formats import load_yolo_classes, parse_annotation
from ..models import ImageInfo
from ..splitter import SplitResult


@dataclass
class YoloExportOptions:
    out_dir: Path
    copy_images: bool = True   # False → 只写 labels + 引用绝对路径


@dataclass
class ExportReport:
    written_images: int = 0
    written_labels: int = 0
    skipped: list[tuple[Path, str]] = field(default_factory=list)


def _shape_to_yolo(label: str, points, iw: int, ih: int, class_idx: dict[str, int]) -> str | None:
    if label not in class_idx or iw <= 0 or ih <= 0 or len(points) < 2:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x1, x2 = min(xs), max(xs)
    y1, y2 = min(ys), max(ys)
    cx = (x1 + x2) / 2 / iw
    cy = (y1 + y2) / 2 / ih
    w = (x2 - x1) / iw
    h = (y2 - y1) / ih
    if w <= 0 or h <= 0:
        return None
    return f"{class_idx[label]} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}"


def export_yolo(
    split: SplitResult,
    opts: YoloExportOptions,
    progress_cb=None,
) -> ExportReport:
    out = Path(opts.out_dir)
    report = ExportReport()

    # 收集所有类别
    all_labels: set[str] = set()
    for imgs in (split.train, split.val, split.test):
        for img in imgs:
            if not img.has_label or img.label_path is None:
                continue
            classes = (
                load_yolo_classes(img.label_path.parent)
                if img.label_path.suffix.lower() == ".txt"
                else None
            )
            r = parse_annotation(img.label_path, img.path, yolo_class_names=classes)
            if r.ok and r.annotation:
                for s in r.annotation.shapes:
                    all_labels.add(s.label)
    class_list = sorted(all_labels)
    class_idx = {n: i for i, n in enumerate(class_list)}

    splits = {"train": split.train, "val": split.val, "test": split.test}
    total = sum(len(v) for v in splits.values())
    done = 0
    for name, imgs in splits.items():
        if not imgs:
            continue
        img_dir = out / "images" / name
        lbl_dir = out / "labels" / name
        img_dir.mkdir(parents=True, exist_ok=True)
        lbl_dir.mkdir(parents=True, exist_ok=True)
        for img in imgs:
            done += 1
            if progress_cb:
                progress_cb(done, total, img.path.name)
            try:
                if opts.copy_images:
                    shutil.copy2(img.path, img_dir / img.path.name)
                    report.written_images += 1

                # 解析标注
                if not img.has_label or img.label_path is None:
                    continue
                with Image.open(img.path) as pim:
                    iw, ih = pim.size
                classes = (
                    load_yolo_classes(img.label_path.parent)
                    if img.label_path.suffix.lower() == ".txt"
                    else None
                )
                r = parse_annotation(img.label_path, img.path, yolo_class_names=classes)
                if not (r.ok and r.annotation):
                    continue
                lines = []
                for s in r.annotation.shapes:
                    line = _shape_to_yolo(s.label, s.points, iw, ih, class_idx)
                    if line:
                        lines.append(line)
                (lbl_dir / (img.path.stem + ".txt")).write_text(
                    "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8"
                )
                report.written_labels += 1
            except Exception as e:  # noqa: BLE001
                report.skipped.append((img.path, str(e)))

    # classes.txt + data.yaml
    (out / "classes.txt").write_text("\n".join(class_list) + "\n", encoding="utf-8")
    yaml_lines = [
        "path: .",
        f"train: images/train",
        f"val: images/val",
    ]
    if split.test:
        yaml_lines.append("test: images/test")
    yaml_lines.append(f"nc: {len(class_list)}")
    yaml_lines.append("names: [" + ", ".join(f"'{c}'" for c in class_list) + "]")
    (out / "data.yaml").write_text("\n".join(yaml_lines) + "\n", encoding="utf-8")

    if progress_cb:
        progress_cb(total, total, "")
    return report
