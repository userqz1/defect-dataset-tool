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
    ByExifDateRule,
    ByFilenamePrefixRule,
    BySubdirRule,
    ClassificationResult,
    ClassificationRule,
    IngestPreview,
    IngestResult,
    ManualRule,
    discover,
    execute,
    execute_with_checks,
    preview,
)
from .ingest import RULES as INGEST_RULES

# ---- Quality / dedup (§6.4) ----
from .dedup import DuplicateGroup, find_duplicates, find_duplicates_from_samples
from .quality import QualityIssue, QualityOptions, check_annotations, check_images

# ---- Split ----
from .splitter import SplitOptions, SplitResult, split_dataset

# ---- Project ----
from .project import WRITEBACK_FORMATS

# ---- Annotation I/O (legacy per-file) ----
from .annotation_formats import parse_annotation
from .annotation_writer import write_annotation

# ---- Unified annotation model + format hub ----
from .unified import BBox, Region, Sample, SampleSet
from .format_in import load_sample, load_samples, load_samples_from_split, load_vlm_jsonl
from .format_out import (
    ExportOptions as UnifiedExportOptions,
    ExportResult as UnifiedExportResult,
    available_formats as unified_formats,
    export_samples,
)
from .format_convert import (
    ConversionHint,
    FieldSupport,
    FormatInfo,
    FORMATS as FORMAT_REGISTRY,
    available_export_formats,
    available_import_formats,
    conversion_hints,
    format_display_name,
    writeback_formats,
)
from .format_rt import RoundTripResult, RTDiff, validate_roundtrip
from .annotation_writer import label_path_for_format, write_annotation_as

# ---- Training versions ----
from .version_builder import (
    TrainingVersionConfig,
    TrainingVersionResult,
    TrainingVersionSummary,
    build_training_version,
    delete_training_version,
    list_training_versions,
)

# ---- History / undo MVP ----
from .history import (
    HistoryEntry,
    append as history_append,
    find_last_undoable,
    read_recent as read_history,
    try_undo_last,
)


# ---- Convenience: schema-driven export dispatcher ----
# (Replaces the v0.1 ``core.exporter.registry.run_export`` helper now that
# Schema is the single source of truth — review #4+#14.)
def run_export(key: str, split, out_dir, copy_images: bool = True,
               progress_cb=None, **extra_options):
    """Run a Schema's writer in one call. Raises ValueError for unknown keys.

    Thin wrapper: fetches Schema by key, builds its options_class with
    out_dir + copy_images (if declared) + any extra kwargs a specific
    schema supports (e.g. ``question`` for LLaVA/Swift/ShareGPT).
    """
    schema = get_schema(key)
    if schema is None:
        raise ValueError(f"未知导出格式: {key}")
    opt_fields = schema.options_class.__dataclass_fields__
    kwargs = {"out_dir": out_dir}
    if "copy_images" in opt_fields:
        kwargs["copy_images"] = copy_images
    for name, value in extra_options.items():
        if name in opt_fields:
            kwargs[name] = value
    options = schema.options_class(**kwargs)
    return schema.writer(split, options, progress_cb=progress_cb)


# ---- Workflow (production lifecycle) ----
from .workflow import (
    WorkflowState,
    WorkflowSummary,
    WorkItem,
    WorkStatus,
    sync_samples as sync_workflow_to_samples,
)

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
    "TrainingVersionConfig", "TrainingVersionResult",
    "TrainingVersionSummary", "build_training_version",
    "list_training_versions", "delete_training_version",
    # Task types
    "TASK_REGISTRY", "TaskType", "TaskTypeInfo", "get_task_info",
    "ReadinessCheck", "TaskReadinessReport", "check_task_readiness",
    # Schemas
    "ComplianceReport", "Schema", "Slot", "SlotKind", "SlotStatus",
    "all_schemas", "get_schema", "schemas_for_task",
    # Ingest
    "INGEST_RULES", "ClassificationResult", "ClassificationRule",
    "IngestPreview", "IngestResult",
    "ByExifDateRule", "ByFilenamePrefixRule", "BySubdirRule", "ManualRule",
    "discover", "execute", "execute_with_checks", "preview",
    # Quality / dedup
    "QualityIssue", "QualityOptions", "check_annotations", "check_images",
    "DuplicateGroup", "find_duplicates", "find_duplicates_from_samples",
    # Split
    "SplitOptions", "SplitResult", "split_dataset",
    # Annotation I/O
    "parse_annotation", "write_annotation",
    # History / undo
    "HistoryEntry", "history_append", "read_history",
    "find_last_undoable", "try_undo_last",
    # Export dispatcher
    "run_export",
    # Unified model + format hub
    "BBox", "Region", "Sample", "SampleSet",
    "load_sample", "load_samples", "load_vlm_jsonl",
    "UnifiedExportOptions", "UnifiedExportResult",
    "export_samples", "unified_formats",
    # Format center
    "ConversionHint", "FieldSupport", "FormatInfo", "FORMAT_REGISTRY",
    "available_export_formats", "available_import_formats",
    "conversion_hints", "format_display_name", "writeback_formats",
    "RoundTripResult", "RTDiff", "validate_roundtrip",
    "label_path_for_format", "write_annotation_as",
    # Workflow
    "WorkflowState", "WorkflowSummary", "WorkItem", "WorkStatus",
    "sync_workflow_to_samples",
    # Pipeline
    "Pipeline", "PipelineContext", "PipelineResult", "Step",
    "DedupStep", "ExportStep", "IngestStep",
    "QualityStep", "ScanStep", "SplitStep",
]
