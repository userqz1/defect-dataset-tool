"""Dataset filesystem scanner. Pure Python — no PyQt.

Layout detection (决定一次、走一条路径)：
    standard  — <root>/<cat>/images/*  (+ labels/*.json)
    flat      — <root>/<cat>/*.jpg     (+ 同级 *.json)
    single    — <root>/*.jpg           (没有类别层，合成 "(未分类)" 类别)
    coco      — <root>/annotations.json (COCO) + 同目录或 images/ 子目录的图片
                类别来自 COCO categories，所有图片 label_path 都指向同一个 JSON
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
    CocoIndex,
    load_yolo_classes,
    parse_annotation,
    parse_coco,
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

def _find_coco_json(root: Path) -> tuple[Path, CocoIndex] | None:
    """Scan root (and an optional ``annotations/`` subdir) for a file that
    parse_coco accepts. Returns (path, index) of the first match."""
    candidates: list[Path] = []
    # Root-level JSONs first
    for e in _scandir_safe(root):
        if e.is_file() and e.name.lower().endswith(".json"):
            candidates.append(Path(e.path))
    # Common COCO layout: annotations/instances_*.json
    ann_dir = root / "annotations"
    if ann_dir.is_dir():
        for e in _scandir_safe(ann_dir):
            if e.is_file() and e.name.lower().endswith(".json"):
                candidates.append(Path(e.path))
    for p in candidates:
        idx = parse_coco(p)
        if idx is not None and idx.by_stem:
            return p, idx
    return None


def _detect_layout(root: Path, exts: set[str]) -> str:
    # COCO check comes first — the "single" and "recursive" heuristics
    # would otherwise blindly match and leave annotations at 0.
    if _find_coco_json(root) is not None:
        return "coco"

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
    elif layout == "coco":
        categories, t_img = _scan_coco(root, exts, progress_cb, counter)
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


def _scan_coco(
    root: Path, exts: set[str], progress_cb: ProgressCb | None, counter: list[int]
) -> tuple[list[Category], int]:
    """Build categories from COCO's ``categories`` + images list.

    All images get ``label_path`` pointing at the COCO JSON; parse_annotation
    has a cached COCO branch so 1000 images only pay one parse.
    """
    found = _find_coco_json(root)
    if found is None:
        return [], 0
    json_path, idx = found

    # Images may live at root, in root/images/, or in whatever file_name said
    image_dirs: list[Path] = [root]
    if (root / "images").is_dir():
        image_dirs.append(root / "images")
    # Walk subdirs that don't look like the annotations dir
    for e in _list_subdirs(root):
        if e.name.lower() != "annotations":
            image_dirs.append(Path(e.path))

    # Dedup by stem for annotation lookup; category assignment from first shape
    image_paths_by_stem: dict[str, Path] = {}
    for d in image_dirs:
        for e in _scandir_safe(d):
            if not e.is_file():
                continue
            ext = os.path.splitext(e.name)[1].lower()
            if ext not in exts:
                continue
            stem = os.path.splitext(e.name)[0]
            image_paths_by_stem.setdefault(stem, Path(e.path))

    by_category: dict[str, list[ImageInfo]] = {}
    label_count_by_cat: dict[str, int] = {}
    UNLABELED = "(未标注)"

    for stem, p in image_paths_by_stem.items():
        shapes = idx.by_stem.get(stem, [])
        has_label = bool(shapes)
        if has_label:
            # Category = first shape's label (COCO images can have multiple
            # classes; this is a display heuristic, the shapes carry truth)
            cat_name = shapes[0].label
            label_count_by_cat[cat_name] = label_count_by_cat.get(cat_name, 0) + 1
        else:
            cat_name = UNLABELED
        by_category.setdefault(cat_name, []).append(
            ImageInfo(
                path=p,
                category=cat_name,
                has_label=has_label,
                label_path=json_path if has_label else None,
            )
        )
        counter[0] += 1
        if progress_cb and counter[0] % PROGRESS_CHUNK == 0:
            progress_cb(counter[0], 0, cat_name)

    categories = [
        Category(
            name=name,
            image_count=len(imgs),
            label_count=label_count_by_cat.get(name, 0),
            images=imgs,
        )
        for name, imgs in sorted(by_category.items())
    ]
    return categories, sum(c.image_count for c in categories)


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
    """Parse every annotation file to compute total_annotations. Mutates dataset.

    Safe to call multiple times — result is deterministic. Tolerant of malformed
    files (parse failures contribute 0 to the count).

    Parallelized with ThreadPoolExecutor: Python's json/xml modules release
    the GIL during C parsing, so threads give ~3-5x speedup on datasets with
    thousands of LabelMe JSONs / YOLO txts / VOC xmls. COCO is unaffected —
    parse_annotation already caches the single JSON.
    """
    total_labels = sum(c.label_count for c in dataset.categories)
    if total_labels == 0:
        dataset.total_annotations = 0
        if progress_cb:
            progress_cb(0, 0, "")
        return 0

    # Collect parse tasks first so we can submit to a pool.
    # Pre-resolve yolo classes per-dir on the main thread to avoid lock contention.
    yolo_classes_cache: dict[Path, list[str] | None] = {}

    # tuple of (label_path, image_path, classes, cat_name)
    tasks: list[tuple[Path, Path, list[str] | None, str]] = []
    for cat in dataset.categories:
        for img in cat.images:
            if not img.has_label or img.label_path is None:
                continue
            classes: list[str] | None = None
            if img.label_path.suffix.lower() == ".txt":
                d = img.label_path.parent
                if d not in yolo_classes_cache:
                    loaded = load_yolo_classes(d)
                    yolo_classes_cache[d] = loaded or None
                classes = yolo_classes_cache[d]
            tasks.append((img.label_path, img.path, classes, cat.name))

    if not tasks:
        dataset.total_annotations = 0
        if progress_cb:
            progress_cb(0, 0, "")
        return 0

    # Parallel parse. 8 threads is plenty — json/xml are C-backed + GIL-released.
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _parse_one(t: tuple[Path, Path, list[str] | None, str]) -> tuple[int, str]:
        label_path, image_path, classes, cat_name = t
        try:
            r = parse_annotation(label_path, image_path, yolo_class_names=classes)
            if r.ok and r.annotation:
                return len(r.annotation.shapes), cat_name
        except Exception:
            pass
        return 0, cat_name

    total_ann = 0
    done = 0
    workers = min(8, max(2, len(tasks) // 100))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for fut in as_completed(pool.submit(_parse_one, t) for t in tasks):
            n, cat_name = fut.result()
            total_ann += n
            done += 1
            if progress_cb and done % PROGRESS_CHUNK == 0:
                progress_cb(done, total_labels, cat_name)

    dataset.total_annotations = total_ann
    if progress_cb:
        progress_cb(total_labels, total_labels, "")
    return total_ann
