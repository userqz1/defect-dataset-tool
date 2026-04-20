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

v0.1 ships the six schemas called out in §14.3: YOLO / COCO / VOC /
ImageFolder / MVTec / ShareGPT.
"""
from __future__ import annotations

from ..task_types import TaskType
from .base import ComplianceReport, Schema, Slot, SlotKind, SlotStatus
from .coco import COCO_SCHEMA
from .imagefolder import IMAGEFOLDER_SCHEMA
from .mvtec import MVTEC_SCHEMA
from .sharegpt import SHAREGPT_SCHEMA
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
# Order matters only for all_schemas()/UI enumeration; keep CV mainline
# (§1.2 "80% users") before VLM differentiation (§1.2 "20% users").

register(YOLO_SCHEMA)
register(COCO_SCHEMA)
register(VOC_SCHEMA)
register(IMAGEFOLDER_SCHEMA)
register(MVTEC_SCHEMA)
register(SHAREGPT_SCHEMA)


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
