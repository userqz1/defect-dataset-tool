"""Tests for core/inbox.py — create_batch, commit_items, summaries.

Exercises the staged-import pipeline end-to-end with real files on disk.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from core.inbox import (
    INBOX_DIR,
    all_batch_summaries,
    batch_status_counts,
    commit_items,
    create_batch,
    inbox_path,
)
from core.workflow import IngestBatch, WorkItem, WorkStatus, WorkflowState


def _make_source_dir(tmp_path: Path, name: str, n: int) -> Path:
    """Create a directory with *n* dummy PNG images."""
    d = tmp_path / name
    d.mkdir(parents=True)
    for i in range(n):
        img = d / f"{name}_{i:03d}.png"
        Image.new("RGB", (32, 32), (100, 100, 100)).save(img)
    return d


# ── create_batch ──────────────────────────────────────────────────────

class TestCreateBatch:
    def test_copies_images_into_inbox(self, tmp_path):
        src = _make_source_dir(tmp_path / "sources", "alpha", 3)
        root = tmp_path / "project"
        root.mkdir()

        batch, items = create_batch(root, [src], name="Test Batch")
        assert batch.name == "Test Batch"
        assert batch.item_count == 3
        assert len(items) == 3

        # Files actually landed in _inbox/<batch_id>/images/
        inbox = inbox_path(root)
        batch_imgs = list((inbox / batch.batch_id / "images").iterdir())
        assert len(batch_imgs) == 3

    def test_items_have_correct_relative_paths(self, tmp_path):
        src = _make_source_dir(tmp_path / "sources", "beta", 2)
        root = tmp_path / "project"
        root.mkdir()

        batch, items = create_batch(root, [src])
        for item in items:
            assert item.relative_path.startswith(f"{INBOX_DIR}/")
            assert item.batch_id == batch.batch_id
            assert item.status is WorkStatus.NEW

    def test_deduplicates_filenames_within_batch(self, tmp_path):
        root = tmp_path / "project"
        root.mkdir()
        # Two source dirs with same-named files
        d1 = tmp_path / "src1"
        d1.mkdir()
        d2 = tmp_path / "src2"
        d2.mkdir()
        for d in (d1, d2):
            Image.new("RGB", (32, 32)).save(d / "photo.png")

        batch, items = create_batch(root, [d1, d2])
        # Both should be imported — one renamed
        assert len(items) == 2
        names = {Path(it.relative_path).name for it in items}
        assert len(names) == 2  # distinct filenames

    def test_skips_non_image_files(self, tmp_path):
        d = tmp_path / "mixed"
        d.mkdir()
        Image.new("RGB", (32, 32)).save(d / "real.jpg")
        (d / "readme.txt").write_text("hello", encoding="utf-8")
        (d / "data.csv").write_text("a,b\n1,2", encoding="utf-8")

        root = tmp_path / "proj"
        root.mkdir()
        batch, items = create_batch(root, [d])
        assert len(items) == 1

    def test_progress_callback_called(self, tmp_path):
        src = _make_source_dir(tmp_path / "s", "img", 2)
        root = tmp_path / "p"
        root.mkdir()
        calls = []
        create_batch(root, [src], progress_cb=lambda i, t, n: calls.append((i, t)))
        # Should have been called for each image + final
        assert len(calls) >= 2


# ── commit_items ──────────────────────────────────────────────────────

class TestCommitItems:
    def test_moves_to_category_dir(self, tmp_path):
        src = _make_source_dir(tmp_path / "s", "img", 2)
        root = tmp_path / "proj"
        root.mkdir()

        batch, items = create_batch(root, [src])
        committed = commit_items(root, items, "defects")
        assert len(committed) == 2

        # Files moved from _inbox to defects/images/
        cat_imgs = list((root / "defects" / "images").iterdir())
        assert len(cat_imgs) == 2

        # Inbox batch dir should be empty (files moved out)
        inbox_imgs = list((inbox_path(root) / batch.batch_id / "images").iterdir())
        assert len(inbox_imgs) == 0

    def test_updates_item_metadata(self, tmp_path):
        src = _make_source_dir(tmp_path / "s", "x", 1)
        root = tmp_path / "p"
        root.mkdir()

        _, items = create_batch(root, [src])
        committed = commit_items(root, items, "scratches")
        assert committed[0].category_hint == "scratches"
        assert committed[0].status is WorkStatus.ANNOTATING
        assert "scratches/images/" in committed[0].relative_path

    def test_creates_labels_dir(self, tmp_path):
        src = _make_source_dir(tmp_path / "s", "z", 1)
        root = tmp_path / "p"
        root.mkdir()

        _, items = create_batch(root, [src])
        commit_items(root, items, "mycat")
        assert (root / "mycat" / "labels").is_dir()


# ── batch_status_counts ──────────────────────────────────────────────

class TestBatchStatusCounts:
    def test_counts_by_status(self):
        ws = WorkflowState(items=[
            WorkItem(item_id="1", relative_path="a.png",
                     batch_id="b1", status=WorkStatus.NEW),
            WorkItem(item_id="2", relative_path="b.png",
                     batch_id="b1", status=WorkStatus.NEW),
            WorkItem(item_id="3", relative_path="c.png",
                     batch_id="b1", status=WorkStatus.READY),
            WorkItem(item_id="4", relative_path="d.png",
                     batch_id="b2", status=WorkStatus.NEW),
        ])
        counts = batch_status_counts(ws, "b1")
        assert counts == {"new": 2, "ready": 1}

    def test_empty_for_unknown_batch(self):
        ws = WorkflowState()
        assert batch_status_counts(ws, "nonexistent") == {}


# ── all_batch_summaries ───────────────────────────────────────────────

class TestAllBatchSummaries:
    def test_returns_per_batch_info(self):
        ws = WorkflowState(
            batches=[
                IngestBatch(batch_id="b1", name="Batch A",
                            source_dirs=["/tmp/src"], item_count=3),
                IngestBatch(batch_id="b2", name="Batch B", item_count=1),
            ],
            items=[
                WorkItem(item_id="1", relative_path="_inbox/b1/images/a.png",
                         batch_id="b1", status=WorkStatus.NEW),
                WorkItem(item_id="2", relative_path="cat/images/b.png",
                         batch_id="b1", status=WorkStatus.READY),
                WorkItem(item_id="3", relative_path="_inbox/b1/images/c.png",
                         batch_id="b1", status=WorkStatus.NEW),
                WorkItem(item_id="4", relative_path="cat/images/d.png",
                         batch_id="b2", status=WorkStatus.ANNOTATING),
            ],
        )
        summaries = all_batch_summaries(ws)
        assert len(summaries) == 2

        s1 = summaries[0]
        assert s1["batch_id"] == "b1"
        assert s1["name"] == "Batch A"
        assert s1["status_counts"] == {"new": 2, "ready": 1}
        assert s1["inbox_count"] == 2  # two items still in _inbox

        s2 = summaries[1]
        assert s2["status_counts"] == {"annotating": 1}
        assert s2["inbox_count"] == 0


# ── End-to-end: create → commit → verify store ───────────────────────

class TestInboxEndToEnd:
    def test_full_pipeline(self, tmp_path):
        """create_batch → register in store → commit_items → verify."""
        from core import workflow_store

        root = tmp_path / "project"
        root.mkdir()
        src = _make_source_dir(tmp_path / "sources", "photo", 4)

        # Step 1: create batch (copies to _inbox)
        batch, items = create_batch(root, [src], name="Import #1")
        assert batch.item_count == 4

        # Step 2: register in workflow store
        state = workflow_store.add_batch(root, batch, items)
        assert len(state.batches) == 1
        assert len(state.items) == 4

        # Step 3: commit first 2 items to "category_a"
        to_commit = items[:2]
        committed = commit_items(root, to_commit, "category_a")
        assert len(committed) == 2
        workflow_store.save(root, state)

        # Step 4: verify post-commit state
        reloaded = workflow_store.load(root)
        # Items are mutated in place by commit_items, so relative_path changed
        committed_paths = {it.relative_path for it in committed}
        for it in reloaded.items:
            if it.item_id in {c.item_id for c in committed}:
                assert it.status is WorkStatus.ANNOTATING

        # Step 5: summaries reflect partial commit
        summaries = all_batch_summaries(state)
        s = summaries[0]
        # 2 items still in _inbox, 2 committed out
        assert s["inbox_count"] == 2
