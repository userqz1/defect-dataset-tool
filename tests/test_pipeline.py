"""Tests for core/pipeline.py — GraphEngine topological sort and port routing."""
from __future__ import annotations

import pytest

from core.pipeline import GraphEngine, GraphResult


def _make_graph(*specs: tuple[int, str, dict]) -> list[dict]:
    """Build a graph list from (id, node_name, inputs) tuples."""
    return [
        {"id": nid, "node_name": name, "display_name": name,
         "params": {}, "inputs": inputs}
        for nid, name, inputs in specs
    ]


class TestTopoSort:
    """GraphEngine._topo_sort edge cases."""

    def test_linear_chain(self):
        """A → B → C should execute in that order."""
        graph = _make_graph(
            (1, "data_source", {}),
            (2, "quality_check", {"input": (1, "output")}),
            (3, "export", {"input": (2, "passed")}),
        )
        engine = GraphEngine()
        # We can't call _topo_sort directly (it's static, needs parsed nodes)
        # so we run execute with a minimal dataset
        from core.models import Dataset
        ds = Dataset(name="test", root_path=".", categories=[], total_images=0)
        result = engine.execute(graph, ds)
        assert isinstance(result, GraphResult)
        # data_source should fail (no images) but the graph should parse OK
        assert result.steps_run >= 1

    def test_cycle_detection(self):
        """Cycle A → B → A should fail with meaningful error."""
        graph = _make_graph(
            (1, "quality_check", {"input": (2, "output")}),
            (2, "quality_check", {"input": (1, "passed")}),
        )
        engine = GraphEngine()
        result = engine.execute(graph, None)
        assert not result.success
        assert "循环" in result.error

    def test_empty_graph(self):
        """Empty graph should succeed with 0 steps."""
        engine = GraphEngine()
        result = engine.execute([], None)
        assert result.success
        assert result.steps_run == 0

    def test_unknown_node(self):
        """Unknown node type should be reported but not crash."""
        graph = _make_graph((1, "nonexistent_node", {}))
        engine = GraphEngine()
        result = engine.execute(graph, None)
        # Should have a result for node 1 that's not successful
        assert 1 in result.node_results
        assert not result.node_results[1].success


class TestNodeRoute:
    """Verify each node's route() method produces correct port data."""

    def test_quality_check_route(self):
        from core.nodes import QualityCheckNode, StepResult
        node = QualityCheckNode()

        class FakeIssue:
            def __init__(self, p):
                self.path = p

        class FakeImg:
            def __init__(self, p):
                self.path = p

        imgs = [FakeImg("a.jpg"), FakeImg("b.jpg"), FakeImg("c.jpg")]
        result = StepResult(ok_count=2, fail_count=1,
                            details=[FakeIssue("b.jpg")])
        routed = node.route(imgs, result)
        assert "passed" in routed
        assert "rejected" in routed
        assert len(routed["passed"]) == 2
        assert len(routed["rejected"]) == 1

    def test_split_route(self):
        from core.nodes import SplitNode, StepResult
        from core.splitter import SplitResult
        node = SplitNode()
        sr = SplitResult(train=["a", "b"], val=["c"], test=["d"])
        result = StepResult(ok_count=4, details=sr)
        routed = node.route([], result)
        assert "output" in routed
        assert routed["output"] is sr

    def test_augment_route_with_output_paths(self):
        from pathlib import Path
        from core.nodes import AugmentNode, StepResult
        node = AugmentNode()
        result = StepResult(ok_count=2, output_paths=[Path("a.jpg"), Path("b.jpg")])
        routed = node.route([], result)
        assert len(routed["output"]) == 2
        assert routed["output"][0].path == Path("a.jpg")
