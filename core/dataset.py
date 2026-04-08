"""Dataset filesystem scanner. Pure Python — no PyQt.

Layout detection (决定一次、走一条路径)：
    standard  — <root>/<cat>/images/*  (+ labels/*.json)
    flat      — <root>/<cat>/*.jpg     (+ 同级 *.json)
    single    — <root>/*.jpg           (没有类别层，合成 "(未分类)" 类别)
    recursive — 根一层既无图也无标准结构，递归向下最多 MAX_DEPTH 层，
                用"图片所在目录名"做类别，同名自动合并
    empty     — 未发现任何图片

扫描策略（两阶段，避免阻塞主流程）：
    Phase 1 (scan_dataset)        — 仅枚举文件 + 检查 label 是否存在，使用 os.scandir 快速遍历，
                                    不打开 JSON。total_annotations 默认 0。
    Phase 2 (count_annotations)   — 可选的后置阶段，遍历所有 has_label 的图片解析 LabelMe JSON，
                                    更新 dataset.total_annotations。

忽略目录：.git node_modules __pycache__ .idea .vscode dist build venv .venv
"""
from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from . import config as _cfg
from .annotation_formats import (
    LABEL_EXTENSIONS,
    YOLO_AUX_FILES,
    load_yolo_classes,
    parse_annotation,
)
from .models import Category, Dataset, ImageInfo

DEFAULT_IMAGE_EXTS = _cfg.image_extensions()
IMAGE_SUBDIR = "images"
LABEL_SUBDIR = "labels"
UNCATEGORIZED = "(未分类)"
MAX_DEPTH = 4
PROGRESS_CHUNK = 200  # 每扫描这么多张图就回调一次进度
IGNORE_DIRS = {
    ".git", ".svn", ".hg",
    "node_modules", "__pycache__", ".idea", ".vscode",
    "dist", "build", "venv", ".venv", "env",
}

# (done, total, current_name).  total<=0 表示未知（前端按 indeterminate 处理）
ProgressCb = Callable[[int, int, str], None]


# ---------- 内部工具 (os.scandir-based) ----------

def _scandir_safe(path: Path):
    try:
        return list(os.scandir(path))
    except OSError:
        return []


def _list_subdirs(root: Path) -> list[os.DirEntry]:
    return [e for e in _scandir_safe(root) if e.is_dir() and e.name not in IGNORE_DIRS]


def _has_image_file(d: Path, exts: set[str]) -> bool:
    for e in _scandir_safe(d):
        if e.is_file() and os.path.splitext(e.name)[1].lower() in exts:
            return True
    return False


# ---------- 布局检测 ----------

def _detect_layout(root: Path, exts: set[str]) -> str:
    subdirs = _list_subdirs(root)

    if _has_image_file(root, exts):
        return "single"

    if not subdirs:
        return "empty"

    for e in subdirs:
        if (Path(e.path) / IMAGE_SUBDIR).is_dir():
            return "standard"

    for e in subdirs:
        if _has_image_file(Path(e.path), exts):
            return "flat"

    for e in subdirs:
        for _ in _walk(Path(e.path), exts, depth=1):
            return "recursive"

    return "empty"


def _walk(start: Path, exts: set[str], depth: int):
    """Yield directories (up to MAX_DEPTH) that directly contain image files."""
    if depth > MAX_DEPTH:
        return
    entries = _scandir_safe(start)
    if any(e.is_file() and os.path.splitext(e.name)[1].lower() in exts for e in entries):
        yield start
    for e in entries:
        if e.is_dir() and e.name not in IGNORE_DIRS:
            yield from _walk(Path(e.path), exts, depth + 1)


# ---------- 主扫描入口 ----------

def scan_dataset(
    root: Path,
    image_exts: set[str] | None = None,
    progress_cb: ProgressCb | None = None,
) -> Dataset:
    root = Path(root)
    exts = image_exts or DEFAULT_IMAGE_EXTS
    if not root.is_dir():
        raise FileNotFoundError(f"Dataset root not found: {root}")

    layout = _detect_layout(root, exts)

    if layout == "empty":
        if progress_cb:
            progress_cb(0, 0, "")
        return Dataset(name=root.name, root_path=root, layout="empty")

    counter = [0]  # mutable cell — 已扫描图片数

    if layout == "single":
        categories, t_img = _scan_single(root, exts, progress_cb, counter)
    elif layout == "recursive":
        categories, t_img = _scan_recursive(root, exts, progress_cb, counter)
    else:
        categories, t_img = _scan_categorical(root, exts, progress_cb, counter)

    if progress_cb:
        progress_cb(t_img, t_img, "")

    return Dataset(
        name=root.name,
        root_path=root,
        categories=categories,
        total_images=t_img,
        total_annotations=0,  # 由 count_annotations() 第二阶段填充
        layout=layout,
    )


# ---------- 扫描实现 ----------

def _build_image_list(
    img_root: Path,
    lbl_root: Path | None,
    category_name: str,
    exts: set[str],
    progress_cb: ProgressCb | None,
    counter: list[int],
) -> tuple[list[ImageInfo], int]:
    """Phase-1 build: enumerate files + check label existence (no JSON parsing)."""
    images: list[ImageInfo] = []
    label_count = 0

    # 一次 scandir 列出 label 目录里 {stem -> 完整文件名}（兼容 .json/.txt/.xml）
    label_by_stem: dict[str, str] | None = None
    if lbl_root is not None:
        label_by_stem = {}
        for e in _scandir_safe(lbl_root):
            if not e.is_file():
                continue
            n = e.name
            if n in YOLO_AUX_FILES:
                continue
            stem, lext = os.path.splitext(n)
            if lext.lower() in LABEL_EXTENSIONS:
                label_by_stem.setdefault(stem, n)

    entries = _scandir_safe(img_root)
    entries.sort(key=lambda e: e.name)
    for e in entries:
        name = e.name
        if not e.is_file():
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext not in exts:
            continue

        label_path: Path | None = None
        if label_by_stem is not None:
            stem = name[: -len(ext)] if ext else name
            label_filename = label_by_stem.get(stem)
            if label_filename:
                label_path = Path(lbl_root) / label_filename  # type: ignore[arg-type]
                label_count += 1

        images.append(
            ImageInfo(
                path=Path(e.path),
                category=category_name,
                has_label=label_path is not None,
                label_path=label_path,
            )
        )
        counter[0] += 1
        if progress_cb and counter[0] % PROGRESS_CHUNK == 0:
            progress_cb(counter[0], 0, category_name)

    return images, label_count


def _scan_categorical(
    root: Path, exts: set[str], progress_cb: ProgressCb | None, counter: list[int]
) -> tuple[list[Category], int]:
    category_dirs = sorted(_list_subdirs(root), key=lambda e: e.name)
    categories: list[Category] = []
    total_images = 0
    for cat_entry in category_dirs:
        cat_dir = Path(cat_entry.path)
        if progress_cb:
            progress_cb(counter[0], 0, cat_dir.name)

        images_dir = cat_dir / IMAGE_SUBDIR
        labels_dir = cat_dir / LABEL_SUBDIR
        if images_dir.is_dir():
            img_root = images_dir
            lbl_root = labels_dir if labels_dir.is_dir() else None
        else:
            img_root = cat_dir
            lbl_root = cat_dir

        images, label_count = _build_image_list(
            img_root, lbl_root, cat_dir.name, exts, progress_cb, counter
        )
        if images:
            categories.append(
                Category(
                    name=cat_dir.name,
                    image_count=len(images),
                    label_count=label_count,
                    images=images,
                )
            )
            total_images += len(images)

    return categories, total_images


def _scan_single(
    root: Path, exts: set[str], progress_cb: ProgressCb | None, counter: list[int]
) -> tuple[list[Category], int]:
    if progress_cb:
        progress_cb(0, 0, UNCATEGORIZED)
    images, label_count = _build_image_list(
        root, root, UNCATEGORIZED, exts, progress_cb, counter
    )
    if not images:
        return [], 0
    return (
        [Category(
            name=UNCATEGORIZED,
            image_count=len(images),
            label_count=label_count,
            images=images,
        )],
        len(images),
    )


def _scan_recursive(
    root: Path, exts: set[str], progress_cb: ProgressCb | None, counter: list[int]
) -> tuple[list[Category], int]:
    image_dirs = list(_walk(root, exts, depth=0))
    buckets: dict[str, list[ImageInfo]] = {}
    bucket_label_count: dict[str, int] = {}

    for d in image_dirs:
        if progress_cb:
            progress_cb(counter[0], 0, d.name)
        cat_name = d.name or root.name
        images, label_count = _build_image_list(
            d, d, cat_name, exts, progress_cb, counter
        )
        if not images:
            continue
        buckets.setdefault(cat_name, []).extend(images)
        bucket_label_count[cat_name] = bucket_label_count.get(cat_name, 0) + label_count

    categories = [
        Category(
            name=name,
            image_count=len(imgs),
            label_count=bucket_label_count.get(name, 0),
            images=imgs,
        )
        for name, imgs in sorted(buckets.items())
    ]
    total_images = sum(c.image_count for c in categories)
    return categories, total_images


# ---------- Phase 2: 标注计数 ----------

def count_annotations(
    dataset: Dataset, progress_cb: ProgressCb | None = None
) -> int:
    """Parse every LabelMe JSON to compute total_annotations. Mutates dataset.

    Safe to call multiple times — result is deterministic. Tolerant of malformed
    files (parse failures contribute 0 to the count).
    """
    total_labels = sum(c.label_count for c in dataset.categories)
    if total_labels == 0:
        dataset.total_annotations = 0
        if progress_cb:
            progress_cb(0, 0, "")
        return 0

    done = 0
    total_ann = 0
    yolo_classes_cache: dict[Path, list[str]] = {}
    for cat in dataset.categories:
        for img in cat.images:
            if not img.has_label or img.label_path is None:
                continue
            classes: list[str] | None = None
            if img.label_path.suffix.lower() == ".txt":
                d = img.label_path.parent
                if d not in yolo_classes_cache:
                    yolo_classes_cache[d] = load_yolo_classes(d)
                classes = yolo_classes_cache[d] or None
            result = parse_annotation(img.label_path, img.path, yolo_class_names=classes)
            if result.ok and result.annotation:
                total_ann += len(result.annotation.shapes)
            done += 1
            if progress_cb and done % PROGRESS_CHUNK == 0:
                progress_cb(done, total_labels, cat.name)

    dataset.total_annotations = total_ann
    if progress_cb:
        progress_cb(total_labels, total_labels, "")
    return total_ann
