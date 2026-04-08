"""Local AI pre-labeling backends.

Each backend implements `Predictor.predict(image_path) -> list[Shape]`.
Backends gracefully self-disable if their dependencies aren't installed,
so the rest of the app keeps working without ultralytics/torch.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .annotation_writer import write_labelme
from .models import Annotation, Shape


class Predictor(Protocol):
    name: str

    def is_available(self) -> bool: ...
    def predict(self, image_path: Path) -> list[Shape]: ...


# ---------- Ultralytics YOLOv8 ----------

class YoloPredictor:
    name = "YOLOv8 (本地)"

    def __init__(self, model_name: str = "yolov8n.pt", conf: float = 0.25) -> None:
        self.model_name = model_name
        self.conf = conf
        self._model = None
        self._error: str | None = None

    def is_available(self) -> bool:
        try:
            import ultralytics  # noqa: F401
            return True
        except Exception as e:  # noqa: BLE001
            self._error = str(e)
            return False

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        from ultralytics import YOLO  # type: ignore
        self._model = YOLO(self.model_name)

    def predict(self, image_path: Path) -> list[Shape]:
        self._ensure_model()
        results = self._model.predict(  # type: ignore
            source=str(image_path), conf=self.conf, verbose=False
        )
        shapes: list[Shape] = []
        for r in results:
            names = r.names
            boxes = getattr(r, "boxes", None)
            if boxes is None:
                continue
            for box in boxes:
                cls_idx = int(box.cls.item()) if hasattr(box.cls, "item") else int(box.cls)
                label = names.get(cls_idx, str(cls_idx)) if isinstance(names, dict) else str(cls_idx)
                xyxy = box.xyxy.tolist()[0]
                x1, y1, x2, y2 = float(xyxy[0]), float(xyxy[1]), float(xyxy[2]), float(xyxy[3])
                shapes.append(
                    Shape(label=label, shape_type="rectangle", points=[(x1, y1), (x2, y2)])
                )
        return shapes


# ---------- 批量驱动 ----------

@dataclass
class PredictResult:
    written: list[Path] = field(default_factory=list)
    failed: list[tuple[Path, str]] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)


def predict_batch(
    image_paths: list[Path],
    predictor: Predictor,
    overwrite: bool = False,
    progress_cb=None,
) -> PredictResult:
    """For each image, run the predictor and write a LabelMe JSON next to it.

    LabelMe path: <image>/../labels/<stem>.json (if parent is `images/`),
    otherwise sibling .json. Skips images that already have a label unless
    overwrite=True.
    """
    from .fileops import label_path_for_image

    result = PredictResult()
    total = len(image_paths)
    for i, img_path in enumerate(image_paths):
        if progress_cb:
            progress_cb(i, total, img_path.name)
        try:
            existing = label_path_for_image(img_path)
            if existing and not overwrite:
                result.skipped.append(img_path)
                continue
            shapes = predictor.predict(img_path)
            if not shapes:
                result.skipped.append(img_path)
                continue
            # 推断目标 LabelMe JSON 路径
            parent = img_path.parent
            if parent.name == "images":
                target = parent.parent / "labels" / (img_path.stem + ".json")
            else:
                target = img_path.with_suffix(".json")
            ann = Annotation(image_path=img_path, shapes=shapes)
            write_labelme(ann, target, img_path)
            result.written.append(target)
        except Exception as e:  # noqa: BLE001
            result.failed.append((img_path, str(e)))
    if progress_cb:
        progress_cb(total, total, "")
    return result
