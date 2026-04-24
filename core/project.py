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


# ---------- State sub-models ----------

@dataclass
class BrowseState:
    category: str = ""
    filter: str = "all"      # all / labeled / unlabeled
    search: str = ""
    page: int = 0


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

    return Project(
        root_path=root,
        name=raw.get("name", root.name),
        task_type=task_type,
        target_format=raw.get("target_format", ""),
        created_at=raw.get("created_at", ""),
        updated_at=raw.get("updated_at", ""),
        notes=raw.get("notes", ""),
        class_names=raw.get("class_names", []),
        annotation_format=ann_fmt,
        browse_state=BrowseState(
            category=bs.get("category", ""),
            filter=bs.get("filter", "all"),
            search=bs.get("search", ""),
            page=bs.get("page", 0),
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
                    task_type: TaskType = TaskType.DETECTION) -> Project:
    """Create a new project for a dataset directory."""
    project = Project(
        root_path=root,
        name=name or root.name,
        task_type=task_type,
        created_at=_now_iso(),
        updated_at=_now_iso(),
    )
    save_project(project)
    return project


@dataclass
class ProjectSummary:
    """Lightweight info for the welcome page project list."""
    root_path: Path
    name: str
    updated_at: str
    exists: bool  # whether the directory still exists
    # Workflow stats (optional — populated when workflow.json exists)
    wf_total: int = 0
    wf_ready: int = 0
    wf_review: int = 0
    wf_new: int = 0


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
        if proj:
            summaries.append(ProjectSummary(
                root_path=root,
                name=proj.name,
                updated_at=proj.updated_at,
                exists=True,
                wf_total=ws.total,
                wf_ready=ws.ready + ws.exported,
                wf_review=ws.review_pending + ws.needs_fix,
                wf_new=ws.new + ws.prelabeled,
            ))
        else:
            summaries.append(ProjectSummary(
                root_path=root, name=root.name, updated_at="", exists=True,
                wf_total=ws.total,
                wf_ready=ws.ready + ws.exported,
                wf_review=ws.review_pending + ws.needs_fix,
                wf_new=ws.new + ws.prelabeled,
            ))
    return summaries
