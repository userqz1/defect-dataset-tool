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
    classes = load_yolo_classes(label_path.parent)
    name_to_idx = {n: i for i, n in enumerate(classes)}

    lines: list[str] = []
    new_classes: list[str] = []  # labels seen in this annotation that aren't in classes.txt
    for s in annotation.shapes:
        if not s.points or len(s.points) < 2:
            continue
        if s.label not in name_to_idx:
            name_to_idx[s.label] = len(name_to_idx)
            classes.append(s.label)
            new_classes.append(s.label)
        idx = name_to_idx[s.label]
        xs = [p[0] for p in s.points]
        ys = [p[1] for p in s.points]
        x1, x2 = min(xs), max(xs)
        y1, y2 = min(ys), max(ys)
        cx = (x1 + x2) / 2 / iw
        cy = (y1 + y2) / 2 / ih
        w = (x2 - x1) / iw
        h = (y2 - y1) / ih
        if w <= 0 or h <= 0:
            continue
        lines.append(f"{idx} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")

    label_path.parent.mkdir(parents=True, exist_ok=True)
    label_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    # classes.txt — review #25:
    # 1) Only rewrite when this annotation introduces a new label (most saves
    #    are pure edits of existing classes → no file touch at all).
    # 2) Under a lock, re-read the file so we don't blow away labels another
    #    thread appended while we were working.
    # 3) Append to the existing list — preserves user's manual ordering /
    #    deletes / comments were they to hand-edit classes.txt between saves.
    if new_classes:
        classes_path = label_path.parent / "classes.txt"
        with _CLASSES_TXT_LOCK:
            disk_classes = load_yolo_classes(label_path.parent)
            for lbl in new_classes:
                if lbl not in disk_classes:
                    disk_classes.append(lbl)
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


# ---------- 内部 ----------

def _image_size(image_path: Path) -> tuple[int, int]:
    try:
        with Image.open(image_path) as im:
            return im.size
    except Exception:
        return 0, 0
