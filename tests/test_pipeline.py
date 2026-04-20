"""Pipeline executor tests — context sharing, error paths, stop_on_error.

Uses synthetic steps + real SplitStep/ExportStep where possible so the
orchestrator's error handling + progress aggregation is exercised.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from core.api import (
    ExportStep,
    Pipeline,
    PipelineContext,
    PipelineResult,
    SplitStep,
)


# ---------- Synthetic Steps for orchestrator testing ----------

@dataclass(frozen=True)
class NoopStep:
    name: str = "noop"
    kind: str = "test"

    def execute(self, ctx, progress_cb=None):
        ctx.meta.setdefault("executed", []).append(self.name)


@dataclass(frozen=True)
class RaisingStep:
    name: str = "boom"
    kind: str = "test"
    stop_on_error: bool = False

    def execute(self, ctx, progress_cb=None):
        raise RuntimeError("intentional")


@dataclass(frozen=True)
class ContextWriterStep:
    key: str = "written"
    value: str = "hello"
    name: str = "writer"
    kind: str = "test"

    def execute(self, ctx, progress_cb=None):
        ctx.meta[self.key] = self.value


# ---------- Tests ----------

class TestEmptyPipeline:
    def test_no_steps_runs_clean(self):
        result = Pipeline(name="empty").run()
        assert isinstance(result, PipelineResult)
        assert result.ok
        assert result.executed == []


class TestContextSharing:
    def test_step_output_visible_to_next(self):
        writer = ContextWriterStep(key="k", value="v")

        @dataclass(frozen=True)
        class Reader:
            name: str = "reader"
            kind: str = "test"

            def execute(self, ctx, progress_cb=None):
                ctx.meta["readback"] = ctx.meta.get("k", "MISSING")

        result = Pipeline(name="rw", steps=[writer, Reader()]).run()
        assert result.ok
        assert result.context.meta["readback"] == "v"


class TestErrorHandling:
    def test_failure_collected_not_raised(self):
        result = Pipeline(
            name="err",
            steps=[NoopStep("ok1"), RaisingStep(), NoopStep("ok2")],
        ).run()
        # Non-fatal by default — "ok1" and "ok2" both ran
        assert result.executed == ["ok1", "ok2"]
        assert len(result.errors) == 1
        step_name, msg = result.errors[0]
        assert step_name == "boom"
        assert "intentional" in msg
        assert not result.ok

    def test_stop_on_error_halts_pipeline(self):
        result = Pipeline(
            name="halt",
            steps=[
                NoopStep("before"),
                RaisingStep(name="fatal", stop_on_error=True),
                NoopStep("after"),
            ],
        ).run()
        assert result.executed == ["before"]
        assert result.skipped == ["after"]
        assert len(result.errors) == 1
        assert not result.ok


class TestProgressCallback:
    def test_step_prefix_in_progress_name(self):
        received: list[tuple[int, int, str]] = []

        def cb(done, total, name):
            received.append((done, total, name))

        @dataclass(frozen=True)
        class EmitsProgress:
            name: str = "emit"
            kind: str = "test"

            def execute(self, ctx, progress_cb=None):
                if progress_cb:
                    progress_cb(1, 3, "foo.jpg")

        Pipeline(name="p", steps=[EmitsProgress()]).run(progress_cb=cb)
        # Pipeline prefixes "[i/N] StepName" before the step's own name
        assert any("emit" in msg and "foo.jpg" in msg for _, _, msg in received)


class TestSplitExportComposition:
    def test_split_then_export_yolo(self, synthetic_dataset, tmp_path):
        out = tmp_path / "yolo_out"
        pipe = Pipeline(
            name="s+e",
            steps=[
                SplitStep(train=0.5, val=0.5, test=0.0, seed=42),
                ExportStep(schema_key="YOLO", out_dir=out, copy_images=True),
            ],
        )
        ctx = PipelineContext(dataset=synthetic_dataset)
        result = pipe.run(ctx)
        assert result.ok, f"errors: {result.errors}"
        assert result.executed == ["划分", "导出"]
        # SplitResult populated
        assert result.context.split is not None
        # YOLO files on disk
        assert (out / "classes.txt").exists()
        assert (out / "data.yaml").exists()
        # ExportReport captured
        assert len(result.context.export_reports) == 1

    def test_export_without_split_errors_cleanly(self, synthetic_dataset, tmp_path):
        out = tmp_path / "nope"
        # Missing SplitStep — ExportStep should record a typed error
        pipe = Pipeline(
            name="no-split",
            steps=[ExportStep(schema_key="YOLO", out_dir=out)],
        )
        ctx = PipelineContext(dataset=synthetic_dataset)
        result = pipe.run(ctx)
        assert not result.ok
        assert len(result.errors) == 1
        _, msg = result.errors[0]
        assert "split" in msg.lower() or "Split" in msg

    def test_export_unknown_schema_errors(self, synthetic_dataset, tmp_path):
        pipe = Pipeline(
            name="bad-schema",
            steps=[
                SplitStep(),
                ExportStep(schema_key="Bogus", out_dir=tmp_path / "x"),
            ],
        )
        ctx = PipelineContext(dataset=synthetic_dataset)
        result = pipe.run(ctx)
        assert not result.ok
        assert any("Bogus" in msg or "未注册" in msg
                   for _, msg in result.errors)
