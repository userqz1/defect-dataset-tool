"""Format importers — read any supported annotation format into Sample.

Every reader returns ``Sample`` objects with **pixel-space** coordinates.
The caller never has to care which format the data was stored in.

Supported readers:
  - LabelMe JSON      (per-image, ``*.json`` with ``shapes``)
  - YOLO              (``*.txt``, one bbox per line)
  - Pascal VOC        (``*.xml``)
  - COCO              (dataset-level ``*.json`` with ``images+annotations+categories``)
  - Classification    (no label file — category from directory name)

Public API:
  ``load_sample(image_info, format_hint, **kw) -> Sample``
  ``load_samples(dataset, format_hint, **kw) -> SampleSet``

Pure Python — no PyQt.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from .models import Dataset, ImageInfo
from .unified import BBox, Region, Sample, SampleSet

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────

def load_sample(
    image_info: ImageInfo,
    format_hint: str = "",
    *,
    yolo_class_names: list[str] | None = None,
    coco_index: _CocoSampleIndex | None = None,
    _prefetched_labelme: Any | None = None,
) -> Sample:
    """Convert one ``ImageInfo`` + its label file into a ``Sample``.

    ``format_hint``: ``"labelme"`` / ``"yolo"`` / ``"voc"`` / ``"coco"`` / ``""``.
    Empty string → auto-detect from file extension.

    Image size is populated from the annotation when possible (LabelMe's
    ``imageWidth/imageHeight``, VOC's ``<size>``, COCO's ``images[].width/height``)
    and only falls back to ``PIL.Image.open`` when the annotation carries
    no size info (YOLO, classification-only, malformed annotations).
    """
    img = image_info
    # Defer the image open — readers below try to populate size from the
    # annotation first; only fall back to PIL if the annotation was silent.
    sample = Sample(
        image_path=img.path,
        image_width=0,
        image_height=0,
        category=img.category,
        has_label=img.has_label,
        label_path=img.label_path,
    )

    if not img.has_label or img.label_path is None:
        # Classification-only: label = category. No annotation file to
        # read size from, so we must open the image.
        if img.category:
            sample.image_labels = [img.category]
        sample.image_width, sample.image_height = _image_size(img.path)
        return sample

    fmt = format_hint or _detect(img.label_path)
    sample.source_format = fmt

    try:
        if fmt == "labelme":
            _read_labelme(sample, img.label_path, _prefetched_labelme)
        elif fmt == "yolo":
            # YOLO bboxes are normalized — we need real image size before
            # _read_yolo runs, and the .txt itself carries none.
            if sample.image_width <= 0 or sample.image_height <= 0:
                sample.image_width, sample.image_height = _image_size(img.path)
            _read_yolo(sample, img.label_path, yolo_class_names)
        elif fmt == "voc":
            _read_voc(sample, img.label_path)
        elif fmt == "coco":
            _read_coco_sample(sample, coco_index)
        else:
            logger.warning("unknown format %r for %s", fmt, img.label_path)
    except Exception:
        logger.debug("parse failed for %s", img.label_path, exc_info=True)

    # Fallback: annotation didn't carry size (e.g., old LabelMe without
    # imageWidth/imageHeight, VOC without <size>, COCO image entry missing
    # width/height). Open the image as a last resort.
    if sample.image_width <= 0 or sample.image_height <= 0:
        sample.image_width, sample.image_height = _image_size(img.path)

    # For image-level tasks: derive image_labels from category if empty
    if not sample.image_labels and img.category:
        sample.image_labels = [img.category]

    return sample


def load_samples(
    dataset: Dataset,
    format_hint: str = "",
    *,
    progress_cb=None,
) -> SampleSet:
    """Load every image in *dataset* into unified ``SampleSet``.

    ``format_hint`` applies uniformly; leave empty to auto-detect per file.
    When ``dataset.layout == "coco"`` the hint is forced to ``"coco"``
    because scan_dataset already resolved every label_path to the single
    dataset-level JSON — any other hint would misparse it.
    """
    # Dataset layout wins over the caller hint. Projects clamp
    # annotation_format to WRITEBACK_FORMATS (labelme/yolo/voc), so a
    # COCO dataset would otherwise be parsed as LabelMe and yield zero
    # shapes.
    if dataset.layout == "coco":
        format_hint = "coco"
    # When no explicit hint is given, infer one from the scanned data.
    # This is the only way the scan path can safely skip per-file
    # auto-detect — callers (session controller) no longer pass the
    # project's annotation_format because that defaults to "labelme"
    # on first-open and would misparse YOLO/VOC datasets.
    if not format_hint:
        format_hint = _infer_format_from_dataset(dataset)

    all_images: list[ImageInfo] = []
    for cat in dataset.categories:
        all_images.extend(cat.images)
    total = len(all_images)

    # Pre-load YOLO class names and COCO indices once per label directory.
    yolo_cache: dict[Path, list[str]] = {}
    coco_cache: dict[Path, _CocoSampleIndex | None] = {}
    # Cache per-path JSON detection + parsed data so each JSON file is
    # read AT MOST ONCE — previously a LabelMe-or-COCO .json was read
    # twice (once to detect, once to parse) and for COCO the same
    # dataset-level JSON was re-detected per-image (N reads of the same
    # file).  Only populated on the auto-detect path; skipped entirely
    # when format_hint is supplied.
    json_detect_cache: dict[Path, tuple[str, Any | None]] = {}

    samples: list[Sample] = []
    for i, img in enumerate(all_images):
        if progress_cb:
            progress_cb(i, total, img.path.name)

        # Resolve format — explicit hint beats per-file detection.
        prefetched_lm: Any | None = None
        if format_hint:
            fmt = format_hint
        elif img.label_path is None:
            fmt = ""
        elif img.label_path.suffix.lower() == ".json":
            entry = json_detect_cache.get(img.label_path)
            if entry is None:
                entry = _detect_json_with_data(img.label_path)
                json_detect_cache[img.label_path] = entry
            fmt, data = entry
            if fmt == "labelme":
                # Reuse the parsed dict in _read_labelme.
                prefetched_lm = data
        else:
            fmt = _detect(img.label_path)

        yolo_names = None
        coco_idx = None

        if fmt == "yolo" and img.label_path:
            lbl_dir = img.label_path.parent
            if lbl_dir not in yolo_cache:
                yolo_cache[lbl_dir] = _load_yolo_classes(lbl_dir)
            yolo_names = yolo_cache[lbl_dir]
        elif fmt == "coco" and img.label_path:
            if img.label_path not in coco_cache:
                # If detection already parsed this JSON, hand it over
                # instead of reading the (potentially huge) file again.
                pre = json_detect_cache.get(img.label_path)
                pre_data = pre[1] if pre else None
                coco_cache[img.label_path] = _build_coco_index(
                    img.label_path, data=pre_data)
            coco_idx = coco_cache[img.label_path]

        samples.append(load_sample(
            img, fmt,
            yolo_class_names=yolo_names,
            coco_index=coco_idx,
            _prefetched_labelme=prefetched_lm,
        ))

    if progress_cb:
        progress_cb(total, total, "")

    return SampleSet(samples=samples)


def load_samples_from_split(
    split: "SplitResult",
    format_hint: str = "",
    *,
    progress_cb=None,
) -> SampleSet:
    """Build a ``SampleSet`` from a ``SplitResult`` (with split labels).

    This is the bridge that lets old ``core.exporter`` writers delegate
    to ``format_out``: the caller already has a SplitResult but needs a
    SampleSet to feed the unified writers.

    Each image is loaded via ``load_sample`` (same parsing as
    ``load_samples``), then tagged with its split name.
    """
    from .splitter import SplitResult  # noqa: F811 – runtime import

    buckets = [("train", split.train), ("val", split.val),
               ("test", split.test)]
    all_images = [(name, img) for name, imgs in buckets for img in imgs]
    total = len(all_images)

    yolo_cache: dict[Path, list[str]] = {}
    coco_cache: dict[Path, _CocoSampleIndex | None] = {}
    json_detect_cache: dict[Path, tuple[str, Any | None]] = {}

    samples: list[Sample] = []
    for i, (split_name, img) in enumerate(all_images):
        if progress_cb:
            progress_cb(i, total, img.path.name)

        prefetched_lm: Any | None = None
        if format_hint:
            fmt = format_hint
        elif img.label_path is None:
            fmt = ""
        elif img.label_path.suffix.lower() == ".json":
            entry = json_detect_cache.get(img.label_path)
            if entry is None:
                entry = _detect_json_with_data(img.label_path)
                json_detect_cache[img.label_path] = entry
            fmt, data = entry
            if fmt == "labelme":
                prefetched_lm = data
        else:
            fmt = _detect(img.label_path)

        yolo_names = None
        coco_idx = None

        if fmt == "yolo" and img.label_path:
            lbl_dir = img.label_path.parent
            if lbl_dir not in yolo_cache:
                yolo_cache[lbl_dir] = _load_yolo_classes(lbl_dir)
            yolo_names = yolo_cache[lbl_dir]
        elif fmt == "coco" and img.label_path:
            if img.label_path not in coco_cache:
                pre = json_detect_cache.get(img.label_path)
                pre_data = pre[1] if pre else None
                coco_cache[img.label_path] = _build_coco_index(
                    img.label_path, data=pre_data)
            coco_idx = coco_cache[img.label_path]

        sample = load_sample(
            img, fmt,
            yolo_class_names=yolo_names,
            coco_index=coco_idx,
            _prefetched_labelme=prefetched_lm,
        )
        sample.split = split_name
        samples.append(sample)

    if progress_cb:
        progress_cb(total, total, "")

    return SampleSet(samples=samples)


# ──────────────────────────────────────────────────────────────────────
# Format detection
# ──────────────────────────────────────────────────────────────────────

def _detect(label_path: Path) -> str:
    ext = label_path.suffix.lower()
    if ext == ".txt":
        return "yolo"
    if ext == ".xml":
        return "voc"
    if ext == ".json":
        return _detect_json(label_path)
    return ""


def _infer_format_from_dataset(dataset: Dataset) -> str:
    """Peek at label suffixes to decide a uniform format for the dataset.

    Returns one of ``"yolo" / "voc" / "labelme" / "coco" / ""``.  Empty
    string means "don't trust any single format — fall back to per-file
    auto-detect" (the legacy path, now cheap because of the json-detect
    cache in ``load_samples``).

    Rules:
      - Mixed suffixes (e.g. both .json and .txt) → ``""``.
      - All ``.txt`` → ``"yolo"``.
      - All ``.xml`` → ``"voc"``.
      - All ``.json`` → peek up to 3 files; if they all look like
        LabelMe or all like COCO, return that.  Otherwise ``""``.

    Notes:
      - ``.json`` is ambiguous (LabelMe vs COCO) — we can't blindly
        return "labelme" here.  scan_dataset already tags COCO datasets
        via ``dataset.layout == "coco"`` (handled by the caller), but
        an edge case of COCO files at standard/flat layout is still
        possible and we should not misparse them.
      - We cap the peek at 3 files: enough to be confident without
        taking the cost this helper is meant to save.
    """
    suffixes: set[str] = set()
    json_samples: list[Path] = []
    for cat in dataset.categories:
        for img in cat.images:
            lp = img.label_path
            if lp is None:
                continue
            sfx = lp.suffix.lower()
            suffixes.add(sfx)
            if sfx == ".json" and len(json_samples) < 3:
                json_samples.append(lp)
            if len(suffixes) > 1:
                return ""  # mixed — auto-detect per file

    if not suffixes:
        return ""
    if suffixes == {".txt"}:
        return "yolo"
    if suffixes == {".xml"}:
        return "voc"
    if suffixes == {".json"} and json_samples:
        detected = {_detect_json(p) for p in json_samples}
        if len(detected) == 1:
            return detected.pop()
    return ""


def _detect_json(json_path: Path) -> str:
    """Distinguish COCO (dataset-level) from LabelMe (per-image)."""
    return _detect_json_with_data(json_path)[0]


def _detect_json_with_data(
    json_path: Path,
) -> tuple[str, Any | None]:
    """Detect and return ``(format, parsed_data)``.

    Callers that will parse the file anyway (LabelMe per-image,
    COCO index build) can reuse ``parsed_data`` instead of reading
    the file a second time.  Returns ``("labelme", None)`` on read/
    parse failure — keeps the fallback identical to the legacy
    behavior.
    """
    try:
        raw = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ("labelme", None)
    if isinstance(raw, dict) and all(
        k in raw for k in ("images", "annotations", "categories")
    ):
        return ("coco", raw)
    return ("labelme", raw)


# ──────────────────────────────────────────────────────────────────────
# LabelMe reader
# ──────────────────────────────────────────────────────────────────────

def _read_labelme(sample: Sample, json_path: Path,
                  data: Any | None = None) -> None:
    if data is None:
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
    if not isinstance(data, dict):
        return

    # LabelMe canonically writes imageWidth/imageHeight — use them so we
    # don't have to open the image.  Falls back to PIL at the call site
    # when the fields are absent or malformed.
    iw = data.get("imageWidth")
    ih = data.get("imageHeight")
    try:
        if isinstance(iw, (int, float)) and iw > 0:
            sample.image_width = int(iw)
        if isinstance(ih, (int, float)) and ih > 0:
            sample.image_height = int(ih)
    except (TypeError, ValueError):
        pass

    for raw in data.get("shapes", []):
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label", "")).strip()
        if not label:
            continue
        shape_type = str(raw.get("shape_type", "polygon"))
        raw_pts = raw.get("points", [])
        pts = _parse_points(raw_pts)
        if not pts:
            continue

        region = Region(label=label, shape_type=shape_type)
        if shape_type == "rectangle" and len(pts) >= 2:
            region.bbox = BBox.from_points(pts)
        elif shape_type in ("polygon", "linestrip"):
            region.polygon = pts
            region.bbox = BBox.from_points(pts)
        elif shape_type == "point" and len(pts) >= 1:
            region.keypoints = [(pts[0][0], pts[0][1], 2)]
            region.bbox = BBox(pts[0][0], pts[0][1], pts[0][0], pts[0][1])
        elif shape_type == "circle" and len(pts) >= 2:
            # center + edge point → approximate bbox
            cx, cy = pts[0]
            ex, ey = pts[1]
            r = ((ex - cx) ** 2 + (ey - cy) ** 2) ** 0.5
            region.bbox = BBox(cx - r, cy - r, cx + r, cy + r)
        else:
            region.bbox = BBox.from_points(pts)

        sample.regions.append(region)


# ──────────────────────────────────────────────────────────────────────
# YOLO reader
# ──────────────────────────────────────────────────────────────────────

def _read_yolo(sample: Sample, txt_path: Path,
               class_names: list[str] | None) -> None:
    try:
        text = txt_path.read_text(encoding="utf-8")
    except OSError:
        return

    iw, ih = sample.image_width, sample.image_height
    if iw <= 0 or ih <= 0:
        # Can't denormalize — skip
        return

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        try:
            cls_id = int(float(parts[0]))
            cx, cy, w, h = (float(x) for x in parts[1:5])
        except ValueError:
            continue

        if class_names and 0 <= cls_id < len(class_names):
            label = class_names[cls_id]
        else:
            label = f"#{cls_id}" if class_names else str(cls_id)

        bbox = BBox.from_yolo(cx, cy, w, h, iw, ih)
        conf = float(parts[5]) if len(parts) > 5 else 1.0
        sample.regions.append(Region(
            label=label, bbox=bbox, shape_type="rectangle",
            confidence=conf,
        ))


def _load_yolo_classes(label_dir: Path) -> list[str]:
    """Read classes.txt / classes.names from label_dir or parent."""
    for d in (label_dir, label_dir.parent):
        for name in ("classes.txt", "classes.names", "labels.txt"):
            p = d / name
            if p.is_file():
                try:
                    return [
                        ln.strip()
                        for ln in p.read_text(encoding="utf-8").splitlines()
                        if ln.strip()
                    ]
                except OSError:
                    pass
    return []


# ──────────────────────────────────────────────────────────────────────
# VOC reader
# ──────────────────────────────────────────────────────────────────────

def _read_voc(sample: Sample, xml_path: Path) -> None:
    try:
        tree = ET.parse(xml_path)
    except (OSError, ET.ParseError):
        return
    root = tree.getroot()

    # VOC canonically carries ``<size><width>..<height>..</size>``. Pull
    # size from there so we don't have to open the image; call site
    # still falls back to PIL if these fields are absent.
    size_el = root.find("size")
    if size_el is not None:
        try:
            w = int(float(size_el.findtext("width", "0")))
            h = int(float(size_el.findtext("height", "0")))
            if w > 0:
                sample.image_width = w
            if h > 0:
                sample.image_height = h
        except (TypeError, ValueError):
            pass

    for obj in root.findall("object"):
        name_el = obj.find("name")
        bnd = obj.find("bndbox")
        if name_el is None or bnd is None:
            continue
        label = (name_el.text or "").strip()
        if not label:
            continue
        try:
            x1 = float(bnd.findtext("xmin", "0"))
            y1 = float(bnd.findtext("ymin", "0"))
            x2 = float(bnd.findtext("xmax", "0"))
            y2 = float(bnd.findtext("ymax", "0"))
        except ValueError:
            continue
        diff = obj.findtext("difficult", "0") == "1"
        trunc = obj.findtext("truncated", "0") == "1"
        sample.regions.append(Region(
            label=label,
            bbox=BBox(x1, y1, x2, y2),
            shape_type="rectangle",
            difficult=diff,
            truncated=trunc,
        ))


# ──────────────────────────────────────────────────────────────────────
# COCO reader
# ──────────────────────────────────────────────────────────────────────

class _CocoSampleIndex:
    """Pre-parsed COCO JSON keyed by image filename stem for O(1) lookup."""
    __slots__ = ("by_stem", "size_by_stem", "categories")

    def __init__(self, by_stem: dict[str, list[dict]],
                 size_by_stem: dict[str, tuple[int, int]],
                 categories: dict[int, str]) -> None:
        self.by_stem = by_stem
        self.size_by_stem = size_by_stem
        self.categories = categories


def _build_coco_index(
    json_path: Path,
    data: Any | None = None,
) -> _CocoSampleIndex | None:
    """Build (or rebuild) a COCO lookup index.

    ``data`` lets callers pass a pre-parsed dict (e.g. detection already
    read the file) so we don't re-read the JSON.  ``None`` → read
    ``json_path`` from disk.
    """
    if data is None:
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
    if not isinstance(data, dict):
        return None
    if not all(k in data for k in ("images", "annotations", "categories")):
        return None

    cats: dict[int, str] = {}
    for c in data.get("categories", []):
        if isinstance(c, dict) and "id" in c and "name" in c:
            cats[int(c["id"])] = str(c["name"])

    img_by_id: dict[int, str] = {}
    size_by_stem: dict[str, tuple[int, int]] = {}
    for img in data.get("images", []):
        if not isinstance(img, dict) or "id" not in img or "file_name" not in img:
            continue
        stem = Path(str(img["file_name"])).stem
        img_by_id[int(img["id"])] = stem
        # COCO ``images[].width/height`` is canonical — use it so we
        # don't open 1000 images to ask PIL for something we already know.
        w = img.get("width")
        h = img.get("height")
        if (isinstance(w, (int, float)) and isinstance(h, (int, float))
                and w > 0 and h > 0):
            size_by_stem[stem] = (int(w), int(h))

    by_stem: dict[str, list[dict]] = {}
    for ann in data.get("annotations", []):
        if not isinstance(ann, dict):
            continue
        iid = ann.get("image_id")
        if iid is None:
            continue
        stem = img_by_id.get(int(iid))
        if stem is None:
            continue
        by_stem.setdefault(stem, []).append(ann)

    return _CocoSampleIndex(
        by_stem=by_stem, size_by_stem=size_by_stem, categories=cats)


def _read_coco_sample(sample: Sample,
                      index: _CocoSampleIndex | None) -> None:
    if index is None:
        return
    stem = sample.image_path.stem
    size = index.size_by_stem.get(stem)
    if size is not None:
        sample.image_width, sample.image_height = size
    anns = index.by_stem.get(stem, [])
    for ann in anns:
        cid = ann.get("category_id")
        label = index.categories.get(int(cid), str(cid)) if cid is not None else ""
        if not label:
            continue

        bbox_raw = ann.get("bbox")  # [x, y, w, h]
        bbox = None
        if isinstance(bbox_raw, list) and len(bbox_raw) >= 4:
            try:
                x, y, w, h = (float(v) for v in bbox_raw[:4])
                if w > 0 and h > 0:
                    bbox = BBox.from_xywh(x, y, w, h)
            except (TypeError, ValueError):
                pass

        seg = ann.get("segmentation")
        polygon = None
        if isinstance(seg, list) and seg and isinstance(seg[0], list):
            flat = seg[0]
            if len(flat) >= 6:
                polygon = [
                    (float(flat[i]), float(flat[i + 1]))
                    for i in range(0, len(flat) - 1, 2)
                ]

        kpts_raw = ann.get("keypoints")
        keypoints = None
        if isinstance(kpts_raw, list) and len(kpts_raw) >= 3:
            keypoints = [
                (float(kpts_raw[i]), float(kpts_raw[i + 1]),
                 int(kpts_raw[i + 2]))
                for i in range(0, len(kpts_raw) - 2, 3)
            ]

        region = Region(
            label=label,
            bbox=bbox,
            polygon=polygon,
            keypoints=keypoints,
            shape_type="polygon" if polygon else "rectangle",
            iscrowd=bool(ann.get("iscrowd", 0)),
        )
        if bbox is None:
            region.ensure_bbox()
        sample.regions.append(region)


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _image_size(path: Path) -> tuple[int, int]:
    """Read (width, height) via PIL — returns (0, 0) on failure."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.size
    except Exception:
        return (0, 0)


def _parse_points(raw: list) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for p in raw:
        if isinstance(p, (list, tuple)) and len(p) >= 2:
            try:
                pts.append((float(p[0]), float(p[1])))
            except (TypeError, ValueError):
                pass
    return pts


# ──────────────────────────────────────────────────────────────────────
# VLM JSONL reader (LLaVA / ShareGPT / Swift conversation data)
# ──────────────────────────────────────────────────────────────────────

def load_vlm_jsonl(
    jsonl_path: Path,
    image_root: Path | None = None,
    *,
    progress_cb=None,
) -> SampleSet:
    """Read a VLM conversation JSONL (or JSON array) into a SampleSet.

    Supported schemas (auto-detected per record):
      - **LLaVA**: ``{"id", "image", "conversations": [{"from","value"}]}``
      - **ShareGPT**: ``{"conversations": [...], "images": [...]}``
      - **Swift**: ``{"query", "response", "images": [...]}``
      - **Caption-only**: ``{"image", "caption"}``

    ``image_root`` resolves relative ``image`` paths. If ``None``, paths
    in the data must be absolute or the image_path will be set as-is.
    """
    jsonl_path = Path(jsonl_path)
    root = Path(image_root) if image_root else jsonl_path.parent

    records: list[dict] = []
    try:
        text = jsonl_path.read_text(encoding="utf-8").strip()
        if text.startswith("["):
            # JSON array (ShareGPT style)
            records = json.loads(text)
        else:
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("failed to read VLM JSONL %s: %s", jsonl_path, e)
        return SampleSet()

    total = len(records)
    samples: list[Sample] = []
    for i, rec in enumerate(records):
        if progress_cb:
            progress_cb(i, total, f"record {i}")
        if not isinstance(rec, dict):
            continue
        sample = _parse_vlm_record(rec, root)
        if sample is not None:
            samples.append(sample)

    if progress_cb:
        progress_cb(total, total, "")
    return SampleSet(samples=samples)


def _parse_vlm_record(rec: dict, root: Path) -> Sample | None:
    """Parse one VLM record into a Sample. Returns None on failure."""
    # Resolve image path
    image_str = rec.get("image") or ""
    images_list = rec.get("images") or []
    if not image_str and images_list:
        image_str = str(images_list[0])
    if not image_str:
        return None

    img_path = Path(image_str)
    if not img_path.is_absolute():
        img_path = root / img_path

    w, h = _image_size(img_path) if img_path.exists() else (0, 0)
    sample = Sample(
        image_path=img_path,
        image_width=w,
        image_height=h,
        source_format="vlm_jsonl",
    )

    # Caption-only
    caption = rec.get("caption") or rec.get("text") or ""
    if isinstance(caption, str) and caption.strip():
        sample.caption = caption.strip()

    # Conversations — LLaVA / ShareGPT format
    convos = rec.get("conversations") or []
    if isinstance(convos, list) and convos:
        parsed = []
        for turn in convos:
            if not isinstance(turn, dict):
                continue
            role = str(turn.get("from", turn.get("role", ""))).strip()
            value = str(turn.get("value", turn.get("content", ""))).strip()
            if role and value:
                parsed.append({"from": role, "value": value})
        if parsed:
            sample.conversations = parsed
            # Extract caption from first GPT response if not set
            if not sample.caption:
                for t in parsed:
                    if t["from"] in ("gpt", "assistant"):
                        sample.caption = t["value"]
                        break

    # Swift format: query + response → conversations
    query = rec.get("query") or ""
    response = rec.get("response") or ""
    if query and response and not sample.conversations:
        sample.conversations = [
            {"from": "human", "value": str(query).strip()},
            {"from": "gpt", "value": str(response).strip()},
        ]
        if not sample.caption:
            sample.caption = str(response).strip()

    # Grounding data
    grounding = rec.get("grounding") or rec.get("objects") or []
    if isinstance(grounding, list):
        parsed_g = []
        for g in grounding:
            if not isinstance(g, dict):
                continue
            entry: dict = {}
            if "label" in g:
                entry["label"] = str(g["label"])
            if "bbox" in g and isinstance(g["bbox"], list):
                entry["bbox"] = [float(v) for v in g["bbox"][:4]]
            if "text" in g:
                entry["text"] = str(g["text"])
            if entry:
                parsed_g.append(entry)
        if parsed_g:
            sample.grounding = parsed_g
            # Also create Regions from grounding bboxes
            for g in parsed_g:
                if "bbox" in g and len(g["bbox"]) >= 4:
                    label = g.get("label", "object")
                    x1, y1, x2, y2 = g["bbox"][:4]
                    sample.regions.append(Region(
                        label=label,
                        bbox=BBox(x1, y1, x2, y2),
                        shape_type="rectangle",
                        text=g.get("text", ""),
                    ))

    sample.has_label = bool(
        sample.caption or sample.conversations or sample.regions)
    return sample
