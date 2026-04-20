"""Ingest runner — discover → preview → execute pipeline.

Three-phase design (DataForge-设计方案-v1.2 §6.2, §6.6):

1. **discover**: scan one or more source directories for images.
2. **preview**: apply a ClassificationRule to get a dry-run of which images
   go into which category — no files are touched.
3. **execute**: copy images into ``<target_root>/<category>/images/``
   following the standard dataset layout. Always copies (never moves)
   by default (§4.4 rule "默认复制不移动").

After execute, the caller should run ``core.dataset.scan_dataset`` on the
target root to build an indexed Dataset, then optionally
``core.quality.check_images`` + ``core.dedup.find_duplicates`` (§6.4).

Pure Python — no PyQt, no GUI imports.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..config import image_extensions
from .rules import ClassificationResult, ClassificationRule


# ---------- Data types ----------

@dataclass
class IngestPreview:
    """Dry-run result: what *would* happen if executed.

    ``categories`` maps category name → list of image paths that would be
    placed there. ``skipped`` lists images that the rule couldn't classify
    or that failed validation.
    """

    rule_name: str
    total_images: int = 0
    categories: dict[str, list[Path]] = field(default_factory=dict)
    skipped: list[tuple[Path, str]] = field(default_factory=list)

    @property
    def category_count(self) -> int:
        return len(self.categories)

    @property
    def placed_count(self) -> int:
        return sum(len(v) for v in self.categories.values())


@dataclass
class IngestResult:
    """Actual execution result.

    ``dataset`` / ``quality_issues`` / ``duplicate_groups`` are populated
    only by ``execute_with_checks``; plain ``execute`` leaves them ``None``.
    """

    copied: int = 0
    skipped: list[tuple[Path, str]] = field(default_factory=list)
    target_root: Path = field(default_factory=lambda: Path("."))
    # Populated by execute_with_checks (§6.4 integration)
    dataset: "object | None" = None            # core.models.Dataset
    quality_issues: "list | None" = None       # list[core.quality.QualityIssue]
    duplicate_groups: "list | None" = None     # list[core.dedup.DuplicateGroup]


# ---------- Phase 1: Discover ----------

def discover(
    source_dirs: list[Path],
    *,
    recursive: bool = True,
    extensions: set[str] | None = None,
) -> list[Path]:
    """Recursively scan directories for image files.

    Returns absolute, deduplicated paths sorted by name.
    ``extensions`` defaults to ``core.config.image_extensions()``.
    """
    exts = extensions or image_extensions()
    seen: set[Path] = set()
    result: list[Path] = []

    for src in source_dirs:
        src = Path(src)
        if not src.is_dir():
            continue
        walker = src.rglob("*") if recursive else src.iterdir()
        for entry in walker:
            if not entry.is_file():
                continue
            if entry.suffix.lower() not in exts:
                continue
            resolved = entry.resolve()
            if resolved not in seen:
                seen.add(resolved)
                result.append(entry)

    result.sort(key=lambda p: p.name.lower())
    return result


# ---------- Phase 2: Preview ----------

def preview(
    image_paths: list[Path],
    rule: ClassificationRule,
) -> IngestPreview:
    """Classify images without touching any files.

    Returns an ``IngestPreview`` that the GUI can display as a table
    (category → count) before the user confirms.
    """
    results = rule.classify(image_paths)
    cats: dict[str, list[Path]] = {}
    skipped: list[tuple[Path, str]] = []

    for cr in results:
        cat = (cr.suggested_category or "").strip()
        if not cat:
            skipped.append((cr.image_path, "empty category"))
            continue
        cats.setdefault(cat, []).append(cr.image_path)

    return IngestPreview(
        rule_name=rule.name,
        total_images=len(image_paths),
        categories=cats,
        skipped=skipped,
    )


# ---------- Phase 3: Execute ----------

def execute(
    pv: IngestPreview,
    target_root: Path,
    *,
    copy: bool = True,
    progress_cb: Callable[[int, int, str], None] | None = None,
) -> IngestResult:
    """Copy (or move) images into the standard dataset layout.

    Layout::

        <target_root>/
        ├── <category_a>/
        │   └── images/
        │       └── *.jpg
        └── <category_b>/
            └── images/
                └── *.jpg

    The ``labels/`` subdirectory is created empty — annotation happens later
    in the annotate phase.
    """
    result = IngestResult(target_root=target_root)
    target_root = Path(target_root)
    target_root.mkdir(parents=True, exist_ok=True)

    total = pv.placed_count
    done = 0
    op = shutil.copy2 if copy else shutil.move

    for category, paths in pv.categories.items():
        img_dir = target_root / category / "images"
        lbl_dir = target_root / category / "labels"
        img_dir.mkdir(parents=True, exist_ok=True)
        lbl_dir.mkdir(parents=True, exist_ok=True)

        for src in paths:
            done += 1
            if progress_cb:
                progress_cb(done, total, src.name)
            try:
                dst = img_dir / src.name
                # Avoid overwriting — append _N suffix if name clashes
                if dst.exists():
                    dst = _unique(dst)
                op(str(src), str(dst))
                result.copied += 1
            except Exception as e:  # noqa: BLE001
                result.skipped.append((src, str(e)))

    if progress_cb:
        progress_cb(total, total, "")
    return result


def _unique(path: Path) -> Path:
    """Append _1, _2, … to avoid overwrite."""
    i = 1
    while True:
        cand = path.with_name(f"{path.stem}_{i}{path.suffix}")
        if not cand.exists():
            return cand
        i += 1


# ---------- Phase 3+: Orchestrated execute + checks (§6.4) ----------

def execute_with_checks(
    pv: IngestPreview,
    target_root: Path,
    *,
    copy: bool = True,
    run_quality: bool = True,
    run_dedup: bool = True,
    progress_cb: Callable[[int, int, str], None] | None = None,
) -> IngestResult:
    """Copy + scan + quality + dedup, all in one pass.

    The default integration for the organize view (v1.2 §6.4):
    1. ``execute`` — copy files into standard layout
    2. ``scan_dataset`` — build an indexed Dataset on the target
    3. (optional) ``check_images`` — quality issues
    4. (optional) ``find_duplicates`` — near-duplicate groups

    Progress is reported per-phase with the phase name prefix (e.g.
    ``"复制 · foo.jpg"``, ``"质检 · bar.jpg"``). The caller's progress
    dialog resets its bar at each phase transition — this is intentional,
    because the phases have different total counts (copy = N images,
    quality + dedup = only the successfully copied subset).
    """
    def _phased(prefix: str):
        if progress_cb is None:
            return None
        return lambda d, t, n: progress_cb(d, t, f"{prefix} · {n}" if n else prefix)

    # Phase 1: copy
    result = execute(pv, target_root, copy=copy, progress_cb=_phased("复制"))

    # Phase 2: scan (cheap, just one callback tick)
    if progress_cb:
        progress_cb(0, 1, "扫描数据集")
    from ..dataset import scan_dataset
    ds = scan_dataset(Path(target_root))
    result.dataset = ds

    all_images = [img for c in ds.categories for img in c.images]
    if not all_images:
        return result  # nothing to check

    # Phase 3: quality
    if run_quality:
        from ..quality import check_images
        result.quality_issues = check_images(all_images, progress_cb=_phased("质检"))

    # Phase 4: dedup
    if run_dedup:
        from ..dedup import find_duplicates
        result.duplicate_groups = find_duplicates(all_images, progress_cb=_phased("去重"))

    if progress_cb:
        progress_cb(1, 1, "")
    return result
