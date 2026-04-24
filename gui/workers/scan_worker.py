"""Background dataset scan worker.

Multi-phase pipeline (all on worker thread):
  1. **scan**  — fast filesystem index (``os.scandir``, no parsing).
                 Emits ``scan_finished(dataset)`` **immediately** so the
                 UI can render the grid/catalogue while Phases 2-3 keep
                 running in the background.
  2. **unify** — ``format_in.load_samples`` → ``SampleSet``. This single
                 pass replaces the old ``count_annotations`` + ``compute_extended_stats``
                 disk-parse pipeline: annotation counts are derived from
                 SampleSet, and extended stats are computed in-memory
                 (~100× faster).
  3. **analyze** — ``ExtendedStats`` from the in-memory SampleSet. Skippable
                 for quick refreshes.

Main thread receives ``scan_finished`` after Phase 1, then a final
``ScanResult`` via ``finished_ok`` after Phases 2-3.
"""
from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from core import index_cache
from core.dataset import scan_dataset
from core.models import Dataset
from core.stats import ExtendedStats

logger = logging.getLogger(__name__)


class ScanResult:
    """Bundle returned by ScanWorker.finished_ok."""
    __slots__ = ("dataset", "ext_stats", "sample_set")

    def __init__(self, dataset: Dataset,
                 ext_stats: ExtendedStats | None,
                 sample_set=None) -> None:
        self.dataset = dataset
        self.ext_stats = ext_stats
        self.sample_set = sample_set          # SampleSet | None


class _ScanCancelled(Exception):
    """Raised inside progress_cb to unwind scan_dataset on user cancel."""


class ScanWorker(QThread):
    progress = pyqtSignal(int, int, str)   # done, total, current name
    phase = pyqtSignal(str)                # "scan" | "unify" | "analyze"
    scan_finished = pyqtSignal(object)     # Dataset — after Phase 1 only
    finished_ok = pyqtSignal(object)       # ScanResult — after all phases
    failed = pyqtSignal(str)
    canceled = pyqtSignal()                # user canceled mid-scan

    def __init__(self, root: Path, parent: QObject | None = None,
                 force_rescan: bool = False,
                 skip_analyze: bool = False) -> None:
        """
        Args:
            root: dataset root directory.
            parent: Qt parent.
            force_rescan: If True, skip the index cache and re-walk the
                filesystem.
            skip_analyze: If True, skip Phase 3 (ExtendedStats).

        Note:
            ``load_samples`` always auto-detects the annotation format
            from the scanned data (COCO layout override + label-suffix
            inference + per-file JSON peek with cache).  We deliberately
            do **not** accept a ``format_hint`` here — trusting
            ``Project.annotation_format`` on first-open of a YOLO/VOC
            dataset would parse every ``.txt``/``.xml`` as LabelMe and
            produce an empty SampleSet.
        """
        super().__init__(parent)
        self._root = root
        self._force_rescan = force_rescan
        self._skip_analyze = skip_analyze
        self._cancel_requested = False
        self.finished.connect(self.deleteLater)

    def cancel(self) -> None:
        self._cancel_requested = True

    def _cb(self, d: int, t: int, c: str) -> None:
        if self._cancel_requested:
            raise _ScanCancelled()
        self.progress.emit(d, t, c)

    # ── Helpers ──────────────────────────────────────────────────────

    def _load_sample_set(self, dataset: Dataset):
        """Phase 2: build SampleSet + backfill Dataset.total_annotations."""
        self.phase.emit("unify")
        try:
            from core.format_in import load_samples
            ss = load_samples(
                dataset,
                progress_cb=self._cb,
            )
        except _ScanCancelled:
            raise
        except Exception:
            logger.exception("load_samples failed — falling back to count_annotations")
            # Safety net: if load_samples blows up, at least get shape counts
            # so the dataset bar / export wizard aren't stuck at 0.
            try:
                from core.dataset import count_annotations
                self.phase.emit("annotate")
                count_annotations(dataset, progress_cb=self._cb)
            except _ScanCancelled:
                raise
            except Exception:
                logger.exception("count_annotations fallback also failed")
            return None
        dataset.total_annotations = ss.total_regions
        return ss

    def _compute_stats(self, dataset: Dataset, ss):
        """Phase 3: ExtendedStats, preferring SampleSet (no I/O)."""
        self.phase.emit("analyze")
        if ss is not None:
            from core.stats import compute_extended_stats_from_samples
            try:
                return compute_extended_stats_from_samples(
                    ss, progress_cb=self._cb)
            except _ScanCancelled:
                raise
            except Exception:
                logger.exception("stats from SampleSet failed")
                return None
        # Fallback when SampleSet failed to build
        from core.stats import compute_extended_stats
        try:
            return compute_extended_stats(dataset, progress_cb=self._cb)
        except _ScanCancelled:
            raise
        except Exception:
            logger.exception("compute_extended_stats fallback failed")
            return None

    # ── Main run ─────────────────────────────────────────────────────

    def run(self) -> None:
        # Phase 0: try cache
        cached = None
        if not self._force_rescan:
            try:
                cached = index_cache.load(self._root)
            except Exception:
                logger.warning("index cache load failed for %s — rescanning",
                               self._root, exc_info=True)
                cached = None
        else:
            try:
                index_cache.clear(self._root)
            except Exception:
                logger.warning("index cache clear failed", exc_info=True)

        if cached is not None:
            # Cache hit — hand the dataset to the UI *immediately* so the
            # grid/catalogue render without waiting for Phase 2.  The
            # SampleSet build keeps running on this worker.
            self.scan_finished.emit(cached)
            dataset = cached
        else:
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
            # Let the UI render NOW — Phases 2-3 continue in background.
            self.scan_finished.emit(dataset)

        # Phase 2: build SampleSet (replaces count_annotations)
        ss = None
        try:
            ss = self._load_sample_set(dataset)
        except _ScanCancelled:
            self.canceled.emit()
            return

        # Persist to cache only on fresh scans (cache already has this dataset)
        if cached is None:
            try:
                index_cache.save(dataset)
            except Exception:
                logger.warning("index cache save failed", exc_info=True)

        # Phase 3: extended statistics (skippable on refresh)
        ext = None
        if not self._skip_analyze:
            try:
                ext = self._compute_stats(dataset, ss)
            except _ScanCancelled:
                self.canceled.emit()
                return

        self.finished_ok.emit(ScanResult(dataset, ext, ss))
