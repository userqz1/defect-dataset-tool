"""Export a filtered subset of images as a new dataset folder.

Layout produced:
    <out_dir>/<category>/images/<file>
    <out_dir>/<category>/labels/<file>.json   (only if label exists)
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from ..fileops import OpResult, label_path_for_image
from ..models import ImageInfo


def export_subset(
    images: list[ImageInfo],
    out_dir: Path,
    copy_labels: bool = True,
    move: bool = False,
    progress_cb=None,
) -> OpResult:
    """Copy (or move) image+label pairs into a fresh dataset tree at `out_dir`."""
    result = OpResult()
    out_dir.mkdir(parents=True, exist_ok=True)
    total = len(images)
    op = shutil.move if move else shutil.copy2

    for i, img in enumerate(images):
        if progress_cb:
            progress_cb(i, total, img.path.name)
        try:
            cat_dir = out_dir / img.category
            img_dir = cat_dir / "images"
            img_dir.mkdir(parents=True, exist_ok=True)
            new_image = _unique(img_dir / img.path.name)
            op(str(img.path), str(new_image))

            if copy_labels:
                label = img.label_path or label_path_for_image(img.path)
                if label and label.is_file():
                    lbl_dir = cat_dir / "labels"
                    lbl_dir.mkdir(parents=True, exist_ok=True)
                    new_label = _unique(lbl_dir / (new_image.stem + ".json"))
                    op(str(label), str(new_label))
                    _patch_image_path(new_label, new_image.name)
            result.succeeded.append(new_image)
        except Exception as e:  # noqa: BLE001
            result.failed.append((img.path, str(e)))
    if progress_cb:
        progress_cb(total, total, "")
    return result


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    i = 1
    while True:
        cand = path.with_name(f"{path.stem}_{i}{path.suffix}")
        if not cand.exists():
            return cand
        i += 1


def _patch_image_path(json_path: Path, new_name: str) -> None:
    try:
        data = json.loads(json_path.read_text(encoding="utf-8-sig"))
        if isinstance(data, dict):
            data["imagePath"] = new_name
            json_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    except Exception:
        pass
