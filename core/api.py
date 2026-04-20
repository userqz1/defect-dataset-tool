"""DataForge public API — stable facade for GUI / CLI / future consumers.

Per DataForge-设计方案-v1.2 §3.3 + §15.1 step 8, ``core/`` exposes a
single public surface so frontends can depend on ``core.api`` without
reaching into submodules. The internal module layout is private and may
refactor between minor versions without breaking API consumers.

v0.1 is additive: existing code that imports from ``core.schema``,
``core.ingest``, etc. keeps working. New code should prefer ``core.api``
so the v0.2 three-package split (``dataforge-core`` / ``dataforge-cli`` /
``dataforge``) lands without rewriting imports.

Surface overview::

    from core import api

    # --- Discover / scan ---
    images  = api.discover([Path("/raw")])
    dataset = api.scan_dataset(Path("/data/project1"))

    # --- Classify + import ---
    pv     = api.preview(images, api.INGEST_RULES["by_filename_prefix"])
    result = api.execute_with_checks(pv, Path("/data/new"))

    # --- Export (Schema-driven) ---
    schema = api.get_schema("YOLO")
    report = schema.validate(dataset)
    if report.ready:
        split = api.split_dataset(dataset, api.SplitOptions())
        schema.writer(split, schema.options_class(out_dir=Path("/out")))

    # --- Task-level readiness ---
    task_report = api.check_task_readiness(dataset, api.TaskType.DETECTION)
"""
from __future__ import annotations

# ---- Scan / models ----
from .dataset import scan_dataset
from .models import Annotation, Category, Dataset, ImageInfo, Shape

# ---- Task types + readiness ----
from .task_readiness import (
    ReadinessCheck,
    TaskReadinessReport,
    check_task_readiness,
)
from .task_types import TASK_REGISTRY, TaskType, TaskTypeInfo, get_task_info

# ---- Schemas (format-level compliance + export) ----
from .schema import (
    ComplianceReport,
    Schema,
    Slot,
    SlotKind,
    SlotStatus,
    all_schemas,
    schemas_for_task,
)
from .schema import get as get_schema

# ---- Ingest (batch import → classify → land) ----
from .ingest import (
    ClassificationResult,
    ClassificationRule,
    IngestPreview,
    IngestResult,
    discover,
    execute,
    execute_with_checks,
    preview,
)
from .ingest import RULES as INGEST_RULES

# ---- Quality / dedup (§6.4) ----
from .dedup import DuplicateGroup, find_duplicates
from .quality import QualityIssue, QualityOptions, check_images

# ---- Split ----
from .splitter import SplitOptions, SplitResult, split_dataset

# ---- Annotation I/O ----
from .annotation_formats import parse_annotation
from .annotation_writer import write_annotation

# ---- Pipeline (v1.2 §4.3 + §7, memory-level; YAML is v0.2) ----
from .pipeline import (
    DedupStep,
    ExportStep,
    IngestStep,
    Pipeline,
    PipelineContext,
    PipelineResult,
    QualityStep,
    ScanStep,
    SplitStep,
    Step,
)


__all__ = [
    # Scan / models
    "Annotation", "Category", "Dataset", "ImageInfo", "Shape",
    "scan_dataset",
    # Task types
    "TASK_REGISTRY", "TaskType", "TaskTypeInfo", "get_task_info",
    "ReadinessCheck", "TaskReadinessReport", "check_task_readiness",
    # Schemas
    "ComplianceReport", "Schema", "Slot", "SlotKind", "SlotStatus",
    "all_schemas", "get_schema", "schemas_for_task",
    # Ingest
    "INGEST_RULES", "ClassificationResult", "ClassificationRule",
    "IngestPreview", "IngestResult",
    "discover", "execute", "execute_with_checks", "preview",
    # Quality / dedup
    "QualityIssue", "QualityOptions", "check_images",
    "DuplicateGroup", "find_duplicates",
    # Split
    "SplitOptions", "SplitResult", "split_dataset",
    # Annotation I/O
    "parse_annotation", "write_annotation",
    # Pipeline
    "Pipeline", "PipelineContext", "PipelineResult", "Step",
    "DedupStep", "ExportStep", "IngestStep",
    "QualityStep", "ScanStep", "SplitStep",
]
