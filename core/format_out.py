"""Format exporters — write SampleSet to any supported target format.

All writers consume ``SampleSet`` (or ``list[Sample]``) directly — no
re-parsing label files from disk. This is the single export entry point.

Supported writers:
  YOLO · COCO · VOC · LabelMe · CSV · JSONL · ImageFolder · MVTec
  LLaVA · ShareGPT · Swift

Public API:
  ``export_samples(sample_set, format, out_dir, opts, progress_cb) -> ExportResult``

Pure Python — no PyQt.
"""
from __future__ import annotations

import csv
import json
import math
import shutil
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from .labels import normalize_label
from .unified import BBox, Region, Sample, SampleSet

# ──────────────────────────────────────────────────────────────────────
# Shared types
# ──────────────────────────────────────────────────────────────────────

@dataclass
class ExportOptions:
    out_dir: Path
    copy_images: bool = True
    # LLM-dataset question prompt (LLaVA / ShareGPT / Swift)
    question: str = "请描述这张图片中的内容。"


@dataclass
class ExportResult:
    written_images: int = 0
    written_labels: int = 0
    skipped: list[tuple[Path, str]] = field(default_factory=list)
    # LLM grounding bookkeeping (LLaVA / ShareGPT / Swift only).
    # ``grounding_fallback_count`` is kept for backward-compatible result
    # shape; current writers do not synthesize text for empty regions.
    # ``grounding_dropped_no_bbox`` — regions with text but no derivable
    # bbox (no polygon / keypoints either) — silently dropped to keep
    # downstream training data clean.
    grounding_fallback_count: int = 0
    grounding_dropped_no_bbox: int = 0


# ──────────────────────────────────────────────────────────────────────
# Dispatcher
# ──────────────────────────────────────────────────────────────────────

_WRITERS: dict[str, Any] = {}  # populated at module bottom


def export_samples(
    ss: SampleSet,
    fmt: str,
    opts: ExportOptions,
    *,
    progress_cb=None,
) -> ExportResult:
    """Write *ss* to *fmt* under ``opts.out_dir``.

    ``fmt`` is case-insensitive: ``"YOLO"``, ``"coco"``, ``"voc"``, etc.
    """
    try:
        from .target_readiness import export_key_for_target_format
        fmt = export_key_for_target_format(fmt)
    except Exception:
        pass
    key = fmt.lower().replace("-", "_").replace(" ", "")
    writer = _WRITERS.get(key)
    if writer is None:
        raise ValueError(
            f"unsupported export format {fmt!r}; "
            f"available: {', '.join(sorted(_WRITERS))}"
        )
    return writer(ss, opts, progress_cb)


def available_formats() -> list[str]:
    """Return sorted list of registered format keys."""
    return sorted(_WRITERS)


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _copy_image(sample: Sample, dst_dir: Path,
                report: ExportResult) -> str:
    """Copy image to *dst_dir*, return relative path from out root."""
    dst = dst_dir / sample.image_path.name
    try:
        dst_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(sample.image_path, dst)
        report.written_images += 1
    except OSError as e:
        report.skipped.append((sample.image_path, str(e)))
    return dst.name


def _copy_path(src: Path, dst_dir: Path, report: ExportResult) -> str:
    """Copy an arbitrary image path to *dst_dir*, return file name."""
    dst = dst_dir / src.name
    try:
        dst_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        report.written_images += 1
    except OSError as e:
        report.skipped.append((src, str(e)))
    return dst.name


def _iter_splits(ss: SampleSet):
    """Yield (split_name, samples) for non-empty splits.

    Unsplit samples are folded INTO the train batch (not yielded as a second
    ``"train"``) so per-split-file writers (COCO/VOC/JSONL/…) don't write
    ``*_train.*`` twice and silently overwrite the first batch.
    """
    train = list(ss.train) + list(ss.unsplit)
    for name, samples in [("train", train), ("val", ss.val),
                          ("test", ss.test)]:
        if samples:
            yield name, samples


def _generate_answer(regions: list[Region]) -> str:
    """Auto-generate a natural-language answer from regions."""
    if not regions:
        return "这张图片中未发现标注目标。"
    labels = [normalize_label(r.label) or r.label for r in regions]
    counts = Counter(labels)
    total = len(regions)
    if total == 1:
        return f"图片中存在1个 {labels[0]}。"
    parts = [f"{c}个 {l}" for l, c in counts.most_common()]
    return f"图片中存在{total}个目标：{'、'.join(parts)}。"


def _sample_answer(sample: Sample) -> str:
    """Get VLM answer: prefer caption / conversations, fall back to auto."""
    if sample.caption:
        return sample.caption
    if sample.conversations:
        for t in sample.conversations:
            if t.get("from") in ("gpt", "assistant"):
                return t.get("value", "")
    return _generate_answer(sample.regions)


def _sample_conversations(sample: Sample, question: str) -> list[dict]:
    """Get VLM conversations: prefer Sample's, fall back to auto-gen."""
    if sample.conversations:
        return sample.conversations
    return [
        {"from": "human", "value": f"<image>\n{question}"},
        {"from": "gpt", "value": _sample_answer(sample)},
    ]


def _sample_grounding(
    sample: Sample, report: ExportResult | None = None,
) -> list[dict]:
    """Extract LLM grounding entries from a sample's regions.

    Returns one dict per region:
        {"label": str, "text": str, "bbox": [x1, y1, x2, y2]  (int)}

    Behavior:

    1. Only user-authored region text is exported as grounding. Empty
       region text means "no grounding annotation" rather than an
       automatic class-template fallback.
    2. Bbox is required. If the region only has a polygon / keypoints,
       ``Region.ensure_bbox`` derives the axis-aligned outer box. If
       neither is available, the region is dropped and
       ``report.grounding_dropped_no_bbox`` is incremented.
    3. Bbox coords are clamped to ints (xyxy pixel) — VLM grounding
       is usually trained against integer pixel coords; floats add
       noise without precision benefit.
    """
    entries: list[dict] = []
    for r in sample.regions:
        text = r.text.strip()
        if not text:
            continue
        bb = r.ensure_bbox()
        if bb is None:
            if report is not None:
                report.grounding_dropped_no_bbox += 1
            continue
        label = normalize_label(r.label)
        if not label:
            continue
        entries.append({
            "label": label,
            "text": text,
            "bbox": [int(round(bb.x1)), int(round(bb.y1)),
                     int(round(bb.x2)), int(round(bb.y2))],
        })
    return entries


def _grounding_answer(entries: list[dict]) -> str:
    """Compose a Chinese assistant answer that embeds bbox + text.

    One sentence per entry — keeps the structure greppable by training
    pipelines that need to extract bbox spans (e.g. Qwen-VL post-
    processing).  Format::

        "图中 {label} 位于 [x1, y1, x2, y2] 区域。{text}"
    """
    parts: list[str] = []
    for e in entries:
        bb = e["bbox"]
        bbox_str = f"[{bb[0]}, {bb[1]}, {bb[2]}, {bb[3]}]"
        parts.append(f"图中 {e['label']} 位于 {bbox_str} 区域。{e['text']}")
    return " ".join(parts)


def _grounding_objects(entries: list[dict]) -> dict:
    """Return ms-swift / Qwen-VL-style ``objects`` block."""
    return {
        "ref": [e["label"] for e in entries],
        "bbox": [e["bbox"] for e in entries],
    }


def _to_openai_messages(convos: list[dict]) -> list[dict]:
    """Map ShareGPT-style ``{from, value}`` turns to OpenAI / ms-swift
    ``{role, content}`` turns.  Unknown ``from`` values pass through
    unchanged so the writer stays format-agnostic."""
    role_map = {"human": "user", "gpt": "assistant"}
    return [{"role": role_map.get(t.get("from", ""), t.get("from", "user")),
             "content": t.get("value", "")}
            for t in convos]


def _assistant_response(convos: list[dict]) -> str:
    """Return the first assistant/GPT turn for legacy JSONL consumers."""
    for turn in convos:
        if turn.get("from") in ("gpt", "assistant"):
            return turn.get("value", "")
    return ""


def _sample_conversations_grounded(
    sample: Sample, question: str, grounding: list[dict],
) -> list[dict]:
    """ShareGPT-shape conversations that embed grounding into the
    assistant turn when ``grounding`` is non-empty.  Falls back to
    ``_sample_conversations`` (caption / auto-answer) otherwise.

    User-authored ``sample.conversations`` always win — we don't
    overwrite hand-written multi-turn data even if grounding is
    available, because the user's intent is explicit.
    """
    if sample.conversations:
        return sample.conversations
    if grounding:
        return [
            {"from": "human", "value": f"<image>\n{question}"},
            {"from": "gpt", "value": _grounding_answer(grounding)},
        ]
    return _sample_conversations(sample, question)


# ══════════════════════════════════════════════════════════════════════
# Writers
# ══════════════════════════════════════════════════════════════════════

# ── YOLO ──────────────────────────────────────────────────────────────

def _write_yolo(ss: SampleSet, opts: ExportOptions,
                progress_cb) -> ExportResult:
    out = opts.out_dir
    report = ExportResult()
    cls_idx = ss.class_to_index
    cls_list = ss.class_names

    all_samples = [(n, s) for n, batch in _iter_splits(ss) for s in batch]
    total = len(all_samples)

    for done, (split, sample) in enumerate(all_samples):
        if progress_cb:
            progress_cb(done, total, sample.image_path.name)
        try:
            iw, ih = sample.image_width, sample.image_height
            img_dir = out / "images" / split
            lbl_dir = out / "labels" / split
            if opts.copy_images:
                _copy_image(sample, img_dir, report)

            lines: list[str] = []
            for r in sample.regions:
                if iw <= 0 or ih <= 0:
                    continue
                label = normalize_label(r.label)
                if label not in cls_idx:
                    continue
                cid = cls_idx[label]
                if r.polygon and len(r.polygon) >= 3:
                    # YOLO-seg line: class + normalized polygon points
                    # (clamped to [0,1]). Otherwise segmentation masks are
                    # silently flattened to boxes on export.
                    coords: list[float] = []
                    for px, py in r.polygon:
                        coords.append(min(max(px / iw, 0.0), 1.0))
                        coords.append(min(max(py / ih, 0.0), 1.0))
                    lines.append(
                        f"{cid} " + " ".join(f"{c:.6f}" for c in coords))
                    continue
                bb = r.ensure_bbox()
                if bb is None:
                    continue
                # Clamp corners to the image so exported coords stay in
                # [0,1] — Ultralytics rejects/clips out-of-bounds boxes.
                cbb = BBox(min(max(bb.x1, 0.0), float(iw)),
                           min(max(bb.y1, 0.0), float(ih)),
                           min(max(bb.x2, 0.0), float(iw)),
                           min(max(bb.y2, 0.0), float(ih)))
                cx, cy, w, h = cbb.to_yolo(iw, ih)
                if w <= 0 or h <= 0:
                    continue
                lines.append(
                    f"{cid} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")
            lbl_dir.mkdir(parents=True, exist_ok=True)
            (lbl_dir / (sample.image_path.stem + ".txt")).write_text(
                "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
            report.written_labels += 1
        except Exception as e:
            report.skipped.append((sample.image_path, str(e)))

    # classes.txt + data.yaml
    (out / "classes.txt").write_text(
        "\n".join(cls_list) + "\n", encoding="utf-8")
    # Only reference splits that actually exist on disk — hardcoding
    # `val: images/val` when there's no val split makes Ultralytics error on
    # a missing directory (unsplit samples land in train, so gate on either).
    yaml = ["path: ."]
    if ss.train or ss.unsplit:
        yaml.append("train: images/train")
    if ss.val:
        yaml.append("val: images/val")
    if ss.test:
        yaml.append("test: images/test")
    yaml += [f"nc: {len(cls_list)}",
             "names: [" + ", ".join(f"'{c}'" for c in cls_list) + "]"]
    (out / "data.yaml").write_text("\n".join(yaml) + "\n", encoding="utf-8")

    if progress_cb:
        progress_cb(total, total, "")
    return report


# ── COCO ──────────────────────────────────────────────────────────────

def _write_coco(ss: SampleSet, opts: ExportOptions,
                progress_cb) -> ExportResult:
    out = opts.out_dir
    ann_dir = out / "annotations"
    ann_dir.mkdir(parents=True, exist_ok=True)
    report = ExportResult()

    all_samples = list(_iter_splits(ss))
    total = sum(len(batch) for _, batch in all_samples)
    done = 0

    # ONE global category map for every split file. Building it per-split (by
    # encounter order) let the same category_id mean different classes in
    # train vs val — a COCO consumer reads the map from one file and applies
    # it to all, so that silently mislabels the dataset. 1-indexed per COCO.
    cat_idx = {name: i + 1 for i, name in enumerate(ss.class_names)}
    cats_json = [{"id": cid, "name": name} for name, cid in cat_idx.items()]

    for split, samples in all_samples:
        images_json: list[dict] = []
        anns_json: list[dict] = []
        next_img = 1
        next_ann = 1

        for sample in samples:
            done += 1
            if progress_cb:
                progress_cb(done, total, sample.image_path.name)
            try:
                if opts.copy_images:
                    _copy_image(sample, out / split, report)
                images_json.append({
                    "id": next_img,
                    "file_name": sample.image_path.name,
                    "width": sample.image_width,
                    "height": sample.image_height,
                })
                for r in sample.regions:
                    bb = r.ensure_bbox()
                    if bb is None:
                        continue
                    label = normalize_label(r.label)
                    if label not in cat_idx:
                        continue
                    x, y, w, h = bb.to_xywh()
                    if w <= 0 or h <= 0:
                        continue
                    ann = {
                        "id": next_ann,
                        "image_id": next_img,
                        "category_id": cat_idx[label],
                        "bbox": [x, y, w, h],
                        "area": w * h,
                        "iscrowd": int(r.iscrowd),
                    }
                    # Keep segmentation masks instead of silently dropping
                    # them to bbox-only (COCO allows both on one annotation).
                    if r.polygon and len(r.polygon) >= 3:
                        ann["segmentation"] = [
                            [c for pt in r.polygon for c in pt]]
                    anns_json.append(ann)
                    next_ann += 1
                next_img += 1
                report.written_labels += 1
            except Exception as e:
                report.skipped.append((sample.image_path, str(e)))

        (ann_dir / f"instances_{split}.json").write_text(
            json.dumps({"images": images_json, "annotations": anns_json,
                         "categories": cats_json},
                        ensure_ascii=False, indent=2),
            encoding="utf-8")

    if progress_cb:
        progress_cb(total, total, "")
    return report


# ── VOC ───────────────────────────────────────────────────────────────

def _write_voc(ss: SampleSet, opts: ExportOptions,
               progress_cb) -> ExportResult:
    out = opts.out_dir
    img_dir = out / "JPEGImages"
    xml_dir = out / "Annotations"
    sets_dir = out / "ImageSets" / "Main"
    for d in (img_dir, xml_dir, sets_dir):
        d.mkdir(parents=True, exist_ok=True)
    report = ExportResult()

    all_samples = list(_iter_splits(ss))
    total = sum(len(batch) for _, batch in all_samples)
    done = 0

    for split, samples in all_samples:
        stems: list[str] = []
        for sample in samples:
            done += 1
            if progress_cb:
                progress_cb(done, total, sample.image_path.name)
            try:
                if opts.copy_images:
                    _copy_image(sample, img_dir, report)
                root = ET.Element("annotation")
                ET.SubElement(root, "folder").text = "JPEGImages"
                ET.SubElement(root, "filename").text = sample.image_path.name
                sz = ET.SubElement(root, "size")
                ET.SubElement(sz, "width").text = str(sample.image_width)
                ET.SubElement(sz, "height").text = str(sample.image_height)
                ET.SubElement(sz, "depth").text = "3"
                for r in sample.regions:
                    bb = r.ensure_bbox()
                    if bb is None or bb.width <= 0 or bb.height <= 0:
                        continue
                    label = normalize_label(r.label)
                    if not label:
                        continue
                    obj = ET.SubElement(root, "object")
                    ET.SubElement(obj, "name").text = label
                    ET.SubElement(obj, "difficult").text = (
                        "1" if r.difficult else "0")
                    ET.SubElement(obj, "truncated").text = (
                        "1" if r.truncated else "0")
                    bnd = ET.SubElement(obj, "bndbox")
                    # round() not int(): int() floors toward zero and
                    # under-reports every box by up to a pixel.
                    ET.SubElement(bnd, "xmin").text = f"{round(bb.x1)}"
                    ET.SubElement(bnd, "ymin").text = f"{round(bb.y1)}"
                    ET.SubElement(bnd, "xmax").text = f"{round(bb.x2)}"
                    ET.SubElement(bnd, "ymax").text = f"{round(bb.y2)}"
                (xml_dir / (sample.image_path.stem + ".xml")).write_bytes(
                    ET.tostring(root, encoding="utf-8", xml_declaration=True))
                report.written_labels += 1
                stems.append(sample.image_path.stem)
            except Exception as e:
                report.skipped.append((sample.image_path, str(e)))
        (sets_dir / f"{split}.txt").write_text(
            "\n".join(stems) + "\n", encoding="utf-8")

    if progress_cb:
        progress_cb(total, total, "")
    return report


# ── LabelMe ───────────────────────────────────────────────────────────

def _write_labelme(ss: SampleSet, opts: ExportOptions,
                   progress_cb) -> ExportResult:
    out = opts.out_dir
    report = ExportResult()
    all_samples = [(n, s) for n, batch in _iter_splits(ss) for s in batch]
    total = len(all_samples)

    for done, (split, sample) in enumerate(all_samples):
        if progress_cb:
            progress_cb(done, total, sample.image_path.name)
        try:
            img_dir = out / "images" / split
            lbl_dir = out / "labels" / split
            if opts.copy_images:
                _copy_image(sample, img_dir, report)
            shapes: list[dict] = []
            for r in sample.regions:
                pts = _region_points(r)
                if not pts:
                    continue
                label = normalize_label(r.label)
                if not label:
                    continue
                shapes.append({
                    "label": label,
                    "points": [[x, y] for x, y in pts],
                    "group_id": None,
                    # LabelMe has no "ellipse"; _region_points emits an oval
                    # polygon for it, so write it out as a polygon.
                    "shape_type": ("polygon" if r.shape_type == "ellipse"
                                   else r.shape_type),
                    "flags": {},
                })
            # JSON lands in labels/<split>/ but the image in images/<split>/;
            # a bare filename makes labelme look next to the JSON and fail to
            # load. Point at the copied image relative to the JSON's dir (or
            # the absolute source when we didn't copy).
            if opts.copy_images:
                image_path = f"../../images/{split}/{sample.image_path.name}"
            else:
                image_path = str(sample.image_path)
            lme = {
                "version": "5.0.0",
                "flags": {},
                "imagePath": image_path,
                "imageData": None,
                "imageWidth": sample.image_width,
                "imageHeight": sample.image_height,
                "shapes": shapes,
            }
            lbl_dir.mkdir(parents=True, exist_ok=True)
            (lbl_dir / (sample.image_path.stem + ".json")).write_text(
                json.dumps(lme, ensure_ascii=False, indent=2),
                encoding="utf-8")
            report.written_labels += 1
        except Exception as e:
            report.skipped.append((sample.image_path, str(e)))

    if progress_cb:
        progress_cb(total, total, "")
    return report


def _region_points(r: Region) -> list[tuple[float, float]]:
    """Extract the LabelMe point list that matches ``r.shape_type``.

    LabelMe validates point counts per type: ``circle`` MUST be exactly
    ``[center, edge]`` (2 pts) and ``point`` exactly 1 pt. A circle/point
    region only carries a bbox after import, so emitting the generic
    4-corner polygon here (while writing ``shape_type: "circle"``) produces
    JSON the labelme GUI rejects. Reconstruct the right geometry instead.
    """
    st = r.shape_type
    if st == "circle" and r.bbox:
        bb = r.bbox
        cx, cy = (bb.x1 + bb.x2) / 2.0, (bb.y1 + bb.y2) / 2.0
        rad = (bb.x2 - bb.x1) / 2.0  # bbox of a circle is a 2r × 2r square
        return [(cx, cy), (cx + rad, cy)]
    if st == "ellipse" and r.bbox:
        # LabelMe has no ellipse → sample an oval polygon from the bbox.
        return _ellipse_polygon(r.bbox)
    if st == "point":
        if r.keypoints:
            x, y, _v = r.keypoints[0]
            return [(x, y)]
        if r.bbox:
            bb = r.bbox
            return [((bb.x1 + bb.x2) / 2.0, (bb.y1 + bb.y2) / 2.0)]
        return []
    if r.polygon:
        return r.polygon
    if r.bbox:
        bb = r.bbox
        if st == "rectangle":
            return [(bb.x1, bb.y1), (bb.x2, bb.y2)]
        # polygon from bbox
        return [(bb.x1, bb.y1), (bb.x2, bb.y1),
                (bb.x2, bb.y2), (bb.x1, bb.y2)]
    if r.keypoints:
        return [(x, y) for x, y, _v in r.keypoints]
    return []


def _ellipse_polygon(bb: BBox, n: int = 24) -> list[tuple[float, float]]:
    """Sample *n* points around the ellipse inscribed in *bb*."""
    cx, cy = (bb.x1 + bb.x2) / 2.0, (bb.y1 + bb.y2) / 2.0
    rx, ry = (bb.x2 - bb.x1) / 2.0, (bb.y2 - bb.y1) / 2.0
    return [
        (cx + rx * math.cos(2.0 * math.pi * k / n),
         cy + ry * math.sin(2.0 * math.pi * k / n))
        for k in range(n)
    ]


# ── CSV ───────────────────────────────────────────────────────────────

_CSV_COLS = [
    "image_path", "category", "label",
    "x1", "y1", "x2", "y2", "shape_type", "split",
]


def _write_csv(ss: SampleSet, opts: ExportOptions,
               progress_cb) -> ExportResult:
    out = opts.out_dir
    out.mkdir(parents=True, exist_ok=True)
    report = ExportResult()
    all_samples = [(n, s) for n, batch in _iter_splits(ss) for s in batch]
    total = len(all_samples)

    csv_path = out / "annotations.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(_CSV_COLS)
        for done, (split, sample) in enumerate(all_samples):
            if progress_cb:
                progress_cb(done, total, sample.image_path.name)
            try:
                img_dir = out / "images" / split
                if opts.copy_images:
                    _copy_image(sample, img_dir, report)
                    rel = f"images/{split}/{sample.image_path.name}"
                else:
                    rel = str(sample.image_path)
                if sample.regions:
                    for r in sample.regions:
                        label = normalize_label(r.label)
                        bb = r.ensure_bbox()
                        if bb:
                            writer.writerow([
                                rel, sample.category, label,
                                f"{bb.x1:.1f}", f"{bb.y1:.1f}",
                                f"{bb.x2:.1f}", f"{bb.y2:.1f}",
                                r.shape_type, split,
                            ])
                        else:
                            writer.writerow([
                                rel, sample.category, label,
                                "", "", "", "", r.shape_type, split,
                            ])
                else:
                    writer.writerow([
                        rel, sample.category, "", "", "", "", "", "", split])
                report.written_labels += 1
            except Exception as e:
                report.skipped.append((sample.image_path, str(e)))

    if progress_cb:
        progress_cb(total, total, "")
    return report


# ── JSONL ─────────────────────────────────────────────────────────────

def _write_jsonl(ss: SampleSet, opts: ExportOptions,
                 progress_cb) -> ExportResult:
    out = opts.out_dir
    report = ExportResult()
    all_splits = list(_iter_splits(ss))
    total = sum(len(b) for _, b in all_splits)
    done = 0

    for split, samples in all_splits:
        lines: list[str] = []
        img_dir = out / "images" / split
        for sample in samples:
            done += 1
            if progress_cb:
                progress_cb(done, total, sample.image_path.name)
            try:
                if opts.copy_images:
                    _copy_image(sample, img_dir, report)
                    rel = f"images/{split}/{sample.image_path.name}"
                else:
                    rel = str(sample.image_path)
                annots = []
                for r in sample.regions:
                    bb = r.ensure_bbox()
                    label = normalize_label(r.label)
                    if not label:
                        continue
                    d: dict[str, Any] = {
                        "label": label,
                        "shape_type": r.shape_type,
                    }
                    if bb:
                        d["bbox"] = [bb.x1, bb.y1, bb.x2, bb.y2]
                    if r.polygon:
                        d["points"] = [[x, y] for x, y in r.polygon]
                    annots.append(d)
                rec = {
                    "image": rel,
                    "width": sample.image_width,
                    "height": sample.image_height,
                    "category": sample.category,
                    "annotations": annots,
                }
                lines.append(json.dumps(rec, ensure_ascii=False))
                report.written_labels += 1
            except Exception as e:
                report.skipped.append((sample.image_path, str(e)))
        (out / f"{split}.jsonl").parent.mkdir(parents=True, exist_ok=True)
        (out / f"{split}.jsonl").write_text(
            "\n".join(lines) + "\n", encoding="utf-8")

    if progress_cb:
        progress_cb(total, total, "")
    return report


# ── ImageFolder ───────────────────────────────────────────────────────

def _write_imagefolder(ss: SampleSet, opts: ExportOptions,
                       progress_cb) -> ExportResult:
    out = opts.out_dir
    out.mkdir(parents=True, exist_ok=True)
    report = ExportResult()
    all_samples = [(n, s) for n, batch in _iter_splits(ss) for s in batch]
    total = len(all_samples)

    for done, (split, sample) in enumerate(all_samples):
        if progress_cb:
            progress_cb(done, total, sample.image_path.name)
        try:
            cat = (sample.category or "").strip()
            if not cat:
                report.skipped.append((sample.image_path, "no category"))
                continue
            _copy_image(sample, out / split / cat, report)
        except Exception as e:
            report.skipped.append((sample.image_path, str(e)))

    if progress_cb:
        progress_cb(total, total, "")
    return report


# ── MVTec ─────────────────────────────────────────────────────────────

def _write_mvtec(ss: SampleSet, opts: ExportOptions,
                 progress_cb) -> ExportResult:
    out = opts.out_dir
    out.mkdir(parents=True, exist_ok=True)
    report = ExportResult()

    def is_good(s: Sample) -> bool:
        return (s.category or "").strip().lower() == "good"

    train_good = [s for s in ss.train if is_good(s)]
    train_defect = [s for s in ss.train if not is_good(s)]
    test_all = list(ss.val) + list(ss.test) + train_defect

    total = len(train_good) + len(test_all)
    done = 0

    for sample in train_good:
        done += 1
        if progress_cb:
            progress_cb(done, total, sample.image_path.name)
        try:
            _copy_image(sample, out / "train" / "good", report)
        except Exception as e:
            report.skipped.append((sample.image_path, str(e)))

    for sample in test_all:
        done += 1
        if progress_cb:
            progress_cb(done, total, sample.image_path.name)
        try:
            cat = (sample.category or "").strip()
            if not cat:
                report.skipped.append((sample.image_path, "no category"))
                continue
            bucket = "good" if cat.lower() == "good" else cat
            _copy_image(sample, out / "test" / bucket, report)
        except Exception as e:
            report.skipped.append((sample.image_path, str(e)))

    if progress_cb:
        progress_cb(total, total, "")
    return report


# ── LLaVA ─────────────────────────────────────────────────────────────

def _write_pairedfolder(ss: SampleSet, opts: ExportOptions,
                        progress_cb) -> ExportResult:
    """Write image-pair datasets as split folders plus pairs.csv."""
    out = opts.out_dir
    out.mkdir(parents=True, exist_ok=True)
    report = ExportResult()
    all_samples = [(split, sample)
                   for split, batch in _iter_splits(ss)
                   for sample in batch]
    total = len(all_samples)
    rows: list[list[str]] = [["split", "image_a", "image_b", "category"]]
    seen_pairs: set[tuple[str, str]] = set()

    for done, (split, sample) in enumerate(all_samples):
        if progress_cb:
            progress_cb(done, total, sample.image_path.name)
        if sample.pair_path is None:
            report.skipped.append((sample.image_path, "missing pair_path"))
            continue
        pair_key = tuple(sorted((str(sample.image_path), str(sample.pair_path))))
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)
        try:
            if opts.copy_images:
                a_name = _copy_path(
                    sample.image_path, out / "images" / split / "a", report)
                b_name = _copy_path(
                    sample.pair_path, out / "images" / split / "b", report)
                rel_a = f"images/{split}/a/{a_name}"
                rel_b = f"images/{split}/b/{b_name}"
            else:
                rel_a = str(sample.image_path)
                rel_b = str(sample.pair_path)
            rows.append([split, rel_a, rel_b, sample.category])
            report.written_labels += 1
        except Exception as e:
            report.skipped.append((sample.image_path, str(e)))

    with (out / "pairs.csv").open("w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f).writerows(rows)

    if progress_cb:
        progress_cb(total, total, "")
    return report


def _write_llava(ss: SampleSet, opts: ExportOptions,
                 progress_cb) -> ExportResult:
    out = opts.out_dir
    report = ExportResult()
    all_splits = list(_iter_splits(ss))
    total = sum(len(b) for _, b in all_splits)
    done = 0

    for split, samples in all_splits:
        lines: list[str] = []
        img_dir = out / "images" / split
        for i, sample in enumerate(samples):
            done += 1
            if progress_cb:
                progress_cb(done, total, sample.image_path.name)
            try:
                if opts.copy_images:
                    _copy_image(sample, img_dir, report)
                    rel = f"images/{split}/{sample.image_path.name}"
                else:
                    rel = str(sample.image_path)
                gnd = _sample_grounding(sample, report)
                convos = _sample_conversations_grounded(
                    sample, opts.question, gnd)
                rec: dict = {
                    "id": f"{split}_{i:06d}",
                    "image": rel,
                    "conversations": convos,
                }
                # Side-channel ``grounding`` field stays — pipelines that
                # parse the assistant text can ignore it; pipelines that
                # train on structured grounding can read it directly.
                if gnd:
                    rec["grounding"] = gnd
                lines.append(json.dumps(rec, ensure_ascii=False))
                report.written_labels += 1
            except Exception as e:
                report.skipped.append((sample.image_path, str(e)))
        out.mkdir(parents=True, exist_ok=True)
        (out / f"llava_{split}.jsonl").write_text(
            "\n".join(lines) + "\n", encoding="utf-8")

    if progress_cb:
        progress_cb(total, total, "")
    return report


# ── ShareGPT ──────────────────────────────────────────────────────────

def _write_sharegpt(ss: SampleSet, opts: ExportOptions,
                    progress_cb) -> ExportResult:
    out = opts.out_dir
    report = ExportResult()
    all_splits = list(_iter_splits(ss))
    total = sum(len(b) for _, b in all_splits)
    done = 0

    for split, samples in all_splits:
        records: list[dict] = []
        img_dir = out / "images" / split
        for sample in samples:
            done += 1
            if progress_cb:
                progress_cb(done, total, sample.image_path.name)
            try:
                if opts.copy_images:
                    _copy_image(sample, img_dir, report)
                    rel = f"images/{split}/{sample.image_path.name}"
                else:
                    rel = str(sample.image_path)
                gnd = _sample_grounding(sample, report)
                convos = _sample_conversations_grounded(
                    sample, opts.question, gnd)
                rec: dict = {
                    "conversations": convos,
                    "images": [rel],
                }
                if gnd:
                    # ``objects`` block is the LLaMA-Factory / ms-swift
                    # convention for structured grounding; ``grounding``
                    # mirrors the rich entries (label + text + bbox) for
                    # pipelines that need the per-region caption too.
                    rec["objects"] = _grounding_objects(gnd)
                    rec["grounding"] = gnd
                records.append(rec)
                report.written_labels += 1
            except Exception as e:
                report.skipped.append((sample.image_path, str(e)))
        out.mkdir(parents=True, exist_ok=True)
        (out / f"sharegpt_{split}.json").write_text(
            json.dumps(records, ensure_ascii=False, indent=2),
            encoding="utf-8")

    # dataset_info.json for LLaMA-Factory
    info = {}
    for split, _ in all_splits:
        info[f"my_dataset_{split}"] = {
            "file_name": f"sharegpt_{split}.json",
            "formatting": "sharegpt",
            "columns": {"messages": "conversations", "images": "images"},
        }
    (out / "dataset_info.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")

    if progress_cb:
        progress_cb(total, total, "")
    return report


# ── Swift ─────────────────────────────────────────────────────────────

def _write_swift(ss: SampleSet, opts: ExportOptions,
                 progress_cb) -> ExportResult:
    """ms-swift / Qwen-VL JSONL writer.

    Output schema per line (one sample per line):

        {
          "messages": [{"role": "user", "content": "<image>..."},
                       {"role": "assistant", "content": "..."}],
          "images":   ["images/train/foo.jpg"],
          "objects":  {"ref": ["Loose"], "bbox": [[120, 86, 240, 180]]}
        }

    ``objects`` is only emitted for samples with at least one grounding
    region (text or fallback) and a derivable bbox.  When grounding is
    present, the assistant message embeds the bbox in natural language
    (via ``_grounding_answer``) so models trained on the text channel
    learn the localization too.
    """
    out = opts.out_dir
    report = ExportResult()
    all_splits = list(_iter_splits(ss))
    total = sum(len(b) for _, b in all_splits)
    done = 0

    for split, samples in all_splits:
        lines: list[str] = []
        img_dir = out / "images" / split
        for sample in samples:
            done += 1
            if progress_cb:
                progress_cb(done, total, sample.image_path.name)
            try:
                if opts.copy_images:
                    _copy_image(sample, img_dir, report)
                    rel = f"images/{split}/{sample.image_path.name}"
                else:
                    rel = str(sample.image_path)
                gnd = _sample_grounding(sample, report)
                convos = _sample_conversations_grounded(
                    sample, opts.question, gnd)
                rec: dict = {
                    "messages": _to_openai_messages(convos),
                    "images": [rel],
                    # Legacy ms-swift/JSONL consumers in this project
                    # still read ``response`` directly. Keep it as a
                    # compatibility alias for the assistant message.
                    "response": _assistant_response(convos),
                }
                if gnd:
                    rec["objects"] = _grounding_objects(gnd)
                lines.append(json.dumps(rec, ensure_ascii=False))
                report.written_labels += 1
            except Exception as e:
                report.skipped.append((sample.image_path, str(e)))
        out.mkdir(parents=True, exist_ok=True)
        (out / f"swift_{split}.jsonl").write_text(
            "\n".join(lines) + "\n", encoding="utf-8")

    if progress_cb:
        progress_cb(total, total, "")
    return report


# ──────────────────────────────────────────────────────────────────────
# Registry
# ──────────────────────────────────────────────────────────────────────

_WRITERS.update({
    "yolo": _write_yolo,
    "coco": _write_coco,
    "voc": _write_voc,
    "labelme": _write_labelme,
    "csv": _write_csv,
    "jsonl": _write_jsonl,
    "imagefolder": _write_imagefolder,
    "mvtec": _write_mvtec,
    "pairedfolder": _write_pairedfolder,
    "llava": _write_llava,
    "sharegpt": _write_sharegpt,
    "swift": _write_swift,
})
