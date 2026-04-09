"""Export to ms-swift format — the standard for Qwen-VL / InternVL fine-tuning via ModelScope.

Output: <out>/swift_{split}.jsonl + images/
Format per line:
  {"query": "<image>问题", "response": "回答", "images": ["images/train/xxx.jpg"]}
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
class SwiftExportOptions:
    out_dir: Path
    copy_images: bool = True
    question: str = "请描述这张图片中的内容。"


@dataclass
class ExportReport:
    written_images: int = 0
    written_labels: int = 0
    skipped: list[tuple[Path, str]] = field(default_factory=list)


def _generate_answer(shapes) -> str:
    if not shapes:
        return "这张图片中未发现标注目标。"
    from collections import Counter
    label_counts = Counter(s.label for s in shapes)
    total = len(shapes)
    if total == 1:
        return f"图片中存在1个 {shapes[0].label}。"
    parts = [f"{count}个 {label}" for label, count in label_counts.most_common()]
    return f"图片中存在{total}个目标：{'、'.join(parts)}。"


def export_swift(
    split: SplitResult,
    opts: SwiftExportOptions,
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
        img_dir = out / "images" / name if opts.copy_images else None
        if img_dir:
            img_dir.mkdir(parents=True, exist_ok=True)

        lines: list[str] = []
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

                shapes = []
                if img.has_label and img.label_path:
                    classes = (
                        load_yolo_classes(img.label_path.parent)
                        if img.label_path.suffix.lower() == ".txt" else None
                    )
                    r = parse_annotation(img.label_path, img.path, yolo_class_names=classes)
                    if r.ok and r.annotation:
                        shapes = r.annotation.shapes

                record = {
                    "query": f"<image>{opts.question}",
                    "response": _generate_answer(shapes),
                    "images": [rel_path],
                }
                lines.append(json.dumps(record, ensure_ascii=False))
                report.written_labels += 1
            except Exception as e:  # noqa: BLE001
                report.skipped.append((img.path, str(e)))

        jsonl_path = out / f"swift_{name}.jsonl"
        jsonl_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if progress_cb:
        progress_cb(total, total, "")
    return report
