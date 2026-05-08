"""Bulk region-text fill — apply one template to many regions at once.

Solves the "I have 2 000 Loose images and want every Loose region to
share the same grounding caption" workflow that the per-image
AnnotationPane editor doesn't scale to.

The function mutates the in-memory SampleSet **and** persists each
affected sample's grounding to its sidecar JSON, so the LLM-data card's
status counts refresh on the next ``sample_set_changed`` re-broadcast
and the export pipeline sees the new text immediately.

Pure Python — no PyQt, no GUI imports.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .annotation_writer import write_grounding
from .unified import SampleSet


@dataclass
class BulkFillResult:
    affected_images: int = 0      # samples we touched (regions changed)
    affected_regions: int = 0     # individual regions whose text changed
    skipped_no_regions: int = 0   # samples with 0 regions — nothing to fill
    skipped_already_filled: int = 0  # regions skipped because text was set
    failed: list[tuple[str, str]] = None  # [(image_path_str, error_msg), ...]

    def __post_init__(self) -> None:
        if self.failed is None:
            self.failed = []


def bulk_fill_region_text(
    sample_set: SampleSet,
    template: str,
    *,
    category: str = "",
    overwrite: bool = False,
    progress_cb: Callable[[int, int, str], None] | None = None,
) -> BulkFillResult:
    """Apply *template* to every region of every matching sample.

    Args:
        sample_set: Live SampleSet from AppState.  Mutated in place.
        template:   The Chinese text to fill into ``Region.text``.
        category:   When non-empty, only samples whose ``category``
                    matches are affected.  Empty = whole dataset.
        overwrite:  When True, every region's text is replaced.  When
                    False (default), regions with non-empty text are
                    left untouched and counted in
                    ``skipped_already_filled``.
        progress_cb: ``(done, total, image_name)`` — called after each
                     sample is processed (whether changed or skipped).

    Returns a :class:`BulkFillResult` with per-bucket counts so the
    caller can surface a useful "applied to N images / M regions"
    summary.

    Persistence: each sample whose regions changed gets its grounding
    sidecar (`<stem>.grounding.json`) rewritten via
    :func:`core.annotation_writer.write_grounding`.  ``Sample.grounding``
    is also rebuilt so the LLM-data card's counts reflect reality.
    """
    template = (template or "").strip()
    if not template:
        return BulkFillResult()

    # Pre-filter to "in-scope" samples so total count matches what the
    # user picked, not "everything in the SampleSet".
    in_scope = [s for s in sample_set.samples
                if (not category) or s.category == category]
    total = len(in_scope)
    result = BulkFillResult()

    for idx, sample in enumerate(in_scope):
        if progress_cb is not None:
            progress_cb(idx, total, sample.image_path.name)

        if not sample.regions:
            result.skipped_no_regions += 1
            continue

        changed = False
        for r in sample.regions:
            if r.text and not overwrite:
                result.skipped_already_filled += 1
                continue
            r.text = template
            result.affected_regions += 1
            changed = True

        if not changed:
            continue

        # Rebuild sample.grounding from the mutated regions so the
        # LLM-data card's per-region count refreshes on the next
        # sample_set_changed re-broadcast.  Mirrors the entry shape
        # exporters expect: {label, text, bbox(int xyxy)}.
        entries = []
        for r in sample.regions:
            bb = r.ensure_bbox()
            if bb is None or not r.text:
                continue
            entries.append({
                "label": r.label,
                "text": r.text,
                "bbox": [int(round(bb.x1)), int(round(bb.y1)),
                         int(round(bb.x2)), int(round(bb.y2))],
            })
        sample.grounding = entries

        try:
            write_grounding(sample.image_path, entries)
        except OSError as e:
            result.failed.append((str(sample.image_path), str(e)))
            continue

        result.affected_images += 1

    if progress_cb is not None:
        progress_cb(total, total, "")

    return result


def count_fill_scope(
    sample_set: SampleSet,
    category: str = "",
    overwrite: bool = False,
) -> tuple[int, int, int]:
    """Preview the impact of a bulk fill without mutating anything.

    Returns ``(affected_images, affected_regions, would_skip)`` so the
    dialog's live preview line can answer "what happens if I hit
    apply right now".

    - ``affected_images`` — samples that have at least one region
      whose text would be written.
    - ``affected_regions`` — total regions whose text would be written.
    - ``would_skip`` — regions skipped because they already have text
      (only relevant when ``overwrite=False``).
    """
    affected_images = 0
    affected_regions = 0
    would_skip = 0
    for s in sample_set.samples:
        if category and s.category != category:
            continue
        if not s.regions:
            continue
        sample_changed = False
        for r in s.regions:
            if r.text and not overwrite:
                would_skip += 1
                continue
            affected_regions += 1
            sample_changed = True
        if sample_changed:
            affected_images += 1
    return affected_images, affected_regions, would_skip
