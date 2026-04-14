"""Cleaning nodes — QualityCheck, Dedup."""
from __future__ import annotations

from .base import ParamDef, PortDef, StepResult


class QualityCheckNode:
    name = "quality_check"
    display_name = "质量检查"
    step_type = "clean"
    description = "检测模糊/空白/过曝/欠曝/损坏图像"
    ports = (
        PortDef("input", "输入", "input", "dataset"),
        PortDef("passed", "合格", "output", "dataset"),
        PortDef("rejected", "不合格", "output", "dataset"),
    )
    parameters = (
        ParamDef("blur_threshold", "模糊阈值", "int", 100, min_val=10, max_val=500),
    )

    def execute(self, images, options, progress_cb=None):
        if not images:
            raise ValueError("质量检查节点没有收到图片，请检查上游连接")
        from ..quality import QualityOptions, check_images
        threshold = options.get("blur_threshold", 100)
        if not (10 <= threshold <= 5000):
            raise ValueError(f"模糊阈值 {threshold} 超出范围 (10-5000)")
        opts = QualityOptions(blur_threshold=threshold)
        issues = check_images(images, opts=opts, progress_cb=progress_cb)
        return StepResult(
            ok_count=len(images) - len(issues),
            fail_count=len(issues),
            details=issues,
        )

    def route(self, input_data, result):
        bad_paths = set()
        if result.details:
            for issue in result.details:
                bad_paths.add(str(getattr(issue, "path", "")))
        passed = [img for img in input_data if str(getattr(img, "path", img)) not in bad_paths]
        rejected = [img for img in input_data if str(getattr(img, "path", img)) in bad_paths]
        return {"passed": passed, "rejected": rejected}


class DedupNode:
    name = "dedup"
    display_name = "重复检测"
    step_type = "clean"
    description = "基于感知哈希发现重复或近似图片"
    ports = (
        PortDef("input", "输入", "input", "dataset"),
        PortDef("unique", "唯一", "output", "dataset"),
        PortDef("duplicates", "重复", "output", "dataset"),
    )
    parameters = (
        ParamDef("threshold", "相似阈值", "int", 5, min_val=0, max_val=20),
    )

    def execute(self, images, options, progress_cb=None):
        if not images:
            raise ValueError("重复检测节点没有收到图片，请检查上游连接")
        from ..dedup import find_duplicates
        threshold = options.get("threshold", 5)
        if not (0 <= threshold <= 64):
            raise ValueError(f"相似阈值 {threshold} 超出范围 (0-64)")
        groups = find_duplicates(images, threshold=threshold, progress_cb=progress_cb)
        dup_count = sum(len(g.images) - 1 for g in groups if len(g.images) > 1)
        return StepResult(
            ok_count=len(images) - dup_count,
            fail_count=dup_count,
            details=groups,
        )

    def route(self, input_data, result):
        dup_paths = set()
        if result.details:
            for group in result.details:
                for img in group.images[1:]:
                    dup_paths.add(str(getattr(img, "path", img)))
        unique = [img for img in input_data if str(getattr(img, "path", img)) not in dup_paths]
        dups = [img for img in input_data if str(getattr(img, "path", img)) in dup_paths]
        return {"unique": unique, "duplicates": dups}
