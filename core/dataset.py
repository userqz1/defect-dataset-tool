"""Dataset filesystem scanner. Pure Python — no PyQt.

Layout detection (决定一次、走一条路径)：
    standard  — <root>/<cat>/images/*  (+ labels/*.json)
    flat      — <root>/<cat>/*.jpg     (+ 同级 *.json)
    single    — <root>/*.jpg           (没有类别层，合成 "(未分类)" 类别)
    recursive — 根一层既无图也无标准结构，递归向下最多 MAX_DEPTH 层，
                用"图片所在目录名"做类别，同名自动合并
    empty     — 未发现任何图片

忽略目录：.git node_modules __pycache__ .idea .vscode dist build venv .venv
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from . import config as _cfg
from .annotation import parse_labelme
from .models import Category, Dataset, ImageInfo

DEFAULT_IMAGE_EXTS = _cfg.image_extensions()
IMAGE_SUBDIR = "images"
LABEL_SUBDIR = "labels"
UNCATEGORIZED = "(未分类)"
MAX_DEPTH = 4
IGNORE_DIRS = {
    ".git", ".svn", ".hg",
    "node_modules", "__pycache__", ".idea", ".vscode",
    "dist", "build", "venv", ".venv", "env",
}

ProgressCb = Callable[[int, int, str], None]


# ---------- 布局检测 ----------

def _has_image_file(d: Path, exts: set[str]) -> bool:
    try:
        for p in d.iterdir():
            if p.is_file() and p.suffix.lower() in exts:
                return True
    except OSError:
        pass
    return False


def _detect_layout(root: Path, exts: set[str]) -> str:
    subdirs = [p for p in root.iterdir() if p.is_dir() and p.name not in IGNORE_DIRS]

    # 根目录本身有图 → single
    if _has_image_file(root, exts):
        return "single"

    if not subdirs:
        return "empty"

    # 任意类别目录包含 images/ → standard
    for d in subdirs:
        if (d / IMAGE_SUBDIR).is_dir():
            return "standard"

    # 任意类别目录直接有图 → flat
    for d in subdirs:
        if _has_image_file(d, exts):
            return "flat"

    # 再往下找,若能找到图片 → recursive
    for d in subdirs:
        for deeper in _walk(d, exts, depth=1):
            return "recursive"

    return "empty"


def _walk(start: Path, exts: set[str], depth: int):
    """Yield directories (up to MAX_DEPTH) that directly contain image files."""
    if depth > MAX_DEPTH:
        return
    try:
        entries = list(start.iterdir())
    except OSError:
        return
    if any(p.is_file() and p.suffix.lower() in exts for p in entries):
        yield start
    for p in entries:
        if p.is_dir() and p.name not in IGNORE_DIRS:
            yield from _walk(p, exts, depth + 1)


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
        return Dataset(name=root.name, root_path=root, layout="empty")

    if layout == "single":
        categories, t_img, t_ann = _scan_single(root, exts, progress_cb)
    elif layout == "recursive":
        categories, t_img, t_ann = _scan_recursive(root, exts, progress_cb)
    else:
        # standard / flat 都走原逻辑：根的直接子目录即类别
        categories, t_img, t_ann = _scan_categorical(root, exts, progress_cb)

    return Dataset(
        name=root.name,
        root_path=root,
        categories=categories,
        total_images=t_img,
        total_annotations=t_ann,
        layout=layout,
    )


# ---------- 扫描实现 ----------

def _build_image_list(
    img_root: Path,
    lbl_root: Path | None,
    category_name: str,
    exts: set[str],
) -> tuple[list[ImageInfo], int, int]:
    images: list[ImageInfo] = []
    label_count = 0
    ann_count = 0
    try:
        entries = sorted(img_root.iterdir())
    except OSError:
        return images, 0, 0
    for img_file in entries:
        if not img_file.is_file() or img_file.suffix.lower() not in exts:
            continue
        label_file: Path | None = None
        if lbl_root is not None:
            candidate = lbl_root / (img_file.stem + ".json")
            if candidate.is_file():
                label_file = candidate
        has_label = label_file is not None
        if has_label:
            label_count += 1
            result = parse_labelme(label_file, img_file)
            if result.ok and result.annotation:
                ann_count += len(result.annotation.shapes)
        images.append(
            ImageInfo(
                path=img_file,
                category=category_name,
                has_label=has_label,
                label_path=label_file,
            )
        )
    return images, label_count, ann_count


def _scan_categorical(
    root: Path, exts: set[str], progress_cb: ProgressCb | None
) -> tuple[list[Category], int, int]:
    category_dirs = sorted(
        p for p in root.iterdir() if p.is_dir() and p.name not in IGNORE_DIRS
    )
    total = len(category_dirs)
    categories: list[Category] = []
    total_images = 0
    total_annotations = 0
    for idx, cat_dir in enumerate(category_dirs):
        if progress_cb:
            progress_cb(idx, total, cat_dir.name)

        images_dir = cat_dir / IMAGE_SUBDIR
        labels_dir = cat_dir / LABEL_SUBDIR
        if images_dir.is_dir():
            img_root = images_dir
            lbl_root = labels_dir if labels_dir.is_dir() else None
        else:
            img_root = cat_dir
            lbl_root = cat_dir

        images, label_count, ann_count = _build_image_list(
            img_root, lbl_root, cat_dir.name, exts
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
            total_annotations += ann_count

    if progress_cb:
        progress_cb(total, total, "")
    return categories, total_images, total_annotations


def _scan_single(
    root: Path, exts: set[str], progress_cb: ProgressCb | None
) -> tuple[list[Category], int, int]:
    if progress_cb:
        progress_cb(0, 1, UNCATEGORIZED)
    images, label_count, ann_count = _build_image_list(
        root, root, UNCATEGORIZED, exts
    )
    if progress_cb:
        progress_cb(1, 1, "")
    if not images:
        return [], 0, 0
    return (
        [Category(
            name=UNCATEGORIZED,
            image_count=len(images),
            label_count=label_count,
            images=images,
        )],
        len(images),
        ann_count,
    )


def _scan_recursive(
    root: Path, exts: set[str], progress_cb: ProgressCb | None
) -> tuple[list[Category], int, int]:
    # 按"图片所在目录名"分组；同名自动合并
    image_dirs = list(_walk(root, exts, depth=0))
    total = len(image_dirs)
    buckets: dict[str, list[ImageInfo]] = {}
    bucket_label_count: dict[str, int] = {}
    total_annotations = 0

    for idx, d in enumerate(image_dirs):
        if progress_cb:
            progress_cb(idx, total, d.name)
        cat_name = d.name or root.name
        images, label_count, ann_count = _build_image_list(d, d, cat_name, exts)
        if not images:
            continue
        buckets.setdefault(cat_name, []).extend(images)
        bucket_label_count[cat_name] = bucket_label_count.get(cat_name, 0) + label_count
        total_annotations += ann_count

    if progress_cb:
        progress_cb(total, total, "")

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
    return categories, total_images, total_annotations
