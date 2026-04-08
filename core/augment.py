"""Image data augmentation generating new samples (does NOT overwrite originals).

Pure Python: PIL + random + numpy. No PyQt, no albumentations dependency.

Augmentations only generate new geometric variants synced with LabelMe JSON
points. Photometric augmentations (brightness/contrast/jitter/noise/blur)
leave the annotation unchanged. Random crop / flip / rotate update the points.

Output goes to a NEW directory chosen by the caller; originals are untouched.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from .fileops import OpResult, label_path_for_image


@dataclass
class AugmentOptions:
    # 几何变换
    flip_h: bool = True
    flip_v: bool = False
    rotate90: bool = False  # 90/180/270 随机
    random_crop: bool = False
    crop_ratio: float = 0.85  # 裁出 0.85x 区域
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
    n_per_image: int = 3  # 每张原图生成几张
    seed: int = 42


@dataclass
class AugmentResult:
    written_images: list[Path] = field(default_factory=list)
    written_labels: list[Path] = field(default_factory=list)
    failed: list[tuple[Path, str]] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.written_images)


def _load_label(image_path: Path) -> dict | None:
    label = label_path_for_image(image_path)
    if label is None or not label.is_file():
        return None
    try:
        data = json.loads(label.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _save_label(json_path: Path, data: dict) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _map_points(shapes: list, fn) -> None:
    for shape in shapes:
        pts = shape.get("points")
        if not isinstance(pts, list):
            continue
        new_pts = []
        for p in pts:
            if isinstance(p, (list, tuple)) and len(p) >= 2:
                try:
                    nx, ny = fn(float(p[0]), float(p[1]))
                    new_pts.append([nx, ny])
                except Exception:
                    new_pts.append(p)
            else:
                new_pts.append(p)
        shape["points"] = new_pts


def _apply_geometric(im: Image.Image, label: dict | None, opts: AugmentOptions, rng: random.Random):
    """Choose a random combination of geometric ops; mutate label in-place."""
    w, h = im.size
    # 翻转
    if opts.flip_h and rng.random() < 0.5:
        im = ImageOps.mirror(im)
        if label and isinstance(label.get("shapes"), list):
            _map_points(label["shapes"], lambda x, y: (w - x, y))
    if opts.flip_v and rng.random() < 0.5:
        im = ImageOps.flip(im)
        if label and isinstance(label.get("shapes"), list):
            _map_points(label["shapes"], lambda x, y: (x, h - y))
    # 旋转 90/180/270
    if opts.rotate90 and rng.random() < 0.5:
        angle = rng.choice([90, 180, 270])
        ow, oh = im.size
        if angle == 90:
            im = im.rotate(-90, expand=True)
            fn = lambda x, y: (oh - y, x)
        elif angle == 180:
            im = im.rotate(180, expand=True)
            fn = lambda x, y: (ow - x, oh - y)
        else:
            im = im.rotate(90, expand=True)
            fn = lambda x, y: (y, ow - x)
        if label and isinstance(label.get("shapes"), list):
            _map_points(label["shapes"], fn)
    # 随机裁剪
    if opts.random_crop:
        ow, oh = im.size
        cw, ch = int(ow * opts.crop_ratio), int(oh * opts.crop_ratio)
        if cw > 0 and ch > 0:
            x0 = rng.randint(0, ow - cw)
            y0 = rng.randint(0, oh - ch)
            im = im.crop((x0, y0, x0 + cw, y0 + ch))
            if label and isinstance(label.get("shapes"), list):
                _map_points(label["shapes"], lambda x, y: (x - x0, y - y0))
                # 过滤完全跑出去的形状
                kept = []
                for s in label["shapes"]:
                    pts = s.get("points") or []
                    if any(0 <= p[0] <= cw and 0 <= p[1] <= ch for p in pts):
                        kept.append(s)
                label["shapes"] = kept
    return im


def _apply_photometric(im: Image.Image, opts: AugmentOptions, rng: random.Random):
    if opts.brightness:
        f = rng.uniform(*opts.brightness_range)
        im = ImageEnhance.Brightness(im).enhance(f)
    if opts.contrast:
        f = rng.uniform(*opts.contrast_range)
        im = ImageEnhance.Contrast(im).enhance(f)
    if opts.color_jitter:
        f = rng.uniform(*opts.color_range)
        im = ImageEnhance.Color(im).enhance(f)
    if opts.gauss_blur and rng.random() < 0.5:
        r = rng.uniform(*opts.blur_radius_range)
        im = im.filter(ImageFilter.GaussianBlur(radius=r))
    if opts.gauss_noise and rng.random() < 0.5:
        try:
            import numpy as np
            arr = np.asarray(im).astype("int16")
            noise = np.random.normal(0, opts.noise_sigma, arr.shape).astype("int16")
            arr = (arr + noise).clip(0, 255).astype("uint8")
            im = Image.fromarray(arr)
        except Exception:
            pass
    return im


def augment_in_memory(image: Image.Image, opts: AugmentOptions, seed: int | None = None) -> Image.Image:
    """Run one augmentation pass on a PIL image and return the result."""
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
) -> tuple[list[Path], list[Path]]:
    """Generate `n_per_image` variants of one image into out_dir.

    out_dir layout: out_dir/images/<stem>_aug{i}.jpg + out_dir/labels/<stem>_aug{i}.json
    """
    images_dir = out_dir / "images"
    labels_dir = out_dir / "labels"
    images_dir.mkdir(parents=True, exist_ok=True)
    written_imgs: list[Path] = []
    written_labels: list[Path] = []

    base_label = _load_label(image_path)

    for i in range(opts.n_per_image):
        with Image.open(image_path) as src:
            im = ImageOps.exif_transpose(src).convert("RGB")
        # 深拷贝标注
        label = json.loads(json.dumps(base_label)) if base_label else None
        im = _apply_geometric(im, label, opts, rng)
        im = _apply_photometric(im, opts, rng)

        out_img = images_dir / f"{image_path.stem}_aug{i + 1}{image_path.suffix}"
        im.save(out_img)
        written_imgs.append(out_img)

        if label is not None:
            label["imagePath"] = out_img.name
            label["imageData"] = None
            label["imageWidth"] = im.size[0]
            label["imageHeight"] = im.size[1]
            out_label = labels_dir / f"{image_path.stem}_aug{i + 1}.json"
            _save_label(out_label, label)
            written_labels.append(out_label)
    return written_imgs, written_labels


def augment_batch(
    image_paths: list[Path],
    out_dir: Path,
    opts: AugmentOptions,
    progress_cb=None,
) -> AugmentResult:
    rng = random.Random(opts.seed)
    result = AugmentResult()
    total = len(image_paths)
    for i, p in enumerate(image_paths):
        if progress_cb:
            progress_cb(i, total, p.name)
        try:
            imgs, labels = augment_image(p, out_dir, opts, rng)
            result.written_images.extend(imgs)
            result.written_labels.extend(labels)
        except Exception as e:  # noqa: BLE001
            result.failed.append((p, str(e)))
    if progress_cb:
        progress_cb(total, total, "")
    return result
