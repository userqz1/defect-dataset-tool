"""Processing node system — re-exports for backward compatibility.

All existing ``from core.nodes import NODES, StepResult`` imports continue to work.
"""
from .base import (
    CATEGORY_META,
    CategoryMeta,
    ParamDef,
    PortDef,
    ProcessingNode,
    ProgressCb,
    StepResult,
    _default_route,
)
from .clean import DedupNode, QualityCheckNode
from .io import DataSourceNode, ExportNode, SplitNode
from .transform import AugmentNode, PredictNode

NODES: dict[str, ProcessingNode] = {
    "data_source": DataSourceNode(),
    "quality_check": QualityCheckNode(),
    "dedup": DedupNode(),
    "augment": AugmentNode(),
    "predict": PredictNode(),
    "split": SplitNode(),
    "export": ExportNode(),
}
"""All available processing nodes, keyed by name."""

__all__ = [
    "NODES",
    "CATEGORY_META",
    "CategoryMeta",
    "ParamDef",
    "PortDef",
    "ProcessingNode",
    "ProgressCb",
    "StepResult",
    "_default_route",
    "QualityCheckNode",
    "DedupNode",
    "AugmentNode",
    "PredictNode",
    "DataSourceNode",
    "SplitNode",
    "ExportNode",
]
