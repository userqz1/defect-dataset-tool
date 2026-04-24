"""Write annotations back to disk in their original format.

For each format we round-trip the original file when possible (preserving
unknown fields), but fall back to a clean serialization if no original exists.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from xml.etree import ElementTree as ET

from PIL import Image

from .annotation_formats import detect_format, load_yolo_classes
from .models import Annotation, Shape


def write_annotation(
    annotation: Annotation,
    label_path: Path,
    image_path: Path,
) -> None:
    """Dispatch save by file extension. Creates the file if missing."""
    fmt = detect_format(label_path)
    if fmt == "labelme":
        write_labelme(annotation, label_path, image_path)
    elif fmt == "yolo":
        write_yolo(annotation, label_path, image_path)
    elif fmt == "voc":
        write_voc(annotation, label_path, image_path)
    else:
        raise ValueError(f"unsupported format for {label_path}")


# ── Extension-suffix map ──────────────────────────────────────────────
_FMT_EXT = {"labelme": ".json", "yolo": ".txt", "voc": ".xml"}


def label_path_for_format(image_path: Path, fmt: str) -> Path:
    """Compute the label file path for *image_path* in the given format.

    Places the label in a sibling ``labels/`` directory when one exists
    alongside ``images/``, otherwise next to the image.
    """
    ext = _FMT_EXT.get(fmt, ".json")
    parent = image_path.parent
    # Standard layout: images/ ↔ labels/
    if parent.name == "images":
        lbl_dir = parent.parent / "labels"
    else:
        lbl_dir = parent
    return lbl_dir / (image_path.stem + ext)


def write_annotation_as(
    annotation: Annotation,
    image_path: Path,
    fmt: str,
) -> Path:
    """Write annotation in a specific format, returning the label path.

    Unlike ``write_annotation`` (which detects format from existing
    file extension), this explicitly writes in *fmt* and computes
    the label path accordingly.
    """
    label_path = label_path_for_format(image_path, fmt)
    if fmt == "labelme":
        write_labelme(annotation, label_path, image_path)
    elif fmt == "yolo":
        write_yolo(annotation, label_path, image_path)
    elif fmt == "voc":
        write_voc(annotation, label_path, image_path)
    else:
        raise ValueError(f"unsupported write-back format: {fmt!r}")
    return label_path


# ---------- LabelMe ----------

def write_labelme(annotation: Annotation, label_path: Path, image_path: Path) -> None:
    # 尝试保留原文件未知字段
    base: dict = {}
    if label_path.is_file():
        try:
            base = json.loads(label_path.read_text(encoding="utf-8"))
            if not isinstance(base, dict):
                base = {}
        except (OSError, json.JSONDecodeError):
            base = {}

    iw, ih = _image_size(image_path)
    base["version"] = base.get("version", "5.0.0")
    base["flags"] = base.get("flags", {})
    base["imagePath"] = image_path.name
    base["imageData"] = None
    base["imageWidth"] = iw
    base["imageHeight"] = ih
    base["shapes"] = [
        {
            "label": s.label,
            "points": [[float(x), float(y)] for x, y in s.points],
            "group_id": None,
            "shape_type": s.shape_type,
            "flags": {},
        }
        for s in annotation.shapes
    ]
    label_path.parent.mkdir(parents=True, exist_ok=True)
    label_path.write_text(
        json.dumps(base, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ---------- YOLO ----------

_CLASSES_TXT_LOCK = threading.Lock()


def write_yolo(annotation: Annotation, label_path: Path, image_path: Path) -> None:
    iw, ih = _image_size(image_path)
    if iw <= 0 or ih <= 0:
        raise ValueError("cannot read image dimensions")

    def _build_lines(name_to_idx: dict[str, int]) -> tuple[list[str], list[str]]:
        lines: list[str] = []
        new_classes: list[str] = []
        for s in annotation.shapes:
            if not s.points or len(s.points) < 2:
                continue
            if s.label not in name_to_idx:
                name_to_idx[s.label] = len(name_to_idx)
                new_classes.append(s.label)
            idx = name_to_idx[s.label]
            xs = [p[0] for p in s.points]
            ys = [p[1] for p in s.points]
            x1, x2 = min(xs), max(xs)
            y1, y2 = min(ys), max(ys)
            cx = (x1 + x2) / 2 / iw
            cy = (y1 + y2) / 2 / ih
            bw = (x2 - x1) / iw
            bh = (y2 - y1) / ih
            if bw <= 0 or bh <= 0:
                continue
            lines.append(f"{idx} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}")
        return lines, new_classes

    label_path.parent.mkdir(parents=True, exist_ok=True)

    # Fast path: no new classes → no lock needed, indices are stable.
    classes = load_yolo_classes(label_path.parent)
    name_to_idx = {n: i for i, n in enumerate(classes)}
    lines, new_classes = _build_lines(dict(name_to_idx))

    if not new_classes:
        label_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        return

    # Slow path: new classes discovered. Acquire lock, re-read classes.txt
    # to get indices consistent with what other threads may have appended,
    # then write both files atomically under the lock.
    with _CLASSES_TXT_LOCK:
        disk_classes = load_yolo_classes(label_path.parent)
        name_to_idx = {n: i for i, n in enumerate(disk_classes)}
        lines, new_classes = _build_lines(dict(name_to_idx))
        label_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        if new_classes:
            for lbl in new_classes:
                if lbl not in disk_classes:
                    disk_classes.append(lbl)
            classes_path = label_path.parent / "classes.txt"
            classes_path.write_text("\n".join(disk_classes) + "\n", encoding="utf-8")


# ---------- Pascal VOC ----------

def write_voc(annotation: Annotation, label_path: Path, image_path: Path) -> None:
    iw, ih = _image_size(image_path)
    root = ET.Element("annotation")
    ET.SubElement(root, "folder").text = image_path.parent.name
    ET.SubElement(root, "filename").text = image_path.name
    size = ET.SubElement(root, "size")
    ET.SubElement(size, "width").text = str(iw)
    ET.SubElement(size, "height").text = str(ih)
    ET.SubElement(size, "depth").text = "3"
    for s in annotation.shapes:
        if not s.points or len(s.points) < 2:
            continue
        xs = [p[0] for p in s.points]
        ys = [p[1] for p in s.points]
        x1, x2 = min(xs), max(xs)
        y1, y2 = min(ys), max(ys)
        if x2 - x1 <= 0 or y2 - y1 <= 0:
            continue
        obj = ET.SubElement(root, "object")
        ET.SubElement(obj, "name").text = s.label
        ET.SubElement(obj, "difficult").text = "0"
        bnd = ET.SubElement(obj, "bndbox")
        ET.SubElement(bnd, "xmin").text = f"{int(x1)}"
        ET.SubElement(bnd, "ymin").text = f"{int(y1)}"
        ET.SubElement(bnd, "xmax").text = f"{int(x2)}"
        ET.SubElement(bnd, "ymax").text = f"{int(y2)}"
    label_path.parent.mkdir(parents=True, exist_ok=True)
    label_path.write_bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True))


# ---------- Caption sidecar ----------

def caption_sidecar_path(image_path: Path) -> Path:
    """Return the sidecar caption file path for *image_path*.

    Convention: ``<stem>.txt`` next to the image — the same convention
    used by Stable Diffusion trainers, BLIP, and most VLM caption tools.
    When the image lives in an ``images/`` directory, the caption goes
    next to the image (NOT in ``labels/``), since it's metadata, not
    an annotation file.
    """
    return image_path.with_suffix(".txt")


def write_caption(image_path: Path, caption: str) -> Path:
    """Write *caption* to a sidecar ``.txt`` file next to *image_path*.

    Creates or overwrites.  Returns the written path.
    """
    p = caption_sidecar_path(image_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(caption, encoding="utf-8")
    return p


def read_caption(image_path: Path) -> str:
    """Read caption from the sidecar ``.txt`` file, or return ``""``."""
    p = caption_sidecar_path(image_path)
    if p.is_file():
        try:
            return p.read_text(encoding="utf-8").strip()
        except OSError:
            return ""
    return ""


# ---------- Conversation sidecar ----------

def conversation_sidecar_path(image_path: Path) -> Path:
    """Return ``<stem>.conversations.json`` next to *image_path*."""
    return image_path.with_suffix(".conversations.json")


def write_conversations(
    image_path: Path, conversations: list[dict[str, str]],
) -> Path:
    """Persist multi-turn conversations to a JSON sidecar.

    Each entry: ``{"from": "human"|"gpt", "value": "..."}``.
    Creates or overwrites.  Returns the written path.
    """
    p = conversation_sidecar_path(image_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(conversations, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return p


def read_conversations(image_path: Path) -> list[dict[str, str]]:
    """Read conversations from the sidecar JSON file, or return ``[]``."""
    p = conversation_sidecar_path(image_path)
    if p.is_file():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return [
                    d for d in data
                    if isinstance(d, dict) and "from" in d and "value" in d
                ]
        except (OSError, json.JSONDecodeError):
            pass
    return []


# ---------- Grounding sidecar ----------

def grounding_sidecar_path(image_path: Path) -> Path:
    """Return ``<stem>.grounding.json`` next to *image_path*."""
    return image_path.with_suffix(".grounding.json")


def write_grounding(
    image_path: Path,
    grounding: list[dict],
) -> Path:
    """Persist region-level text data (grounding) to a JSON sidecar.

    Each entry: ``{"label": "...", "bbox": [x1,y1,x2,y2], "text": "..."}``.
    Returns the written path.
    """
    p = grounding_sidecar_path(image_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(grounding, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return p


def read_grounding(image_path: Path) -> list[dict]:
    """Read grounding data from sidecar, or return ``[]``."""
    p = grounding_sidecar_path(image_path)
    if p.is_file():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return [
                    d for d in data
                    if isinstance(d, dict) and ("label" in d or "text" in d)
                ]
        except (OSError, json.JSONDecodeError):
            pass
    return []


# ---------- 内部 ----------

def _image_size(image_path: Path) -> tuple[int, int]:
    try:
        with Image.open(image_path) as im:
            return im.size
    except Exception:
        return 0, 0
