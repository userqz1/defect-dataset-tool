"""Background thumbnail generation worker.

Workflow:
- Main thread enqueues ImageInfo via request_thumb(img_info)
- The QThread run loop hands each path to a small thread pool, which
  generates JPEG bytes + reads dimensions
- Emits thumb_ready(path_str, jpeg_bytes, w, h)

Generation is pooled rather than serial because decoding dominates the
cost and PIL releases the GIL while it decodes. Together with the
``draft()`` fast path in ``core.thumbnail_cache``, a cold 80-thumbnail
screen of 5120x5120 JPEGs went from ~9.6 s to ~0.4 s.
"""
from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Empty, Queue

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from core.thumbnail_cache import ThumbnailCache

logger = logging.getLogger(__name__)


class ThumbnailWorker(QThread):
    thumb_ready = pyqtSignal(str, bytes, int, int)  # path, jpeg bytes, w, h

    def __init__(
        self,
        size: int = 170,
        parent: QObject | None = None,
        workers: int | None = None,
    ) -> None:
        super().__init__(parent)
        self._queue: Queue[Path | None] = Queue()
        self._size = size
        self._cache = ThumbnailCache()
        self._running = True
        # Decoding a JPEG is the dominant cost and PIL releases the GIL
        # while doing it, so threads scale here — the same reasoning
        # ``core.dataset.count_annotations`` already relies on. Capped
        # because the win flattens out and every extra thread holds a
        # full-size decode buffer.
        self._workers = workers or max(2, min(8, (os.cpu_count() or 4)))
        # Bumped by ``clear_queue``; results tagged with a stale
        # generation are dropped instead of ghosting into a view that
        # has already moved on to another filter/page.
        self._generation = 0

    def request(self, path: Path) -> None:
        self._queue.put(path)

    def clear_queue(self) -> None:
        """Drop everything not yet started and disown what is in flight."""
        self._generation += 1
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except Empty:
                break

    def stop(self) -> None:
        """Graceful shutdown: signal the run loop, wake the queue, wait."""
        self._running = False
        self._queue.put(None)  # 唤醒 — matches the `if path is None: break`
        if not self.wait(5000):
            logger.warning("ThumbnailWorker did not stop within 5 s — "
                           "terminating thread")
            self.terminate()
            self.wait(2000)
        try:
            self._cache.close()
        except Exception:
            logger.exception("thumbnail cache close failed")

    def run(self) -> None:
        # shutdown(wait=False, cancel_futures=True) on the way out: the
        # default would block until every queued future finished, which
        # can outlast ``stop``'s 5 s budget and get the thread killed.
        pool = ThreadPoolExecutor(
            max_workers=self._workers, thread_name_prefix="thumb")
        try:
            while self._running:
                try:
                    path = self._queue.get(timeout=0.5)
                except Empty:
                    continue
                if path is None:
                    break
                pool.submit(self._render, path, self._generation)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def _render(self, path: Path, generation: int) -> None:
        """Generate one thumbnail on a pool thread and publish it.

        Emitting a signal off a non-Qt thread is fine — the connection to
        the main thread resolves to a queued one — but the result is
        dropped if the view moved on (``clear_queue`` bumped the
        generation) or we are shutting down.
        """
        if not self._running or generation != self._generation:
            return
        try:
            data = self._cache.get_or_generate(path, self._size)
            if data is None:
                return
            dim = self._cache.get_dimensions(path) or (0, 0)
            if not self._running or generation != self._generation:
                return
            self.thumb_ready.emit(str(path), data, dim[0], dim[1])
        except Exception:
            # Never let one bad image tear down the whole worker.
            logger.exception("thumbnail worker failed on %s", path)
