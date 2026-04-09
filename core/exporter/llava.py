"""Export to LLaVA conversation JSONL format for multimodal LLM fine-tuning.

Output: <out>/llava_train.jsonl (+ val/test) + copied images.
Each line follows the LLaVA format:
  {"id": "unique_id", "image": "relative/path.jpg",
   "conversations": [
     {"from": "human", "value": "<image>\\n这张图片中有什么缺陷？"},
     {"from": "gpt", "value": "图片中存在2处缺陷：1处裂纹（位于图像左侧）..."}
   ]}
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
class LlavaExportOptions:
    out_dir: Path
    copy_images: bool = True
    question: str = "这张图片中有什么缺陷？请描述缺陷的类型、位置和数量。"


@dataclass
class ExportReport:
    written_images: int = 0
    written_labels: int = 0
    skipped: list[tuple[Path, str]] = field(default_factory=list)


def _position_desc(points, iw: int, ih: int) -> str:
    """Generate a rough position description from bbox center."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    cx = (min(xs) + max(xs)) / 2 / iw
    cy = (min(ys) + max(ys)) / 2 / ih
    h = "左侧" if cx < 0.33 else ("右侧" if cx > 0.67 else "中部")
    v = "上方" if cy < 0.33 else ("下方" if cy > 0.67 else "中部")
    if h == "中部" and v == "中部":
        return "图像中央"
    return f"图像{v}{h}"


def _generate_answer(shapes, iw: int, ih: int) -> str:
    """Auto-generate a natural language answer from annotation shapes."""
    if not shapes:
        return "这张图片中未发现明显缺陷，图像表面状态正常。"

    from collections import Counter
    label_counts = Counter(s.label for s in shapes)
    total = len(shapes)

    if total == 1:
        s = shapes[0]
        pos = _position_desc(s.points, iw, ih)
        return f"图片中存在1处{s.label}缺陷，位于{pos}。"

    parts = []
    for label, count in label_counts.most_common():
        # Find first shape of this label for position
        first = next(s for s in shapes if s.label == label)
        pos = _position_desc(first.points, iw, ih)
        parts.append(f"{count}处{label}（{pos}附近）")

    return f"图片中存在{total}处缺陷：{'、'.join(parts)}。"


def export_llava(
    split: SplitResult,
    opts: LlavaExportOptions,
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
        jsonl_path = out / f"llava_{name}.jsonl"
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        img_dir = out / "images" / name if opts.copy_images else None
        if img_dir:
            img_dir.mkdir(parents=True, exist_ok=True)

        lines: list[str] = []
        for i, img in enumerate(imgs):
            done += 1
            if progress_cb:
                progress_cb(done, total, img.path.name)
            try:
                with Image.open(img.path) as pim:
                    iw, ih = pim.size

                if img_dir:
                    shutil.copy2(img.path, img_dir / img.path.name)
                    report.written_images += 1
                    rel_path = f"images/{name}/{img.path.name}"
                else:
                    rel_path = str(img.path)

                # Parse annotations
                shapes = []
                if img.has_label and img.label_path:
                    classes = (
                        load_yolo_classes(img.label_path.parent)
                        if img.label_path.suffix.lower() == ".txt" else None
                    )
                    r = parse_annotation(img.label_path, img.path, yolo_class_names=classes)
                    if r.ok and r.annotation:
                        shapes = r.annotation.shapes

                answer = _generate_answer(shapes, iw, ih)
                record = {
                    "id": f"{name}_{i:06d}",
                    "image": rel_path,
                    "conversations": [
                        {"from": "human", "value": f"<image>\n{opts.question}"},
                        {"from": "gpt", "value": answer},
                    ],
                }
                lines.append(json.dumps(record, ensure_ascii=False))
                report.written_labels += 1
            except Exception as e:  # noqa: BLE001
                report.skipped.append((img.path, str(e)))

        jsonl_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if progress_cb:
        progress_cb(total, total, "")
    return report
