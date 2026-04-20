"""Schema registry — single source of truth for export formats.

Per DataForge-设计方案-v1.2.md §5.5, built-in schemas register themselves
here at import time. Any UI surface that needs "the list of export formats"
or "the schema for format X" must go through this module rather than
importing individual schema modules directly.

Public API::

    from core.schema import get, all_schemas, schemas_for_task

    yolo = get("YOLO")                          # Schema | None
    every = all_schemas()                       # list[Schema]
    for_det = schemas_for_task(TaskType.DETECTION)

Ten schemas registered as of the v1.2 unification (review #4+#14 retired
the separate ``core.exporter.registry`` table). v0.1 §14.3 mainline set is
YOLO / COCO / VOC / ImageFolder / MVTec / ShareGPT; CSV / JSONL / LLaVA /
Swift come along for the ride because their writers already existed.
"""
from __future__ import annotations

from ..task_types import TaskType
from .base import ComplianceReport, Schema, Slot, SlotKind, SlotStatus
from .coco import COCO_SCHEMA
from .csv import CSV_SCHEMA
from .imagefolder import IMAGEFOLDER_SCHEMA
from .jsonl import JSONL_SCHEMA
from .llava import LLAVA_SCHEMA
from .mvtec import MVTEC_SCHEMA
from .sharegpt import SHAREGPT_SCHEMA
from .swift import SWIFT_SCHEMA
from .voc import VOC_SCHEMA
from .yolo import YOLO_SCHEMA


_REGISTRY: dict[str, Schema] = {}


def register(schema: Schema) -> None:
    """Register a schema. Later registrations with the same key overwrite."""
    _REGISTRY[schema.key] = schema


def get(key: str) -> Schema | None:
    """Look up a schema by key. Returns None for unknown keys."""
    return _REGISTRY.get(key)


def all_schemas() -> list[Schema]:
    """Every registered schema, in registration order."""
    return list(_REGISTRY.values())


def schemas_for_task(task_type: TaskType) -> list[Schema]:
    """Schemas that declare support for the given task type."""
    return [s for s in _REGISTRY.values() if task_type in s.task_types]


# ---------- built-in registrations ----------
# Order matters only for all_schemas()/UI enumeration: CV mainline first
# (§1.2 "80% users"), generic tabular/flat middle, VLM specialties last.

register(YOLO_SCHEMA)
register(COCO_SCHEMA)
register(VOC_SCHEMA)
register(IMAGEFOLDER_SCHEMA)
register(MVTEC_SCHEMA)
register(CSV_SCHEMA)
register(JSONL_SCHEMA)
register(SHAREGPT_SCHEMA)
register(LLAVA_SCHEMA)
register(SWIFT_SCHEMA)


__all__ = [
    "ComplianceReport",
    "Schema",
    "Slot",
    "SlotKind",
    "SlotStatus",
    "all_schemas",
    "get",
    "register",
    "schemas_for_task",
]
