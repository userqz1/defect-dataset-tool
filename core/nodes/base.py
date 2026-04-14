"""Node system base types — Protocol, PortDef, ParamDef, StepResult, CategoryMeta.

Pure Python — no GUI imports.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable


# ---------- Port & parameter definitions ----------

@dataclass(frozen=True)
class PortDef:
    """Typed port on a processing node."""
    name: str           # machine key, e.g. "passed"
    label: str          # display, e.g. "合格"
    direction: str      # "input" | "output"
    data_type: str = "dataset"   # "dataset" | "report"


@dataclass(frozen=True)
class ParamDef:
    """Configurable parameter on a processing node."""
    name: str
    label: str
    type: str          # "int" | "float" | "str" | "bool" | "choice" | "path"
    default: Any = None
    choices: tuple[str, ...] | None = None
    min_val: float | None = None
    max_val: float | None = None


# ---------- Result type ----------

@dataclass
class StepResult:
    """Uniform result returned by every processing node."""
    ok_count: int = 0
    fail_count: int = 0
    output_paths: list[Path] = field(default_factory=list)
    details: Any = None          # node-specific payload


# ---------- Protocol ----------

ProgressCb = Callable[[int, int, str], None]


@runtime_checkable
class ProcessingNode(Protocol):
    """Interface that every processing node must satisfy."""

    @property
    def name(self) -> str: ...

    @property
    def display_name(self) -> str: ...

    @property
    def step_type(self) -> str: ...

    @property
    def description(self) -> str: ...

    def execute(
        self,
        images: list,
        options: dict[str, Any],
        progress_cb: ProgressCb | None = None,
    ) -> StepResult: ...

    def route(
        self,
        input_data: list,
        result: StepResult,
    ) -> dict[str, Any]: ...


def _default_route(spec, input_data: list, result: StepResult) -> dict[str, Any]:
    """Fallback route: single output port passes through input data."""
    ports = getattr(spec, "ports", ())
    out_ports = [p for p in ports if p.direction == "output"]
    port_name = out_ports[0].name if out_ports else "output"
    return {port_name: input_data}


# ---------- Category visual metadata (pure Python — no Qt) ----------

@dataclass(frozen=True)
class CategoryMeta:
    """Display metadata for a node category. Token names resolved in GUI layer."""
    display_name: str       # e.g. "清洁"
    color_token: str        # e.g. "NODE_CAT_CLEAN" — getattr(T, token) in GUI
    icon_name: str          # FluentIcon enum name, e.g. "CERTIFICATE"


CATEGORY_META: dict[str, CategoryMeta] = {
    "clean":   CategoryMeta("清洁", "NODE_CAT_CLEAN", "CERTIFICATE"),
    "augment": CategoryMeta("增强", "NODE_CAT_AUGMENT", "ADD"),
    "split":   CategoryMeta("划分", "NODE_CAT_SPLIT", "TILES"),
    "export":  CategoryMeta("导出", "NODE_CAT_EXPORT", "SHARE"),
    "input":   CategoryMeta("输入", "NODE_CAT_INPUT", "FOLDER"),
}
