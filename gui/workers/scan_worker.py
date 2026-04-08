"""Background dataset scan worker."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from core import index_cache
from core.dataset import scan_dataset
from core.models import Dataset


class ScanWorker(QThread):
    progress = pyqtSignal(int, int, str)   # done, total, current category
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
            dataset = scan_dataset(
                self._root,
                progress_cb=lambda d, t, c: self.progress.emit(d, t, c),
            )
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))
            return
        try:
            index_cache.save(dataset)
        except Exception:
            pass
        self.finished_ok.emit(dataset)
