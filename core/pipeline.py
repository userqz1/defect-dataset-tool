"""Pipeline execution engine — graph-based node execution with port routing.

Pure Python — no PyQt imports.

Usage::

    from core.pipeline import GraphEngine

    engine = GraphEngine()
    result = engine.execute(graph, dataset, progress_cb=my_cb)
    # result.node_results[node_id] has per-node StepResult + input/output data
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .models import Dataset, ImageInfo


# ---------- Result types ----------

ProgressCb = Callable[[int, int, str], None]


@dataclass
class NodeResult:
    """Per-node execution result with input/output data for workspace display."""
    node_name: str
    display_name: str
    success: bool
    message: str
    input_data: Any = None       # data the node received
    output_data: dict[str, Any] = field(default_factory=dict)  # port → data
    step_result: Any = None      # raw StepResult from the node


@dataclass
class GraphResult:
    """Result from graph-based execution."""
    success: bool
    steps_run: int
    steps_total: int
    node_results: dict[int, NodeResult] = field(default_factory=dict)
    error: str = ""


# ---------- Engine ----------

class GraphEngine:
    """Graph-aware pipeline executor with topological sort and port routing.

    Reads the connection graph from the canvas, topologically sorts nodes,
    and routes data between connected ports.
    """

    def execute(
        self,
        graph: list[dict],
        dataset: Dataset | None,
        progress_cb: ProgressCb | None = None,
    ) -> GraphResult:
        from .nodes import NODES

        # Parse graph into _GraphNodeDefs
        nodes = {g["id"]: _GraphNodeDef(**g) for g in graph}
        total = len(nodes)

        # Topological sort (Kahn's algorithm)
        try:
            order = self._topo_sort(nodes)
        except ValueError as e:
            return GraphResult(success=False, steps_run=0, steps_total=total, error=str(e))

        # Port data: node_id → {port_name → data}
        port_data: dict[int, dict[str, Any]] = {}
        results: dict[int, NodeResult] = {}

        for i, nid in enumerate(order):
            ndef = nodes[nid]
            spec = NODES.get(ndef.node_name)
            if spec is None:
                results[nid] = NodeResult(
                    ndef.node_name, ndef.display_name, False,
                    f"未知节点: {ndef.node_name}")
                continue

            if progress_cb:
                progress_cb(i, total, f"执行: {spec.display_name}")

            try:
                # Collect input data from upstream ports
                input_data = self._collect_input(ndef, port_data, dataset)

                # Execute the node
                step_result = spec.execute(input_data, dict(ndef.params), progress_cb=None)

                # Route outputs to downstream ports
                outputs = self._route_outputs(ndef.node_name, spec, step_result, input_data)
                port_data[nid] = outputs

                results[nid] = NodeResult(
                    ndef.node_name, spec.display_name, True,
                    f"完成: {step_result.ok_count} 通过",
                    input_data=input_data,
                    output_data=outputs,
                    step_result=step_result,
                )

            except Exception as e:
                results[nid] = NodeResult(
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
        ndef: _GraphNodeDef,
        port_data: dict[int, dict[str, Any]],
        dataset: Dataset | None,
    ) -> Any:
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
    def _route_outputs(node_name: str, spec, result, input_data) -> dict[str, Any]:
        """Map a StepResult to per-output-port data."""
        ports = getattr(spec, "ports", ())
        out_ports = [p for p in ports if p.direction == "output"]

        # -- Quality check: split into passed / rejected --
        if node_name == "quality_check":
            bad_paths = set()
            if result.details:
                for issue in result.details:
                    bad_paths.add(str(getattr(issue, "path", "")))
            passed = [img for img in input_data if str(getattr(img, "path", img)) not in bad_paths]
            rejected = [img for img in input_data if str(getattr(img, "path", img)) in bad_paths]
            return {"passed": passed, "rejected": rejected}

        # -- Dedup: split into unique / duplicates --
        if node_name == "dedup":
            dup_paths = set()
            if result.details:
                for group in result.details:
                    # First image in group is kept; rest are duplicates
                    for img in group.images[1:]:
                        dup_paths.add(str(getattr(img, "path", img)))
            unique = [img for img in input_data if str(getattr(img, "path", img)) not in dup_paths]
            dups = [img for img in input_data if str(getattr(img, "path", img)) in dup_paths]
            return {"unique": unique, "duplicates": dups}

        # -- Augment: output new image paths (not originals) --
        if node_name == "augment" and result.output_paths:
            new_infos = [
                ImageInfo(path=p, category="augmented")
                for p in result.output_paths
            ]
            return {"output": new_infos}

        # -- Split: output the SplitResult directly for export to consume --
        if node_name == "split" and result.details:
            return {"output": result.details}

        # -- Default: single output passes through input --
        if len(out_ports) <= 1:
            port_name = out_ports[0].name if out_ports else "output"
            return {port_name: input_data}

        # Fallback: all outputs get the same data
        return {p.name: input_data for p in out_ports}

    @staticmethod
    def _topo_sort(nodes: dict[int, _GraphNodeDef]) -> list[int]:
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


# ---------- Internal ----------

@dataclass
class _GraphNodeDef:
    """A node in the execution graph."""
    id: int
    node_name: str
    display_name: str
    params: dict[str, Any]
    inputs: dict[str, tuple[int, str]]  # port_name → (upstream_id, upstream_port)
