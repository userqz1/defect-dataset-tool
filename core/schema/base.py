"""Schema base types — Slot / SlotStatus / ComplianceReport / Schema.

Defines the core contract between export formats and the rest of the app,
per DataForge-设计方案-v1.2.md §5.2-§5.4.

Every export format (YOLO, COCO, VOC, ImageFolder, MVTec, ShareGPT…) is a
``Schema`` instance declaring:

- **slots**: what pieces the target format needs (images, labels, split…)
- **validator** (per slot): does the current Dataset fill this slot?
- **writer**: how to produce the format on disk
- **options_class**: the dataclass used to configure writer kwargs

``Schema.validate(dataset)`` returns a ``ComplianceReport`` — the single
interface any UI component must use to ask "can this dataset export as X?".

Pure Python — no PyQt, no GUI imports.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal

from ..models import Dataset
from ..task_types import TaskType


# Per §5.3 rule 3: fixed kind enumeration.
SlotKind = Literal["images", "labels", "split", "meta", "config"]


@dataclass(frozen=True)
class SlotStatus:
    """Result of a single slot validator call.

    Returned by ``Slot.validator(dataset)``. Keeps human-readable strings
    so the UI can display them directly without re-computing formats.
    """

    ok: bool
    current_text: str = ""   # what the dataset currently has, e.g. "1,234 张"
    required_text: str = ""  # what the format requires, e.g. "≥ 1"
    action_text: str = ""    # fix suggestion, e.g. "导入图片"
    fix_command: str = ""    # machine-readable fix target, e.g. "ingest" (optional)
    count: int = 0           # for progress bars
    target: int = 0          # for progress bars (0 = not applicable)

    @property
    def progress(self) -> float:
        """0.0 ~ 1.0 fill progress."""
        if self.ok:
            return 1.0
        if self.target > 0 and self.count > 0:
            return min(self.count / self.target, 0.99)
        return 0.0


@dataclass(frozen=True)
class Slot:
    """One requirement slot in a target format."""

    key: str                                      # machine id, e.g. "images"
    name: str                                     # UI label, e.g. "图片"
    kind: SlotKind
    required: bool
    validator: Callable[[Dataset], SlotStatus]


@dataclass
class ComplianceReport:
    """Full compliance report for one (Schema, Dataset) pair.

    Per §5.4: this is the *only* interface the rest of the app uses to ask
    whether a dataset can export as a given format.
    """

    schema_key: str
    results: list[tuple[Slot, SlotStatus]] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        """True iff every required slot is ok."""
        return all(status.ok for slot, status in self.results if slot.required)

    @property
    def required_count(self) -> int:
        return sum(1 for slot, _ in self.results if slot.required)

    @property
    def required_filled(self) -> int:
        return sum(1 for slot, status in self.results if slot.required and status.ok)

    def missing(self) -> list[Slot]:
        """Required slots that are not yet ok."""
        return [slot for slot, status in self.results if slot.required and not status.ok]

    @property
    def progress_text(self) -> str:
        return f"{self.required_filled}/{self.required_count}"


@dataclass(frozen=True)
class Schema:
    """One export format's full declaration.

    Registered in ``core.schema`` registry; every UI surface (export wizard,
    CLI ``check``, pipeline ``export`` step) loads schemas through that
    registry rather than holding if/elif chains.
    """

    key: str                                   # machine id, e.g. "YOLO"
    display_name: str                          # UI label, e.g. "YOLO (Ultralytics)"
    description: str                           # one-line tooltip
    task_types: tuple[TaskType, ...]           # which TaskTypes this schema serves
    slots: tuple[Slot, ...]
    options_class: type                        # writer kwargs dataclass
    writer: Callable                           # (split, opts, progress_cb) -> ExportReport
    directory_preview: str = ""                # output tree preview for wizard
    docs_url: str = ""                         # external docs link

    def validate(self, dataset: Dataset) -> ComplianceReport:
        """Run every slot's validator against the dataset."""
        results = [(slot, slot.validator(dataset)) for slot in self.slots]
        return ComplianceReport(schema_key=self.key, results=results)
