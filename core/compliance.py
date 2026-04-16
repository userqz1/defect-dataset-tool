"""Dataset compliance checker — auto-checks if a dataset is training-ready.

Given a Dataset + TaskType, produces a structured ComplianceReport
with pass/fail status per check item. Each failed item suggests
which tool can fix it.

Pure Python — no PyQt imports.

Usage::

    from core.compliance import check_compliance
    report = check_compliance(dataset, task_type)
    for c in report.checks:
        print(c.icon, c.item, c.current, "→", c.action if not c.passed else "OK")
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .models import Dataset
from .task_types import TaskType, TASK_REGISTRY


@dataclass
class ComplianceCheck:
    """One item in the compliance report."""
    category: str      # "structure" / "quality" / "annotation" / "quantity" / "split"
    item: str          # human-readable check name
    passed: bool
    current: str       # what the dataset has now
    required: str      # what the standard requires (empty if informational)
    action: str        # suggested tool/action (empty if passed)

    @property
    def icon(self) -> str:
        return "✓" if self.passed else "✗"


@dataclass
class ComplianceReport:
    """Full compliance report for a dataset."""
    task_type: TaskType
    checks: list[ComplianceCheck] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def pass_count(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    @property
    def fail_count(self) -> int:
        return sum(1 for c in self.checks if not c.passed)


def check_compliance(dataset: Dataset, task_type: TaskType) -> ComplianceReport:
    """Run all compliance checks for a dataset against its task type requirements."""
    info = TASK_REGISTRY.get(task_type)
    checks: list[ComplianceCheck] = []

    n_images = sum(c.image_count for c in dataset.categories)
    n_labels = sum(c.label_count for c in dataset.categories)
    n_cats = len(dataset.categories)
    n_unlabeled = n_images - n_labels

    # 1. Has images?
    checks.append(ComplianceCheck(
        category="structure",
        item="图片数量",
        passed=n_images > 0,
        current=f"{n_images:,} 张",
        required="≥ 1",
        action="" if n_images > 0 else "导入图片",
    ))

    # 2. Has categories?
    checks.append(ComplianceCheck(
        category="structure",
        item="分类数",
        passed=n_cats > 0,
        current=f"{n_cats} 个",
        required="≥ 1",
        action="",
    ))

    # 3. Annotation coverage (for tasks that need shapes)
    if info and info.needs_shapes:
        coverage = n_labels / n_images if n_images else 0
        checks.append(ComplianceCheck(
            category="annotation",
            item="标注覆盖",
            passed=n_unlabeled == 0,
            current=f"{n_labels:,}/{n_images:,} ({coverage:.0%})",
            required="100%",
            action=f"{n_unlabeled} 张未标注" if n_unlabeled else "",
        ))

    # 4. Class balance
    if n_cats >= 2:
        counts = [c.image_count for c in dataset.categories if c.image_count > 0]
        if counts:
            ratio = max(counts) / min(counts) if min(counts) > 0 else float("inf")
            balanced = ratio <= 10
            checks.append(ComplianceCheck(
                category="quantity",
                item="类别平衡",
                passed=balanced,
                current=f"{ratio:.1f}:1",
                required="≤ 10:1",
                action=f"最大类/最小类 = {ratio:.0f}:1" if not balanced else "",
            ))

    # 5. Min per class
    if n_cats > 0:
        min_count = min(c.image_count for c in dataset.categories)
        min_cat = next(c.name for c in dataset.categories if c.image_count == min_count)
        enough = min_count >= 10
        checks.append(ComplianceCheck(
            category="quantity",
            item="每类最少张数",
            passed=enough,
            current=f"最少: {min_cat} ({min_count}张)",
            required="≥ 10",
            action=f"「{min_cat}」仅 {min_count} 张" if not enough else "",
        ))

    # Note: 可用导出格式 not included — it's static task metadata,
    # shown in the export dialog itself, not a dataset gate.

    return ComplianceReport(task_type=task_type, checks=checks)
