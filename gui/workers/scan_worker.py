"""Background dataset scan worker (two-phase: fast index → annotation count)."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from core import index_cache
from core.dataset import count_annotations, scan_dataset
from core.models import Dataset


class ScanWorker(QThread):
    # done, total, current name. total<=0 表示未知（前端按 indeterminate 处理）
    progress = pyqtSignal(int, int, str)
    phase = pyqtSignal(str)                 # "scan" | "annotate"
    finished_ok = pyqtSignal(object)        # Dataset
    failed = pyqtSignal(str)

    def __init__(self, root: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._root = root

    def run(self) -> None:
        # 优先尝试缓存
        try:
            cached = index_cache.load(self._root)
        except Exception:
            cached = None
        if cached is not None:
            self.finished_ok.emit(cached)
            return

        try:
            self.phase.emit("scan")
            dataset = scan_dataset(
                self._root,
                progress_cb=lambda d, t, c: self.progress.emit(d, t, c),
            )
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))
            return

        # Phase 2: 解析标注
        try:
            self.phase.emit("annotate")
            count_annotations(
                dataset,
                progress_cb=lambda d, t, c: self.progress.emit(d, t, c),
            )
        except Exception:
            pass  # 标注解析失败不影响主流程

        try:
            index_cache.save(dataset)
        except Exception:
            pass
        self.finished_ok.emit(dataset)
