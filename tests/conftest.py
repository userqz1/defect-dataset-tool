"""Shared pytest fixtures.

``synthetic_dataset`` builds a real-on-disk 6-image / 2-category labeled
dataset and returns a ``Dataset`` pointing at it. Previously defined in
tests/test_exporters.py; moved here so all test files share one builder
instead of each rolling its own.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from core.models import Category, Dataset, ImageInfo


def _write_image(path: Path, color: tuple[int, int, int] = (200, 200, 100)) -> None:
    Image.new("RGB", (64, 64), color).save(path)


def _write_labelme(json_path: Path, image_path: Path, label: str) -> None:
    payload = {
        "version": "5.0.1",
        "shapes": [
            {
                "label": label,
                "points": [[8.0, 8.0], [40.0, 40.0]],
                "group_id": None,
                "shape_type": "rectangle",
                "flags": {},
            }
        ],
        "imagePath": image_path.name,
        "imageHeight": 64,
        "imageWidth": 64,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def synthetic_dataset(tmp_path: Path) -> Dataset:
    """Real-on-disk 6-image, 2-category, all-labeled dataset."""
    root = tmp_path / "raw"
    cats: list[Category] = []
    plan = [("cat", 4, (200, 100, 100)), ("dog", 2, (100, 200, 100))]
    for cls_name, n, color in plan:
        cat_dir = root / cls_name
        img_dir = cat_dir / "images"
        lbl_dir = cat_dir / "labels"
        img_dir.mkdir(parents=True)
        lbl_dir.mkdir(parents=True)

        images: list[ImageInfo] = []
        for i in range(n):
            ip = img_dir / f"{cls_name}_{i}.png"
            jp = lbl_dir / f"{cls_name}_{i}.json"
            _write_image(ip, color)
            _write_labelme(jp, ip, cls_name)
            images.append(ImageInfo(
                path=ip, category=cls_name,
                width=64, height=64,
                has_label=True, label_path=jp,
            ))
        cats.append(Category(
            name=cls_name, image_count=n, label_count=n, images=images,
        ))

    return Dataset(
        name="synthetic", root_path=root, categories=cats,
        total_images=6, total_annotations=6, layout="standard",
    )


@pytest.fixture
def empty_dataset(tmp_path: Path) -> Dataset:
    """Dataset with zero categories/images — for testing "not ready" branches."""
    return Dataset(
        name="empty", root_path=tmp_path / "empty",
        categories=[], total_images=0, total_annotations=0, layout="empty",
    )


@pytest.fixture
def unlabeled_dataset(tmp_path: Path) -> Dataset:
    """3 images, 2 categories, zero labels — tests the unlabeled path."""
    root = tmp_path / "raw_unlabeled"
    cats: list[Category] = []
    for cls_name, n, color in [("a", 2, (200, 100, 100)), ("b", 1, (100, 200, 100))]:
        img_dir = root / cls_name / "images"
        img_dir.mkdir(parents=True)
        images: list[ImageInfo] = []
        for i in range(n):
            ip = img_dir / f"{cls_name}_{i}.png"
            _write_image(ip, color)
            images.append(ImageInfo(path=ip, category=cls_name,
                                    width=64, height=64, has_label=False))
        cats.append(Category(name=cls_name, image_count=n, label_count=0, images=images))
    return Dataset(
        name="unlabeled", root_path=root, categories=cats,
        total_images=3, total_annotations=0, layout="standard",
    )
