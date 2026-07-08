"""Regression tests for dirty class labels from third-party annotation tools."""
from __future__ import annotations

from pathlib import Path

from core.format_out import ExportOptions, export_samples
from core.unified import BBox, Region, Sample, SampleSet


def test_yolo_export_normalizes_region_label_for_class_lookup(tmp_path):
    ss = SampleSet(samples=[
        Sample(
            image_path=Path("Loose_0202.jpg"),
            image_width=100,
            image_height=100,
            regions=[
                Region(
                    label="fastener_core\n",
                    bbox=BBox(10, 20, 60, 80),
                    shape_type="rectangle",
                )
            ],
        )
    ])

    out = tmp_path / "out"
    result = export_samples(
        ss,
        "YOLO",
        ExportOptions(out_dir=out, copy_images=False),
    )

    assert not result.skipped
    assert (out / "classes.txt").read_text(encoding="utf-8").strip() == "fastener_core"
    label_text = (out / "labels" / "train" / "Loose_0202.txt").read_text(encoding="utf-8")
    assert label_text.startswith("0 ")
