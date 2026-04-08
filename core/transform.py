"""Geometric image operations with synchronous LabelMe coordinate updates.

All operations write a new image + new JSON, suffixing the filename so the
original is preserved (overridden by `inplace=True` on each function).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from PIL import Image, ImageOps

from .fileops import OpResult, label_path_for_image


# ---------- 通用 ----------

def _output_path(src: Path, suffix: str, inplace: bool) -> Path:
    if inplace:
        return src
    return src.with_name(src.stem + suffix + src.suffix)


def _load_json(label: Path) -> dict | None:
    try:
        data = json.loads(label.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _save_json(label: Path, data: dict) -> None:
    label.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _transform_points(
    shapes: list[dict],
    fn,
) -> None:
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


# ---------- Resize ----------

@dataclass
class ResizeOptions:
    width: int | None = None
    height: int | None = None
    keep_ratio: bool = True
    inplace: bool = False
    suffix: str = "_resized"


def resize_one(image_path: Path, opts: ResizeOptions) -> Path:
    with Image.open(image_path) as im:
        im = ImageOps.exif_transpose(im)
        ow, oh = im.size
        tw, th = opts.width or ow, opts.height or oh
        if opts.keep_ratio and opts.width and opts.height:
            ratio = min(tw / ow, th / oh)
            tw, th = int(ow * ratio), int(oh * ratio)
        elif opts.keep_ratio and opts.width:
            th = int(oh * (tw / ow))
        elif opts.keep_ratio and opts.height:
            tw = int(ow * (th / oh))
        new_im = im.resize((tw, th), Image.Resampling.LANCZOS)
        out = _output_path(image_path, opts.suffix, opts.inplace)
        new_im.save(out)

    sx, sy = tw / ow, th / oh
    label = label_path_for_image(image_path)
    if label and label.is_file():
        data = _load_json(label)
        if data and isinstance(data.get("shapes"), list):
            _transform_points(data["shapes"], lambda x, y: (x * sx, y * sy))
            data["imageWidth"] = tw
            data["imageHeight"] = th
            data["imagePath"] = out.name
            new_label = out.with_suffix(".json")
            _save_json(new_label, data)
    return out


# ---------- Crop ----------

@dataclass
class CropOptions:
    x: int
    y: int
    width: int
    height: int
    inplace: bool = False
    suffix: str = "_crop"


def crop_one(image_path: Path, opts: CropOptions) -> Path:
    with Image.open(image_path) as im:
        im = ImageOps.exif_transpose(im)
        box = (opts.x, opts.y, opts.x + opts.width, opts.y + opts.height)
        new_im = im.crop(box)
        out = _output_path(image_path, opts.suffix, opts.inplace)
        new_im.save(out)

    label = label_path_for_image(image_path)
    if label and label.is_file():
        data = _load_json(label)
        if data and isinstance(data.get("shapes"), list):
            _transform_points(data["shapes"], lambda x, y: (x - opts.x, y - opts.y))
            # 过滤完全跑到边界外的形状
            kept = []
            for s in data["shapes"]:
                pts = s.get("points") or []
                if any(0 <= p[0] <= opts.width and 0 <= p[1] <= opts.height for p in pts):
                    kept.append(s)
            data["shapes"] = kept
            data["imageWidth"] = opts.width
            data["imageHeight"] = opts.height
            data["imagePath"] = out.name
            new_label = out.with_suffix(".json")
            _save_json(new_label, data)
    return out


# ---------- Rotate ----------

@dataclass
class RotateOptions:
    angle: Literal[90, 180, 270]
    inplace: bool = False
    suffix: str = "_rot"


def rotate_one(image_path: Path, opts: RotateOptions) -> Path:
    with Image.open(image_path) as im:
        im = ImageOps.exif_transpose(im)
        ow, oh = im.size
        # PIL 旋转方向：正数 = 逆时针；这里 90/180/270 含义为顺时针
        if opts.angle == 90:
            new_im = im.rotate(-90, expand=True)
        elif opts.angle == 180:
            new_im = im.rotate(180, expand=True)
        else:  # 270
            new_im = im.rotate(90, expand=True)
        out = _output_path(image_path, f"{opts.suffix}{opts.angle}", opts.inplace)
        new_im.save(out)
        nw, nh = new_im.size

    label = label_path_for_image(image_path)
    if label and label.is_file():
        data = _load_json(label)
        if data and isinstance(data.get("shapes"), list):
            if opts.angle == 90:
                fn = lambda x, y: (oh - y, x)
            elif opts.angle == 180:
                fn = lambda x, y: (ow - x, oh - y)
            else:  # 270
                fn = lambda x, y: (y, ow - x)
            _transform_points(data["shapes"], fn)
            data["imageWidth"] = nw
            data["imageHeight"] = nh
            data["imagePath"] = out.name
            _save_json(out.with_suffix(".json"), data)
    return out


# ---------- Flip ----------

@dataclass
class FlipOptions:
    direction: Literal["horizontal", "vertical"]
    inplace: bool = False
    suffix: str = "_flip"


def flip_one(image_path: Path, opts: FlipOptions) -> Path:
    with Image.open(image_path) as im:
        im = ImageOps.exif_transpose(im)
        ow, oh = im.size
        if opts.direction == "horizontal":
            new_im = ImageOps.mirror(im)
        else:
            new_im = ImageOps.flip(im)
        suffix = opts.suffix + ("_h" if opts.direction == "horizontal" else "_v")
        out = _output_path(image_path, suffix, opts.inplace)
        new_im.save(out)

    label = label_path_for_image(image_path)
    if label and label.is_file():
        data = _load_json(label)
        if data and isinstance(data.get("shapes"), list):
            if opts.direction == "horizontal":
                fn = lambda x, y: (ow - x, y)
            else:
                fn = lambda x, y: (x, oh - y)
            _transform_points(data["shapes"], fn)
            data["imagePath"] = out.name
            _save_json(out.with_suffix(".json"), data)
    return out


# ---------- 批量 ----------

def batch_apply(
    image_paths: list[Path],
    op_fn,
    opts,
    progress_cb=None,
) -> OpResult:
    result = OpResult()
    total = len(image_paths)
    for i, p in enumerate(image_paths):
        if progress_cb:
            progress_cb(i, total, p.name)
        try:
            out = op_fn(p, opts)
            result.succeeded.append(out)
        except Exception as e:  # noqa: BLE001
            result.failed.append((p, str(e)))
    if progress_cb:
        progress_cb(total, total, "")
    return result
