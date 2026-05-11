"""Image-pair inference helpers.

Pure Python utilities for turning an ordinary SampleSet into image-pair
samples. The GUI can later grow a manual pair editor; this keeps the
current image-pair preset closed for common paired-folder layouts.
"""
from __future__ import annotations

import csv
import os
import re
from pathlib import Path

from .unified import Sample, SampleSet


_PAIR_SUFFIX_RE = re.compile(
    r"([_\-\s]?(a|b|left|right|before|after|source|target|src|dst|1|2))$",
    re.IGNORECASE,
)


def infer_pairs(sample_set: SampleSet) -> SampleSet:
    """Populate missing ``pair_path`` values by filename stem.

    Supported inputs:
    - ``pairs.csv`` at the common dataset root with ``image_a,image_b``
    - ``A/foo.jpg`` + ``B/foo.jpg`` (same stem in two folders)
    - ``foo_A.jpg`` + ``foo_B.jpg`` / ``foo_before`` + ``foo_after``

    Existing explicit pair paths are preserved. Reciprocal links are added so
    both images read as complete in the annotation grid. Exporters deduplicate
    reciprocal pairs when writing.
    """
    _apply_pair_manifest(sample_set.samples)

    groups: dict[str, list[Sample]] = {}
    for sample in sample_set.samples:
        groups.setdefault(_pair_key(sample.image_path), []).append(sample)

    for samples in groups.values():
        if len(samples) < 2:
            continue
        samples.sort(key=lambda s: str(s.image_path).lower())
        # Pair adjacent samples. For the common two-view case this creates
        # reciprocal links; for larger groups it forms stable pairs.
        for i in range(0, len(samples) - 1, 2):
            a = samples[i]
            b = samples[i + 1]
            if a.pair_path is None:
                a.pair_path = b.image_path
            if b.pair_path is None:
                b.pair_path = a.image_path
            if not a.has_label:
                a.has_label = True
            if not b.has_label:
                b.has_label = True
    return sample_set


def _apply_pair_manifest(samples: list[Sample]) -> None:
    if not samples:
        return
    try:
        root = Path(os.path.commonpath([str(s.image_path) for s in samples]))
    except (OSError, ValueError):
        return
    manifest = root / "pairs.csv"
    if not manifest.exists() and root.is_file():
        manifest = root.parent / "pairs.csv"
    if not manifest.exists():
        return

    by_path: dict[str, Sample] = {
        _norm_path(s.image_path): s for s in samples
    }
    try:
        with manifest.open("r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                a_raw = row.get("image_a") or row.get("a") or row.get("left")
                b_raw = row.get("image_b") or row.get("b") or row.get("right")
                if not a_raw or not b_raw:
                    continue
                a = by_path.get(_norm_path((manifest.parent / a_raw).resolve()))
                b = by_path.get(_norm_path((manifest.parent / b_raw).resolve()))
                if a is None or b is None:
                    continue
                a.pair_path = b.image_path
                b.pair_path = a.image_path
                a.has_label = True
                b.has_label = True
    except OSError:
        return


def _norm_path(path: Path) -> str:
    return str(Path(path).resolve()).lower()


def unique_pair_samples(samples: list[Sample]) -> list[Sample]:
    """Return one representative Sample per complete pair."""
    out: list[Sample] = []
    seen: set[tuple[str, str]] = set()
    for sample in samples:
        if sample.pair_path is None:
            continue
        key = tuple(sorted((str(sample.image_path), str(sample.pair_path))))
        if key in seen:
            continue
        seen.add(key)
        out.append(sample)
    return out


def _pair_key(path: Path) -> str:
    stem = path.stem.strip().lower()
    stem = _PAIR_SUFFIX_RE.sub("", stem)
    return stem or path.stem.strip().lower()
