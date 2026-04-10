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


# ---------- Port & parameter definitions ----------

@dataclass(frozen=True)
class PortDef:
    """Typed port on a processing node."""
    name: str           # machine key, e.g. "passed"
    label: str          # display, e.g. "合格"
    direction: str      # "input" | "output"
    data_type: str = "dataset"   # "dataset" | "report"


@dataclass(frozen=True)
class ParamDef:
    """Configurable parameter on a processing node."""
    name: str
    label: str
    type: str          # "int" | "float" | "str" | "bool" | "choice" | "path"
    default: Any = None
    choices: tuple[str, ...] | None = None
    min_val: float | None = None
    max_val: float | None = None


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
    ports = (
        PortDef("input", "输入", "input", "dataset"),
        PortDef("passed", "合格", "output", "dataset"),
        PortDef("rejected", "不合格", "output", "dataset"),
    )
    parameters = (
        ParamDef("blur_threshold", "模糊阈值", "int", 100, min_val=10, max_val=500),
    )

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
    ports = (
        PortDef("input", "输入", "input", "dataset"),
        PortDef("unique", "唯一", "output", "dataset"),
        PortDef("duplicates", "重复", "output", "dataset"),
    )
    parameters = (
        ParamDef("threshold", "相似阈值", "int", 5, min_val=0, max_val=20),
    )

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
    ports = (
        PortDef("input", "输入", "input", "dataset"),
        PortDef("output", "增强后", "output", "dataset"),
    )
    parameters = (
        ParamDef("flip_h", "水平翻转", "bool", True),
        ParamDef("flip_v", "垂直翻转", "bool", False),
        ParamDef("rotate", "随机旋转", "bool", True),
        ParamDef("brightness", "亮度调整", "bool", True),
    )

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
    ports = (
        PortDef("input", "输入", "input", "dataset"),
        PortDef("train", "训练集", "output", "dataset"),
        PortDef("val", "验证集", "output", "dataset"),
        PortDef("test", "测试集", "output", "dataset"),
    )
    parameters = (
        ParamDef("train_ratio", "训练集比例", "float", 0.8, min_val=0.1, max_val=0.95),
        ParamDef("val_ratio", "验证集比例", "float", 0.1, min_val=0.0, max_val=0.5),
        ParamDef("test_ratio", "测试集比例", "float", 0.1, min_val=0.0, max_val=0.5),
        ParamDef("stratified", "分层采样", "bool", True),
    )

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


class DataSourceNode:
    name = "data_source"
    display_name = "数据源"
    step_type = "input"
    description = "加载数据集目录，作为流程入口"
    ports = (
        PortDef("output", "数据集", "output", "dataset"),
    )
    parameters = (
        ParamDef("root_dir", "数据集目录", "path", ""),
    )

    def execute(self, images, options, progress_cb=None):
        return StepResult(ok_count=len(images) if images else 0)


class ExportNode:
    name = "export"
    display_name = "导出"
    step_type = "export"
    description = "导出为 YOLO/COCO/VOC 等格式"
    ports = (
        PortDef("input", "输入", "input", "dataset"),
    )
    parameters = (
        ParamDef("format", "导出格式", "choice", "YOLO",
                 choices=("YOLO", "COCO", "VOC", "CSV")),
        ParamDef("out_dir", "输出目录", "path", ""),
    )

    def execute(self, images, options, progress_cb=None):
        fmt = options.get("format", "yolo")
        out_dir = Path(options.get("out_dir", "."))
        from .exporter import export_dataset
        result = export_dataset(images, fmt, out_dir, progress_cb=progress_cb)
        return StepResult(
            ok_count=result.get("count", 0),
            output_paths=result.get("paths", []),
            details=result,
        )


# ---------- Category visual metadata (pure Python — no Qt) ----------

@dataclass(frozen=True)
class CategoryMeta:
    """Display metadata for a node category. Token names resolved in GUI layer."""
    display_name: str       # e.g. "清洁"
    color_token: str        # e.g. "NODE_CAT_CLEAN" — getattr(T, token) in GUI
    icon_name: str          # FluentIcon enum name, e.g. "CERTIFICATE"


CATEGORY_META: dict[str, CategoryMeta] = {
    "clean":   CategoryMeta("清洁", "NODE_CAT_CLEAN", "CERTIFICATE"),
    "augment": CategoryMeta("增强", "NODE_CAT_AUGMENT", "ADD"),
    "split":   CategoryMeta("划分", "NODE_CAT_SPLIT", "TILES"),
    "export":  CategoryMeta("导出", "NODE_CAT_EXPORT", "SHARE"),
    "input":   CategoryMeta("输入", "NODE_CAT_INPUT", "FOLDER"),
}


# ---------- Node registry ----------

NODES: dict[str, ProcessingNode] = {
    "data_source": DataSourceNode(),
    "quality_check": QualityCheckNode(),
    "augment": AugmentNode(),
    "split": SplitNode(),
    "export": ExportNode(),
}
"""All available processing nodes, keyed by name."""
