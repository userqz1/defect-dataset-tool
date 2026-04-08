"""Background thumbnail generation worker.

Workflow:
- Main thread enqueues ImageInfo via request_thumb(img_info)
- Worker thread generates JPEG bytes + reads dimensions
- Emits thumb_ready(path_str, jpeg_bytes, w, h)
"""
from __future__ import annotations

from pathlib import Path
from queue import Empty, Queue

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from core.thumbnail_cache import ThumbnailCache


class ThumbnailWorker(QThread):
    thumb_ready = pyqtSignal(str, bytes, int, int)  # path, jpeg bytes, w, h

    def __init__(
        self,
        size: int = 170,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._queue: Queue[Path | None] = Queue()
        self._size = size
        self._cache = ThumbnailCache()
        self._running = True

    def request(self, path: Path) -> None:
        self._queue.put(path)

    def clear_queue(self) -> None:
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except Empty:
                break

    def stop(self) -> None:
        self._running = False
        self._queue.put(None)  # 唤醒
        self.wait(2000)

    def run(self) -> None:
        while self._running:
            try:
                path = self._queue.get(timeout=0.5)
            except Empty:
                continue
            if path is None:
                break
            data = self._cache.get_or_generate(path, self._size)
            if data is None:
                continue
            dim = self._cache.get_dimensions(path) or (0, 0)
            self.thumb_ready.emit(str(path), data, dim[0], dim[1])
