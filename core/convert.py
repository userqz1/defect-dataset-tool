"""Image format conversion. Single file or batch.

Each conversion writes a NEW file (default behavior preserves the original).
If a paired LabelMe JSON exists, a corresponding new JSON is written with
the `imagePath` field updated.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps
from send2trash import send2trash

from .fileops import OpResult, label_path_for_image

SUPPORTED_FORMATS = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".bmp": "BMP",
    ".webp": "WEBP",
    ".tiff": "TIFF",
}


@dataclass
class ConvertOptions:
    target_ext: str = ".png"        # e.g. ".jpg" / ".png" / ".webp"
    quality: int = 92               # JPEG/WebP quality
    keep_exif: bool = True
    overwrite: bool = False
    delete_original: bool = False   # 转完后删除原图（默认不删，安全）

    def __post_init__(self) -> None:
        ext = self.target_ext.lower()
        if not ext.startswith("."):
            ext = "." + ext
        self.target_ext = ext
        if ext not in SUPPORTED_FORMATS:
            raise ValueError(f"unsupported target format: {ext}")


def convert_one(image_path: Path, opts: ConvertOptions) -> Path:
    """Convert a single image. Returns new path. Raises on error."""
    pil_format = SUPPORTED_FORMATS[opts.target_ext]
    new_path = image_path.with_suffix(opts.target_ext)
    if new_path == image_path:
        return image_path  # 同格式不动
    if new_path.exists() and not opts.overwrite:
        # 加 _converted 后缀避免覆盖
        new_path = image_path.with_name(image_path.stem + "_converted" + opts.target_ext)

    with Image.open(image_path) as im:
        im = ImageOps.exif_transpose(im)
        # JPEG 不支持 alpha
        if pil_format == "JPEG" and im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGB")
        save_kwargs: dict = {}
        if pil_format in ("JPEG", "WEBP"):
            save_kwargs["quality"] = opts.quality
        if opts.keep_exif:
            exif = im.info.get("exif")
            if exif:
                save_kwargs["exif"] = exif
        im.save(new_path, format=pil_format, **save_kwargs)

    # 同步 JSON
    label = label_path_for_image(image_path)
    if label and label.is_file():
        new_label = new_path.with_suffix(".json")
        if new_label != label:
            try:
                data = json.loads(label.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    data["imagePath"] = new_path.name
                new_label.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            except Exception:
                pass

    # Send to Recycle Bin rather than hard-unlink — review point #10.
    # Conversion is user-initiated but not infallible (bad PIL config,
    # JPEG from HDR TIFF losing bit depth, etc.); original must be
    # recoverable on at least the first surprise.
    if opts.delete_original and new_path != image_path:
        try:
            send2trash(str(image_path))
            if label and label.is_file() and label.suffix == ".json":
                new_json = new_path.with_suffix(".json")
                if new_json.exists() and new_json != label:
                    send2trash(str(label))
        except OSError:
            # Swallow: new_path is already on disk, so we don't want to
            # fail the whole convert over a trashing failure. Caller
            # sees success; the stray original is visible in the UI.
            pass

    return new_path


def convert_batch(
    image_paths: list[Path],
    opts: ConvertOptions,
    progress_cb=None,
) -> OpResult:
    """Convert many images. Returns OpResult with successes/failures."""
    result = OpResult()
    total = len(image_paths)
    for i, p in enumerate(image_paths):
        if progress_cb:
            progress_cb(i, total, str(p.name))
        try:
            new_path = convert_one(p, opts)
            result.succeeded.append(new_path)
        except Exception as e:  # noqa: BLE001
            result.failed.append((p, str(e)))
    if progress_cb:
        progress_cb(total, total, "")
    return result
