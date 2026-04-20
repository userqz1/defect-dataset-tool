"""Multi-format annotation parsers. Pure Python — no PyQt.

Supports:
    - LabelMe   (*.json, dict with "shapes")
    - YOLO      (*.txt, one box per line, normalized cx cy w h)
    - Pascal VOC (*.xml)
    - COCO      (single *.json with "annotations" list — handled by parse_coco)

All parsers are tolerant: malformed inputs return ParseResult(None, error_str)
rather than raising. Per-image dispatch is `parse_annotation(label_path, image_path)`,
which picks the parser from the file extension.

YOLO bbox parsing needs the image's pixel dimensions to denormalize; we lazily
open the image with PIL only when needed and cache the result via the caller.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from .annotation import ParseResult, parse_labelme
from .models import Annotation, Shape

LABEL_EXTENSIONS = {".json", ".txt", ".xml"}

# YOLO 标签目录里常见的"非标注文件"（类名表 / 配置 / 校验文件等）
YOLO_AUX_FILES = {
    "classes.txt",
    "classes.names",
    "labels.txt",
    "predefined_classes.txt",
    "data.yaml",
    "data.yml",
    ".gitignore",
}


# ---------- 公共调度 ----------

def parse_annotation(
    label_path: Path,
    image_path: Path | None = None,
    yolo_class_names: list[str] | None = None,
) -> ParseResult:
    """Pick a parser by file extension and run it.

    `.json` dispatches to COCO when the file is dataset-level (contains
    images+annotations+categories keys); otherwise to per-image LabelMe.
    The COCO file is cached (by mtime) so thousands of images hitting the
    same JSON pay only one parse cost.
    """
    ext = label_path.suffix.lower()
    if ext == ".json":
        coco = _load_coco_cached(label_path)
        if coco is not None:
            if image_path is None:
                return ParseResult(None, "COCO annotation requires image_path")
            shapes = coco.by_stem.get(image_path.stem, [])
            return ParseResult(Annotation(image_path=image_path, shapes=list(shapes)))
        # Not COCO — treat as per-image LabelMe
        return parse_labelme(label_path, image_path)
    if ext == ".txt":
        return parse_yolo(label_path, image_path, class_names=yolo_class_names)
    if ext == ".xml":
        return parse_voc(label_path, image_path)
    return ParseResult(None, f"unsupported label format: {ext}")


# Module-global cache: path → (mtime_ns, CocoIndex|None).
#
# Thread-safety (review point #3): count_annotations now uses a
# ThreadPoolExecutor(max_workers=8), so multiple worker threads can race
# on the same cache miss. Without a lock, two threads observing no cache
# entry would both parse the (potentially large) COCO JSON and clobber
# each other's dict write. The Lock is held only for the dict read/write;
# the parse itself runs outside the critical section so concurrent misses
# on *different* JSONs still overlap.
import threading as _threading
_COCO_CACHE: dict[Path, tuple[int, "CocoIndex | None"]] = {}
_COCO_CACHE_MAX = 8
_COCO_CACHE_LOCK = _threading.Lock()
_COCO_CACHE_INFLIGHT: dict[Path, _threading.Event] = {}


def _load_coco_cached(json_path: Path) -> "CocoIndex | None":
    """Parse a COCO JSON once per mtime. Returns None for non-COCO JSONs
    (per-image LabelMe) so callers can fall through.

    Thread-safe: coalesces concurrent misses on the same path via an
    inflight-events map, so a 500MB COCO file is parsed at most once
    per mtime even under 8-way parallel ingest. The waiter-wakeup-miss
    path (cache was evicted while waiters slept) also re-enters the
    ownership race instead of every waiter parsing independently
    (review #7 — with a cache of size 8 and 8 waiters this edge case
    isn't rare when ingesting multiple COCO datasets back-to-back).
    """
    try:
        mtime = json_path.stat().st_mtime_ns
    except OSError:
        return None

    while True:
        is_owner = False
        with _COCO_CACHE_LOCK:
            cached = _COCO_CACHE.get(json_path)
            if cached and cached[0] == mtime:
                return cached[1]
            inflight = _COCO_CACHE_INFLIGHT.get(json_path)
            if inflight is None:
                inflight = _threading.Event()
                _COCO_CACHE_INFLIGHT[json_path] = inflight
                is_owner = True

        if is_owner:
            # Parse outside the lock (I/O + JSON decode can be slow).
            try:
                idx = parse_coco(json_path)
            finally:
                with _COCO_CACHE_LOCK:
                    if len(_COCO_CACHE) >= _COCO_CACHE_MAX:
                        _COCO_CACHE.pop(next(iter(_COCO_CACHE)))
                    _COCO_CACHE[json_path] = (mtime, idx)
                    _COCO_CACHE_INFLIGHT.pop(json_path, None)
                inflight.set()
            return idx

        # Waiter: block until the owner publishes, then consult the cache.
        inflight.wait()
        with _COCO_CACHE_LOCK:
            cached = _COCO_CACHE.get(json_path)
            if cached and cached[0] == mtime:
                return cached[1]
        # Cache miss after wakeup — owner failed or LRU evicted our entry.
        # Loop back and race for ownership instead of every waker parsing
        # the same 500MB JSON in parallel.


def detect_format(label_path: Path) -> str:
    ext = label_path.suffix.lower()
    return {
        ".json": "labelme",
        ".txt": "yolo",
        ".xml": "voc",
    }.get(ext, "unknown")


# ---------- YOLO ----------

def load_yolo_classes(label_dir: Path) -> list[str]:
    """Read classes.txt / classes.names if present in label_dir or its parent."""
    for d in (label_dir, label_dir.parent):
        for name in ("classes.txt", "classes.names", "labels.txt"):
            p = d / name
            if p.is_file():
                try:
                    return [
                        line.strip()
                        for line in p.read_text(encoding="utf-8").splitlines()
                        if line.strip()
                    ]
                except OSError:
                    pass
    return []


def _image_size(image_path: Path | None) -> tuple[int, int] | None:
    if image_path is None or not image_path.is_file():
        return None
    try:
        from PIL import Image
        with Image.open(image_path) as im:
            return im.size  # (w, h)
    except Exception:  # noqa: BLE001
        return None


def parse_yolo(
    label_path: Path,
    image_path: Path | None = None,
    class_names: list[str] | None = None,
) -> ParseResult:
    """Parse a YOLO .txt label file. Each line: 'cls cx cy w h' (normalized 0-1).

    Returns ``ParseResult`` with:

    - ``coord_space="pixel"`` when an ``image_path`` is supplied (and the
      image opens) — points are denormalized to pixel coords.
    - ``coord_space="normalized"`` when no image is supplied or the open
      fails — points stay in the raw 0..1 space. Consumers MUST check
      this field before writing the result back out; treating normalized
      points as pixels silently corrupts data (review #4).
    """
    try:
        text = label_path.read_text(encoding="utf-8")
    except OSError as e:
        return ParseResult(None, f"read failed: {e}")

    size = _image_size(image_path)
    if size is not None:
        iw, ih = size
        coord_space = "pixel"
    else:
        iw, ih = 1, 1
        coord_space = "normalized"

    shapes: list[Shape] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        try:
            cls = int(float(parts[0]))
            cx, cy, w, h = (float(x) for x in parts[1:5])
        except ValueError:
            continue
        # 反归一化到像素坐标（若有 image size）；否则留作归一化。
        cxp, cyp = cx * iw, cy * ih
        wp, hp = w * iw, h * ih
        x1, y1 = cxp - wp / 2, cyp - hp / 2
        x2, y2 = cxp + wp / 2, cyp + hp / 2
        if class_names and 0 <= cls < len(class_names):
            label = class_names[cls]
        else:
            label = str(cls)
        shapes.append(
            Shape(label=label, shape_type="rectangle", points=[(x1, y1), (x2, y2)])
        )

    return ParseResult(
        Annotation(image_path=image_path or label_path.with_suffix(".jpg"), shapes=shapes),
        coord_space=coord_space,
    )


# ---------- Pascal VOC ----------

def parse_voc(label_path: Path, image_path: Path | None = None) -> ParseResult:
    """Parse a Pascal VOC XML annotation file."""
    try:
        tree = ET.parse(label_path)
    except (OSError, ET.ParseError) as e:
        return ParseResult(None, f"invalid xml: {e}")

    root = tree.getroot()
    shapes: list[Shape] = []
    for obj in root.findall("object"):
        name_el = obj.find("name")
        bnd = obj.find("bndbox")
        if name_el is None or bnd is None:
            continue
        try:
            xmin = float(bnd.findtext("xmin", "0"))
            ymin = float(bnd.findtext("ymin", "0"))
            xmax = float(bnd.findtext("xmax", "0"))
            ymax = float(bnd.findtext("ymax", "0"))
        except ValueError:
            continue
        label = (name_el.text or "").strip()
        if not label:
            continue
        shapes.append(
            Shape(
                label=label,
                shape_type="rectangle",
                points=[(xmin, ymin), (xmax, ymax)],
            )
        )

    img_path = image_path
    if img_path is None:
        fn = root.findtext("filename")
        if fn:
            img_path = label_path.parent / fn

    return ParseResult(
        Annotation(image_path=img_path or label_path.with_suffix(".jpg"), shapes=shapes)
    )


# ---------- COCO (centralized) ----------

@dataclass
class CocoIndex:
    """Index of a single COCO annotations.json keyed by image filename stem."""
    by_stem: dict[str, list[Shape]]
    categories: dict[int, str]


def parse_coco(json_path: Path) -> CocoIndex | None:
    """Load a COCO annotations file and group shapes by image filename stem.

    Returns None if the file is not a recognizable COCO file.
    """
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

    images_by_id: dict[int, str] = {}
    for img in data.get("images", []):
        if not isinstance(img, dict):
            continue
        iid = img.get("id")
        fn = img.get("file_name")
        if iid is None or not fn:
            continue
        images_by_id[int(iid)] = Path(str(fn)).stem

    by_stem: dict[str, list[Shape]] = {}
    for ann in data.get("annotations", []):
        if not isinstance(ann, dict):
            continue
        iid = ann.get("image_id")
        cid = ann.get("category_id")
        bbox = ann.get("bbox")
        if iid is None or cid is None or not isinstance(bbox, list) or len(bbox) < 4:
            continue
        stem = images_by_id.get(int(iid))
        if stem is None:
            continue
        try:
            x, y, w, h = (float(v) for v in bbox[:4])
        except (TypeError, ValueError):
            continue
        label = cats.get(int(cid), str(cid))
        by_stem.setdefault(stem, []).append(
            Shape(
                label=label,
                shape_type="rectangle",
                points=[(x, y), (x + w, y + h)],
            )
        )

    return CocoIndex(by_stem=by_stem, categories=cats)
