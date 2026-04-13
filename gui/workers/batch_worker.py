"""Generic background worker for batch file operations.

Wraps any callable of signature `fn(progress_cb) -> OpResult` so dialogs can
stay simple: they build a closure, hand it to this worker, and listen to
signals.
"""
from __future__ import annotations

from typing import Any, Callable

from PyQt6.QtCore import QThread, pyqtSignal


class BatchWorker(QThread):
    progress = pyqtSignal(int, int, str)   # done, total, current name
    finished_ok = pyqtSignal(object)       # 任意结果对象（OpResult / list / ...）
    failed = pyqtSignal(str)

    def __init__(self, fn: Callable[[Callable[[int, int, str], None]], Any]) -> None:
        super().__init__()
        self._fn = fn
        self.finished.connect(self.deleteLater)

    def run(self) -> None:  # noqa: D401
        try:
            result = self._fn(lambda d, t, c: self.progress.emit(d, t, c))
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))
            return
        self.finished_ok.emit(result)
