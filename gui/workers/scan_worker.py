"""Background dataset scan worker.

Three phases, all in worker thread:
  1. scan      — fast filesystem index
  2. annotate  — parse annotation files for counts
  3. analyze   — compute extended stats (per-class, imbalance, sizes)

Main thread receives a single (Dataset, ExtendedStats) result when done.
"""
from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from core import index_cache
from core.dataset import count_annotations, scan_dataset
from core.models import Dataset
from core.stats import ExtendedStats, compute_extended_stats

logger = logging.getLogger(__name__)


class ScanResult:
    """Bundle returned by ScanWorker.finished_ok."""
    __slots__ = ("dataset", "ext_stats")

    def __init__(self, dataset: Dataset, ext_stats: ExtendedStats | None) -> None:
        self.dataset = dataset
        self.ext_stats = ext_stats


class _ScanCancelled(Exception):
    """Raised inside progress_cb to unwind scan_dataset on user cancel."""


class ScanWorker(QThread):
    progress = pyqtSignal(int, int, str)   # done, total, current name
    phase = pyqtSignal(str)                # "scan" | "annotate" | "analyze"
    finished_ok = pyqtSignal(object)       # ScanResult
    failed = pyqtSignal(str)
    canceled = pyqtSignal()                # user canceled mid-scan

    def __init__(self, root: Path, parent: QObject | None = None,
                 force_rescan: bool = False) -> None:
        """
        Args:
            root: dataset root directory.
            parent: Qt parent.
            force_rescan: If True, skip the index cache and re-walk the
                filesystem. Used by the manual "刷新" button — users hit it
                because they know something changed that mtime-fingerprint
                might miss (e.g. annotation file edits in-place).
        """
        super().__init__(parent)
        self._root = root
        self._force_rescan = force_rescan
        self._cancel_requested = False
        self.finished.connect(self.deleteLater)

    def cancel(self) -> None:
        """Request cooperative cancellation. The next progress_cb call
        raises _ScanCancelled, unwinding core.dataset.scan_dataset and
        landing in this worker's except branch so ``canceled`` is emitted.
        """
        self._cancel_requested = True

    def _cb(self, d: int, t: int, c: str) -> None:
        """Progress callback wrapper that checks the cancel flag."""
        if self._cancel_requested:
            raise _ScanCancelled()
        self.progress.emit(d, t, c)

    def run(self) -> None:
        # Phase 0: try cache (non-fatal — stale/corrupt cache → rescan)
        cached = None
        if not self._force_rescan:
            try:
                cached = index_cache.load(self._root)
            except Exception:
                logger.warning("index cache load failed for %s — rescanning",
                               self._root, exc_info=True)
                cached = None
        else:
            # Manual refresh: nuke the cache so next open is also fresh
            try:
                index_cache.clear(self._root)
            except Exception:
                logger.warning("index cache clear failed", exc_info=True)

        if cached is not None:
            # Still compute extended stats even for cached dataset
            self.phase.emit("analyze")
            try:
                ext = compute_extended_stats(cached, progress_cb=self._cb)
            except _ScanCancelled:
                self.canceled.emit()
                return
            except Exception:
                logger.exception("extended stats failed on cached dataset")
                ext = None
            self.finished_ok.emit(ScanResult(cached, ext))
            return

        # Phase 1: filesystem scan (fatal — no dataset → no UI)
        try:
            self.phase.emit("scan")
            dataset = scan_dataset(self._root, progress_cb=self._cb)
        except _ScanCancelled:
            self.canceled.emit()
            return
        except Exception as e:  # noqa: BLE001
            logger.exception("scan_dataset failed for %s", self._root)
            self.failed.emit(str(e))
            return

        # Phase 2: parse annotation counts (non-fatal — 0 counts better than no UI)
        try:
            self.phase.emit("annotate")
            count_annotations(dataset, progress_cb=self._cb)
        except _ScanCancelled:
            self.canceled.emit()
            return
        except Exception:
            logger.exception("count_annotations failed — continuing with 0 counts")

        try:
            index_cache.save(dataset)
        except Exception:
            logger.warning("index cache save failed — next open will rescan",
                           exc_info=True)

        # Phase 3: extended statistics (non-fatal — readiness bar degrades)
        ext = None
        try:
            self.phase.emit("analyze")
            ext = compute_extended_stats(dataset, progress_cb=self._cb)
        except _ScanCancelled:
            self.canceled.emit()
            return
        except Exception:
            logger.exception("compute_extended_stats failed")

        self.finished_ok.emit(ScanResult(dataset, ext))
