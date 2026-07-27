"""Workflow data models — per-image production status tracking.

Separates sample-level work state from the scan-snapshot model
(Dataset/ImageInfo) and from project-level config (Project). This is
the layer that turns DataForge from a "browse & process" tool into a
continuous dataset production workbench.

Pure Python — no PyQt.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class WorkStatus(str, Enum):
    """Per-image production lifecycle status."""
    NEW = "new"
    PRELABELED = "prelabeled"
    ANNOTATING = "annotating"
    REVIEW_PENDING = "review_pending"
    NEEDS_FIX = "needs_fix"
    READY = "ready"
    EXPORTED = "exported"


@dataclass
class WorkItem:
    """One tracked image in the workflow.

    ``relative_path`` is always relative to the project root — never
    absolute. This makes directory relocation and export replay resilient.
    """
    item_id: str
    relative_path: str          # e.g. "defects/images/001.jpg"
    batch_id: str = ""
    status: WorkStatus = WorkStatus.NEW
    category_hint: str = ""     # suggested or assigned category
    has_label: bool = False
    split: str = ""             # "train" / "val" / "test" / ""
    updated_at: str = ""
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "relative_path": self.relative_path,
            "batch_id": self.batch_id,
            "status": self.status.value,
            "category_hint": self.category_hint,
            "has_label": self.has_label,
            "split": self.split,
            "updated_at": self.updated_at,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> WorkItem:
        status = d.get("status", "new")
        try:
            status = WorkStatus(status)
        except ValueError:
            status = WorkStatus.NEW
        return cls(
            item_id=d.get("item_id", ""),
            relative_path=d.get("relative_path", ""),
            batch_id=d.get("batch_id", ""),
            status=status,
            category_hint=d.get("category_hint", ""),
            has_label=d.get("has_label", False),
            split=d.get("split", ""),
            updated_at=d.get("updated_at", ""),
            notes=d.get("notes", ""),
        )


@dataclass
class IngestBatch:
    """A tracked import operation."""
    batch_id: str
    name: str = ""
    created_at: str = ""
    source_dirs: list[str] = field(default_factory=list)
    rule_name: str = ""
    item_count: int = 0

    def to_dict(self) -> dict:
        return {
            "batch_id": self.batch_id,
            "name": self.name,
            "created_at": self.created_at,
            "source_dirs": self.source_dirs,
            "rule_name": self.rule_name,
            "item_count": self.item_count,
        }

    @classmethod
    def from_dict(cls, d: dict) -> IngestBatch:
        return cls(
            batch_id=d.get("batch_id", ""),
            name=d.get("name", ""),
            created_at=d.get("created_at", ""),
            source_dirs=d.get("source_dirs", []),
            rule_name=d.get("rule_name", ""),
            item_count=d.get("item_count", 0),
        )


@dataclass
class WorkflowState:
    """Top-level container persisted to .dataforge/workflow.json."""
    batches: list[IngestBatch] = field(default_factory=list)
    items: list[WorkItem] = field(default_factory=list)
    active_batch_id: str = ""

    def to_dict(self) -> dict:
        return {
            "batches": [b.to_dict() for b in self.batches],
            "items": [i.to_dict() for i in self.items],
            "active_batch_id": self.active_batch_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> WorkflowState:
        return cls(
            batches=[IngestBatch.from_dict(b)
                     for b in d.get("batches", [])],
            items=[WorkItem.from_dict(i)
                   for i in d.get("items", [])],
            active_batch_id=d.get("active_batch_id", ""),
        )


@dataclass
class WorkflowSummary:
    """Pre-computed counts for UI display (dataset bar, welcome cards)."""
    total: int = 0
    new: int = 0
    prelabeled: int = 0
    annotating: int = 0
    review_pending: int = 0
    needs_fix: int = 0
    ready: int = 0
    exported: int = 0
    batch_count: int = 0

    @classmethod
    def from_state(cls, state: WorkflowState) -> WorkflowSummary:
        counts: dict[str, int] = {}
        for item in state.items:
            counts[item.status.value] = counts.get(item.status.value, 0) + 1
        return cls(
            total=len(state.items),
            new=counts.get("new", 0),
            prelabeled=counts.get("prelabeled", 0),
            annotating=counts.get("annotating", 0),
            review_pending=counts.get("review_pending", 0),
            needs_fix=counts.get("needs_fix", 0),
            ready=counts.get("ready", 0),
            exported=counts.get("exported", 0),
            batch_count=len(state.batches),
        )

    @classmethod
    def from_sample_set(cls, sample_set: "SampleSet",
                        batch_count: int = 0) -> WorkflowSummary:
        """Derive summary directly from SampleSet work_status fields.

        More accurate than ``from_state`` after a sync because it only
        counts images that actually exist on disk (SampleSet is built
        from a fresh scan). Dead WorkItems (deleted files) are excluded.
        """
        counts = sample_set.work_status_counts
        total = len(sample_set.samples)
        return cls(
            total=total,
            new=counts.get("new", 0),
            prelabeled=counts.get("prelabeled", 0),
            annotating=counts.get("annotating", 0),
            review_pending=counts.get("review_pending", 0),
            needs_fix=counts.get("needs_fix", 0),
            ready=counts.get("ready", 0),
            exported=counts.get("exported", 0),
            batch_count=batch_count,
        )


# -- Helpers --

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def make_id() -> str:
    return uuid.uuid4().hex[:12]


# -- SampleSet ↔ Workflow sync --

def sync_samples(
    state: WorkflowState,
    sample_set: "SampleSet",
    root: Path,
    *,
    auto_create: bool = True,
) -> bool:
    """Populate ``Sample.work_status`` from the workflow and optionally
    create ``WorkItem`` entries for newly discovered images.

    Returns *True* if *state* was mutated (new items added), in which
    case the caller should persist the updated state.

    Path bridge: ``WorkItem.relative_path`` uses forward slashes relative
    to ``root``; ``Sample.image_path`` is an absolute ``Path``. The
    resolution normalizes both sides to ``posix``-style relative strings.
    """
    from .unified import SampleSet  # avoid circular at module level

    # Build lookup: relative-path (posix) → WorkItem
    path_to_item: dict[str, WorkItem] = {}
    for item in state.items:
        path_to_item[item.relative_path] = item

    mutated = False
    now = _now_iso()

    for sample in sample_set.samples:
        # Resolve sample's image path to a posix relative string
        try:
            rel = sample.image_path.relative_to(root)
        except (ValueError, TypeError):
            # image outside project root — skip
            continue
        rel_posix = rel.as_posix()

        wi = path_to_item.get(rel_posix)
        if wi is not None:
            # Existing tracked item — stamp status onto sample
            sample.work_status = wi.status.value
        elif auto_create:
            # New image discovered by scan — assign initial status.
            # An image counts as "pre-labeled" if it already has any
            # annotation data the project might care about: traditional
            # regions, image-level multi-label tags, OR LLM data
            # (caption / conversations / grounding).  Looking only at
            # ``sample.regions`` mis-classifies LLM-only annotated
            # images as NEW and undercounts the pre-labeled bucket.
            has_traditional = bool(sample.regions or sample.image_labels)
            has_llm = bool(
                (sample.caption or "").strip()
                or sample.conversations
                or sample.grounding
            )
            initial = (
                WorkStatus.PRELABELED if (has_traditional or has_llm)
                else WorkStatus.NEW
            )
            new_item = WorkItem(
                item_id=make_id(),
                relative_path=rel_posix,
                status=initial,
                category_hint=sample.category,
                has_label=sample.has_label,
                split=sample.split,
                updated_at=now,
            )
            state.items.append(new_item)
            path_to_item[rel_posix] = new_item
            sample.work_status = initial.value
            mutated = True
        else:
            sample.work_status = ""

    return mutated
