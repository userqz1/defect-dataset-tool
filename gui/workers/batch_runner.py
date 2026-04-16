"""BatchRunner — unified worker + ProgressDialog + result handling.

Before this existed, every tool button in DatasetBrowserView was writing
the same 40-line dance:

    progress = ProgressDialog("...")
    progress.show()
    worker = BatchWorker(task)
    worker.progress.connect(lambda d, t, n: progress.set_progress(d, t, n))
    def on_done(result): progress.accept(); ...
    def on_fail(msg): progress.accept(); InfoBar.error(...)
    worker.finished_ok.connect(on_done)
    worker.failed.connect(on_fail)
    worker.start()
    self._quality_worker = worker  # keep reference alive

BatchRunner collapses all of that into:

    BatchRunner(self, "质量检查").run(
        task=lambda cb: check_images(images, opts, progress_cb=cb),
        on_done=handle_issues,
    )

Multiple concurrent tools are fine — each instance keeps its worker
alive via a self-reference that is cleared when the worker finishes.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from PyQt6.QtCore import QObject
from qfluentwidgets import InfoBar, InfoBarPosition

from gui.dialogs.op_dialogs import ProgressDialog
from gui.workers.batch_worker import BatchWorker

logger = logging.getLogger(__name__)


class BatchRunner(QObject):
    """One-shot runner for a background batch operation with UI feedback.

    Lifetime: parent is the view that owns the run. BatchRunner stores a
    strong reference on itself until the worker signals finished_ok/failed,
    after which it deletes itself to avoid piling up.
    """

    def __init__(self, parent: QObject, title: str) -> None:
        super().__init__(parent)
        self._title = title
        self._progress: ProgressDialog | None = None
        self._worker: BatchWorker | None = None

    def run(
        self,
        task: Callable[[Callable[[int, int, str], None]], Any],
        on_done: Callable[[Any], None],
        on_fail: Callable[[str], None] | None = None,
    ) -> None:
        """Start the background operation.

        Args:
            task: Callable accepting a progress_cb(done, total, name) and
                returning any result object.
            on_done: Called on the GUI thread with the task's return value.
            on_fail: Optional override. Default shows an error InfoBar with
                the title "<title>失败" and the exception message.
        """
        parent_widget = self.parent()
        parent_window = (parent_widget.window()
                         if hasattr(parent_widget, "window") else None)

        self._progress = ProgressDialog(self._title, parent=parent_window)
        self._progress.show()

        worker = BatchWorker(task)
        self._worker = worker

        def handle_progress(d: int, t: int, n: str) -> None:
            if self._progress is not None:
                self._progress.set_progress(d, t, n)

        def handle_done(result: Any) -> None:
            self._close_progress()
            try:
                on_done(result)
            except Exception:
                logger.exception("on_done handler failed for %s", self._title)
            self.deleteLater()

        def handle_fail(msg: str) -> None:
            self._close_progress()
            try:
                if on_fail is not None:
                    on_fail(msg)
                else:
                    InfoBar.error(
                        f"{self._title}失败", msg,
                        parent=parent_window, duration=5000,
                        position=InfoBarPosition.TOP,
                    )
            except Exception:
                logger.exception("on_fail handler failed for %s", self._title)
            self.deleteLater()

        worker.progress.connect(handle_progress)
        worker.finished_ok.connect(handle_done)
        worker.failed.connect(handle_fail)
        worker.start()

    def _close_progress(self) -> None:
        if self._progress is not None:
            self._progress.accept()
            self._progress = None
