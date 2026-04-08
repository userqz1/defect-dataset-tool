"""Image quality checks. Pure Python — no PyQt.

Detects four kinds of issues:
    - corrupt: file unreadable / decode failed
    - blank:   nearly-uniform image (low pixel std)
    - blur:    low Laplacian variance (focus measure)
    - over:    over/under-exposed (mean luminance near 0 or 255)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageOps, ImageStat

from .models import ImageInfo


@dataclass
class QualityOptions:
    blur_threshold: float = 100.0   # Laplacian variance < this → blurry
    blank_std_max: float = 5.0      # luminance std < this → blank
    exposure_low: float = 15.0      # mean luminance < this → underexposed
    exposure_high: float = 240.0    # mean luminance > this → overexposed
    sample_size: int = 512          # downscale long edge for speed


@dataclass
class QualityIssue:
    image: ImageInfo
    kinds: list[str]                # subset of {corrupt, blank, blur, over, under}
    metrics: dict[str, float] = field(default_factory=dict)


def _laplacian_variance(im: Image.Image) -> float:
    """Cheap focus measure without numpy: 3x3 Laplacian via PIL ImageFilter."""
    from PIL import ImageFilter
    gray = im.convert("L")
    lap = gray.filter(ImageFilter.Kernel((3, 3), [0, 1, 0, 1, -4, 1, 0, 1, 0], scale=1))
    stat = ImageStat.Stat(lap)
    # stddev² ≈ variance
    return float(stat.stddev[0]) ** 2


def check_one(image_path: Path, opts: QualityOptions) -> tuple[list[str], dict[str, float]]:
    try:
        with Image.open(image_path) as im:
            im = ImageOps.exif_transpose(im)
            im.thumbnail((opts.sample_size, opts.sample_size))
            gray = im.convert("L")
            stat = ImageStat.Stat(gray)
            mean = float(stat.mean[0])
            stddev = float(stat.stddev[0])
            lap_var = _laplacian_variance(im)
    except Exception as e:  # noqa: BLE001
        return ["corrupt"], {"error": 0.0, "_msg": 0.0}

    kinds: list[str] = []
    if stddev < opts.blank_std_max:
        kinds.append("blank")
    if lap_var < opts.blur_threshold and "blank" not in kinds:
        kinds.append("blur")
    if mean < opts.exposure_low:
        kinds.append("under")
    elif mean > opts.exposure_high:
        kinds.append("over")
    return kinds, {"mean": mean, "std": stddev, "lap_var": lap_var}


def check_images(
    images: list[ImageInfo],
    opts: QualityOptions | None = None,
    progress_cb=None,
) -> list[QualityIssue]:
    opts = opts or QualityOptions()
    issues: list[QualityIssue] = []
    total = len(images)
    for i, img in enumerate(images):
        if progress_cb:
            progress_cb(i, total, img.path.name)
        kinds, metrics = check_one(img.path, opts)
        if kinds:
            issues.append(QualityIssue(image=img, kinds=kinds, metrics=metrics))
    if progress_cb:
        progress_cb(total, total, "")
    return issues
