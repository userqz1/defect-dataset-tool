"""Classification rules — pluggable strategies that assign categories to images.

Each rule is a frozen dataclass with a ``classify(paths)`` method. The method
returns a ``ClassificationResult`` per image: a suggested category + the rule
name that produced it.

v0.1 ships four built-in rules (DataForge-设计方案-v1.2 §6.3):

- **by_filename_prefix** — first token before ``_`` or ``-``
- **by_subdir** — immediate parent directory name
- **by_exif_date** — EXIF DateTimeOriginal → ``YYYY-MM``
- **manual** — everything → ``未分类`` (user reclassifies in UI)

Pure Python — no PyQt, no GUI imports.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ClassificationResult:
    """One image's classification outcome."""

    image_path: Path
    suggested_category: str
    rule_name: str = ""


# ---------- Protocol ----------

@runtime_checkable
class ClassificationRule(Protocol):
    """Strategy for assigning a category to each image."""

    name: str

    def classify(self, paths: list[Path]) -> list[ClassificationResult]: ...


# ---------- Concrete rules ----------

@dataclass(frozen=True)
class ByFilenamePrefixRule:
    """Category = first token before ``_`` or ``-`` in the filename.

    Example: ``crack_001.jpg`` → ``crack``, ``good-0042.png`` → ``good``.
    Falls back to ``未分类`` if no separator found.
    """

    name: str = "by_filename_prefix"
    separators: str = "_-"

    def classify(self, paths: list[Path]) -> list[ClassificationResult]:
        pat = re.compile(f"[{re.escape(self.separators)}]")
        out: list[ClassificationResult] = []
        for p in paths:
            stem = p.stem
            m = pat.search(stem)
            cat = stem[:m.start()] if m and m.start() > 0 else "未分类"
            out.append(ClassificationResult(p, cat, self.name))
        return out


@dataclass(frozen=True)
class BySubdirRule:
    """Category = immediate parent directory name.

    Example: ``data/scratch/001.jpg`` → ``scratch``.
    Falls back to ``未分类`` if the parent is the source root (no subdir).
    """

    name: str = "by_subdir"
    source_root: Path | None = None  # set to disambiguate root-level images

    def classify(self, paths: list[Path]) -> list[ClassificationResult]:
        out: list[ClassificationResult] = []
        for p in paths:
            parent = p.parent.name
            if self.source_root and p.parent.resolve() == self.source_root.resolve():
                parent = "未分类"
            out.append(ClassificationResult(p, parent or "未分类", self.name))
        return out


@dataclass(frozen=True)
class ByExifDateRule:
    """Category = EXIF DateTimeOriginal formatted as ``YYYY-MM``.

    Falls back to ``未分类`` if EXIF is missing or unreadable (common for
    industrial/synthetic images).

    Uses Pillow's ``Image.getexif()`` + IFD tag 36867 (DateTimeOriginal) or
    306 (DateTime). Tolerates malformed dates gracefully.
    """

    name: str = "by_exif_date"
    date_format: str = "%Y-%m"

    def classify(self, paths: list[Path]) -> list[ClassificationResult]:
        out: list[ClassificationResult] = []
        for p in paths:
            cat = self._extract_date(p) or "未分类"
            out.append(ClassificationResult(p, cat, self.name))
        return out

    def _extract_date(self, path: Path) -> str:
        try:
            from PIL import Image
            with Image.open(path) as im:
                exif = im.getexif()
                # 36867 = DateTimeOriginal, 306 = DateTime (fallback)
                raw = exif.get(36867) or exif.get(306) or ""
                if not raw:
                    return ""
                # "2023:08:15 14:30:00" → datetime
                from datetime import datetime
                dt = datetime.strptime(raw.strip()[:19], "%Y:%m:%d %H:%M:%S")
                return dt.strftime(self.date_format)
        except Exception:
            return ""


@dataclass(frozen=True)
class ManualRule:
    """Everything goes to a single bucket — user reclassifies in UI later."""

    name: str = "manual"
    default_category: str = "未分类"

    def classify(self, paths: list[Path]) -> list[ClassificationResult]:
        return [ClassificationResult(p, self.default_category, self.name) for p in paths]


# ---------- Registry ----------

RULES: dict[str, ClassificationRule] = {
    "by_filename_prefix": ByFilenamePrefixRule(),
    "by_subdir": BySubdirRule(),
    "by_exif_date": ByExifDateRule(),
    "manual": ManualRule(),
}
"""All built-in rules, keyed by machine name."""
