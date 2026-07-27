"""Target-format annotation readiness helpers.

These helpers answer a UI-facing question: for the project's current target
format, is this sample annotated enough to be considered complete?

The module is pure Python and deliberately independent from Qt. GUI views use
it for "labeled / unlabeled" filters, and detail navigation uses the same
predicate for "next incomplete".
"""
from __future__ import annotations

from collections.abc import Iterable

from .task_types import TASK_REGISTRY, TaskType
from .unified import Region, Sample


def normalize_target_format(target_format: str) -> str:
    """Return a compact, case-insensitive target-format key."""
    return (
        (target_format or "")
        .strip()
        .lower()
        .replace(" ", "")
        .replace("-", "")
        .replace("_", "")
        .replace("/", "")
    )


def schema_key_for_target_format(target_format: str) -> str:
    """Map product-facing target names to exporter schema keys."""
    normalized = normalize_target_format(target_format)
    if normalized in {"yolo", "yoloultralytics", "ultralytics"}:
        return "YOLO"
    if normalized in {"yoloobb", "ultralyticsobb", "obb"}:
        return "YOLO-OBB"
    if normalized in {"dota", "dotalabeltxt"}:
        return "DOTA"
    if normalized in {"coco", "cocodetection"}:
        return "COCO"
    if normalized in {"voc", "pascalvoc"}:
        return "VOC"
    if normalized in {"caption", "captionjsonl", "imagecaptionjsonl"}:
        return "JSONL"
    if normalized in {"jsonl", "jsonlines"}:
        return "JSONL"
    if normalized in {"labelme", "labelmejson"}:
        return "LabelMe JSON"
    if normalized in {"imagefolder", "folder"}:
        return "ImageFolder"
    if normalized in {"pairedfolder", "pairfolder", "imagepair", "pair"}:
        return "PairedFolder"
    if normalized in {"mvtec", "mvtecad"}:
        return "MVTec"
    if normalized in {"llava", "llavajsonl"}:
        return "LLaVA"
    if normalized in {"sharegpt", "sharegptjson", "sharegptjsonl"}:
        return "ShareGPT"
    if normalized in {"swift", "msswift", "swiftjsonl", "qwenvl"}:
        return "Swift"
    return target_format


def target_format_for_schema_key(schema_key: str) -> str:
    """Map schema keys back to the saved project target-format value."""
    return schema_key


def export_key_for_target_format(target_format: str) -> str:
    """Return the ``format_out`` writer key for a product target format."""
    schema_key = schema_key_for_target_format(target_format)
    normalized = normalize_target_format(schema_key)
    aliases = {
        "pascalvoc": "voc",
        "jsonlines": "jsonl",
        "captionjsonl": "jsonl",
        "imagecaptionjsonl": "jsonl",
        "labelmejson": "labelme",
        "mvtecad": "mvtec",
        "msswift": "swift",
        "pairedfolder": "pairedfolder",
        "qwenvl": "swift",
    }
    return aliases.get(normalized, normalized)


def target_format_is_exportable(target_format: str) -> bool:
    """Return True when a target format has a concrete export writer."""
    try:
        from .format_out import available_formats
        return export_key_for_target_format(target_format) in available_formats()
    except Exception:
        return False


def sample_is_complete_for_target(
    sample: Sample,
    target_format: str,
    task_type: TaskType | str | None = None,
) -> bool:
    """Return True when *sample* has the fields needed by *target_format*.

    This is stricter than "has a label file": for example Caption JSONL needs
    caption text, while segmentation targets need polygon geometry.
    """
    target = normalize_target_format(target_format)

    if target in {"classification", "multilabel", "imageclass"}:
        return bool(sample.image_labels or sample.category)
    if target in {"anomaly", "anomalydetection"}:
        return bool(sample.image_labels or sample.category)
    if target in {"bbox", "box", "detection", "objectdetection"}:
        return any(_region_has_geometry(r) for r in sample.regions)
    if target in {"orientedbbox", "orientedbox", "orienteddetection",
                  "yoloobb", "ultralyticsobb", "obb", "dota", "dotalabeltxt"}:
        return any(_region_has_polygon(r) for r in sample.regions)
    if target in {"segmentation", "semanticsegmentation", "instancesegmentation"}:
        return any(_region_has_polygon(r) for r in sample.regions)
    if target in {"keypoint", "keypointdetection"}:
        return any(_region_has_keypoint(r) for r in sample.regions)
    if target in {"pair", "imagepair", "pairedfolder", "pairfolder"}:
        return bool(sample.pair_path)
    if target in {"caption", "captionjsonl", "imagecaptionjsonl"}:
        return bool((sample.caption or "").strip())
    if target in {"llava", "llavajsonl"}:
        if _task_supports_grounding(task_type):
            return _has_grounding(sample)
        return bool(sample.conversations)
    if target in {"sharegpt", "sharegptjson", "sharegptjsonl"}:
        if _task_supports_grounding(task_type):
            return _has_grounding(sample)
        return bool(sample.conversations)
    if target in {"swift", "msswift", "swiftjsonl", "qwenvl"}:
        if _task_supports_grounding(task_type):
            return _has_grounding(sample)
        return bool(sample.conversations)
    if target in {"vlmgrounding", "grounding"}:
        return _has_grounding(sample)
    if target in {"vlmconversation", "conversation", "conversations"}:
        return bool(sample.conversations)
    if target in {"vlmfull", "fullvlm"}:
        return (
            bool((sample.caption or "").strip())
            and bool(sample.conversations)
            and _has_grounding(sample)
        )

    task = _coerce_task_type(task_type)
    if task is None:
        return bool(sample.regions or sample.image_labels or sample.has_label)

    info = TASK_REGISTRY.get(task)
    if info is None:
        return bool(sample.regions or sample.image_labels or sample.has_label)
    if info.needs_image_label:
        return bool(sample.image_labels or sample.category)
    if task in {TaskType.SEMANTIC_SEG, TaskType.INSTANCE_SEG}:
        return any(_region_has_polygon(r) for r in sample.regions)
    if task is TaskType.KEYPOINT:
        return any(_region_has_keypoint(r) for r in sample.regions)
    if task is TaskType.ORIENTED_DET:
        return any(_region_has_polygon(r) for r in sample.regions)
    if info.needs_shapes:
        return any(_region_has_geometry(r) for r in sample.regions)
    return bool(sample.has_label or sample.image_labels or sample.category)


def completed_paths_for_target(
    samples: Iterable[Sample],
    target_format: str,
    task_type: TaskType | str | None = None,
) -> set[str]:
    """Return image-path strings complete for the selected target format."""
    return {
        str(sample.image_path)
        for sample in samples
        if sample_is_complete_for_target(sample, target_format, task_type)
    }


def _coerce_task_type(task_type: TaskType | str | None) -> TaskType | None:
    if task_type is None:
        return None
    if isinstance(task_type, TaskType):
        return task_type
    try:
        return TaskType(str(task_type))
    except ValueError:
        return None


def _task_supports_grounding(task_type: TaskType | str | None) -> bool:
    task = _coerce_task_type(task_type)
    return task in {
        TaskType.DETECTION,
        TaskType.ORIENTED_DET,
        TaskType.SEMANTIC_SEG,
        TaskType.INSTANCE_SEG,
    }


def _has_grounding(sample: Sample) -> bool:
    if sample.regions:
        return all(
            _region_has_geometry(region) and (region.text or "").strip()
            for region in sample.regions
        )
    return bool(sample.grounding)


def _region_has_geometry(region: Region) -> bool:
    return bool(region.bbox or region.polygon or region.keypoints)


def _region_has_polygon(region: Region) -> bool:
    return bool(region.polygon) or region.shape_type in {
        "polygon",
        "linestrip",
    }


def _region_has_keypoint(region: Region) -> bool:
    return bool(region.keypoints) or region.shape_type == "point"
