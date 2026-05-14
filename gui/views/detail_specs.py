"""Task-workbench specs — DetailView's sidebar layout per task.

DetailView is a **shell** (topbar + viewer + sidebar workbench).
The segment layout inside the sidebar (which panes exist, which is the
default, what sub-features each pane has) is driven entirely by the
:class:`TaskWorkbenchSpec` returned by :func:`spec_for`.

The spec is derived from ``task_type`` plus the project's target-format
capabilities.  Commercial annotation tools make the dataset target the
source of truth for the labeling interface: a pure YOLO project should
not show LLM fields, and a caption-only project should not look like a
detection workbench.

Segments are optional, with order preserved when present:

    [ 标注 ] [ VLM ] [ 状态 ]

Default segment follows the active project template.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from core.task_types import TaskType


class DetailSegment(str, Enum):
    """Which segment of the DetailView sidebar is currently active."""

    ANNOTATION = "annotation"
    VLM = "vlm"
    STATUS = "status"


class ImageLabelKind(str, Enum):
    """How the 标注 segment renders for image-level tasks.

    - ``NONE`` — task uses a shape-list pane (detection/seg/keypoint).
    - ``SINGLE`` — single-label classification: pick ONE class chip.
    - ``MULTI`` — multi-label: toggle multiple chips.
    - ``ANOMALY`` — OK/NG primary toggle, NG drills into anomaly type.
    """

    NONE = "none"
    SINGLE = "single"
    MULTI = "multi"
    ANOMALY = "anomaly"


@dataclass(frozen=True)
class TaskWorkbenchSpec:
    """Layout + feature flags for the DetailView sidebar.

    ``has_*`` flags gate *instantiation* — a False flag means the pane
    is never created, so no widget tree, no signals, no retranslate
    subscribers. The SegmentedWidget skips the corresponding tab.

    Pane sub-feature flags (``shape_tools``, ``supports_grounding``,
    ``has_caption``, ``has_conversations``) are only read when the
    owning pane's ``has_*`` is True.
    """

    has_annotation: bool
    has_vlm: bool
    has_status: bool
    default_segment: DetailSegment

    # --- 标注 pane sub-features (read when has_annotation=True) ---
    # Empty tuple = no drawing tools at all (classification / anomaly).
    # Values from ImageViewer.set_draw_shape_type: "rectangle",
    # "polygon", "point".
    shape_tools: tuple[str, ...] = ()
    # Whether the task supports grounding (per-shape region text).
    # When True the VLM pane includes a grounding editor.
    supports_grounding: bool = False
    # Image-level label workbench kind. ImageLabelKind.NONE means the
    # 标注 segment uses the shape-list pane; the other values switch it
    # to ImageLabelPane in the matching mode.
    image_label_kind: ImageLabelKind = ImageLabelKind.NONE

    # --- VLM pane sub-features (read when has_vlm=True) ---
    has_caption: bool = False
    has_conversations: bool = False


# ── Per-task base templates ──────────────────────────────────────────
# These describe "what this task can do at all", stripped of optional
# VLM editing is always available where annotation exists.

@dataclass(frozen=True)
class _TaskBase:
    """Immutable per-task features — shape tools + grounding eligibility."""

    has_annotation: bool
    shape_tools: tuple[str, ...]
    # Whether the grounding cap has any effect for this task.  Image-
    # level tasks (classification/anomaly/pair) have no shapes to
    # attach region text to, so the cap is silently ignored.
    supports_grounding: bool
    # Image-level label workbench kind. NONE for tasks that use the
    # shape-list pane.
    image_label_kind: ImageLabelKind = ImageLabelKind.NONE


_CLASSIFICATION_BASE = _TaskBase(
    has_annotation=True, shape_tools=(), supports_grounding=False,
    image_label_kind=ImageLabelKind.SINGLE,
)
_MULTI_LABEL_BASE = _TaskBase(
    has_annotation=True, shape_tools=(), supports_grounding=False,
    image_label_kind=ImageLabelKind.MULTI,
)
_ANOMALY_BASE = _TaskBase(
    has_annotation=True, shape_tools=(), supports_grounding=False,
    image_label_kind=ImageLabelKind.ANOMALY,
)
_DETECTION_BASE = _TaskBase(
    # Axis-aligned object detection — rectangle only.
    has_annotation=True, shape_tools=("rectangle",), supports_grounding=True,
)
_ORIENTED_DET_BASE = _TaskBase(
    # Rotated/oriented object detection — polygon only (rectangles can't
    # encode rotation).  task_types.py:102 declares valid_shape_types=
    # ("polygon",) for ORIENTED_DET; the spec must match or users would
    # be allowed to draw rectangles that downstream exporters reject.
    has_annotation=True, shape_tools=("polygon",), supports_grounding=True,
)
_SEGMENTATION_BASE = _TaskBase(
    # Semantic / instance segmentation.
    has_annotation=True, shape_tools=("polygon",), supports_grounding=True,
)
_KEYPOINT_BASE = _TaskBase(
    # Keypoint: point primary, rect for bbox anchor.  No grounding UI
    # because keypoints aren't the usual grounding target.
    has_annotation=True, shape_tools=("point", "rectangle"),
    supports_grounding=False,
)
_IMAGE_PAIR_BASE = _TaskBase(
    # Pair task is image-level; no shape editing surface.
    has_annotation=True, shape_tools=(), supports_grounding=False,
)


_TASK_BASES: dict[TaskType, _TaskBase] = {
    TaskType.CLASSIFICATION: _CLASSIFICATION_BASE,
    TaskType.MULTI_LABEL:    _MULTI_LABEL_BASE,
    TaskType.ANOMALY:        _ANOMALY_BASE,
    TaskType.DETECTION:      _DETECTION_BASE,
    TaskType.ORIENTED_DET:   _ORIENTED_DET_BASE,
    TaskType.SEMANTIC_SEG:   _SEGMENTATION_BASE,
    TaskType.INSTANCE_SEG:   _SEGMENTATION_BASE,
    TaskType.KEYPOINT:       _KEYPOINT_BASE,
    TaskType.IMAGE_PAIR:     _IMAGE_PAIR_BASE,
}


# Conservative fallback for unknown task types: behave like detection
# (shapes + grounding-eligible). Classification would be wrong-by-default
# since a user with unknown-task data is more often "labeled region data
# that we haven't classified yet" than "image-level labels".
_DEFAULT_BASE = _DETECTION_BASE


def spec_for(
    task_type: TaskType | None,
    *,
    enable_caption: bool = False,
    enable_conversations: bool = False,
    enable_grounding: bool = False,
    show_annotation: bool = True,
    show_status: bool = True,
    shape_tools_without_annotation: bool = False,
    shape_tools_override: tuple[str, ...] | None = None,
) -> TaskWorkbenchSpec:
    """Build the workbench spec for ``task_type``."""
    base = _DEFAULT_BASE if task_type is None else _TASK_BASES.get(
        task_type, _DEFAULT_BASE)

    has_annotation = base.has_annotation and show_annotation
    supports_grounding = bool(enable_grounding and base.supports_grounding)
    has_caption = bool(enable_caption)
    has_conversations = bool(enable_conversations)
    has_vlm = has_caption or has_conversations or supports_grounding

    has_shape_tools = has_annotation or shape_tools_without_annotation
    shape_tools = (
        shape_tools_override
        if shape_tools_override is not None else base.shape_tools
    )

    # Default segment follows the active work surface.  Pure VLM projects
    # land on the VLM editor; mixed projects can still expose drawing tools
    # from the topbar without showing a separate "traditional annotation"
    # pane.
    default_segment = (
        DetailSegment.ANNOTATION if has_annotation else DetailSegment.VLM
    )

    return TaskWorkbenchSpec(
        has_annotation=has_annotation,
        has_vlm=has_vlm,
        has_status=show_status,
        default_segment=default_segment,
        shape_tools=shape_tools if has_shape_tools else (),
        supports_grounding=supports_grounding,
        has_caption=has_caption,
        has_conversations=has_conversations,
        image_label_kind=base.image_label_kind,
    )


# Default spec — still exported for call sites that want "whatever the
# shell falls back to before a project is bound".
DEFAULT_SPEC = spec_for(None)
