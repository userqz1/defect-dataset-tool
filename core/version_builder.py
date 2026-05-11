"""Training-version builder.

Creates immutable training snapshots under ``<project>/versions/`` from the
authoritative SampleSet. This is intentionally read-only with respect to the
project dataset: original images and labels are never rewritten.
"""
from __future__ import annotations

import json
import random
import shutil
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from .format_out import ExportOptions, ExportResult, export_samples
from .target_readiness import export_key_for_target_format
from .unified import Sample, SampleSet


@dataclass(frozen=True)
class TrainingVersionConfig:
    """Configuration for one generated training version."""

    fmt: str
    scope: str = "all"  # all / ready / filtered
    categories: tuple[str, ...] = ()
    train_ratio: int = 80
    val_ratio: int = 10
    test_ratio: int = 10
    stratified: bool = True
    seed: int = 42
    copy_images: bool = True
    version_name: str = ""


@dataclass(frozen=True)
class TrainingVersionResult:
    """Result of one version generation run."""

    out_dir: Path
    fmt: str
    sample_count: int
    train_count: int
    val_count: int
    test_count: int
    export_result: ExportResult


@dataclass(frozen=True)
class TrainingVersionSummary:
    """Metadata for a generated training version on disk."""

    name: str
    path: Path
    fmt: str
    created_at: str
    sample_count: int
    train_count: int
    val_count: int
    test_count: int


def build_training_version(
    sample_set: SampleSet,
    project_root: Path,
    config: TrainingVersionConfig,
    *,
    progress_cb=None,
) -> TrainingVersionResult:
    """Export a versioned training snapshot under ``project_root/versions``."""
    config = replace(config, fmt=export_key_for_target_format(config.fmt))
    samples = _filter_samples(sample_set.samples, config)
    if config.fmt == "pairedfolder":
        from .pairing import unique_pair_samples
        samples = unique_pair_samples(samples)
    if not samples:
        raise ValueError("no samples match the selected version scope")

    samples = _assign_splits(samples, config)
    version_set = SampleSet(samples=samples)

    out_dir = _version_dir(project_root, config)
    opts = ExportOptions(out_dir=out_dir, copy_images=config.copy_images)
    export_result = export_samples(version_set, config.fmt, opts,
                                   progress_cb=progress_cb)

    sample_count = len(samples)
    train_count = sum(1 for s in samples if s.split == "train")
    val_count = sum(1 for s in samples if s.split == "val")
    test_count = sum(1 for s in samples if s.split == "test")
    _write_version_meta(
        out_dir,
        config=config,
        sample_count=sample_count,
        train_count=train_count,
        val_count=val_count,
        test_count=test_count,
    )

    return TrainingVersionResult(
        out_dir=out_dir,
        fmt=config.fmt,
        sample_count=sample_count,
        train_count=train_count,
        val_count=val_count,
        test_count=test_count,
        export_result=export_result,
    )


def list_training_versions(project_root: Path) -> list[TrainingVersionSummary]:
    """Return generated training versions under ``<project>/versions``."""
    versions_dir = Path(project_root) / "versions"
    if not versions_dir.exists():
        return []

    summaries: list[TrainingVersionSummary] = []
    for child in versions_dir.iterdir():
        if not child.is_dir():
            continue
        summaries.append(_read_version_summary(child))
    return sorted(summaries, key=lambda s: s.created_at or s.name, reverse=True)


def delete_training_version(path: Path, project_root: Path) -> bool:
    """Delete one generated version, guarded to the project's versions dir."""
    versions_root = (Path(project_root) / "versions").resolve()
    target = Path(path).resolve()
    if target == versions_root:
        return False
    try:
        target.relative_to(versions_root)
    except ValueError:
        return False
    if not target.exists() or not target.is_dir():
        return False
    shutil.rmtree(target)
    return True


def _filter_samples(
    samples: list[Sample],
    config: TrainingVersionConfig,
) -> list[Sample]:
    out = list(samples)
    if config.scope == "ready":
        out = [s for s in out if s.work_status in ("ready", "exported")]
    if config.categories:
        keep = set(config.categories)
        out = [s for s in out if s.category in keep]
    return out


def _assign_splits(
    samples: list[Sample],
    config: TrainingVersionConfig,
) -> list[Sample]:
    rng = random.Random(config.seed)
    groups: list[list[Sample]]
    if config.stratified:
        by_cat: dict[str, list[Sample]] = {}
        for sample in samples:
            by_cat.setdefault(sample.category or "", []).append(sample)
        groups = list(by_cat.values())
    else:
        groups = [list(samples)]

    assigned: list[Sample] = []
    for group in groups:
        shuffled = list(group)
        rng.shuffle(shuffled)
        for sample, split in zip(shuffled, _split_labels(len(shuffled), config)):
            assigned.append(replace(sample, split=split))
    return assigned


def _split_labels(n: int, config: TrainingVersionConfig) -> list[str]:
    total = max(1, config.train_ratio + config.val_ratio + config.test_ratio)
    train_n = int(round(n * config.train_ratio / total))
    val_n = int(round(n * config.val_ratio / total))
    if train_n + val_n > n:
        overflow = train_n + val_n - n
        val_n = max(0, val_n - overflow)
    test_n = max(0, n - train_n - val_n)
    labels = ["train"] * train_n + ["val"] * val_n + ["test"] * test_n
    if len(labels) < n:
        labels.extend(["train"] * (n - len(labels)))
    return labels[:n]


def _version_dir(project_root: Path, config: TrainingVersionConfig) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fmt = (config.fmt or "export").lower().replace(" ", "_").replace("-", "_")
    name = config.version_name.strip() or f"v_{ts}_{fmt}"
    safe = "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in name)
    versions = Path(project_root) / "versions"
    out = versions / safe
    if out.exists():
        for i in range(2, 1000):
            candidate = versions / f"{safe}_{i}"
            if not candidate.exists():
                out = candidate
                break
    out.mkdir(parents=True, exist_ok=False)
    return out


def _write_version_meta(
    out_dir: Path,
    *,
    config: TrainingVersionConfig,
    sample_count: int,
    train_count: int,
    val_count: int,
    test_count: int,
) -> None:
    payload = {
        "name": out_dir.name,
        "format": config.fmt,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "sample_count": sample_count,
        "train_count": train_count,
        "val_count": val_count,
        "test_count": test_count,
        "scope": config.scope,
        "categories": list(config.categories),
        "train_ratio": config.train_ratio,
        "val_ratio": config.val_ratio,
        "test_ratio": config.test_ratio,
        "stratified": config.stratified,
        "copy_images": config.copy_images,
    }
    (out_dir / "version.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _read_version_summary(path: Path) -> TrainingVersionSummary:
    meta_path = path / "version.json"
    data: dict = {}
    if meta_path.exists():
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    return TrainingVersionSummary(
        name=str(data.get("name") or path.name),
        path=path,
        fmt=str(data.get("format") or ""),
        created_at=str(data.get("created_at") or ""),
        sample_count=int(data.get("sample_count") or 0),
        train_count=int(data.get("train_count") or 0),
        val_count=int(data.get("val_count") or 0),
        test_count=int(data.get("test_count") or 0),
    )
