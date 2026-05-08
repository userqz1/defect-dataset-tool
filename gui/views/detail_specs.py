"""Task-workbench specs — DetailView's sidebar layout per task.

DetailView is a **shell** (topbar + viewer + sidebar with 3 segments).
The segment layout inside the sidebar (which panes exist, which is the
default, what sub-features each pane has) is driven entirely by the
:class:`TaskWorkbenchSpec` returned by :func:`spec_for`.

The spec is derived from ``task_type``.  VLM fields are no longer gated
by project-level capability switches: large-model annotation is just a
different annotation mode, not a capability the project must opt into.

Three fixed segments, order preserved:

    [ 标注 ] [ VLM ] [ 状态 ]

Default segment is always 标注; users explicitly switch to 大模型标注
when they want caption / conversation / grounding data.
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

    Pane sub-feature flags (``shape_tools``, ``show_region_text``,
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
    # Per-shape grounding-text editor below the shape list.
    show_region_text: bool = False
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


def spec_for(task_type: TaskType | None) -> TaskWorkbenchSpec:
    """Build the workbench spec for ``task_type``."""
    base = _DEFAULT_BASE if task_type is None else _TASK_BASES.get(
        task_type, _DEFAULT_BASE)

    has_vlm = base.has_annotation
    show_region_text = base.supports_grounding

    # Default segment: always the structured 标注 surface — it covers
    # shape edit (detection / seg / keypoint) AND image-level chips
    # (classification / multi-label / anomaly).  The VLM segment is
    # opt-in via the segment switcher; landing on it by default would
    # surprise users who were expecting the conventional annotation
    # workspace first.
    default_segment = DetailSegment.ANNOTATION

    return TaskWorkbenchSpec(
        has_annotation=base.has_annotation,
        has_vlm=has_vlm,
        has_status=True,
        default_segment=default_segment,
        shape_tools=base.shape_tools,
        show_region_text=show_region_text,
        has_caption=True,
        has_conversations=True,
        image_label_kind=base.image_label_kind,
    )


# Default spec — still exported for call sites that want "whatever the
# shell falls back to before a project is bound".
DEFAULT_SPEC = spec_for(None)
