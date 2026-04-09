"""Pipeline execution engine — runs processing nodes in sequence.

The core of v2 architecture: PipelineContext carries data through nodes,
each node reads from and writes to the context.

Pure Python — no PyQt imports.

Usage::

    from core.pipeline import PipelineContext, PipelineEngine

    ctx = PipelineContext.from_dataset(dataset, task_type)
    engine = PipelineEngine()
    engine.add_step("quality_check", {"blur_threshold": 100})
    engine.add_step("split", {"train": 0.8, "val": 0.1, "test": 0.1})

    result = engine.execute(ctx, progress_cb=my_cb)
    print(result.success, result.step_results)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .models import Dataset, ImageInfo
from .task_types import TaskType


# ---------- Pipeline Context ----------

@dataclass
class PipelineContext:
    """Mutable context that flows through the pipeline.

    Each node reads from this, modifies it, and passes it on.
    """
    dataset: Dataset
    task_type: TaskType

    # Active image list — nodes filter/expand this
    images: list[ImageInfo] = field(default_factory=list)

    # Accumulated results from each step
    step_results: dict[str, Any] = field(default_factory=dict)

    # Images flagged by quality/dedup checks (path → reason)
    flagged: dict[str, str] = field(default_factory=dict)

    # Split result (populated by split node)
    split: Any = None  # SplitResult

    # Export output path
    export_path: Path | None = None

    @classmethod
    def from_dataset(cls, dataset: Dataset, task_type: TaskType) -> PipelineContext:
        all_images = [img for cat in dataset.categories for img in cat.images]
        return cls(
            dataset=dataset,
            task_type=task_type,
            images=all_images,
        )


# ---------- Step Definition ----------

@dataclass
class StepDef:
    """A configured step in the pipeline."""
    node_name: str
    options: dict[str, Any] = field(default_factory=dict)


# ---------- Step Result ----------

@dataclass
class StepResultRecord:
    node_name: str
    display_name: str
    success: bool
    message: str
    details: Any = None


# ---------- Pipeline Result ----------

@dataclass
class PipelineResult:
    success: bool
    steps_run: int
    steps_total: int
    step_results: list[StepResultRecord] = field(default_factory=list)
    error: str = ""


# ---------- Engine ----------

ProgressCb = Callable[[int, int, str], None]


class PipelineEngine:
    """Executes a sequence of processing steps on a PipelineContext."""

    def __init__(self) -> None:
        self._steps: list[StepDef] = []

    def add_step(self, node_name: str, options: dict | None = None) -> None:
        self._steps.append(StepDef(node_name, options or {}))

    def clear(self) -> None:
        self._steps.clear()

    @property
    def steps(self) -> list[StepDef]:
        return list(self._steps)

    def execute(
        self,
        ctx: PipelineContext,
        progress_cb: ProgressCb | None = None,
    ) -> PipelineResult:
        """Run all steps in sequence. Returns PipelineResult."""
        from .nodes import NODES

        results: list[StepResultRecord] = []
        total = len(self._steps)

        for i, step in enumerate(self._steps):
            node = NODES.get(step.node_name)
            if node is None:
                results.append(StepResultRecord(
                    node_name=step.node_name,
                    display_name=step.node_name,
                    success=False,
                    message=f"未知节点: {step.node_name}",
                ))
                continue

            if progress_cb:
                progress_cb(i, total, f"执行: {node.display_name}")

            try:
                step_result = node.execute(ctx.images, step.options, progress_cb=None)

                # Apply step effects to context
                self._apply_result(ctx, step.node_name, step_result)

                results.append(StepResultRecord(
                    node_name=step.node_name,
                    display_name=node.display_name,
                    success=True,
                    message=f"完成: {step_result.ok_count} 项通过, {step_result.fail_count} 项问题",
                    details=step_result.details,
                ))
                ctx.step_results[step.node_name] = step_result

            except Exception as e:
                results.append(StepResultRecord(
                    node_name=step.node_name,
                    display_name=node.display_name,
                    success=False,
                    message=str(e),
                ))
                return PipelineResult(
                    success=False,
                    steps_run=i + 1,
                    steps_total=total,
                    step_results=results,
                    error=f"{node.display_name} 执行失败: {e}",
                )

        if progress_cb:
            progress_cb(total, total, "全部完成")

        return PipelineResult(
            success=True,
            steps_run=total,
            steps_total=total,
            step_results=results,
        )

    @staticmethod
    def _apply_result(ctx: PipelineContext, node_name: str, result) -> None:
        """Update pipeline context based on a step's result."""
        if node_name == "quality_check" and result.details:
            # Flag bad images
            for issue in result.details:
                ctx.flagged[str(issue.path)] = issue.kind

        elif node_name == "dedup" and result.details:
            # Flag duplicates
            for group in result.details:
                for dup_path in group.duplicates:
                    ctx.flagged[str(dup_path)] = "duplicate"

        elif node_name == "split" and result.details:
            ctx.split = result.details
