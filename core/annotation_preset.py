"""Annotation presets — single-pick recipe that locks task_type + VLM caps.

The user picks one of these at project creation; the preset deterministically
sets ``task_type``, ``enable_caption``, ``enable_conversations``,
``enable_grounding`` so the user doesn't have to reason about capability
flags separately.  Each preset names the export format it targets so the
mental model stays "I'm building a YOLO / LLaVA / ImageFolder dataset",
not "I have to remember which of the three VLM checkboxes to toggle".

A ``CUSTOM`` sentinel preserves the legacy "task_type + 3 free caps" shape
for advanced users who don't fit any preset.

Pure Python — no PyQt imports.
"""
from __future__ import annotations

from dataclasses import dataclass

from .task_types import TaskType


@dataclass(frozen=True)
class AnnotationPreset:
    """Recipe that derives task_type + capability flags from a single pick.

    ``id`` is what gets persisted on :class:`core.project.Project`; everything
    else is presentation / derivation data the UI consumes from
    :data:`PRESETS`.
    """

    id: str
    display_name: str        # 用户可见的卡片标题
    description: str         # 一行说明,卡片副标题
    task_type: TaskType
    caption: bool
    conversations: bool
    grounding: bool
    target_export: str       # 推荐导出格式名(信息性)


CUSTOM_ID = "custom"


# Order here = order of cards in the picker grid.
PRESETS: tuple[AnnotationPreset, ...] = (
    AnnotationPreset(
        id="detection_yolo",
        display_name="目标检测 · YOLO",
        description="矩形框检测,导出为 YOLO 训练目录",
        task_type=TaskType.DETECTION,
        caption=False, conversations=False, grounding=False,
        target_export="YOLO",
    ),
    AnnotationPreset(
        id="detection_coco",
        display_name="目标检测 · COCO",
        description="矩形框检测,导出为 COCO JSON",
        task_type=TaskType.DETECTION,
        caption=False, conversations=False, grounding=False,
        target_export="COCO",
    ),
    AnnotationPreset(
        id="classification",
        display_name="图像分类",
        description="单标签分类,导出为 ImageFolder",
        task_type=TaskType.CLASSIFICATION,
        caption=False, conversations=False, grounding=False,
        target_export="ImageFolder",
    ),
    AnnotationPreset(
        id="anomaly_mvtec",
        display_name="异常检测 · MVTec",
        description="OK / NG 图像级标签,导出为 MVTec 目录",
        task_type=TaskType.ANOMALY,
        caption=False, conversations=False, grounding=False,
        target_export="MVTec",
    ),
    AnnotationPreset(
        id="semantic_seg",
        display_name="语义分割 · JSONL",
        description="多边形像素分割,导出为可训练 JSONL",
        task_type=TaskType.SEMANTIC_SEG,
        caption=False, conversations=False, grounding=False,
        target_export="JSONL",
    ),
    AnnotationPreset(
        id="instance_seg",
        display_name="实例分割 · JSONL",
        description="多边形实例分割,导出为可训练 JSONL",
        task_type=TaskType.INSTANCE_SEG,
        caption=False, conversations=False, grounding=False,
        target_export="JSONL",
    ),
    AnnotationPreset(
        id="keypoint",
        display_name="关键点检测 · LabelMe",
        description="点 + 锚框,导出为 LabelMe JSON",
        task_type=TaskType.KEYPOINT,
        caption=False, conversations=False, grounding=False,
        target_export="LabelMe JSON",
    ),
    AnnotationPreset(
        id="oriented_dota",
        display_name="旋转框检测 · YOLO-OBB",
        description="四点旋转框,导出为 YOLO-OBB 或 DOTA",
        task_type=TaskType.ORIENTED_DET,
        caption=False, conversations=False, grounding=False,
        target_export="YOLO-OBB",
    ),
    AnnotationPreset(
        id="vlm_llava",
        display_name="VLM 数据集 · LLaVA",
        description="检测框 + 区域描述 + 整图 caption,导出为 LLaVA",
        task_type=TaskType.DETECTION,
        caption=True, conversations=False, grounding=True,
        target_export="LLaVA",
    ),
    AnnotationPreset(
        id="vlm_sharegpt",
        display_name="VLM 多轮 · ShareGPT",
        description="检测框 + 区域描述 + 多轮对话,导出为 ShareGPT",
        task_type=TaskType.DETECTION,
        caption=False, conversations=True, grounding=True,
        target_export="ShareGPT",
    ),
    AnnotationPreset(
        id="vlm_swift",
        display_name="VLM 全套 · Swift / Qwen-VL",
        description="caption + 多轮对话 + 区域描述,导出为 ms-swift",
        task_type=TaskType.DETECTION,
        caption=True, conversations=True, grounding=True,
        target_export="Swift",
    ),
    AnnotationPreset(
        id="vlm_caption",
        display_name="图文配对 · Caption JSONL",
        description="整图 caption,导出为 image / caption JSONL",
        task_type=TaskType.DETECTION,
        caption=True, conversations=False, grounding=False,
        target_export="Caption JSONL",
    ),
    AnnotationPreset(
        id="image_pair",
        display_name="图像对",
        description="成对图像比对,导出为 PairedFolder",
        task_type=TaskType.IMAGE_PAIR,
        caption=False, conversations=False, grounding=False,
        target_export="PairedFolder",
    ),
)


PRESETS_BY_ID: dict[str, AnnotationPreset] = {p.id: p for p in PRESETS}


def preset_by_id(preset_id: str) -> AnnotationPreset | None:
    """Lookup a preset by id; returns None for 'custom' or unknown ids."""
    return PRESETS_BY_ID.get(preset_id)


def detect_preset_id(
    task_type: TaskType,
    caption: bool,
    conversations: bool,
    grounding: bool,
) -> str:
    """Reverse-engineer a preset id from a project's existing flags.

    Used when loading a legacy project that has no ``preset_id`` saved.
    Returns the matching preset's id, or ``CUSTOM_ID`` when no preset
    in :data:`PRESETS` matches the exact (task_type, caps) tuple.
    """
    for preset in PRESETS:
        if (preset.task_type == task_type
                and preset.caption == caption
                and preset.conversations == conversations
                and preset.grounding == grounding):
            return preset.id
    return CUSTOM_ID
