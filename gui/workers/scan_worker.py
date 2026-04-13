"""Background dataset scan worker.

Three phases, all in worker thread:
  1. scan      — fast filesystem index
  2. annotate  — parse annotation files for counts
  3. analyze   — compute extended stats (per-class, imbalance, sizes)

Main thread receives a single (Dataset, ExtendedStats) result when done.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from core import index_cache
from core.dataset import count_annotations, scan_dataset
from core.models import Dataset
from core.stats import ExtendedStats, compute_extended_stats


class ScanResult:
    """Bundle returned by ScanWorker.finished_ok."""
    __slots__ = ("dataset", "ext_stats")

    def __init__(self, dataset: Dataset, ext_stats: ExtendedStats | None) -> None:
        self.dataset = dataset
        self.ext_stats = ext_stats


class ScanWorker(QThread):
    progress = pyqtSignal(int, int, str)   # done, total, current name
    phase = pyqtSignal(str)                # "scan" | "annotate" | "analyze"
    finished_ok = pyqtSignal(object)       # ScanResult
    failed = pyqtSignal(str)

    def __init__(self, root: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._root = root
        self.finished.connect(self.deleteLater)

    def run(self) -> None:
        # Phase 0: try cache
        try:
            cached = index_cache.load(self._root)
        except Exception:
            cached = None

        if cached is not None:
            # Still compute extended stats even for cached dataset
            self.phase.emit("analyze")
            try:
                ext = compute_extended_stats(
                    cached,
                    progress_cb=lambda d, t, c: self.progress.emit(d, t, c),
                )
            except Exception:
                ext = None
            self.finished_ok.emit(ScanResult(cached, ext))
            return

        # Phase 1: filesystem scan
        try:
            self.phase.emit("scan")
            dataset = scan_dataset(
                self._root,
                progress_cb=lambda d, t, c: self.progress.emit(d, t, c),
            )
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))
            return

        # Phase 2: parse annotation counts
        try:
            self.phase.emit("annotate")
            count_annotations(
                dataset,
                progress_cb=lambda d, t, c: self.progress.emit(d, t, c),
            )
        except Exception:
            pass

        try:
            index_cache.save(dataset)
        except Exception:
            pass

        # Phase 3: extended statistics
        ext = None
        try:
            self.phase.emit("analyze")
            ext = compute_extended_stats(
                dataset,
                progress_cb=lambda d, t, c: self.progress.emit(d, t, c),
            )
        except Exception:
            pass

        self.finished_ok.emit(ScanResult(dataset, ext))
