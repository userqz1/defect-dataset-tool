"""Export to Pascal VOC format (per-image XML + ImageSets/Main split lists)."""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

from PIL import Image

from ..annotation_formats import load_yolo_classes, parse_annotation
from ..splitter import SplitResult


@dataclass
class VocExportOptions:
    out_dir: Path
    copy_images: bool = True


@dataclass
class ExportReport:
    written_images: int = 0
    written_xml: int = 0
    skipped: list[tuple[Path, str]] = field(default_factory=list)


def _make_xml(filename: str, iw: int, ih: int, objects: list[tuple[str, float, float, float, float]]) -> bytes:
    root = ET.Element("annotation")
    ET.SubElement(root, "folder").text = "JPEGImages"
    ET.SubElement(root, "filename").text = filename
    size = ET.SubElement(root, "size")
    ET.SubElement(size, "width").text = str(iw)
    ET.SubElement(size, "height").text = str(ih)
    ET.SubElement(size, "depth").text = "3"
    for label, x1, y1, x2, y2 in objects:
        obj = ET.SubElement(root, "object")
        ET.SubElement(obj, "name").text = label
        ET.SubElement(obj, "difficult").text = "0"
        bnd = ET.SubElement(obj, "bndbox")
        ET.SubElement(bnd, "xmin").text = f"{int(x1)}"
        ET.SubElement(bnd, "ymin").text = f"{int(y1)}"
        ET.SubElement(bnd, "xmax").text = f"{int(x2)}"
        ET.SubElement(bnd, "ymax").text = f"{int(y2)}"
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def export_voc(
    split: SplitResult,
    opts: VocExportOptions,
    progress_cb=None,
) -> ExportReport:
    out = Path(opts.out_dir)
    img_dir = out / "JPEGImages"
    xml_dir = out / "Annotations"
    sets_dir = out / "ImageSets" / "Main"
    for d in (img_dir, xml_dir, sets_dir):
        d.mkdir(parents=True, exist_ok=True)
    report = ExportReport()

    splits = {"train": split.train, "val": split.val, "test": split.test}
    total = sum(len(v) for v in splits.values())
    done = 0
    for name, imgs in splits.items():
        if not imgs:
            continue
        stems: list[str] = []
        for img in imgs:
            done += 1
            if progress_cb:
                progress_cb(done, total, img.path.name)
            try:
                with Image.open(img.path) as pim:
                    iw, ih = pim.size
                if opts.copy_images:
                    shutil.copy2(img.path, img_dir / img.path.name)
                    report.written_images += 1
                objects = []
                if img.has_label and img.label_path is not None:
                    classes = (
                        load_yolo_classes(img.label_path.parent)
                        if img.label_path.suffix.lower() == ".txt"
                        else None
                    )
                    r = parse_annotation(img.label_path, img.path, yolo_class_names=classes)
                    if r.ok and r.annotation:
                        for s in r.annotation.shapes:
                            xs = [p[0] for p in s.points]
                            ys = [p[1] for p in s.points]
                            x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
                            if x2 - x1 <= 0 or y2 - y1 <= 0:
                                continue
                            objects.append((s.label, x1, y1, x2, y2))
                xml_bytes = _make_xml(img.path.name, iw, ih, objects)
                (xml_dir / (img.path.stem + ".xml")).write_bytes(xml_bytes)
                report.written_xml += 1
                stems.append(img.path.stem)
            except Exception as e:  # noqa: BLE001
                report.skipped.append((img.path, str(e)))
        (sets_dir / f"{name}.txt").write_text(
            "\n".join(stems) + "\n", encoding="utf-8"
        )

    if progress_cb:
        progress_cb(total, total, "")
    return report
