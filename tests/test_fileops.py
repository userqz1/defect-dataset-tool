"""Tests for destructive image/label file operations."""
from __future__ import annotations

from pathlib import Path

from core.fileops import delete_pairs
from core.models import ImageInfo


def test_delete_pairs_permanently_removes_image_and_label(tmp_path: Path) -> None:
    image_dir = tmp_path / "part" / "images"
    label_dir = tmp_path / "part" / "labels"
    image_dir.mkdir(parents=True)
    label_dir.mkdir(parents=True)
    image_path = image_dir / "sample.jpg"
    label_path = label_dir / "sample.json"
    image_path.write_bytes(b"image")
    label_path.write_text("{}", encoding="utf-8")
    image = ImageInfo(
        path=image_path,
        category="part",
        has_label=True,
        label_path=label_path,
    )

    result = delete_pairs([image])

    assert result.succeeded == [image_path]
    assert result.failed == []
    assert not image_path.exists()
    assert not label_path.exists()


def test_delete_pairs_finds_standard_layout_label(tmp_path: Path) -> None:
    image_dir = tmp_path / "part" / "images"
    label_dir = tmp_path / "part" / "labels"
    image_dir.mkdir(parents=True)
    label_dir.mkdir(parents=True)
    image_path = image_dir / "sample.png"
    label_path = label_dir / "sample.json"
    image_path.write_bytes(b"image")
    label_path.write_text("{}", encoding="utf-8")
    image = ImageInfo(path=image_path, category="part", has_label=True)

    result = delete_pairs([image])

    assert result.ok_count == 1
    assert not image_path.exists()
    assert not label_path.exists()
