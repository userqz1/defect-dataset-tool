"""Processing node abstraction — unified interface for all data operations.

Each node wraps an existing core function (quality, dedup, augment, split, export)
with a standard protocol so that future UIs (node graph, pipeline builder) can
discover, configure, and execute them uniformly.

Usage::

    from core.nodes import NODES, StepResult

    node = NODES["quality_check"]
    result = node.execute(images, {"blur_threshold": 100}, progress_cb=my_cb)
    print(result.ok_count, result.details)

The existing core functions are NOT modified — nodes are thin wrappers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable


# ---------- Result type ----------

@dataclass
class StepResult:
    """Uniform result returned by every processing node."""
    ok_count: int = 0
    fail_count: int = 0
    output_paths: list[Path] = field(default_factory=list)
    details: Any = None          # node-specific payload


# ---------- Protocol ----------

ProgressCb = Callable[[int, int, str], None]


@runtime_checkable
class ProcessingNode(Protocol):
    """Interface that every processing node must satisfy."""

    @property
    def name(self) -> str:
        """Machine-readable identifier (e.g. 'quality_check')."""
        ...

    @property
    def display_name(self) -> str:
        """Human-readable label for UI (e.g. '质量检查')."""
        ...

    @property
    def step_type(self) -> str:
        """Category: 'clean' | 'augment' | 'transform' | 'split' | 'export'."""
        ...

    @property
    def description(self) -> str:
        """One-line description for tooltips."""
        ...

    def execute(
        self,
        images: list,
        options: dict[str, Any],
        progress_cb: ProgressCb | None = None,
    ) -> StepResult:
        """Run the processing step. *images* is list[ImageInfo] or list[Path]."""
        ...


# ---------- Concrete nodes wrapping existing core functions ----------

class QualityCheckNode:
    name = "quality_check"
    display_name = "质量检查"
    step_type = "clean"
    description = "检测模糊/空白/过曝/欠曝/损坏图像"

    def execute(self, images, options, progress_cb=None):
        from .quality import QualityOptions, check_images
        opts = QualityOptions(blur_threshold=options.get("blur_threshold", 100))
        issues = check_images(images, opts=opts, progress_cb=progress_cb)
        return StepResult(
            ok_count=len(images) - len(issues),
            fail_count=len(issues),
            details=issues,
        )


class DedupNode:
    name = "dedup"
    display_name = "重复检测"
    step_type = "clean"
    description = "基于感知哈希发现重复或近似图片"

    def execute(self, images, options, progress_cb=None):
        from .dedup import find_duplicates
        threshold = options.get("threshold", 5)
        groups = find_duplicates(images, threshold=threshold, progress_cb=progress_cb)
        dup_count = sum(len(g.duplicates) for g in groups)
        return StepResult(
            ok_count=len(images) - dup_count,
            fail_count=dup_count,
            details=groups,
        )


class AugmentNode:
    name = "augment"
    display_name = "数据增强"
    step_type = "augment"
    description = "生成增强样本"

    def execute(self, images, options, progress_cb=None):
        from .augment import AugmentOptions, augment_batch
        out_dir = Path(options.pop("out_dir"))
        opts = AugmentOptions(**options)
        result = augment_batch(
            [img.path if hasattr(img, "path") else img for img in images],
            out_dir, opts, progress_cb=progress_cb,
        )
        return StepResult(
            ok_count=len(result.written_images),
            fail_count=len(result.failed),
            output_paths=result.written_images,
            details=result,
        )


class SplitNode:
    name = "split"
    display_name = "数据集划分"
    step_type = "split"
    description = "划分 train/val/test"

    def execute(self, images, options, progress_cb=None):
        from .splitter import SplitOptions, split_dataset
        # images here is actually a Dataset
        dataset = images
        opts = SplitOptions(
            train_ratio=options.get("train", 0.8),
            val_ratio=options.get("val", 0.1),
            test_ratio=options.get("test", 0.1),
            stratified=options.get("stratified", True),
        )
        result = split_dataset(dataset, opts)
        total = len(result.train) + len(result.val) + len(result.test)
        return StepResult(ok_count=total, details=result)


# ---------- Node registry ----------

NODES: dict[str, ProcessingNode] = {
    "quality_check": QualityCheckNode(),
    "dedup": DedupNode(),
    "augment": AugmentNode(),
    "split": SplitNode(),
}
"""All available processing nodes, keyed by name."""
