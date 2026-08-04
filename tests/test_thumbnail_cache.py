"""Tests for the on-disk thumbnail cache.

The interesting behaviour is the ``draft()`` fast path added for speed:
it must not change the contract (output still fits the requested box,
still decodable JPEG) and must stay a no-op for formats that do not
support DCT scaling.
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from core.thumbnail_cache import ThumbnailCache

SIZE = 64


@pytest.fixture
def cache(tmp_path: Path) -> ThumbnailCache:
    c = ThumbnailCache(cache_dir=tmp_path / "thumbs")
    yield c
    c.close()


def _make(path: Path, size: tuple[int, int], fmt: str) -> Path:
    Image.new("RGB", size, (180, 90, 40)).save(path, format=fmt)
    return path


@pytest.mark.parametrize(
    ("name", "fmt"),
    [("big.jpg", "JPEG"), ("big.png", "PNG"), ("big.bmp", "BMP")],
)
def test_thumbnail_fits_requested_box(cache, tmp_path, name, fmt):
    """draft() is JPEG-only; PNG/BMP must still come out correct."""
    src = _make(tmp_path / name, (1024, 768), fmt)
    data = cache.get_or_generate(src, SIZE)
    assert data is not None
    with Image.open(io.BytesIO(data)) as im:
        assert im.format == "JPEG"
        assert max(im.size) <= SIZE
        # aspect ratio preserved (4:3 source)
        assert im.size[0] > im.size[1]


def test_non_square_aspect_is_preserved(cache, tmp_path):
    src = _make(tmp_path / "tall.jpg", (400, 1200), "JPEG")
    data = cache.get_or_generate(src, SIZE)
    with Image.open(io.BytesIO(data)) as im:
        assert im.size[1] <= SIZE
        assert im.size[1] > im.size[0]


def test_second_call_is_a_cache_hit(cache, tmp_path):
    src = _make(tmp_path / "a.jpg", (800, 800), "JPEG")
    first = cache.get_or_generate(src, SIZE)
    second = cache.get_or_generate(src, SIZE)
    assert first == second


def test_touching_the_file_invalidates_the_entry(cache, tmp_path):
    """The cache key embeds mtime, so an edited image re-renders."""
    src = _make(tmp_path / "b.jpg", (800, 800), "JPEG")
    first = cache.get_or_generate(src, SIZE)
    Image.new("RGB", (800, 800), (10, 200, 10)).save(src, format="JPEG")
    second = cache.get_or_generate(src, SIZE)
    assert first != second


def test_dimensions_report_the_source_size(cache, tmp_path):
    src = _make(tmp_path / "c.jpg", (640, 480), "JPEG")
    assert cache.get_dimensions(src) == (640, 480)


def test_unreadable_file_returns_none_and_does_not_raise(cache, tmp_path):
    bad = tmp_path / "not_an_image.jpg"
    bad.write_bytes(b"definitely not a JPEG")
    assert cache.get_or_generate(bad, SIZE) is None
    assert cache.get_dimensions(bad) is None
