"""Image data augmentation generating new samples (does NOT overwrite originals).

Pure Python: PIL + random. No PyQt, no albumentations.

Geometric variants (flip/rotate/crop/copy-paste) update annotation points in
pixel coordinates. Photometric variants (brightness/contrast/jitter/noise/blur)
leave annotations unchanged.

Annotations are loaded via ``format_in`` (unified parsing) and written back
via ``annotation_writer``, so LabelMe / YOLO / Pascal VOC are all supported —
the generated label file matches the source format.
"""
from __future__ import annotations

import copy
import logging
import random
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

from .annotation_writer import write_annotation
from .fileops import OpResult, label_path_for_image
from .models import Annotation, Shape

_log = logging.getLogger(__name__)


@dataclass
class AugmentOptions:
    # 几何变换
    flip_h: bool = True
    flip_v: bool = False
    rotate90: bool = False
    random_crop: bool = False
    crop_ratio: float = 0.85
    copy_paste: bool = False          # 从标注池里抠一个目标粘到随机位置
    copy_paste_prob: float = 0.7      # 每次生成应用的概率
    # 光度变换
    brightness: bool = True
    brightness_range: tuple[float, float] = (0.7, 1.3)
    contrast: bool = True
    contrast_range: tuple[float, float] = (0.7, 1.3)
    color_jitter: bool = False
    color_range: tuple[float, float] = (0.7, 1.3)
    gauss_blur: bool = False
    blur_radius_range: tuple[float, float] = (0.5, 1.5)
    gauss_noise: bool = False
    noise_sigma: float = 8.0
    # 通用
    n_per_image: int = 3
    seed: int = 42


@dataclass
class AugmentResult:
    written_images: list[Path] = field(default_factory=list)
    written_labels: list[Path] = field(default_factory=list)
    failed: list[tuple[Path, str]] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.written_images)


# ---------- 标注 IO (多格式) ----------

def _load_annotation(image_path: Path) -> tuple[Annotation | None, Path | None]:
    """Load annotation via format_in (unified parsing).

    Returns (Annotation, label_path) or (None, label_path).
    The Sample's regions are converted back to the legacy Annotation/Shape
    model that the geometric transform helpers operate on.
    """
    label = label_path_for_image(image_path)
    if label is None or not label.is_file():
        return None, None
    try:
        from .format_in import load_sample
        from .models import ImageInfo
        img_info = ImageInfo(
            path=image_path, category="",
            has_label=True, label_path=label,
        )
        sample = load_sample(img_info)
        if not sample.regions:
            return None, label
        # Convert unified regions → legacy Annotation/Shape
        shapes: list[Shape] = []
        for r in sample.regions:
            pts: list[tuple[float, float]]
            if r.polygon:
                pts = list(r.polygon)
            elif r.bbox:
                if r.shape_type == "rectangle":
                    pts = [(r.bbox.x1, r.bbox.y1), (r.bbox.x2, r.bbox.y2)]
                else:
                    bb = r.bbox
                    pts = [(bb.x1, bb.y1), (bb.x2, bb.y1),
                           (bb.x2, bb.y2), (bb.x1, bb.y2)]
            else:
                continue
            shapes.append(Shape(
                label=r.label,
                shape_type=r.shape_type,
                points=pts,
            ))
        ann = Annotation(image_path=image_path, shapes=shapes)
        return ann, label
    except Exception:
        return None, label


def _shape_bbox(shape: Shape) -> tuple[float, float, float, float]:
    xs = [p[0] for p in shape.points]
    ys = [p[1] for p in shape.points]
    return min(xs), min(ys), max(xs), max(ys)


def _map_shape_points(shapes: list[Shape], fn) -> None:
    for s in shapes:
        s.points = [tuple(fn(float(x), float(y))) for x, y in s.points]


# ---------- Pure coordinate transforms (unit-testable) ----------
#
# Each ``*_points`` helper takes the image's pre-transform size (``w``,
# ``h``) and returns a point-mapping function ``(x, y) -> (x', y')``.
# Keeping the math in standalone callables means tests/test_augment_geom
# can parametrize over (transform, input_pt, expected_pt) without having
# to monkey-patch rng to force random branches.


def flip_h_points(w: int, h: int):
    """Horizontal mirror: x -> w - x."""
    return lambda x, y: (w - x, y)


def flip_v_points(w: int, h: int):
    """Vertical mirror: y -> h - y."""
    return lambda x, y: (x, h - y)


def rotate_90_points(w: int, h: int):
    """90° clockwise (PIL im.rotate(-90, expand=True)).

    Original (w,h) — after rotate output is (h, w). Mapping:
        (x, y) -> (h - y, x)
    """
    return lambda x, y: (h - y, x)


def rotate_180_points(w: int, h: int):
    """180° (PIL im.rotate(180, expand=True))."""
    return lambda x, y: (w - x, h - y)


def rotate_270_points(w: int, h: int):
    """270° clockwise = 90° counter-clockwise (PIL im.rotate(90, expand=True))."""
    return lambda x, y: (y, w - x)


def crop_points(x0: int, y0: int):
    """Crop offset — every point shifts by (-x0, -y0)."""
    return lambda x, y: (x - x0, y - y0)


# ---------- 几何 ----------

def _apply_geometric(
    im: Image.Image,
    ann: Annotation | None,
    opts: AugmentOptions,
    rng: random.Random,
):
    if opts.flip_h and rng.random() < 0.5:
        w, h = im.size
        im = ImageOps.mirror(im)
        if ann:
            _map_shape_points(ann.shapes, flip_h_points(w, h))
    if opts.flip_v and rng.random() < 0.5:
        w, h = im.size
        im = ImageOps.flip(im)
        if ann:
            _map_shape_points(ann.shapes, flip_v_points(w, h))
    if opts.rotate90 and rng.random() < 0.5:
        angle = rng.choice([90, 180, 270])
        ow, oh = im.size
        if angle == 90:
            im = im.rotate(-90, expand=True)
            fn = rotate_90_points(ow, oh)
        elif angle == 180:
            im = im.rotate(180, expand=True)
            fn = rotate_180_points(ow, oh)
        else:
            im = im.rotate(90, expand=True)
            fn = rotate_270_points(ow, oh)
        if ann:
            _map_shape_points(ann.shapes, fn)
    if opts.random_crop:
        ow, oh = im.size
        cw, ch = int(ow * opts.crop_ratio), int(oh * opts.crop_ratio)
        if cw > 0 and ch > 0:
            x0 = rng.randint(0, ow - cw)
            y0 = rng.randint(0, oh - ch)
            im = im.crop((x0, y0, x0 + cw, y0 + ch))
            if ann:
                _map_shape_points(ann.shapes, crop_points(x0, y0))
                kept = []
                for s in ann.shapes:
                    if any(0 <= p[0] <= cw and 0 <= p[1] <= ch for p in s.points):
                        kept.append(s)
                ann.shapes = kept
    return im


# ---------- 光度 ----------

def _apply_photometric(im: Image.Image, opts: AugmentOptions, rng: random.Random):
    if opts.brightness:
        im = ImageEnhance.Brightness(im).enhance(rng.uniform(*opts.brightness_range))
    if opts.contrast:
        im = ImageEnhance.Contrast(im).enhance(rng.uniform(*opts.contrast_range))
    if opts.color_jitter:
        im = ImageEnhance.Color(im).enhance(rng.uniform(*opts.color_range))
    if opts.gauss_blur and rng.random() < 0.5:
        im = im.filter(ImageFilter.GaussianBlur(radius=rng.uniform(*opts.blur_radius_range)))
    if opts.gauss_noise and rng.random() < 0.5:
        try:
            import numpy as np
            arr = np.asarray(im).astype("int16")
            noise = np.random.normal(0, opts.noise_sigma, arr.shape).astype("int16")
            arr = (arr + noise).clip(0, 255).astype("uint8")
            im = Image.fromarray(arr)
        except Exception:
            # numpy missing or image mode incompatible — augmentation still
            # proceeds with other transforms applied, just no noise.
            _log.warning("gauss_noise skipped", exc_info=True)
    return im


# ---------- Copy-Paste ----------

PastePoolEntry = tuple[Path, Shape]  # (源图, 源 shape)


def build_paste_pool(image_paths: list[Path]) -> list[PastePoolEntry]:
    """Collect all labeled shapes from the given images as a paste pool."""
    pool: list[PastePoolEntry] = []
    for p in image_paths:
        ann, _ = _load_annotation(p)
        if ann is None:
            continue
        for s in ann.shapes:
            if not s.points or len(s.points) < 2:
                continue
            pool.append((p, s))
    return pool


def _apply_copy_paste(
    im: Image.Image,
    ann: Annotation | None,
    pool: list[PastePoolEntry],
    opts: AugmentOptions,
    rng: random.Random,
):
    """Pick one random shape, crop its bbox from its source image, paste into
    the current image at a random valid location, and append a translated shape.
    """
    if not pool or rng.random() > opts.copy_paste_prob:
        return im
    src_path, src_shape = rng.choice(pool)
    try:
        with Image.open(src_path) as s:
            src_im = ImageOps.exif_transpose(s).convert("RGBA")
    except Exception:
        return im
    x1, y1, x2, y2 = _shape_bbox(src_shape)
    sw, sh = src_im.size
    x1 = max(0, int(x1)); y1 = max(0, int(y1))
    x2 = min(sw, int(x2)); y2 = min(sh, int(y2))
    if x2 - x1 < 4 or y2 - y1 < 4:
        return im
    patch = src_im.crop((x1, y1, x2, y2)).copy()  # .copy() to materialize lazy crop
    pw, ph = patch.size

    # 多边形 → 按 mask 抠图,只留形状内部的像素;矩形 → 整块
    if src_shape.shape_type == "polygon" and len(src_shape.points) >= 3:
        mask = Image.new("L", (pw, ph), 0)
        local_pts = [(float(px - x1), float(py - y1)) for (px, py) in src_shape.points]
        ImageDraw.Draw(mask).polygon(local_pts, fill=255)
        patch.putalpha(mask)

    tw, th = im.size
    if pw >= tw or ph >= th:
        return im
    dx = rng.randint(0, tw - pw)
    dy = rng.randint(0, th - ph)

    im_rgba = im.convert("RGBA")
    im_rgba.paste(patch, (dx, dy), patch)
    im = im_rgba.convert("RGB")

    if ann is not None:
        # 复制 shape,坐标平移到新位置 (bbox 起点 → dx,dy)
        new_shape = Shape(
            label=src_shape.label,
            shape_type=src_shape.shape_type,
            points=[
                (float(px - x1 + dx), float(py - y1 + dy))
                for (px, py) in src_shape.points
            ],
        )
        ann.shapes.append(new_shape)
    return im


# ---------- 主流程 ----------

def augment_in_memory(
    image: Image.Image, opts: AugmentOptions, seed: int | None = None
) -> Image.Image:
    """One-shot preview: no label round-trip, no copy-paste pool."""
    rng = random.Random(seed if seed is not None else opts.seed)
    im = ImageOps.exif_transpose(image).convert("RGB")
    im = _apply_geometric(im, None, opts, rng)
    im = _apply_photometric(im, opts, rng)
    return im


def augment_image(
    image_path: Path,
    out_dir: Path,
    opts: AugmentOptions,
    rng: random.Random,
    paste_pool: list[PastePoolEntry] | None = None,
) -> tuple[list[Path], list[Path]]:
    images_dir = out_dir / "images"
    labels_dir = out_dir / "labels"
    images_dir.mkdir(parents=True, exist_ok=True)
    written_imgs: list[Path] = []
    written_labels: list[Path] = []

    base_ann, src_label = _load_annotation(image_path)
    label_ext = src_label.suffix if src_label else ".json"

    for i in range(opts.n_per_image):
        with Image.open(image_path) as src:
            im = ImageOps.exif_transpose(src).convert("RGB")
        ann = copy.deepcopy(base_ann) if base_ann is not None else None

        im = _apply_geometric(im, ann, opts, rng)
        im = _apply_photometric(im, opts, rng)
        if opts.copy_paste and paste_pool:
            im = _apply_copy_paste(im, ann, paste_pool, opts, rng)

        out_img = images_dir / f"{image_path.stem}_aug{i + 1}{image_path.suffix}"
        im.save(out_img)
        written_imgs.append(out_img)

        if ann is not None and ann.shapes:
            # 重新绑定到新的 image_path，让 writer 填正确尺寸/文件名
            ann.image_path = out_img
            out_label = labels_dir / f"{image_path.stem}_aug{i + 1}{label_ext}"
            labels_dir.mkdir(parents=True, exist_ok=True)
            try:
                write_annotation(ann, out_label, out_img)
                written_labels.append(out_label)
            except Exception:
                pass
    return written_imgs, written_labels


def augment_batch(
    image_paths: list[Path],
    out_dir: Path,
    opts: AugmentOptions,
    progress_cb=None,
) -> AugmentResult:
    rng = random.Random(opts.seed)
    result = AugmentResult()
    pool: list[PastePoolEntry] = []
    if opts.copy_paste:
        pool = build_paste_pool(image_paths)
    total = len(image_paths)
    for i, p in enumerate(image_paths):
        if progress_cb:
            progress_cb(i, total, p.name)
        try:
            imgs, labels = augment_image(p, out_dir, opts, rng, paste_pool=pool)
            result.written_images.extend(imgs)
            result.written_labels.extend(labels)
        except Exception as e:  # noqa: BLE001
            result.failed.append((p, str(e)))
    if progress_cb:
        progress_cb(total, total, "")
    return result
