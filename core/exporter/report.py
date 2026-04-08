"""CSV / JSON report exporter for a Dataset."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from ..models import Dataset
from ..stats import compute_stats


def export_csv(dataset: Dataset, out_dir: Path) -> list[Path]:
    """Export 2 CSVs: category summary + per-image listing. Returns paths written."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    summary = out_dir / f"{dataset.name}_categories.csv"
    with summary.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["category", "image_count", "label_count", "unlabeled_count", "completion_pct"])
        for cat in sorted(dataset.categories, key=lambda c: c.image_count, reverse=True):
            unlabeled = cat.image_count - cat.label_count
            pct = (cat.label_count / cat.image_count * 100) if cat.image_count else 0.0
            w.writerow([cat.name, cat.image_count, cat.label_count, unlabeled, f"{pct:.1f}"])
    written.append(summary)

    listing = out_dir / f"{dataset.name}_images.csv"
    with listing.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["category", "filename", "path", "has_label", "label_path"])
        for cat in dataset.categories:
            for img in cat.images:
                w.writerow([
                    cat.name,
                    img.path.name,
                    str(img.path),
                    int(img.has_label),
                    str(img.label_path) if img.label_path else "",
                ])
    written.append(listing)
    return written


def export_json(dataset: Dataset, out_dir: Path) -> Path:
    """Export full dataset stats + listing as a single JSON."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stats = compute_stats(dataset)
    payload = {
        "name": dataset.name,
        "root_path": str(dataset.root_path),
        "summary": {
            "total_images": stats.total_images,
            "total_annotations": stats.total_annotations,
            "category_count": stats.category_count,
            "unlabeled_count": stats.unlabeled_count,
            "avg_annotations_per_image": stats.avg_annotations_per_image,
            "label_completion_rate": stats.label_completion_rate,
        },
        "categories": [
            {
                "name": c.name,
                "image_count": c.image_count,
                "label_count": c.label_count,
                "images": [
                    {
                        "filename": img.path.name,
                        "path": str(img.path),
                        "has_label": img.has_label,
                        "label_path": str(img.label_path) if img.label_path else None,
                    }
                    for img in c.images
                ],
            }
            for c in dataset.categories
        ],
    }
    out_path = out_dir / f"{dataset.name}_report.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path
