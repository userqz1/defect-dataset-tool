"""Built-in Pipeline Steps — thin wrappers over core operations.

Each Step is a frozen dataclass holding its parameters. ``execute`` reads
the ``PipelineContext``, calls into the corresponding core module, and
writes results back to the context.

v0.1 ships 6 built-in kinds (DataForge-设计方案-v1.2 §7.2):

- ``IngestStep``  — wraps ``core.ingest.execute_with_checks``
- ``ScanStep``    — wraps ``core.dataset.scan_dataset`` (re-index only)
- ``QualityStep`` — wraps ``core.quality.check_images``
- ``DedupStep``   — wraps ``core.dedup.find_duplicates``
- ``SplitStep``   — wraps ``core.splitter.split_dataset``
- ``ExportStep``  — wraps ``Schema.writer`` (Schema-driven, v1.2 §5.5)

Adding a new Step: implement the ``core.pipeline.base.Step`` protocol —
a frozen dataclass with ``name`` + ``kind`` + ``execute`` does the job.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .base import PipelineContext, ProgressCb


# ---------- Ingest ----------

@dataclass(frozen=True)
class IngestStep:
    """Discover → preview → execute_with_checks.

    Populates ``ctx.dataset`` / ``ctx.quality_issues`` / ``ctx.duplicate_groups``.
    """

    source_dirs: tuple[Path, ...]
    target_root: Path
    rule_name: str = "by_filename_prefix"
    run_quality: bool = True
    run_dedup: bool = True
    copy: bool = True
    name: str = "导入"
    kind: str = "ingest"
    stop_on_error: bool = True  # no downstream Step can work without ctx.dataset

    def execute(self, ctx: PipelineContext, progress_cb: ProgressCb | None = None) -> None:
        from ..ingest import RULES, discover, execute_with_checks, preview
        if self.rule_name not in RULES:
            raise ValueError(f"未知分类规则: {self.rule_name}")
        paths = discover(list(self.source_dirs))
        ctx.source_paths = paths
        pv = preview(paths, RULES[self.rule_name])
        result = execute_with_checks(
            pv, self.target_root,
            copy=self.copy,
            run_quality=self.run_quality,
            run_dedup=self.run_dedup,
            progress_cb=progress_cb,
        )
        ctx.dataset = result.dataset
        ctx.quality_issues = result.quality_issues
        ctx.duplicate_groups = result.duplicate_groups


# ---------- Scan (re-index existing dataset root) ----------

@dataclass(frozen=True)
class ScanStep:
    """Load an already-structured dataset from disk into ``ctx.dataset``."""

    root: Path
    name: str = "扫描"
    kind: str = "scan"
    stop_on_error: bool = True

    def execute(self, ctx: PipelineContext, progress_cb: ProgressCb | None = None) -> None:
        from ..dataset import scan_dataset
        ctx.dataset = scan_dataset(self.root, progress_cb=progress_cb)


# ---------- Quality ----------

@dataclass(frozen=True)
class QualityStep:
    """Run quality checks on ``ctx.dataset``. Populates ``ctx.quality_issues``."""

    blur_threshold: float = 100.0
    blank_std_max: float = 5.0
    exposure_low: float = 15.0
    exposure_high: float = 240.0
    name: str = "质检"
    kind: str = "quality"

    def execute(self, ctx: PipelineContext, progress_cb: ProgressCb | None = None) -> None:
        if ctx.dataset is None:
            raise RuntimeError("QualityStep 需要 ctx.dataset (前置 IngestStep 或 ScanStep)")
        from ..quality import QualityOptions, check_images
        opts = QualityOptions(
            blur_threshold=self.blur_threshold,
            blank_std_max=self.blank_std_max,
            exposure_low=self.exposure_low,
            exposure_high=self.exposure_high,
        )
        all_images = [img for c in ctx.dataset.categories for img in c.images]
        ctx.quality_issues = check_images(all_images, opts, progress_cb=progress_cb)


# ---------- Dedup ----------

@dataclass(frozen=True)
class DedupStep:
    """Run perceptual-hash dedup. Populates ``ctx.duplicate_groups``."""

    threshold: int = 5
    name: str = "去重"
    kind: str = "dedup"

    def execute(self, ctx: PipelineContext, progress_cb: ProgressCb | None = None) -> None:
        if ctx.dataset is None:
            raise RuntimeError("DedupStep 需要 ctx.dataset (前置 IngestStep 或 ScanStep)")
        from ..dedup import find_duplicates
        all_images = [img for c in ctx.dataset.categories for img in c.images]
        ctx.duplicate_groups = find_duplicates(
            all_images, threshold=self.threshold, progress_cb=progress_cb)


# ---------- Split ----------

@dataclass(frozen=True)
class SplitStep:
    """Split ``ctx.dataset`` into train/val/test. Populates ``ctx.split``."""

    train: float = 0.8
    val: float = 0.1
    test: float = 0.1
    seed: int | None = None
    name: str = "划分"
    kind: str = "split"
    stop_on_error: bool = True

    def execute(self, ctx: PipelineContext, progress_cb: ProgressCb | None = None) -> None:
        if ctx.dataset is None:
            raise RuntimeError("SplitStep 需要 ctx.dataset")
        from ..splitter import SplitOptions, split_dataset
        kwargs = dict(train=self.train, val=self.val, test=self.test)
        if self.seed is not None:
            kwargs["seed"] = self.seed
        ctx.split = split_dataset(ctx.dataset, SplitOptions(**kwargs))
        if progress_cb:
            progress_cb(1, 1, "")


# ---------- Export ----------

@dataclass(frozen=True)
class ExportStep:
    """Schema-driven export. Appends an ExportReport to ``ctx.export_reports``.

    ``extra_options`` lets you pass format-specific kwargs (e.g. ShareGPT's
    ``question`` prompt) without baking them into the Step API.
    """

    schema_key: str
    out_dir: Path
    copy_images: bool = True
    extra_options: dict = field(default_factory=dict)
    name: str = "导出"
    kind: str = "export"

    def execute(self, ctx: PipelineContext, progress_cb: ProgressCb | None = None) -> None:
        if ctx.split is None:
            raise RuntimeError("ExportStep 需要 ctx.split (前置 SplitStep)")
        from ..schema import get as get_schema
        schema = get_schema(self.schema_key)
        if schema is None:
            raise ValueError(f"未注册的格式: {self.schema_key}")

        opt_fields = schema.options_class.__dataclass_fields__
        kwargs: dict = {"out_dir": self.out_dir}
        if "copy_images" in opt_fields:
            kwargs["copy_images"] = self.copy_images
        # Forward only fields the options class actually declares
        for k, v in self.extra_options.items():
            if k in opt_fields:
                kwargs[k] = v
        options = schema.options_class(**kwargs)

        report = schema.writer(ctx.split, options, progress_cb=progress_cb)
        ctx.export_reports.append(report)
