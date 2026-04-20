"""File operations on image+label pairs. Pure Python — no PyQt.

All operations work on the (image, optional label JSON) pair as a unit.
Destructive ops use send2trash so the user can recover from Recycle Bin.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from send2trash import send2trash

from .models import ImageInfo


@dataclass
class OpResult:
    succeeded: list[Path] = field(default_factory=list)
    failed: list[tuple[Path, str]] = field(default_factory=list)

    @property
    def ok_count(self) -> int:
        return len(self.succeeded)

    @property
    def fail_count(self) -> int:
        return len(self.failed)


# ---------- 路径推断 ----------

def label_path_for_image(image_path: Path) -> Path | None:
    """Try common LabelMe layouts to find the JSON for an image."""
    # 1) <category>/labels/<stem>.json
    parent = image_path.parent
    if parent.name == "images":
        cat_root = parent.parent
        candidate = cat_root / "labels" / (image_path.stem + ".json")
        if candidate.is_file():
            return candidate
    # 2) sibling .json
    sibling = image_path.with_suffix(".json")
    if sibling.is_file():
        return sibling
    return None


def _new_label_path(new_image_path: Path, original_label: Path) -> Path:
    """Compute the destination path for a label file given the new image location."""
    # 如果原 label 在 labels/ 子目录里 → 新位置也用 labels/
    if original_label.parent.name == "labels":
        new_cat = new_image_path.parent
        if new_cat.name == "images":
            new_cat = new_cat.parent
        new_dir = new_cat / "labels"
        new_dir.mkdir(parents=True, exist_ok=True)
        return new_dir / (new_image_path.stem + ".json")
    # sibling
    return new_image_path.with_suffix(".json")


def _update_image_path_in_json(json_path: Path, new_image_name: str) -> None:
    """Update the `imagePath` field of a LabelMe JSON in-place. Best-effort."""
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return
    if isinstance(data, dict):
        data["imagePath"] = new_image_name
        try:
            json_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            pass


# ---------- 删除 ----------

def delete_pairs(images: list[ImageInfo], to_trash: bool = True,
                  progress_cb=None) -> OpResult:
    """Delete image + corresponding label JSON. Defaults to Recycle Bin."""
    result = OpResult()
    total = len(images)
    for i, img in enumerate(images):
        if progress_cb:
            progress_cb(i, total, img.path.name)
        try:
            label = img.label_path or label_path_for_image(img.path)
            if to_trash:
                send2trash(str(img.path))
                if label and label.is_file():
                    send2trash(str(label))
            else:
                img.path.unlink(missing_ok=True)
                if label and label.is_file():
                    label.unlink(missing_ok=True)
            result.succeeded.append(img.path)
        except Exception as e:  # noqa: BLE001
            result.failed.append((img.path, str(e)))
    if progress_cb:
        progress_cb(total, total, "")
    return result


# ---------- 移动到其他类别 ----------

def move_to_category(
    images: list[ImageInfo],
    dataset_root: Path,
    target_category: str,
    progress_cb=None,
) -> OpResult:
    """Move image+label pairs into <dataset_root>/<target_category>/{images,labels}/."""
    result = OpResult()
    target_images_dir = dataset_root / target_category / "images"
    target_images_dir.mkdir(parents=True, exist_ok=True)

    total = len(images)
    for i, img in enumerate(images):
        if progress_cb:
            progress_cb(i, total, img.path.name)
        try:
            new_image = target_images_dir / img.path.name
            new_image = _ensure_unique(new_image)
            shutil.move(str(img.path), str(new_image))

            label = img.label_path or label_path_for_image(img.path)
            if label and label.is_file():
                new_label = _new_label_path(new_image, label)
                new_label = _ensure_unique(new_label)
                shutil.move(str(label), str(new_label))
                _update_image_path_in_json(new_label, new_image.name)

            result.succeeded.append(new_image)
        except Exception as e:  # noqa: BLE001
            result.failed.append((img.path, str(e)))
    if progress_cb:
        progress_cb(total, total, "")
    return result


# ---------- 重命名 ----------

def rename_pair(image: ImageInfo, new_stem: str) -> OpResult:
    """Rename a single image and its label JSON to a new stem (no extension)."""
    result = OpResult()
    try:
        new_image = image.path.with_name(new_stem + image.path.suffix)
        if new_image.exists():
            raise FileExistsError(f"target exists: {new_image.name}")
        image.path.rename(new_image)

        label = image.label_path or label_path_for_image(image.path)
        if label and label.is_file():
            new_label = label.with_name(new_stem + ".json")
            label.rename(new_label)
            _update_image_path_in_json(new_label, new_image.name)

        result.succeeded.append(new_image)
    except Exception as e:  # noqa: BLE001
        result.failed.append((image.path, str(e)))
    return result


def batch_rename(
    images: list[ImageInfo],
    pattern: str = "{cat}_{idx:04d}",
    start: int = 1,
) -> OpResult:
    """Batch rename using a Python format pattern.

    Available placeholders:
        {cat}    - category name
        {idx}    - 1-based index
        {stem}   - original stem
    """
    result = OpResult()
    # 两阶段重命名以避免冲突：先全部加临时前缀
    temp_paths: list[tuple[ImageInfo, Path, Path | None]] = []
    for i, img in enumerate(images):
        try:
            tmp = img.path.with_name(f"__renaming__{i}__{img.path.name}")
            img.path.rename(tmp)
            label = img.label_path or label_path_for_image(img.path)
            tmp_label: Path | None = None
            if label and label.is_file():
                tmp_label = label.with_name(f"__renaming__{i}__{label.name}")
                label.rename(tmp_label)
            temp_paths.append((img, tmp, tmp_label))
        except Exception as e:  # noqa: BLE001
            result.failed.append((img.path, f"stage1: {e}"))

    for i, (img, tmp_image, tmp_label) in enumerate(temp_paths):
        try:
            new_stem = pattern.format(cat=img.category, idx=start + i, stem=img.path.stem)
            new_image = tmp_image.with_name(new_stem + img.path.suffix)
            tmp_image.rename(new_image)
            if tmp_label is not None:
                new_label = tmp_label.with_name(new_stem + ".json")
                tmp_label.rename(new_label)
                _update_image_path_in_json(new_label, new_image.name)
            result.succeeded.append(new_image)
        except Exception as e:  # noqa: BLE001
            result.failed.append((tmp_image, f"stage2: {e}"))
    return result


# ---------- 类别管理 ----------


def rename_category(
    dataset_root: Path,
    old_name: str,
    new_name: str,
    progress_cb=None,
) -> OpResult:
    """Rename a category folder. Returns OpResult with the new folder path."""
    result = OpResult()
    old_dir = dataset_root / old_name
    new_dir = dataset_root / new_name
    if not old_dir.is_dir():
        result.failed.append((old_dir, "源类别不存在"))
        return result
    if new_dir.exists():
        result.failed.append((new_dir, "目标类别已存在"))
        return result
    try:
        old_dir.rename(new_dir)
        result.succeeded.append(new_dir)
    except Exception as e:  # noqa: BLE001
        result.failed.append((old_dir, str(e)))
    return result


def merge_categories(
    dataset_root: Path,
    sources: list[str],
    target: str,
    progress_cb=None,
) -> OpResult:
    """Merge source categories into a target category by moving all image+label pairs."""
    result = OpResult()
    target_images_dir = dataset_root / target / "images"
    target_images_dir.mkdir(parents=True, exist_ok=True)

    total = 0
    for src_name in sources:
        src_dir = dataset_root / src_name
        if src_dir.is_dir():
            imgs_dir = src_dir / "images"
            if imgs_dir.is_dir():
                total += sum(1 for _ in imgs_dir.iterdir())

    done = 0
    for src_name in sources:
        if src_name == target:
            continue
        src_dir = dataset_root / src_name
        if not src_dir.is_dir():
            result.failed.append((src_dir, "不存在"))
            continue
        imgs_dir = src_dir / "images"
        lbls_dir = src_dir / "labels"
        if imgs_dir.is_dir():
            for f in list(imgs_dir.iterdir()):
                done += 1
                if progress_cb:
                    progress_cb(done, total, f.name)
                try:
                    new_img = _ensure_unique(target_images_dir / f.name)
                    shutil.move(str(f), str(new_img))
                    # Move corresponding label
                    lbl = lbls_dir / (f.stem + ".json") if lbls_dir.is_dir() else None
                    if lbl and lbl.is_file():
                        target_labels_dir = dataset_root / target / "labels"
                        target_labels_dir.mkdir(parents=True, exist_ok=True)
                        new_lbl = _ensure_unique(target_labels_dir / (new_img.stem + ".json"))
                        shutil.move(str(lbl), str(new_lbl))
                        _update_image_path_in_json(new_lbl, new_img.name)
                    result.succeeded.append(new_img)
                except Exception as e:  # noqa: BLE001
                    result.failed.append((f, str(e)))
        # Remove empty source directory
        try:
            shutil.rmtree(str(src_dir))
        except OSError:
            pass
    return result


def split_category(
    dataset_root: Path,
    source: str,
    new_name: str,
    images: list[ImageInfo],
    progress_cb=None,
) -> OpResult:
    """Move selected images from source category into a new category."""
    return move_to_category(images, dataset_root, new_name,
                             progress_cb=progress_cb)


# ---------- 助手 ----------

def _ensure_unique(path: Path) -> Path:
    """If `path` exists, append _1, _2, ..."""
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    i = 1
    while True:
        candidate = parent / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            return candidate
        i += 1
