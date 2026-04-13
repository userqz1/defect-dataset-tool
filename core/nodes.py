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

    def route(
        self,
        input_data: list,
        result: StepResult,
    ) -> dict[str, Any]:
        """Map execution result to per-output-port data.

        Default: single-output passthrough. Override for multi-output
        or transformed-output nodes.
        """
        ...


def _default_route(spec, input_data: list, result: StepResult) -> dict[str, Any]:
    """Fallback route: single output port passes through input data."""
    ports = getattr(spec, "ports", ())
    out_ports = [p for p in ports if p.direction == "output"]
    port_name = out_ports[0].name if out_ports else "output"
    return {port_name: input_data}


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
        if not images:
            raise ValueError("质量检查节点没有收到图片，请检查上游连接")
        from .quality import QualityOptions, check_images
        threshold = options.get("blur_threshold", 100)
        if not (10 <= threshold <= 5000):
            raise ValueError(f"模糊阈值 {threshold} 超出范围 (10-5000)")
        opts = QualityOptions(blur_threshold=threshold)
        issues = check_images(images, opts=opts, progress_cb=progress_cb)
        return StepResult(
            ok_count=len(images) - len(issues),
            fail_count=len(issues),
            details=issues,
        )

    def route(self, input_data, result):
        bad_paths = set()
        if result.details:
            for issue in result.details:
                bad_paths.add(str(getattr(issue, "path", "")))
        passed = [img for img in input_data if str(getattr(img, "path", img)) not in bad_paths]
        rejected = [img for img in input_data if str(getattr(img, "path", img)) in bad_paths]
        return {"passed": passed, "rejected": rejected}


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
        if not images:
            raise ValueError("重复检测节点没有收到图片，请检查上游连接")
        from .dedup import find_duplicates
        threshold = options.get("threshold", 5)
        if not (0 <= threshold <= 64):
            raise ValueError(f"相似阈值 {threshold} 超出范围 (0-64)")
        groups = find_duplicates(images, threshold=threshold, progress_cb=progress_cb)
        dup_count = sum(len(g.images) - 1 for g in groups if len(g.images) > 1)
        return StepResult(
            ok_count=len(images) - dup_count,
            fail_count=dup_count,
            details=groups,
        )

    def route(self, input_data, result):
        dup_paths = set()
        if result.details:
            for group in result.details:
                for img in group.images[1:]:
                    dup_paths.add(str(getattr(img, "path", img)))
        unique = [img for img in input_data if str(getattr(img, "path", img)) not in dup_paths]
        dups = [img for img in input_data if str(getattr(img, "path", img)) in dup_paths]
        return {"unique": unique, "duplicates": dups}


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
        ParamDef("out_dir", "输出目录", "path", ""),
    )

    def execute(self, images, options, progress_cb=None):
        if not images:
            raise ValueError("数据增强节点没有收到图片，请检查上游连接")
        from .augment import AugmentOptions, augment_batch
        opts_dict = dict(options)  # don't mutate caller's dict
        out_dir = Path(opts_dict.pop("out_dir", ""))
        if not str(out_dir) or str(out_dir) == ".":
            raise ValueError("数据增强节点需要配置输出目录（双击节点设置）")
        out_dir.mkdir(parents=True, exist_ok=True)
        opts = AugmentOptions(**{k: v for k, v in opts_dict.items()
                                 if hasattr(AugmentOptions, k)})
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

    def route(self, input_data, result):
        from .models import ImageInfo
        if result.output_paths:
            return {"output": [ImageInfo(path=p, category="augmented")
                               for p in result.output_paths]}
        return {"output": input_data}


class SplitNode:
    name = "split"
    display_name = "数据集划分"
    step_type = "split"
    description = "划分 train/val/test"
    ports = (
        PortDef("input", "输入", "input", "dataset"),
        PortDef("output", "划分结果", "output", "dataset"),
    )
    parameters = (
        ParamDef("train_ratio", "训练集比例", "float", 0.8, min_val=0.1, max_val=0.95),
        ParamDef("val_ratio", "验证集比例", "float", 0.1, min_val=0.0, max_val=0.5),
        ParamDef("test_ratio", "测试集比例", "float", 0.1, min_val=0.0, max_val=0.5),
        ParamDef("stratified", "分层采样", "bool", True),
    )

    def execute(self, images, options, progress_cb=None):
        if not images:
            raise ValueError("划分节点没有收到图片，请检查上游连接")
        from .models import Category, Dataset
        from .splitter import SplitOptions, split_dataset

        train_r = options.get("train_ratio", 0.8)
        val_r = options.get("val_ratio", 0.1)
        test_r = options.get("test_ratio", 0.1)
        total_r = train_r + val_r + test_r
        if total_r <= 0:
            raise ValueError("划分比例之和必须大于 0")

        # Accept both Dataset and list[ImageInfo]
        if isinstance(images, Dataset):
            dataset = images
        else:
            # Build synthetic Dataset from image list for split_dataset()
            by_cat: dict[str, list] = {}
            for img in images:
                by_cat.setdefault(getattr(img, "category", "default"), []).append(img)
            cats = [Category(name=name, image_count=len(imgs), images=imgs)
                    for name, imgs in by_cat.items()]
            dataset = Dataset(
                name="pipeline", root_path=Path("."),
                categories=cats, total_images=len(images),
            )

        opts = SplitOptions(
            train=options.get("train_ratio", 0.8),
            val=options.get("val_ratio", 0.1),
            test=options.get("test_ratio", 0.1),
            stratified=options.get("stratified", True),
        )
        result = split_dataset(dataset, opts)
        total = len(result.train) + len(result.val) + len(result.test)
        return StepResult(ok_count=total, details=result)

    def route(self, input_data, result):
        """Output the SplitResult itself, not the input images."""
        return {"output": result.details} if result.details else {"output": input_data}


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
        if images is None:
            raise ValueError("数据源未加载数据集，请双击节点选择目录")
        if not images:
            raise ValueError("数据集目录中没有找到图片")
        return StepResult(ok_count=len(images))


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
        if not images:
            raise ValueError("导出节点没有收到数据，请检查上游连接")
        from .splitter import SplitResult
        fmt = options.get("format", "YOLO").upper()
        if fmt not in ("YOLO", "COCO", "VOC", "CSV"):
            raise ValueError(f"不支持的导出格式: {fmt}")
        out_dir_str = options.get("out_dir", "")
        if not out_dir_str or out_dir_str == ".":
            raise ValueError("导出节点需要配置输出目录（双击节点设置）")
        out_dir = Path(out_dir_str)

        # Accept SplitResult (from split node) or plain image list
        if isinstance(images, SplitResult):
            split = images
        else:
            # No upstream split → all images as train
            split = SplitResult(train=list(images), val=[], test=[])

        if fmt == "YOLO":
            from .exporter.yolo import YoloExportOptions, export_yolo
            report = export_yolo(split, YoloExportOptions(out_dir=out_dir),
                                 progress_cb=progress_cb)
        elif fmt == "COCO":
            from .exporter.coco import CocoExportOptions, export_coco
            report = export_coco(split, CocoExportOptions(out_dir=out_dir),
                                 progress_cb=progress_cb)
        elif fmt == "VOC":
            from .exporter.voc import VocExportOptions, export_voc
            report = export_voc(split, VocExportOptions(out_dir=out_dir),
                                progress_cb=progress_cb)
        elif fmt == "CSV":
            from .exporter.csv_export import export_csv_dataset
            report = export_csv_dataset(split, out_dir, progress_cb=progress_cb)
        else:
            return StepResult(fail_count=1, details=f"不支持的格式: {fmt}")

        count = getattr(report, "written_images", 0)
        return StepResult(ok_count=count, details=report)


class PredictNode:
    name = "predict"
    display_name = "AI 预标注"
    step_type = "augment"
    description = "使用 YOLOv8 自动生成标注"
    ports = (
        PortDef("input", "输入", "input", "dataset"),
        PortDef("output", "已标注", "output", "dataset"),
    )
    parameters = (
        ParamDef("model", "模型", "str", "yolov8n.pt"),
        ParamDef("confidence", "置信度", "float", 0.25, min_val=0.05, max_val=0.95),
        ParamDef("overwrite", "覆盖已有标注", "bool", False),
    )

    def execute(self, images, options, progress_cb=None):
        from .predictor import YoloPredictor, predict_batch
        model = options.get("model", "yolov8n.pt")
        conf = options.get("confidence", 0.25)
        overwrite = options.get("overwrite", False)
        predictor = YoloPredictor(model_name=model, conf=conf)
        if not predictor.is_available():
            raise ValueError("YOLOv8 不可用，请先安装 ultralytics: pip install ultralytics")
        paths = [img.path if hasattr(img, "path") else img for img in images]
        result = predict_batch(paths, predictor, overwrite=overwrite,
                               progress_cb=progress_cb)
        return StepResult(
            ok_count=len(result.written),
            fail_count=len(result.failed),
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
    "dedup": DedupNode(),
    "augment": AugmentNode(),
    "predict": PredictNode(),
    "split": SplitNode(),
    "export": ExportNode(),
}
"""All available processing nodes, keyed by name."""
