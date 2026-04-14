"""I/O nodes — DataSource, Split, Export."""
from __future__ import annotations

from pathlib import Path

from .base import ParamDef, PortDef, StepResult


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
        from ..models import Category, Dataset
        from ..splitter import SplitOptions, split_dataset

        train_r = options.get("train_ratio", 0.8)
        val_r = options.get("val_ratio", 0.1)
        test_r = options.get("test_ratio", 0.1)
        total_r = train_r + val_r + test_r
        if total_r <= 0:
            raise ValueError("划分比例之和必须大于 0")

        if isinstance(images, Dataset):
            dataset = images
        else:
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
        return {"output": result.details} if result.details else {"output": input_data}


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
                 choices=("YOLO", "COCO", "VOC", "CSV", "JSONL",
                          "LLaVA", "ShareGPT", "Swift")),
        ParamDef("out_dir", "输出目录", "path", ""),
    )

    def execute(self, images, options, progress_cb=None):
        if not images:
            raise ValueError("导出节点没有收到数据，请检查上游连接")
        from ..splitter import SplitResult
        from ..exporter.registry import run_export

        fmt = options.get("format", "YOLO").upper()
        out_dir_str = options.get("out_dir", "")
        if not out_dir_str or out_dir_str == ".":
            raise ValueError("导出节点需要配置输出目录（双击节点设置）")
        out_dir = Path(out_dir_str)

        if isinstance(images, SplitResult):
            split = images
        else:
            split = SplitResult(train=list(images), val=[], test=[])

        report = run_export(fmt, split, out_dir, progress_cb=progress_cb)
        count = getattr(report, "written_images", 0)
        return StepResult(ok_count=count, details=report)
