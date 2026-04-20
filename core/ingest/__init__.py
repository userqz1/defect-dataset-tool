"""Ingest module — batch import, classify, and land images into a dataset.

Per DataForge-设计方案-v1.2 §6, the ingest pipeline has three phases:

1. ``discover(source_dirs)`` → list of image paths
2. ``preview(paths, rule)`` → IngestPreview (dry-run)
3. ``execute(preview, target_root)`` → IngestResult (copy files)

After execute, the caller should ``core.dataset.scan_dataset(target_root)``
to build an indexed Dataset, then optionally chain quality + dedup checks.

Public API::

    from core.ingest import discover, preview, execute
    from core.ingest import RULES, ByFilenamePrefixRule, BySubdirRule

    paths = discover([Path("/raw/data")])
    pv = preview(paths, RULES["by_filename_prefix"])
    print(pv.categories)  # {'crack': [PosixPath(...)], 'good': [...]}
    result = execute(pv, Path("/datasets/project1"))
"""
from .rules import (
    RULES,
    ByExifDateRule,
    ByFilenamePrefixRule,
    BySubdirRule,
    ClassificationResult,
    ClassificationRule,
    ManualRule,
)
from .runner import (
    IngestPreview,
    IngestResult,
    discover,
    execute,
    execute_with_checks,
    preview,
)

__all__ = [
    "RULES",
    "ByExifDateRule",
    "ByFilenamePrefixRule",
    "BySubdirRule",
    "ClassificationResult",
    "ClassificationRule",
    "IngestPreview",
    "IngestResult",
    "ManualRule",
    "discover",
    "execute",
    "execute_with_checks",
    "preview",
]
