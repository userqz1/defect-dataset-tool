"""Transform nodes — Augment, Predict."""
from __future__ import annotations

from pathlib import Path

from .base import ParamDef, PortDef, StepResult


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
        from ..augment import AugmentOptions, augment_batch
        opts_dict = dict(options)
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
        from ..models import ImageInfo
        if result.output_paths:
            return {"output": [ImageInfo(path=p, category="augmented")
                               for p in result.output_paths]}
        return {"output": input_data}


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
        from ..predictor import YoloPredictor, predict_batch
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
