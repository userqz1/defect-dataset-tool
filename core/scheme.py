"""Scheme persistence — save/load canvas state as JSON.

A scheme captures the full node graph: nodes, positions, connections,
and per-node parameters. Stored in ~/.dataforge/schemes/.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


SCHEMES_DIR = Path.home() / ".dataforge" / "schemes"


@dataclass
class SchemeNode:
    node_name: str
    display_name: str
    step_type: str
    x: float
    y: float
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class SchemeConnection:
    src_idx: int        # index in nodes list
    src_port: str       # output port name
    tgt_idx: int
    tgt_port: str       # input port name


@dataclass
class Scheme:
    name: str
    nodes: list[SchemeNode] = field(default_factory=list)
    connections: list[SchemeConnection] = field(default_factory=list)
    created: str = ""
    modified: str = ""

    def __post_init__(self) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        if not self.created:
            self.created = now
        if not self.modified:
            self.modified = now


def save_scheme(scheme: Scheme, path: Path | None = None) -> Path:
    """Save scheme to JSON. Returns the file path."""
    if path is None:
        SCHEMES_DIR.mkdir(parents=True, exist_ok=True)
        safe_name = scheme.name.replace(" ", "_").replace("/", "_")
        path = SCHEMES_DIR / f"{safe_name}.json"

    scheme.modified = datetime.now().isoformat(timespec="seconds")
    data = {
        "name": scheme.name,
        "created": scheme.created,
        "modified": scheme.modified,
        "nodes": [asdict(n) for n in scheme.nodes],
        "connections": [asdict(c) for c in scheme.connections],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_scheme(path: Path) -> Scheme | None:
    """Load scheme from JSON file."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        nodes = [SchemeNode(**n) for n in data.get("nodes", [])]
        conns = [SchemeConnection(**c) for c in data.get("connections", [])]
        return Scheme(
            name=data.get("name", path.stem),
            nodes=nodes,
            connections=conns,
            created=data.get("created", ""),
            modified=data.get("modified", ""),
        )
    except Exception:
        return None


def list_recent_schemes(limit: int = 20) -> list[tuple[Path, str, str]]:
    """List recent schemes: [(path, name, modified), ...] sorted by modified desc."""
    SCHEMES_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    for f in SCHEMES_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            results.append((f, data.get("name", f.stem), data.get("modified", "")))
        except Exception:
            continue
    results.sort(key=lambda x: x[2], reverse=True)
    return results[:limit]


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

TEMPLATES: list[Scheme] = [
    Scheme(
        name="质量清洗流程",
        nodes=[
            SchemeNode("data_source", "数据源", "input", 100, 80),
            SchemeNode("quality_check", "质量检查", "clean", 360, 80),
            SchemeNode("export", "导出", "export", 620, 80),
        ],
        connections=[
            SchemeConnection(0, "output", 1, "input"),
            SchemeConnection(1, "passed", 2, "input"),
        ],
    ),
    Scheme(
        name="YOLO 导出流程",
        nodes=[
            SchemeNode("data_source", "数据源", "input", 100, 80),
            SchemeNode("split", "数据集划分", "split", 360, 80),
            SchemeNode("export", "导出", "export", 620, 80),
        ],
        connections=[
            SchemeConnection(0, "output", 1, "input"),
            SchemeConnection(1, "train", 2, "input"),
        ],
    ),
    Scheme(
        name="完整处理流程",
        nodes=[
            SchemeNode("data_source", "数据源", "input", 100, 100),
            SchemeNode("quality_check", "质量检查", "clean", 340, 40),
            SchemeNode("augment", "数据增强", "augment", 340, 180),
            SchemeNode("split", "数据集划分", "split", 580, 100),
            SchemeNode("export", "导出", "export", 820, 100),
        ],
        connections=[
            SchemeConnection(0, "output", 1, "input"),
            SchemeConnection(1, "passed", 2, "input"),
            SchemeConnection(2, "output", 3, "input"),
            SchemeConnection(3, "train", 4, "input"),
        ],
    ),
]
