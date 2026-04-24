"""Tests for core/workflow.py and core/workflow_store.py.

Covers: WorkflowState round-trip, WorkStatus transitions, IngestBatch
registration, WorkflowSummary derivation, sync_samples behaviour.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.workflow import (
    IngestBatch,
    WorkItem,
    WorkStatus,
    WorkflowState,
    WorkflowSummary,
    make_id,
    sync_samples,
)
from core import workflow_store
from core.unified import Sample, SampleSet


# ── Fixtures ───────────────────────────────────────────────────────────

def _make_item(rel: str, status: WorkStatus = WorkStatus.NEW,
               batch_id: str = "") -> WorkItem:
    return WorkItem(
        item_id=make_id(),
        relative_path=rel,
        batch_id=batch_id,
        status=status,
    )


def _make_sample(root: Path, rel: str) -> Sample:
    """Sample whose image_path = root / rel."""
    return Sample(image_path=root / rel)


# ── WorkflowState serialization ───────────────────────────────────────

class TestWorkflowStateSerialization:
    def test_round_trip_empty(self):
        ws = WorkflowState()
        assert WorkflowState.from_dict(ws.to_dict()).batches == []
        assert WorkflowState.from_dict(ws.to_dict()).items == []

    def test_round_trip_with_items(self):
        ws = WorkflowState(
            batches=[IngestBatch(batch_id="b1", name="Batch 1",
                                 item_count=3)],
            items=[
                _make_item("a/images/1.png", WorkStatus.NEW, "b1"),
                _make_item("a/images/2.png", WorkStatus.READY, "b1"),
            ],
            active_batch_id="b1",
        )
        loaded = WorkflowState.from_dict(ws.to_dict())
        assert len(loaded.batches) == 1
        assert loaded.batches[0].name == "Batch 1"
        assert len(loaded.items) == 2
        assert loaded.items[1].status is WorkStatus.READY
        assert loaded.active_batch_id == "b1"

    def test_unknown_status_falls_back_to_new(self):
        raw = {"item_id": "x", "relative_path": "a.png",
               "status": "nonexistent"}
        item = WorkItem.from_dict(raw)
        assert item.status is WorkStatus.NEW


# ── WorkflowSummary ───────────────────────────────────────────────────

class TestWorkflowSummary:
    def test_from_state_counts(self):
        ws = WorkflowState(items=[
            _make_item("a.png", WorkStatus.NEW),
            _make_item("b.png", WorkStatus.NEW),
            _make_item("c.png", WorkStatus.READY),
            _make_item("d.png", WorkStatus.ANNOTATING),
        ], batches=[IngestBatch(batch_id="b1")])
        s = WorkflowSummary.from_state(ws)
        assert s.total == 4
        assert s.new == 2
        assert s.ready == 1
        assert s.annotating == 1
        assert s.batch_count == 1

    def test_from_sample_set(self):
        ss = SampleSet(samples=[
            Sample(image_path=Path("a.png"), work_status="new"),
            Sample(image_path=Path("b.png"), work_status="ready"),
            Sample(image_path=Path("c.png"), work_status="ready"),
        ])
        s = WorkflowSummary.from_sample_set(ss, batch_count=2)
        assert s.total == 3
        assert s.new == 1
        assert s.ready == 2
        assert s.batch_count == 2


# ── workflow_store persistence ────────────────────────────────────────

class TestWorkflowStore:
    def test_save_load_round_trip(self, tmp_path):
        root = tmp_path / "proj"
        root.mkdir()
        ws = WorkflowState(
            items=[_make_item("x.png", WorkStatus.ANNOTATING)],
            batches=[IngestBatch(batch_id="b1", name="B1")],
        )
        workflow_store.save(root, ws)
        loaded = workflow_store.load(root)
        assert len(loaded.items) == 1
        assert loaded.items[0].status is WorkStatus.ANNOTATING
        assert loaded.batches[0].name == "B1"

    def test_load_missing_returns_empty(self, tmp_path):
        ws = workflow_store.load(tmp_path)
        assert len(ws.items) == 0
        assert len(ws.batches) == 0

    def test_add_batch(self, tmp_path):
        root = tmp_path / "proj"
        root.mkdir()
        batch = IngestBatch(batch_id="b1", name="First")
        items = [_make_item("img1.png", batch_id="b1")]
        state = workflow_store.add_batch(root, batch, items)
        assert state.active_batch_id == "b1"
        assert len(state.items) == 1

        # Second batch appends
        batch2 = IngestBatch(batch_id="b2", name="Second")
        items2 = [_make_item("img2.png", batch_id="b2")]
        state2 = workflow_store.add_batch(root, batch2, items2)
        assert len(state2.batches) == 2
        assert len(state2.items) == 2
        assert state2.active_batch_id == "b2"

    def test_update_status(self, tmp_path):
        root = tmp_path / "proj"
        root.mkdir()
        item = _make_item("x.png", WorkStatus.NEW)
        iid = item.item_id
        workflow_store.save(root, WorkflowState(items=[item]))

        updated = workflow_store.update_status(
            root, [iid], WorkStatus.READY)
        assert updated.items[0].status is WorkStatus.READY
        assert updated.items[0].updated_at != ""

    def test_remove_items(self, tmp_path):
        root = tmp_path / "proj"
        root.mkdir()
        i1 = _make_item("a.png")
        i2 = _make_item("b.png")
        workflow_store.save(root, WorkflowState(items=[i1, i2]))

        updated = workflow_store.remove_items(root, [i1.item_id])
        assert len(updated.items) == 1
        assert updated.items[0].item_id == i2.item_id


# ── sync_samples ──────────────────────────────────────────────────────

class TestSyncSamples:
    def test_stamps_existing_items(self, tmp_path):
        root = tmp_path
        ws = WorkflowState(items=[
            _make_item("cat/images/a.png", WorkStatus.READY),
        ])
        ss = SampleSet(samples=[
            _make_sample(root, "cat/images/a.png"),
        ])
        mutated = sync_samples(ws, ss, root, auto_create=False)
        assert not mutated
        assert ss.samples[0].work_status == "ready"

    def test_auto_creates_for_new_images(self, tmp_path):
        root = tmp_path
        ws = WorkflowState()
        ss = SampleSet(samples=[
            _make_sample(root, "defects/images/001.png"),
        ])
        mutated = sync_samples(ws, ss, root, auto_create=True)
        assert mutated
        assert len(ws.items) == 1
        assert ws.items[0].relative_path == "defects/images/001.png"
        assert ss.samples[0].work_status == "new"

    def test_auto_create_prelabeled_when_regions(self, tmp_path):
        from core.unified import BBox, Region
        root = tmp_path
        ws = WorkflowState()
        s = _make_sample(root, "x/images/img.png")
        s.regions = [Region(label="crack", bbox=BBox(0, 0, 10, 10))]
        ss = SampleSet(samples=[s])
        sync_samples(ws, ss, root)
        assert ws.items[0].status is WorkStatus.PRELABELED
        assert ss.samples[0].work_status == "prelabeled"

    def test_skips_auto_create_when_disabled(self, tmp_path):
        root = tmp_path
        ws = WorkflowState()
        ss = SampleSet(samples=[_make_sample(root, "x.png")])
        mutated = sync_samples(ws, ss, root, auto_create=False)
        assert not mutated
        assert len(ws.items) == 0
        assert ss.samples[0].work_status == ""
