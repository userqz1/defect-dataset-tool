"""Pipeline base types — Step protocol + Pipeline + Context + Result.

Per DataForge-设计方案-v1.2 §4.3 + §7, a Pipeline is an ordered list of
``Step`` objects that mutate a shared ``PipelineContext``. This is the
memory-level abstraction only — **YAML serialization is v0.2**
(v0.1 §14.3 explicitly defers it).

Design notes:

- ``Step`` is a Protocol, not a base class: any object with the right
  shape works. Built-in Steps (``core.pipeline.steps``) are frozen
  dataclasses so they're trivially constructible and hashable.
- ``PipelineContext`` is a simple dataclass carrying the cumulative
  artifacts. Steps read/write fields directly — no dict soup.
- ``Pipeline.run`` catches per-step exceptions; execution continues to
  the next step unless a step is marked ``stop_on_error=True``. Errors
  are collected in ``PipelineResult.errors`` for the caller to surface.
- The ``progress_cb`` signature mirrors every other core operation:
  ``(done, total, name)``. Each Step prepends
  ``"[i/N] StepName · "`` to the name so UI progress bars can show
  step-level status without custom wiring.

Pure Python — no PyQt, no GUI imports.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable

from ..models import Dataset
from ..splitter import SplitResult


ProgressCb = Callable[[int, int, str], None]


# ---------- Context ----------

@dataclass
class PipelineContext:
    """Shared state between Steps in one Pipeline run.

    Every Step reads what it needs from the context and writes its
    outputs back. Fields are ``None`` until a Step populates them.
    """

    # Populated by IngestStep / ScanStep
    dataset: Dataset | None = None
    source_paths: list[Path] = field(default_factory=list)

    # Populated by QualityStep
    quality_issues: list[Any] | None = None      # list[core.quality.QualityIssue]

    # Populated by DedupStep
    duplicate_groups: list[Any] | None = None    # list[core.dedup.DuplicateGroup]

    # Populated by SplitStep
    split: SplitResult | None = None

    # Populated by ExportStep
    export_reports: list[Any] = field(default_factory=list)  # list[ExportReport]

    # Free-form metadata for custom Steps / tests
    meta: dict[str, Any] = field(default_factory=dict)


# ---------- Step protocol ----------

@runtime_checkable
class Step(Protocol):
    """One unit of work in a Pipeline.

    Required attributes:

    - ``name`` — human-readable label shown in progress UI
    - ``kind`` — machine identifier ("ingest" / "quality" / "export" / ...)

    Optional attribute:

    - ``stop_on_error: bool`` — if True, raising propagates to ``Pipeline.run``
      instead of being collected in ``errors``. Default False.
    """

    name: str
    kind: str

    def execute(
        self,
        ctx: PipelineContext,
        progress_cb: ProgressCb | None = None,
    ) -> None: ...


# ---------- Pipeline ----------

@dataclass
class PipelineResult:
    """Per-run outcome. Errors are non-fatal by default (see Step.stop_on_error)."""

    executed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)  # (step_name, msg)
    context: PipelineContext = field(default_factory=PipelineContext)

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass
class Pipeline:
    """Ordered Step list + executor.

    Usage::

        pipe = Pipeline(
            name="YOLO 检测数据集标准流程",
            steps=[
                IngestStep(source_dirs=[...], target_root=...),
                SplitStep(train=0.8, val=0.1, test=0.1),
                ExportStep(schema_key="YOLO", out_dir=...),
            ],
        )
        result = pipe.run(progress_cb=print)
        assert result.ok
        print(result.context.export_reports[0].written_images)
    """

    name: str
    steps: list[Step] = field(default_factory=list)

    def run(
        self,
        ctx: PipelineContext | None = None,
        progress_cb: ProgressCb | None = None,
    ) -> PipelineResult:
        """Execute steps in order. Non-fatal errors are collected."""
        ctx = ctx or PipelineContext()
        result = PipelineResult(context=ctx)
        total = len(self.steps)

        for i, step in enumerate(self.steps, start=1):
            prefix = f"[{i}/{total}] {step.name}"
            if progress_cb:
                progress_cb(0, 1, prefix)

            def step_cb(d: int, t: int, n: str, _p=prefix) -> None:
                if progress_cb:
                    progress_cb(d, t, f"{_p} · {n}" if n else _p)

            try:
                step.execute(ctx, step_cb)
                result.executed.append(step.name)
            except Exception as e:  # noqa: BLE001
                result.errors.append((step.name, str(e)))
                if getattr(step, "stop_on_error", False):
                    # Mark remaining as skipped and stop
                    for remaining in self.steps[i:]:
                        result.skipped.append(remaining.name)
                    break

        if progress_cb:
            progress_cb(1, 1, "")
        return result
