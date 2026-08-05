"""Resume markers: per dataset, by path, and never a lie."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from core import last_position as lp


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    """Never touch the real ~/.dataforge/last_position.json."""
    monkeypatch.setattr(lp, "POSITIONS_PATH", tmp_path / "last_position.json")


def _img(tmp_path: Path, name: str) -> Path:
    p = tmp_path / name
    p.write_bytes(b"x")
    return p


def test_nothing_recorded_yet(tmp_path):
    assert lp.recall(tmp_path) is None


def test_round_trip(tmp_path):
    img = _img(tmp_path, "a.png")
    lp.remember(tmp_path, img)
    got = lp.recall(tmp_path)
    assert got is not None
    assert got.image == img
    assert got.saved_at


def test_latest_write_wins(tmp_path):
    a, b = _img(tmp_path, "a.png"), _img(tmp_path, "b.png")
    lp.remember(tmp_path, a)
    lp.remember(tmp_path, b)
    assert lp.recall(tmp_path).image == b


def test_datasets_are_independent(tmp_path):
    d1, d2 = tmp_path / "one", tmp_path / "two"
    d1.mkdir(), d2.mkdir()
    a, b = _img(d1, "a.png"), _img(d2, "b.png")
    lp.remember(d1, a)
    lp.remember(d2, b)
    assert lp.recall(d1).image == a
    assert lp.recall(d2).image == b


def test_a_deleted_image_reports_no_position(tmp_path):
    """Better to resume nowhere than to resume somewhere wrong."""
    img = _img(tmp_path, "gone.png")
    lp.remember(tmp_path, img)
    img.unlink()
    assert lp.recall(tmp_path) is None


def test_the_same_root_spelled_differently_is_one_entry(tmp_path):
    """`D:\\data` and `D:/data/.` must not each hold half the history."""
    img_a, img_b = _img(tmp_path, "a.png"), _img(tmp_path, "b.png")
    lp.remember(tmp_path, img_a)
    lp.remember(Path(str(tmp_path) + "/."), img_b)
    raw = lp._load_raw()
    assert len(raw) == 1, f"root spelled two ways made {len(raw)} entries"
    assert lp.recall(tmp_path).image == img_b


def test_store_is_capped_and_evicts_oldest(tmp_path, monkeypatch):
    monkeypatch.setattr(lp, "MAX_ENTRIES", 3)
    img = _img(tmp_path, "a.png")
    for i in range(5):
        root = tmp_path / f"ds{i}"
        root.mkdir()
        lp.remember(root, img, now=datetime(2026, 1, 1 + i, 12, 0, 0))
    raw = lp._load_raw()
    assert len(raw) == 3
    # The three most recent survived; the first two were evicted.
    assert lp.recall(tmp_path / "ds0") is None
    assert lp.recall(tmp_path / "ds1") is None
    assert lp.recall(tmp_path / "ds4") is not None


def test_forget(tmp_path):
    img = _img(tmp_path, "a.png")
    lp.remember(tmp_path, img)
    lp.forget(tmp_path)
    assert lp.recall(tmp_path) is None
    lp.forget(tmp_path)  # idempotent


def test_corrupt_file_is_not_fatal(tmp_path):
    lp.POSITIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    lp.POSITIONS_PATH.write_text("{ not json", encoding="utf-8")
    assert lp.recall(tmp_path) is None
    img = _img(tmp_path, "a.png")
    lp.remember(tmp_path, img)          # recovers by overwriting
    assert lp.recall(tmp_path).image == img


def test_unwritable_store_does_not_raise(tmp_path, monkeypatch):
    """A full disk must not take the annotation session down."""
    monkeypatch.setattr(lp, "POSITIONS_PATH",
                        tmp_path / "no" / "such" / "dir" / "p.json")

    def _boom(*a, **k):
        raise OSError("read-only")

    monkeypatch.setattr(Path, "mkdir", _boom)
    lp.remember(tmp_path, _img(tmp_path, "a.png"))   # must not raise
