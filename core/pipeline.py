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

        # Parse graph into _GraphNodeDefs (explicit fields to avoid blowup on extra keys)
        nodes = {
            g["id"]: _GraphNodeDef(
                id=g["id"],
                node_name=g["node_name"],
                display_name=g.get("display_name", g["node_name"]),
                params=g.get("params", {}),
                inputs=g.get("inputs", {}),
            )
            for g in graph
        }
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
        """Delegate routing to the node's own route() method."""
        if hasattr(spec, "route"):
            try:
                return spec.route(input_data, result)
            except Exception:
                pass
        # Fallback for nodes without route(): single-output passthrough
        from .nodes import _default_route
        return _default_route(spec, input_data, result)

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
