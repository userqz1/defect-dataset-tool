"""Pipeline package — ordered Step list + executor.

See ``core.pipeline.base`` for the protocol + executor,
``core.pipeline.steps`` for built-in Step implementations.

YAML serialization is intentionally absent in v0.1 (see v1.2 §14.3).
v0.2 adds a ``load_pipeline(path)`` / ``save_pipeline(p, path)`` pair
that maps YAML dicts to Step constructors via a ``kind`` registry.
"""
from .base import (
    Pipeline,
    PipelineContext,
    PipelineResult,
    ProgressCb,
    Step,
)
from .steps import (
    DedupStep,
    ExportStep,
    IngestStep,
    QualityStep,
    ScanStep,
    SplitStep,
)

__all__ = [
    # Core abstractions
    "Pipeline", "PipelineContext", "PipelineResult", "ProgressCb", "Step",
    # Built-in steps
    "DedupStep", "ExportStep", "IngestStep",
    "QualityStep", "ScanStep", "SplitStep",
]
