"""DetailView records where the user left off; BrowserView offers it back.

The core store is covered in test_last_position.py. This is about the
wiring: that a marker is written for the image actually on screen, that
it is scoped to the right dataset, and that the 继续上次 entry only
appears when it leads somewhere.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6", reason="GUI test")

from PyQt6.QtGui import QImage, QPixmap  # noqa: E402

from core import last_position as lp  # noqa: E402
from core.models import Annotation, ImageInfo  # noqa: E402
from gui.views.detail_view import DetailView  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(lp, "POSITIONS_PATH", tmp_path / "pos.json")


def _images(tmp_path: Path, n: int = 5) -> list[ImageInfo]:
    out = []
    for i in range(n):
        p = tmp_path / f"img{i}.png"
        p.write_bytes(b"x")
        out.append(ImageInfo(path=p, category="cat"))
    return out


def _detail(tmp_path: Path, imgs: list[ImageInfo], index: int) -> DetailView:
    v = DetailView()
    img = QImage(60, 60, QImage.Format.Format_RGB32)
    img.fill(0x202020)
    v.viewer.load_pixmap(QPixmap.fromImage(img))
    v._images = imgs
    v._index = index
    v._annotation = Annotation(image_path=imgs[index].path, shapes=[])
    return v


def test_position_is_recorded_for_the_visible_image(qapp, tmp_path):
    imgs = _images(tmp_path)
    v = _detail(tmp_path, imgs, 2)
    v.set_dataset_root(tmp_path)
    v._persist_position()
    got = lp.recall(tmp_path)
    assert got is not None and got.image == imgs[2].path


def test_nothing_is_recorded_without_a_dataset_root(qapp, tmp_path):
    """Better no marker than every dataset filed under one key."""
    v = _detail(tmp_path, _images(tmp_path), 1)
    v._persist_position()
    assert lp.recall(tmp_path) is None


def test_writes_are_debounced_not_per_image(qapp, tmp_path):
    """Holding A/D walks images faster than the store should be rewritten."""
    imgs = _images(tmp_path)
    v = _detail(tmp_path, imgs, 0)
    v.set_dataset_root(tmp_path)
    assert v._position_timer.isSingleShot()
    assert v._position_timer.interval() >= 500
    v._position_timer.start()
    assert v._position_timer.isActive()
    # Nothing on disk yet — the timer has not fired.
    assert lp.recall(tmp_path) is None


def test_hiding_flushes_the_pending_marker(qapp, tmp_path):
    """Leaving the workbench is exactly when 'where was I' matters."""
    imgs = _images(tmp_path)
    v = _detail(tmp_path, imgs, 3)
    v.set_dataset_root(tmp_path)
    v._position_timer.start()          # pending, not yet written
    v.show()
    v.hide()
    got = lp.recall(tmp_path)
    assert got is not None and got.image == imgs[3].path
    assert not v._position_timer.isActive()


def test_marker_survives_images_being_deleted_around_it(qapp, tmp_path):
    """Stored by path, so an index shift cannot silently retarget it."""
    imgs = _images(tmp_path)
    v = _detail(tmp_path, imgs, 4)
    v.set_dataset_root(tmp_path)
    v._persist_position()
    imgs[0].path.unlink()
    imgs[1].path.unlink()
    assert lp.recall(tmp_path).image == imgs[4].path
