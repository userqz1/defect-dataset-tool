"""Data collection standards — generate specs for clients, validate incoming data.

Pure Python — no PyQt imports.

Workflow:
  1. User configures a DataStandard (categories, image reqs, naming rules)
  2. generate_standard_doc() → Markdown file that client follows for data collection
  3. generate_empty_structure() → empty folder skeleton matching the standard
  4. validate_against_standard() → check if a scanned Dataset meets the standard
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from .models import Dataset


@dataclass
class CategorySpec:
    name: str
    description: str = ""           # 该类别的定义说明（给甲方看）
    example_image: str = ""         # 示例图路径


@dataclass
class DataStandard:
    """A complete data collection specification."""
    categories: list[CategorySpec] = field(default_factory=list)
    image_formats: list[str] = field(default_factory=lambda: [".jpg", ".png"])
    min_resolution: tuple[int, int] = (640, 480)
    max_file_size_mb: float = 10.0
    naming_pattern: str = r"[a-zA-Z0-9_\-]+"
    naming_example: str = "crack_001.jpg"
    min_images_per_category: int = 50
    require_labels: bool = False     # 甲方是否需要提供标注
    notes: str = ""                  # 额外说明

    def to_dict(self) -> dict:
        d = asdict(self)
        d["min_resolution"] = list(self.min_resolution)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> DataStandard:
        cats = [CategorySpec(**c) for c in d.get("categories", [])]
        res = d.get("min_resolution", [640, 480])
        return cls(
            categories=cats,
            image_formats=d.get("image_formats", [".jpg", ".png"]),
            min_resolution=tuple(res) if isinstance(res, (list, tuple)) else (640, 480),
            max_file_size_mb=d.get("max_file_size_mb", 10.0),
            naming_pattern=d.get("naming_pattern", r"[a-zA-Z0-9_\-]+"),
            naming_example=d.get("naming_example", "crack_001.jpg"),
            min_images_per_category=d.get("min_images_per_category", 50),
            require_labels=d.get("require_labels", False),
            notes=d.get("notes", ""),
        )


# ---------- 生成采集规范文档 ----------

def generate_standard_doc(
    standard: DataStandard,
    project_name: str,
    output_path: Path,
) -> Path:
    """Generate a Markdown data collection guide for the client."""
    lines: list[str] = []
    lines.append(f"# {project_name} — 数据采集规范\n")
    lines.append(f"生成日期：{datetime.now().strftime('%Y-%m-%d')}\n")

    # 1. 目录结构
    lines.append("## 一、目录结构\n")
    lines.append("请按以下结构组织数据：\n")
    lines.append("```")
    lines.append(f"{project_name}/")
    for cat in standard.categories:
        lines.append(f"  ├── {cat.name}/")
        lines.append(f"  │   ├── images/    ← 放原始图片")
        if standard.require_labels:
            lines.append(f"  │   └── labels/    ← 放标注文件")
    lines.append("```\n")

    # 2. 图片要求
    lines.append("## 二、图片要求\n")
    fmts = "、".join(f.upper().lstrip(".") for f in standard.image_formats)
    lines.append(f"| 项目 | 要求 |")
    lines.append(f"|------|------|")
    lines.append(f"| 格式 | {fmts}（推荐 JPG） |")
    lines.append(f"| 最小分辨率 | {standard.min_resolution[0]} × {standard.min_resolution[1]} 像素 |")
    lines.append(f"| 单张大小 | ≤ {standard.max_file_size_mb} MB |")
    lines.append(f"| 命名规则 | 英文/数字/下划线，示例：`{standard.naming_example}` |")
    lines.append(f"| 每类最少 | {standard.min_images_per_category} 张 |")
    lines.append("")

    # 3. 分类说明
    lines.append("## 三、分类说明\n")
    lines.append("| 类别名称 | 说明 |")
    lines.append("|----------|------|")
    for cat in standard.categories:
        desc = cat.description or "（待补充）"
        lines.append(f"| {cat.name} | {desc} |")
    lines.append("")

    # 4. 标注规则（如果需要）
    if standard.require_labels:
        lines.append("## 四、标注规则\n")
        lines.append("- 使用 [LabelMe](https://github.com/wkentaro/labelme) 工具标注")
        lines.append("- 标注框应紧贴目标边缘，不要留过大空白")
        lines.append("- 类别名称必须与上方表格一致（区分大小写）")
        lines.append("- 每张图片标注完成后保存为同名 `.json` 文件")
        lines.append("")

    # 5. 交付检查清单
    lines.append("## " + ("五" if standard.require_labels else "四") + "、交付检查清单\n")
    lines.append(f"- [ ] 每个类别至少 {standard.min_images_per_category} 张图片")
    lines.append(f"- [ ] 图片格式为 {fmts}")
    lines.append(f"- [ ] 分辨率不低于 {standard.min_resolution[0]}×{standard.min_resolution[1]}")
    lines.append(f"- [ ] 文件名符合规则：`{standard.naming_pattern}`")
    lines.append(f"- [ ] 目录结构符合上方模板")
    if standard.require_labels:
        lines.append("- [ ] 每张图片都有对应的标注文件")
    lines.append("")

    # 6. 额外说明
    if standard.notes:
        lines.append("## 备注\n")
        lines.append(standard.notes)
        lines.append("")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = output_path / f"{project_name}_数据采集规范.md"
    doc.write_text("\n".join(lines), encoding="utf-8")
    return doc


# ---------- 生成空目录结构 ----------

def generate_empty_structure(
    standard: DataStandard,
    root: Path,
) -> None:
    """Create empty folder skeleton for data collection."""
    for cat in standard.categories:
        (root / cat.name / "images").mkdir(parents=True, exist_ok=True)
        if standard.require_labels:
            (root / cat.name / "labels").mkdir(parents=True, exist_ok=True)


# ---------- 校验 ----------

@dataclass
class ValidationIssue:
    severity: str   # "error" | "warning"
    message: str


def validate_against_standard(
    dataset: Dataset,
    standard: DataStandard,
    progress_cb=None,
) -> list[ValidationIssue]:
    """Validate a scanned dataset against a data standard. Returns list of issues."""
    issues: list[ValidationIssue] = []
    expected_cats = {c.name for c in standard.categories}
    actual_cats = {c.name for c in dataset.categories}

    # Category checks
    missing = expected_cats - actual_cats
    extra = actual_cats - expected_cats
    for name in sorted(missing):
        issues.append(ValidationIssue("error", f"缺少类别：{name}"))
    for name in sorted(extra):
        issues.append(ValidationIssue("warning", f"多出未定义的类别：{name}"))

    # Per-category checks
    name_re = re.compile(f"^{standard.naming_pattern}$") if standard.naming_pattern else None
    all_images = [img for cat in dataset.categories for img in cat.images]
    total = len(all_images)

    for i, img in enumerate(all_images):
        if progress_cb and i % 100 == 0:
            progress_cb(i + 1, total, img.path.name)

        # Format check
        ext = img.path.suffix.lower()
        if ext not in standard.image_formats:
            issues.append(ValidationIssue(
                "error", f"格式不合规：{img.path.name}（{ext}，要求 {standard.image_formats}）"
            ))

        # Naming check
        if name_re and not name_re.match(img.path.stem):
            issues.append(ValidationIssue(
                "warning", f"命名不规范：{img.path.name}（要求匹配 {standard.naming_pattern}）"
            ))

        # File size check
        try:
            size_mb = img.path.stat().st_size / (1024 * 1024)
            if size_mb > standard.max_file_size_mb:
                issues.append(ValidationIssue(
                    "warning", f"文件过大：{img.path.name}（{size_mb:.1f}MB，上限 {standard.max_file_size_mb}MB）"
                ))
        except OSError:
            pass

        # Label check
        if standard.require_labels and not img.has_label:
            issues.append(ValidationIssue(
                "error", f"缺少标注：{img.path.name}"
            ))

    # Min count per category
    for cat in dataset.categories:
        if cat.name in expected_cats and cat.image_count < standard.min_images_per_category:
            issues.append(ValidationIssue(
                "warning",
                f"类别 {cat.name} 图片不足：{cat.image_count} 张"
                f"（要求 ≥{standard.min_images_per_category}）"
            ))

    return issues
