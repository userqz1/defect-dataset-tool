"""Train/val/test split. Pure Python — no PyQt.

Three modes:
    - ratio:  按比例切分 (train/val/test = 0~1)
    - count:  按具体数量切分 (train_n/val_n/test_n)
    - manual: 调用方提供三段 ImageInfo 列表，本模块只做容器+落盘

ratio / count 都支持 stratified（按类别均衡）。
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Literal

from .models import Dataset, ImageInfo


class SplitMode(str, Enum):
    """How split_dataset decides where each image goes."""
    RATIO = "ratio"     # train/val/test are fractions 0..1
    COUNT = "count"     # explicit per-split counts
    MANUAL = "manual"   # caller assembles train/val/test themselves

# Retained for BrowseState / project.json serialization: Literal here lets
# static type checkers accept raw strings round-tripped from disk.
SplitModeStr = Literal["ratio", "count", "manual"]


@dataclass
class SplitOptions:
    mode: SplitMode | SplitModeStr = SplitMode.RATIO
    # ratio 模式
    train: float = 0.8
    val: float = 0.1
    test: float = 0.1
    # count 模式（每个 split 的具体张数；剩余落入 train）
    train_n: int = 0
    val_n: int = 0
    test_n: int = 0
    # 通用
    seed: int = 42
    stratified: bool = True

    def normalized_ratio(self) -> tuple[float, float, float]:
        s = self.train + self.val + self.test
        if s <= 0:
            return 0.8, 0.1, 0.1
        return self.train / s, self.val / s, self.test / s


@dataclass
class SplitResult:
    train: list[ImageInfo] = field(default_factory=list)
    val: list[ImageInfo] = field(default_factory=list)
    test: list[ImageInfo] = field(default_factory=list)

    @property
    def counts(self) -> tuple[int, int, int]:
        return len(self.train), len(self.val), len(self.test)


def _slice_ratio(items: list[ImageInfo], opts: SplitOptions):
    tr, va, te = opts.normalized_ratio()
    n = len(items)
    n_tr = int(round(n * tr))
    n_va = int(round(n * va))
    n_te = n - n_tr - n_va
    if n_te < 0:
        n_va += n_te
        n_te = 0
    return items[:n_tr], items[n_tr:n_tr + n_va], items[n_tr + n_va:n_tr + n_va + n_te]


def _slice_count(items: list[ImageInfo], opts: SplitOptions, scale: float = 1.0):
    """按数量切。scale 用于 stratified 时按类别比例缩放配额。"""
    n = len(items)
    n_va = min(int(round(opts.val_n * scale)), n)
    n_te = min(int(round(opts.test_n * scale)), n - n_va)
    if opts.train_n > 0:
        n_tr = min(int(round(opts.train_n * scale)), n - n_va - n_te)
    else:
        n_tr = n - n_va - n_te  # 剩余全给 train
    return (
        items[:n_tr],
        items[n_tr:n_tr + n_va],
        items[n_tr + n_va:n_tr + n_va + n_te],
    )


def split_dataset(dataset: Dataset, opts: SplitOptions | None = None) -> SplitResult:
    opts = opts or SplitOptions()
    # Accept both SplitMode enum and legacy plain-string for backward compat
    mode = opts.mode.value if isinstance(opts.mode, SplitMode) else opts.mode
    if mode == SplitMode.MANUAL.value:
        # manual 由调用方组装；这里返回空
        return SplitResult()

    rng = random.Random(opts.seed)
    result = SplitResult()
    slicer = _slice_ratio if mode == SplitMode.RATIO.value else _slice_count

    if opts.stratified:
        total = sum(c.image_count for c in dataset.categories) or 1
        for cat in dataset.categories:
            imgs = list(cat.images)
            rng.shuffle(imgs)
            scale = len(imgs) / total
            tr, va, te = slicer(imgs, opts, scale) if slicer is _slice_count else slicer(imgs, opts)
            result.train.extend(tr)
            result.val.extend(va)
            result.test.extend(te)
    else:
        all_imgs = [img for c in dataset.categories for img in c.images]
        rng.shuffle(all_imgs)
        tr, va, te = slicer(all_imgs, opts, 1.0) if slicer is _slice_count else slicer(all_imgs, opts)
        result.train, result.val, result.test = tr, va, te
    return result


def manual_split(
    train: list[ImageInfo],
    val: list[ImageInfo],
    test: list[ImageInfo],
) -> SplitResult:
    return SplitResult(train=list(train), val=list(val), test=list(test))


def write_split_lists(result: SplitResult, out_dir: Path) -> dict[str, Path]:
    """Write train.txt / val.txt / test.txt with absolute image paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for name, imgs in (("train", result.train), ("val", result.val), ("test", result.test)):
        if not imgs:
            continue
        p = out_dir / f"{name}.txt"
        p.write_text(
            "\n".join(str(img.path) for img in imgs) + "\n", encoding="utf-8"
        )
        written[name] = p
    return written
