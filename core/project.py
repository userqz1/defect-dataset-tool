"""Project persistence — stores dataset workspace state in .dataforge/project.json.

Pure Python — no PyQt imports.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .recent import load_recent
from .task_types import TaskType

PROJECT_DIR = ".dataforge"
PROJECT_FILE = "project.json"

# Formats that support per-image write-back (in-place annotation save).
# COCO is dataset-level (single JSON) so it cannot be a project's
# ``annotation_format`` — it would break DetailView save, augment
# write-back, and format_migrate.  Use ``annotation_format`` only for
# values listed here.
WRITEBACK_FORMATS: tuple[str, ...] = ("labelme", "yolo", "voc")

_DEFAULT_TARGET_FORMATS: dict[TaskType, str] = {
    TaskType.CLASSIFICATION: "ImageFolder",
    TaskType.MULTI_LABEL: "CSV",
    TaskType.ANOMALY: "MVTec",
    TaskType.DETECTION: "YOLO",
    TaskType.ORIENTED_DET: "JSONL",
    TaskType.SEMANTIC_SEG: "JSONL",
    TaskType.INSTANCE_SEG: "JSONL",
    TaskType.KEYPOINT: "LabelMe JSON",
    TaskType.IMAGE_PAIR: "PairedFolder",
}


def default_target_format_for_task(task_type: TaskType) -> str:
    """Return the non-blocking annotation target for a task type."""
    return _DEFAULT_TARGET_FORMATS.get(task_type, "YOLO")


def exportable_target_format_for_task(
    task_type: TaskType,
    target_format: str,
) -> str:
    """Return an exportable target format for *task_type*.

    Legacy projects may persist targets whose UI existed before the writer
    did (for example DOTA or COCO-seg). Clamp those to the task's current
    supported default so annotation, filtering, and version generation stay
    on one closed path.
    """
    target = (target_format or "").strip()
    if target:
        try:
            from .target_readiness import (
                export_key_for_target_format,
                target_format_is_exportable,
            )
            if (target_format_is_exportable(target)
                    and export_key_for_target_format(target)
                    in _allowed_export_keys_for_task(task_type)):
                return target
        except Exception:
            pass
    return default_target_format_for_task(task_type)


def _allowed_export_keys_for_task(task_type: TaskType) -> set[str]:
    try:
        from .schema import schemas_for_task
        options = [schema.key for schema in schemas_for_task(task_type)]
    except Exception:
        options = []
    if not options:
        from .task_types import TASK_REGISTRY
        info = TASK_REGISTRY.get(task_type)
        options = list(info.export_formats if info else ())
    try:
        from .target_readiness import export_key_for_target_format
        return {export_key_for_target_format(option) for option in options}
    except Exception:
        return set()


_IMAGE_EXTS: frozenset[str] = frozenset({
    ".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp",
})


def infer_preset_for_root(root: Path) -> tuple[TaskType, str]:
    """Best-effort preset inference for first-time folder opens.

    The launcher should not interrupt "open folder" with a second task-type
    dialog.  We infer a reasonable default from common dataset structures and
    let users correct it later from 项目设置 → 数据集预设.
    """
    from .annotation_preset import CUSTOM_ID

    label_exts: set[str] = set()
    json_candidates: list[Path] = []
    has_images = False
    has_category_image_dirs = False

    scanned = 0
    try:
        iterator = root.rglob("*")
        for p in iterator:
            scanned += 1
            if scanned > 5000:
                break
            try:
                if p.is_dir():
                    if p.name.lower() == "images" and p.parent != root:
                        has_category_image_dirs = True
                    continue
                if not p.is_file():
                    continue
            except OSError:
                continue

            suffix = p.suffix.lower()
            if suffix in _IMAGE_EXTS:
                has_images = True
                continue
            if suffix in {".txt", ".xml", ".json"}:
                label_exts.add(suffix)
                if suffix == ".json" and len(json_candidates) < 8:
                    json_candidates.append(p)
    except OSError:
        pass

    if ".txt" in label_exts:
        return TaskType.DETECTION, "detection_yolo"
    if ".xml" in label_exts:
        # Pascal VOC has no dedicated preset card; keep task correct and mark
        # the preset as custom. The scan pass will still sync writeback format
        # to "voc".
        return TaskType.DETECTION, CUSTOM_ID
    if ".json" in label_exts:
        return _infer_json_preset(json_candidates)
    if has_category_image_dirs:
        return TaskType.CLASSIFICATION, "classification"
    if has_images:
        return TaskType.DETECTION, "detection_yolo"
    return TaskType.DETECTION, "detection_yolo"


def _infer_json_preset(paths: list[Path]) -> tuple[TaskType, str]:
    """Infer COCO / LabelMe-ish JSON presets from a few samples."""
    import json

    saw_polygon = False
    saw_shape = False
    saw_image_label = False
    for path in paths:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(raw, dict):
            continue
        if all(k in raw for k in ("images", "annotations", "categories")):
            return TaskType.DETECTION, "detection_coco"
        shapes = raw.get("shapes")
        if isinstance(shapes, list):
            for shape in shapes[:16]:
                if not isinstance(shape, dict):
                    continue
                saw_shape = True
                st = str(shape.get("shape_type", "")).lower()
                pts = shape.get("points")
                if st == "polygon" or (
                    isinstance(pts, list) and len(pts) > 2
                ):
                    saw_polygon = True
        if raw.get("image_labels") or raw.get("category"):
            saw_image_label = True

    if saw_polygon:
        return TaskType.INSTANCE_SEG, "instance_seg"
    if saw_shape:
        return TaskType.DETECTION, "detection_yolo"
    if saw_image_label:
        return TaskType.CLASSIFICATION, "classification"
    return TaskType.DETECTION, "detection_yolo"


# ---------- State sub-models ----------

@dataclass
class BrowseState:
    """Persisted browse-page state — what the user was last looking at.

    Pagination retired in v3.4 (infinite-scroll); legacy ``page`` keys
    on disk are silently ignored on load and not written back.
    """

    category: str = ""
    filter: str = "all"      # all / labeled / unlabeled / issues / dups / wf_*
    search: str = ""


@dataclass
class SplitState:
    mode: str = "ratio"       # ratio / count / manual
    train: float = 0.8
    val: float = 0.1
    test: float = 0.1
    stratified: bool = True
    manual_train: list[str] = field(default_factory=list)   # image paths
    manual_val: list[str] = field(default_factory=list)
    manual_test: list[str] = field(default_factory=list)


@dataclass
class ExportConfig:
    format: str = "YOLO"
    copy_images: bool = True


@dataclass
class ReviewProgress:
    reviewed: list[str] = field(default_factory=list)   # image paths
    flagged: list[str] = field(default_factory=list)


# ---------- Project ----------

@dataclass
class Project:
    root_path: Path
    name: str
    task_type: TaskType = TaskType.DETECTION
    target_format: str = ""
    created_at: str = ""
    updated_at: str = ""
    notes: str = ""
    class_names: list[str] = field(default_factory=list)
    annotation_format: str = "labelme"      # must be one of WRITEBACK_FORMATS
    # --- Annotation preset (single source of truth for task + VLM caps) ---
    # Picked at project creation; deterministically sets ``task_type`` +
    # the three ``enable_*`` capability flags below via the table in
    # :mod:`core.annotation_preset`.  ``"custom"`` (or empty) means the
    # user opted out of presets and is configuring caps manually.
    preset_id: str = ""
    # --- Optional capability flags (derived from preset for non-custom) ---
    # These add on top of the base ``task_type`` template.  A detection
    # project with ``enable_grounding=True`` shows the per-shape region-
    # text editor; with ``enable_caption=True`` / ``enable_conversations
    # =True`` it also grows a VLM segment in DetailView.  A
    # classification project can opt into VLM the same way.  All default
    # to False — legacy projects behave exactly as before.
    enable_caption: bool = False
    enable_conversations: bool = False
    enable_grounding: bool = False
    browse_state: BrowseState = field(default_factory=BrowseState)
    split_state: SplitState = field(default_factory=SplitState)
    export_config: ExportConfig = field(default_factory=ExportConfig)
    review_progress: ReviewProgress = field(default_factory=ReviewProgress)


def _project_path(root: Path) -> Path:
    return root / PROJECT_DIR / PROJECT_FILE


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_get(d: dict, key: str, default=None):
    v = d.get(key)
    return v if v is not None else default


def load_project(root: Path) -> Project | None:
    """Load project from .dataforge/project.json. Returns None if not found."""
    path = _project_path(root)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None

    bs = raw.get("browse_state") or {}
    ss = raw.get("split_state") or {}
    ec = raw.get("export_config") or {}
    rp = raw.get("review_progress") or {}

    # Parse task_type with fallback
    try:
        task_type = TaskType(raw.get("task_type", TaskType.DETECTION.value))
    except ValueError:
        task_type = TaskType.DETECTION

    # Clamp annotation_format to writeback-capable formats.
    # Legacy projects may have "coco" or other invalid values.
    ann_fmt = raw.get("annotation_format", "labelme")
    if ann_fmt not in WRITEBACK_FORMATS:
        ann_fmt = "labelme"

    enable_caption = bool(raw.get("enable_caption", False))
    enable_conversations = bool(raw.get("enable_conversations", False))
    enable_grounding = bool(raw.get("enable_grounding", False))

    preset_id = raw.get("preset_id", "")
    if not preset_id:
        from .annotation_preset import detect_preset_id
        preset_id = detect_preset_id(
            task_type, enable_caption, enable_conversations, enable_grounding,
        )
    target_format = raw.get("target_format", "")
    if not target_format:
        from .annotation_preset import preset_by_id
        preset = preset_by_id(preset_id)
        if preset is not None:
            target_format = preset.target_export
    if not target_format:
        target_format = default_target_format_for_task(task_type)
    target_format = exportable_target_format_for_task(
        task_type, target_format)

    return Project(
        root_path=root,
        name=raw.get("name", root.name),
        task_type=task_type,
        target_format=target_format,
        created_at=raw.get("created_at", ""),
        updated_at=raw.get("updated_at", ""),
        notes=raw.get("notes", ""),
        class_names=raw.get("class_names", []),
        annotation_format=ann_fmt,
        preset_id=preset_id,
        # Capability flags — default off for legacy projects that were
        # saved before these fields existed.
        enable_caption=enable_caption,
        enable_conversations=enable_conversations,
        enable_grounding=enable_grounding,
        browse_state=BrowseState(
            category=bs.get("category", ""),
            filter=bs.get("filter", "all"),
            search=bs.get("search", ""),
            # legacy "page" key on disk is silently dropped — pagination
            # retired in v3.4 in favor of infinite-scroll.
        ),
        split_state=SplitState(
            mode=ss.get("mode", "ratio"),
            train=ss.get("train", 0.8),
            val=ss.get("val", 0.1),
            test=ss.get("test", 0.1),
            stratified=ss.get("stratified", True),
            manual_train=ss.get("manual_train", []),
            manual_val=ss.get("manual_val", []),
            manual_test=ss.get("manual_test", []),
        ),
        export_config=ExportConfig(
            format=ec.get("format", "YOLO"),
            copy_images=ec.get("copy_images", True),
        ),
        review_progress=ReviewProgress(
            reviewed=rp.get("reviewed", []),
            flagged=rp.get("flagged", []),
        ),
        # Legacy "data_standard" field (from removed core/standards.py) is
        # silently dropped — its value was always None in practice.
    )


def save_project(project: Project) -> None:
    """Save project state to .dataforge/project.json."""
    project.updated_at = _now_iso()
    path = _project_path(project.root_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "name": project.name,
        "task_type": project.task_type.value,
        "target_format": project.target_format,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
        "notes": project.notes,
        "class_names": project.class_names,
        "annotation_format": project.annotation_format,
        "preset_id": project.preset_id,
        "enable_caption": project.enable_caption,
        "enable_conversations": project.enable_conversations,
        "enable_grounding": project.enable_grounding,
        "browse_state": asdict(project.browse_state),
        "split_state": asdict(project.split_state),
        "export_config": asdict(project.export_config),
        "review_progress": asdict(project.review_progress),
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def create_project(root: Path, name: str | None = None,
                    task_type: TaskType = TaskType.DETECTION,
                    preset_id: str = "") -> Project:
    """Create a new project for a dataset directory.

    When ``preset_id`` matches an entry in :mod:`core.annotation_preset`,
    its task_type + caps override the explicit ``task_type`` arg — picking
    a preset is the user's way of saying "I want this exact recipe", so
    we don't second-guess it from a stale arg.  An unknown id (including
    ``"custom"``) leaves the project on the explicit ``task_type`` with
    all caps off.
    """
    from .annotation_preset import preset_by_id

    caption = conversations = grounding = False
    target_format = default_target_format_for_task(task_type)
    preset = preset_by_id(preset_id)
    if preset is not None:
        task_type = preset.task_type
        caption = preset.caption
        conversations = preset.conversations
        grounding = preset.grounding
        target_format = preset.target_export

    project = Project(
        root_path=root,
        name=name or root.name,
        task_type=task_type,
        target_format=target_format,
        preset_id=preset_id,
        enable_caption=caption,
        enable_conversations=conversations,
        enable_grounding=grounding,
        created_at=_now_iso(),
        updated_at=_now_iso(),
    )
    save_project(project)
    return project


def apply_preset(project: Project, preset_id: str) -> bool:
    """Re-apply ``preset_id`` to *project*; return True when caps changed.

    Used by the 更改预设 dialog to flip an existing project to a new
    recipe.  ``preset_id == "custom"`` (or empty) is a no-op on the caps
    — the user is opting *out* of preset-driven caps and intends to
    toggle the three checkboxes manually, so we leave the current caps
    intact and just flag the project as ``preset_id="custom"``.
    """
    from .annotation_preset import CUSTOM_ID, preset_by_id

    project.preset_id = preset_id
    preset = preset_by_id(preset_id)
    if preset is None or preset_id == CUSTOM_ID:
        changed = False
        fixed_target = exportable_target_format_for_task(
            project.task_type, project.target_format)
        if project.target_format != fixed_target:
            project.target_format = fixed_target
            changed = True
        if not project.target_format:
            project.target_format = default_target_format_for_task(
                project.task_type)
            changed = True
        return changed
    changed = (project.task_type != preset.task_type
               or project.enable_caption != preset.caption
               or project.enable_conversations != preset.conversations
               or project.enable_grounding != preset.grounding
               or project.target_format != preset.target_export)
    project.task_type = preset.task_type
    project.target_format = preset.target_export
    project.enable_caption = preset.caption
    project.enable_conversations = preset.conversations
    project.enable_grounding = preset.grounding
    return changed


@dataclass
class ProjectSummary:
    """Lightweight info for the welcome page project list.

    Reads JSON files only — no full filesystem scan — so the page can
    refresh quickly even with many recents.
    """
    root_path: Path
    name: str
    updated_at: str
    exists: bool                       # directory still exists
    has_project: bool = False          # .dataforge/project.json present
    # Project metadata (populated when has_project is True)
    task_type: TaskType | None = None
    target_format: str = ""
    annotation_format: str = ""
    class_count: int = 0
    version_count: int = 0
    latest_version_format: str = ""
    # Workflow stats (populated when workflow.json exists; otherwise 0)
    wf_total: int = 0
    wf_ready: int = 0
    wf_review: int = 0
    wf_new: int = 0
    wf_in_progress: int = 0            # annotating + others mid-pipeline


def list_known_projects() -> list[ProjectSummary]:
    """Build project summaries from the recent list + project.json files."""
    from . import workflow_store

    summaries: list[ProjectSummary] = []
    for path_str in load_recent():
        root = Path(path_str)
        if not root.is_dir():
            summaries.append(ProjectSummary(
                root_path=root, name=root.name, updated_at="", exists=False
            ))
            continue
        proj = load_project(root)
        # Quick workflow summary (reads JSON, no scan)
        ws = workflow_store.summarize(root)
        try:
            from .version_builder import list_training_versions
            versions = list_training_versions(root)
        except Exception:
            versions = []
        wf_in_progress = max(0, ws.total - (
            (ws.ready + ws.exported)
            + (ws.review_pending + ws.needs_fix)
            + (ws.new + ws.prelabeled)
        ))
        if proj:
            summaries.append(ProjectSummary(
                root_path=root,
                name=proj.name,
                updated_at=proj.updated_at,
                exists=True,
                has_project=True,
                task_type=proj.task_type,
                target_format=proj.target_format,
                annotation_format=proj.annotation_format,
                class_count=len(proj.class_names),
                version_count=len(versions),
                latest_version_format=versions[0].fmt if versions else "",
                wf_total=ws.total,
                wf_ready=ws.ready + ws.exported,
                wf_review=ws.review_pending + ws.needs_fix,
                wf_new=ws.new + ws.prelabeled,
                wf_in_progress=wf_in_progress,
            ))
        else:
            summaries.append(ProjectSummary(
                root_path=root, name=root.name, updated_at="", exists=True,
                has_project=False,
                version_count=len(versions),
                latest_version_format=versions[0].fmt if versions else "",
                wf_total=ws.total,
                wf_ready=ws.ready + ws.exported,
                wf_review=ws.review_pending + ws.needs_fix,
                wf_new=ws.new + ws.prelabeled,
                wf_in_progress=wf_in_progress,
            ))
    return summaries
