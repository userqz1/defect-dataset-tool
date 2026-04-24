"""Image quality checks. Pure Python — no PyQt.

Pixel-level checks (via PIL):
    - corrupt: file unreadable / decode failed
    - blank:   nearly-uniform image (low pixel std)
    - blur:    low Laplacian variance (focus measure)
    - over:    over/under-exposed (mean luminance near 0 or 255)

Annotation-level checks (via SampleSet — no I/O):
    - empty_label:  label file exists but contains no regions
    - zero_area:    a region has a bounding box with 0 area
    - oob:          a region extends outside the image bounds
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image, ImageOps, ImageStat

from .models import ImageInfo

if TYPE_CHECKING:
    from .unified import SampleSet


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
        return ["corrupt"], {"error": str(e)}

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
    images,
    opts: QualityOptions | None = None,
    progress_cb=None,
    total: int | None = None,
) -> list[QualityIssue]:
    """Check images for quality issues. Uses ThreadPoolExecutor for speed.

    Accepts ``list[ImageInfo]`` or any ``Iterable[ImageInfo]``. For
    iterables that don't support ``len()`` (generators, chain), pass the
    expected count via ``total`` so progress_cb has a denominator; if
    omitted we materialize the iterable into a list.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    opts = opts or QualityOptions()
    issues: list[QualityIssue] = []

    # If caller didn't give a total, try len(); otherwise materialize.
    if total is None:
        try:
            total = len(images)  # type: ignore[arg-type]
        except TypeError:
            images = list(images)
            total = len(images)
    done = 0

    workers = min(8, max(1, total // 10))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(check_one, img.path, opts): img for img in images
        }
        for fut in as_completed(futures):
            done += 1
            img = futures[fut]
            if progress_cb and done % 20 == 0:
                progress_cb(done, total, img.path.name)
            try:
                kinds, metrics = fut.result()
                if kinds:
                    issues.append(QualityIssue(image=img, kinds=kinds, metrics=metrics))
            except Exception:
                issues.append(QualityIssue(image=img, kinds=["corrupt"], metrics={}))

    if progress_cb:
        progress_cb(total, total, "")
    return issues


# ---------- Annotation-level checks (SampleSet, no I/O) ----------

def check_annotations(
    sample_set: SampleSet,
    progress_cb=None,
) -> list[QualityIssue]:
    """Find annotation anomalies by inspecting the in-memory SampleSet.

    Returns ``QualityIssue`` items with *synthetic* ``ImageInfo`` objects
    (only ``path`` is set) so callers can merge them with pixel-level
    results transparently.

    Check kinds:
      - ``empty_label`` — label file exists but contains no regions.
      - ``zero_area``   — a region's bounding box has 0 area (degenerate).
      - ``oob``         — region bbox extends beyond image dimensions.
    """
    from .unified import SampleSet as _SS  # noqa: F811 — runtime import

    issues: list[QualityIssue] = []
    total = len(sample_set.samples)
    for i, sample in enumerate(sample_set.samples):
        if progress_cb and i % 100 == 0:
            name = Path(sample.image_path).name
            progress_cb(i, total, name)

        kinds: list[str] = []
        metrics: dict[str, float] = {}

        # Empty label file
        if sample.has_label and not sample.regions:
            kinds.append("empty_label")

        # Per-region checks
        zero_count = 0
        oob_count = 0
        for r in sample.regions:
            bb = r.ensure_bbox()
            if bb is None:
                continue
            if bb.area == 0:
                zero_count += 1
            if sample.image_width > 0 and sample.image_height > 0:
                if (bb.x1 < 0 or bb.y1 < 0
                        or bb.x2 > sample.image_width
                        or bb.y2 > sample.image_height):
                    oob_count += 1
        if zero_count:
            kinds.append("zero_area")
            metrics["zero_area_count"] = zero_count
        if oob_count:
            kinds.append("oob")
            metrics["oob_count"] = oob_count

        if kinds:
            # Construct a lightweight ImageInfo for compatibility with
            # the existing QualityIssue / UI pipeline.
            img = ImageInfo(
                path=Path(sample.image_path),
                category=sample.category,
                has_label=sample.has_label,
                label_path=sample.label_path,
            )
            issues.append(QualityIssue(image=img, kinds=kinds, metrics=metrics))

    if progress_cb:
        progress_cb(total, total, "")
    return issues
