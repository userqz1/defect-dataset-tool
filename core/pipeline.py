"""Pipeline execution engine — runs processing nodes in sequence.

The core of v2 architecture: PipelineContext carries data through nodes,
each node reads from and writes to the context.

Pure Python — no PyQt imports.

Usage::

    from core.pipeline import PipelineContext, PipelineEngine

    ctx = PipelineContext.from_dataset(dataset, task_type)
    engine = PipelineEngine()
    engine.add_step("quality_check", {"blur_threshold": 100})
    engine.add_step("split", {"train": 0.8, "val": 0.1, "test": 0.1})

    result = engine.execute(ctx, progress_cb=my_cb)
    print(result.success, result.step_results)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .models import Dataset, ImageInfo
from .task_types import TaskType


# ---------- Pipeline Context ----------

@dataclass
class PipelineContext:
    """Mutable context that flows through the pipeline.

    Each node reads from this, modifies it, and passes it on.
    """
    dataset: Dataset
    task_type: TaskType

    # Active image list — nodes filter/expand this
    images: list[ImageInfo] = field(default_factory=list)

    # Accumulated results from each step
    step_results: dict[str, Any] = field(default_factory=dict)

    # Images flagged by quality/dedup checks (path → reason)
    flagged: dict[str, str] = field(default_factory=dict)

    # Split result (populated by split node)
    split: Any = None  # SplitResult

    # Export output path
    export_path: Path | None = None

    @classmethod
    def from_dataset(cls, dataset: Dataset, task_type: TaskType) -> PipelineContext:
        all_images = [img for cat in dataset.categories for img in cat.images]
        return cls(
            dataset=dataset,
            task_type=task_type,
            images=all_images,
        )


# ---------- Step Definition ----------

@dataclass
class StepDef:
    """A configured step in the pipeline."""
    node_name: str
    options: dict[str, Any] = field(default_factory=dict)


# ---------- Step Result ----------

@dataclass
class StepResultRecord:
    node_name: str
    display_name: str
    success: bool
    message: str
    details: Any = None


# ---------- Pipeline Result ----------

@dataclass
class PipelineResult:
    success: bool
    steps_run: int
    steps_total: int
    step_results: list[StepResultRecord] = field(default_factory=list)
    error: str = ""


# ---------- Engine ----------

ProgressCb = Callable[[int, int, str], None]


class PipelineEngine:
    """Executes a sequence of processing steps on a PipelineContext."""

    def __init__(self) -> None:
        self._steps: list[StepDef] = []

    def add_step(self, node_name: str, options: dict | None = None) -> None:
        self._steps.append(StepDef(node_name, options or {}))

    def clear(self) -> None:
        self._steps.clear()

    @property
    def steps(self) -> list[StepDef]:
        return list(self._steps)

    def execute(
        self,
        ctx: PipelineContext,
        progress_cb: ProgressCb | None = None,
    ) -> PipelineResult:
        """Run all steps in sequence. Returns PipelineResult."""
        from .nodes import NODES

        results: list[StepResultRecord] = []
        total = len(self._steps)

        for i, step in enumerate(self._steps):
            node = NODES.get(step.node_name)
            if node is None:
                results.append(StepResultRecord(
                    node_name=step.node_name,
                    display_name=step.node_name,
                    success=False,
                    message=f"未知节点: {step.node_name}",
                ))
                continue

            if progress_cb:
                progress_cb(i, total, f"执行: {node.display_name}")

            try:
                step_result = node.execute(ctx.images, step.options, progress_cb=None)

                # Apply step effects to context
                self._apply_result(ctx, step.node_name, step_result)

                results.append(StepResultRecord(
                    node_name=step.node_name,
                    display_name=node.display_name,
                    success=True,
                    message=f"完成: {step_result.ok_count} 项通过, {step_result.fail_count} 项问题",
                    details=step_result.details,
                ))
                ctx.step_results[step.node_name] = step_result

            except Exception as e:
                results.append(StepResultRecord(
                    node_name=step.node_name,
                    display_name=node.display_name,
                    success=False,
                    message=str(e),
                ))
                return PipelineResult(
                    success=False,
                    steps_run=i + 1,
                    steps_total=total,
                    step_results=results,
                    error=f"{node.display_name} 执行失败: {e}",
                )

        if progress_cb:
            progress_cb(total, total, "全部完成")

        return PipelineResult(
            success=True,
            steps_run=total,
            steps_total=total,
            step_results=results,
        )

    @staticmethod
    def _apply_result(ctx: PipelineContext, node_name: str, result) -> None:
        """Update pipeline context based on a step's result."""
        if node_name == "quality_check" and result.details:
            for issue in result.details:
                ctx.flagged[str(issue.path)] = issue.kind

        elif node_name == "dedup" and result.details:
            for group in result.details:
                for img in group.images[1:]:
                    ctx.flagged[str(img)] = "duplicate"

        elif node_name == "split" and result.details:
            ctx.split = result.details


# ---------- Graph-based Engine (v3) ----------

@dataclass
class GraphNodeDef:
    """A node in the execution graph."""
    id: int
    node_name: str
    display_name: str
    params: dict[str, Any]
    inputs: dict[str, tuple[int, str]]  # port_name → (upstream_id, upstream_port)


@dataclass
class GraphResult:
    """Result from graph-based execution."""
    success: bool
    steps_run: int
    steps_total: int
    node_results: dict[int, StepResultRecord] = field(default_factory=dict)
    error: str = ""


class GraphEngine:
    """Graph-aware pipeline executor with topological sort and port routing.

    Unlike PipelineEngine which runs nodes sequentially, GraphEngine:
    - Reads the connection graph from the canvas
    - Topologically sorts nodes by dependencies
    - Routes data between connected ports
    """

    def execute(
        self,
        graph: list[dict],
        dataset: Dataset | None,
        progress_cb: ProgressCb | None = None,
    ) -> GraphResult:
        from .nodes import NODES

        # Parse graph into GraphNodeDefs
        nodes = {g["id"]: GraphNodeDef(**g) for g in graph}
        total = len(nodes)

        # Topological sort (Kahn's algorithm)
        try:
            order = self._topo_sort(nodes)
        except ValueError as e:
            return GraphResult(success=False, steps_run=0, steps_total=total, error=str(e))

        # Port data: node_id → {port_name → data}
        port_data: dict[int, dict[str, Any]] = {}
        results: dict[int, StepResultRecord] = {}

        for i, nid in enumerate(order):
            ndef = nodes[nid]
            spec = NODES.get(ndef.node_name)
            if spec is None:
                results[nid] = StepResultRecord(
                    ndef.node_name, ndef.display_name, False, f"未知节点: {ndef.node_name}")
                continue

            if progress_cb:
                progress_cb(i, total, f"执行: {spec.display_name}")

            try:
                # Collect input data from upstream ports
                images = self._collect_input(ndef, port_data, dataset)

                # Execute the node
                step_result = spec.execute(images, ndef.params, progress_cb=None)

                # Store per-output data
                port_data[nid] = self._route_outputs(ndef.node_name, spec, step_result, images)

                results[nid] = StepResultRecord(
                    ndef.node_name, spec.display_name, True,
                    f"完成: {step_result.ok_count} 通过",
                    details=step_result.details,
                )

            except Exception as e:
                results[nid] = StepResultRecord(
                    ndef.node_name, spec.display_name, False, str(e))
                return GraphResult(
                    success=False, steps_run=i + 1, steps_total=total,
                    node_results=results,
                    error=f"{spec.display_name} 失败: {e}",
                )

        if progress_cb:
            progress_cb(total, total, "全部完成")

        return GraphResult(
            success=True, steps_run=total, steps_total=total, node_results=results)

    def _collect_input(
        self,
        ndef: GraphNodeDef,
        port_data: dict[int, dict[str, Any]],
        dataset: Dataset | None,
    ) -> list:
        """Gather input data for a node from upstream connections."""
        if not ndef.inputs:
            # Source node — use dataset images
            if dataset:
                return [img for cat in dataset.categories for img in cat.images]
            return []
        # Use first connected input port's data
        for _port_name, (upstream_id, upstream_port) in ndef.inputs.items():
            upstream = port_data.get(upstream_id, {})
            data = upstream.get(upstream_port)
            if data is not None:
                return data
        return []

    @staticmethod
    def _route_outputs(node_name: str, spec, result, input_images: list) -> dict[str, Any]:
        """Map a StepResult to per-output-port data."""
        ports = getattr(spec, "ports", ())
        out_ports = [p for p in ports if p.direction == "output"]

        if len(out_ports) <= 1:
            # Single output — pass through (possibly filtered)
            port_name = out_ports[0].name if out_ports else "output"
            return {port_name: input_images}

        # Multi-output: route based on node semantics
        if node_name == "quality_check":
            bad_paths = set()
            if result.details:
                for issue in result.details:
                    bad_paths.add(str(getattr(issue, "path", "")))
            passed = [img for img in input_images if str(getattr(img, "path", img)) not in bad_paths]
            rejected = [img for img in input_images if str(getattr(img, "path", img)) in bad_paths]
            return {"passed": passed, "rejected": rejected}

        if node_name == "dedup":
            dup_paths = set()
            if result.details:
                for group in result.details:
                    for img in group.images[1:]:
                        dup_paths.add(str(img))
            unique = [img for img in input_images if str(getattr(img, "path", img)) not in dup_paths]
            dups = [img for img in input_images if str(getattr(img, "path", img)) in dup_paths]
            return {"unique": unique, "duplicates": dups}

        if node_name == "split" and result.details:
            sr = result.details
            return {"train": sr.train, "val": sr.val, "test": sr.test}

        # Fallback: all outputs get the same data
        return {p.name: input_images for p in out_ports}

    @staticmethod
    def _topo_sort(nodes: dict[int, GraphNodeDef]) -> list[int]:
        """Kahn's algorithm. Raises ValueError on cycle."""
        in_degree: dict[int, int] = {nid: 0 for nid in nodes}
        adj: dict[int, list[int]] = {nid: [] for nid in nodes}

        for nid, ndef in nodes.items():
            for _port, (upstream_id, _upstream_port) in ndef.inputs.items():
                if upstream_id in nodes:
                    adj[upstream_id].append(nid)
                    in_degree[nid] += 1

        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        order: list[int] = []

        while queue:
            nid = queue.pop(0)
            order.append(nid)
            for child in adj[nid]:
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)

        if len(order) != len(nodes):
            raise ValueError("管线中存在循环依赖")

        return order
