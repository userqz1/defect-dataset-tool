"""Export to ShareGPT multimodal format — the standard for LLaMA-Factory VLM fine-tuning.

Covers: LLaVA, Qwen-VL, InternVL, GLM-4V, Phi-Vision, CogVLM, etc.
via LLaMA-Factory (the most popular open-source fine-tuning framework).

Output: <out>/sharegpt_{split}.json + images/ + dataset_info.json
Format per sample:
  {"conversations": [{"from": "human", "value": "<image>问题"},
                     {"from": "gpt", "value": "回答"}],
   "images": ["images/train/xxx.jpg"]}
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
class ShareGptExportOptions:
    out_dir: Path
    copy_images: bool = True
    question: str = "请描述这张图片中的内容。"


@dataclass
class ExportReport:
    written_images: int = 0
    written_labels: int = 0
    skipped: list[tuple[Path, str]] = field(default_factory=list)


def _generate_answer(shapes, iw: int, ih: int) -> str:
    """Auto-generate a description from annotation shapes."""
    if not shapes:
        return "这张图片中未发现标注目标。"

    from collections import Counter
    label_counts = Counter(s.label for s in shapes)
    total = len(shapes)

    if total == 1:
        s = shapes[0]
        return f"图片中存在1个 {s.label}。"

    parts = [f"{count}个 {label}" for label, count in label_counts.most_common()]
    return f"图片中存在{total}个目标：{'、'.join(parts)}。"


def export_sharegpt(
    split: SplitResult,
    opts: ShareGptExportOptions,
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

        samples: list[dict] = []
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

                # Parse annotations for answer generation
                shapes = []
                if img.has_label and img.label_path:
                    classes = (
                        load_yolo_classes(img.label_path.parent)
                        if img.label_path.suffix.lower() == ".txt" else None
                    )
                    r = parse_annotation(img.label_path, img.path, yolo_class_names=classes)
                    if r.ok and r.annotation:
                        shapes = r.annotation.shapes

                with Image.open(img.path) as pim:
                    pass  # just validate image is readable

                answer = _generate_answer(shapes, 0, 0)
                sample = {
                    "conversations": [
                        {"from": "human", "value": f"<image>\n{opts.question}"},
                        {"from": "gpt", "value": answer},
                    ],
                    "images": [rel_path],
                }
                samples.append(sample)
                report.written_labels += 1
            except Exception as e:  # noqa: BLE001
                report.skipped.append((img.path, str(e)))

        json_path = out / f"sharegpt_{name}.json"
        json_path.write_text(
            json.dumps(samples, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # Generate dataset_info.json for LLaMA-Factory
    _write_dataset_info(out, list(splits.keys()))

    if progress_cb:
        progress_cb(total, total, "")
    return report


def _write_dataset_info(out: Path, split_names: list[str]) -> None:
    """Generate dataset_info.json so LLaMA-Factory can directly load."""
    info = {}
    for name in split_names:
        json_path = out / f"sharegpt_{name}.json"
        if json_path.exists():
            info[f"my_dataset_{name}"] = {
                "file_name": f"sharegpt_{name}.json",
                "formatting": "sharegpt",
                "columns": {
                    "messages": "conversations",
                    "images": "images",
                },
            }
    (out / "dataset_info.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
    )
