"""Round-trip format validation — export → re-import → compare.

Verifies that SampleSet survives a format round-trip without silent
data loss. Used by the conversion wizard's "验证" button and by
automated tests.

Pure Python — no PyQt.
"""
from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .unified import Sample, SampleSet


@dataclass
class RTDiff:
    """One per-sample difference found during round-trip."""
    image_name: str
    field: str          # "region_count", "bbox", "label", "caption", etc.
    expected: str
    actual: str


@dataclass
class RoundTripResult:
    """Outcome of a round-trip validation run."""
    fmt: str
    original_count: int = 0
    reimported_count: int = 0
    matched: int = 0
    diffs: list[RTDiff] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return (not self.errors
                and not self.diffs
                and self.original_count == self.reimported_count)

    @property
    def loss_rate(self) -> float:
        if self.original_count == 0:
            return 0.0
        return len(self.diffs) / self.original_count


def validate_roundtrip(
    ss: SampleSet,
    fmt: str,
    *,
    progress_cb=None,
) -> RoundTripResult:
    """Export *ss* to *fmt* in a temp dir, re-import, compare.

    Only checks formats that have both a writer and a reader. VLM
    formats (llava/sharegpt/swift) use the VLM JSONL reader for
    re-import.
    """
    result = RoundTripResult(fmt=fmt, original_count=len(ss.samples))

    # Validate format is round-trippable
    _REIMPORT_MAP = {
        "labelme": "labelme",
        "yolo": "yolo",
        "voc": "voc",
        "coco": "coco",
        "llava": "vlm_jsonl",
        "sharegpt": "vlm_jsonl",
        "swift": "vlm_jsonl",
    }
    reimport_fmt = _REIMPORT_MAP.get(fmt)
    if reimport_fmt is None:
        result.errors.append(f"format '{fmt}' has no round-trip reader")
        return result

    with tempfile.TemporaryDirectory(prefix="dataforge_rt_") as tmpdir:
        out_dir = Path(tmpdir)

        # Phase 1: Export
        try:
            from .format_out import ExportOptions, export_samples
            export_opts = ExportOptions(
                out_dir=out_dir,
                copy_images=True,
            )
            export_result = export_samples(ss, fmt, export_opts,
                                           progress_cb=progress_cb)
            if export_result.skipped:
                for path, err in export_result.skipped[:5]:
                    result.errors.append(f"export skip: {path.name}: {err}")
        except Exception as e:
            result.errors.append(f"export failed: {e}")
            return result

        # Phase 2: Re-import
        try:
            reimported = _reimport(out_dir, reimport_fmt, fmt)
        except Exception as e:
            result.errors.append(f"reimport failed: {e}")
            return result

        result.reimported_count = len(reimported.samples)

        # Phase 3: Compare
        _compare(ss, reimported, result, fmt)

    return result


def _reimport(out_dir: Path, reimport_fmt: str, export_fmt: str) -> SampleSet:
    """Re-import exported data from *out_dir*."""
    if reimport_fmt == "vlm_jsonl":
        from .format_in import load_vlm_jsonl
        jsonl_files = list(out_dir.rglob("*.jsonl")) + list(out_dir.rglob("*.json"))
        all_samples = []
        for jf in jsonl_files:
            if jf.name.startswith("dataset_info"):
                continue
            ss = load_vlm_jsonl(jf, image_root=out_dir)
            all_samples.extend(ss.samples)
        return SampleSet(samples=all_samples)

    # Standard annotation formats: pair image files with their label files
    # directly (the export layout uses images/<split>/ + labels/<split>/
    # which doesn't match scan_dataset's expected <category>/images/ layout).
    from .format_in import (
        _read_labelme,
        _read_yolo,
        _read_voc,
        _image_size,
    )
    from .unified import Sample as _S

    _LABEL_EXT = {"labelme": ".json", "yolo": ".txt", "voc": ".xml"}
    lbl_ext = _LABEL_EXT.get(reimport_fmt, ".json")

    # Collect all images
    img_exts = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
    images = [f for f in out_dir.rglob("*") if f.is_file()
              and f.suffix.lower() in img_exts]

    # Index label files by stem
    label_files = {f.stem: f for f in out_dir.rglob(f"*{lbl_ext}")
                   if f.is_file()}

    # For YOLO: load class names once
    yolo_names: list[str] | None = None
    if reimport_fmt == "yolo":
        classes_txt = out_dir / "classes.txt"
        if classes_txt.exists():
            yolo_names = [
                ln.strip()
                for ln in classes_txt.read_text(encoding="utf-8-sig").splitlines()
                if ln.strip()
            ]

    samples: list[_S] = []
    for img_path in images:
        w, h = _image_size(img_path)
        sample = _S(image_path=img_path, image_width=w, image_height=h)
        lbl = label_files.get(img_path.stem)
        if lbl is not None:
            sample.has_label = True
            sample.label_path = lbl
            sample.source_format = reimport_fmt
            if reimport_fmt == "labelme":
                _read_labelme(sample, lbl)
            elif reimport_fmt == "yolo":
                _read_yolo(sample, lbl, yolo_names)
            elif reimport_fmt == "voc":
                _read_voc(sample, lbl)
        samples.append(sample)

    return SampleSet(samples=samples)


def _compare(original: SampleSet, reimported: SampleSet,
             result: RoundTripResult, fmt: str) -> None:
    """Compare original and reimported SampleSets, populate diffs."""
    # Index reimported by image filename stem
    re_by_stem: dict[str, Sample] = {}
    for s in reimported.samples:
        re_by_stem[s.image_path.stem] = s

    for orig in original.samples:
        stem = orig.image_path.stem
        reim = re_by_stem.get(stem)
        if reim is None:
            result.diffs.append(RTDiff(
                image_name=stem,
                field="missing",
                expected="present",
                actual="absent",
            ))
            continue

        result.matched += 1

        # Compare region count
        if len(orig.regions) != len(reim.regions):
            result.diffs.append(RTDiff(
                image_name=stem,
                field="region_count",
                expected=str(len(orig.regions)),
                actual=str(len(reim.regions)),
            ))

        # Compare labels (sorted set)
        orig_labels = sorted(r.label for r in orig.regions)
        reim_labels = sorted(r.label for r in reim.regions)
        if orig_labels != reim_labels:
            result.diffs.append(RTDiff(
                image_name=stem,
                field="labels",
                expected=", ".join(orig_labels) or "(none)",
                actual=", ".join(reim_labels) or "(none)",
            ))

        # Compare bboxes (within tolerance)
        if fmt in ("yolo", "voc", "coco", "labelme"):
            _compare_bboxes(orig, reim, result)

        # Compare VLM fields
        if fmt in ("llava", "sharegpt", "swift"):
            if orig.caption and not reim.caption:
                result.diffs.append(RTDiff(
                    image_name=stem,
                    field="caption",
                    expected=orig.caption[:80],
                    actual="(empty)",
                ))


def _compare_bboxes(orig: Sample, reim: Sample,
                    result: RoundTripResult, tol: float = 2.0) -> None:
    """Compare bounding boxes with a pixel tolerance."""
    orig_bbs = [r.ensure_bbox() for r in orig.regions if r.ensure_bbox()]
    reim_bbs = [r.ensure_bbox() for r in reim.regions if r.ensure_bbox()]

    if len(orig_bbs) != len(reim_bbs):
        return  # already flagged by region_count

    # Sort by (x1, y1) for stable comparison
    orig_sorted = sorted(orig_bbs, key=lambda b: (b.x1, b.y1))
    reim_sorted = sorted(reim_bbs, key=lambda b: (b.x1, b.y1))

    for ob, rb in zip(orig_sorted, reim_sorted):
        dx = max(abs(ob.x1 - rb.x1), abs(ob.x2 - rb.x2))
        dy = max(abs(ob.y1 - rb.y1), abs(ob.y2 - rb.y2))
        if dx > tol or dy > tol:
            result.diffs.append(RTDiff(
                image_name=orig.image_path.stem,
                field="bbox_coords",
                expected=f"({ob.x1:.1f},{ob.y1:.1f},{ob.x2:.1f},{ob.y2:.1f})",
                actual=f"({rb.x1:.1f},{rb.y1:.1f},{rb.x2:.1f},{rb.y2:.1f})",
            ))
            break  # one diff per image is enough
