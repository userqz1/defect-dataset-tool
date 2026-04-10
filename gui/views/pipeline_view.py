"""Pipeline view — node editor canvas + format grid + execution.

Central workspace: users see the target format grid at top,
drag/add processing nodes on the canvas, connect them,
and execute the pipeline to fill the grid.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel,
    FluentIcon as FIF,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    StrongBodyLabel,
)

from core.models import Dataset
from core.nodes import NODES
from gui.theme import T
from gui.widgets.node_editor import NodeCanvas
from gui.workers.batch_worker import BatchWorker


class PipelineView(QWidget):
    """Node-based pipeline editor with format grid."""

    dataset_changed = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("pipelineView")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._dataset: Dataset | None = None
        self._worker: BatchWorker | None = None
        self._target_format = "YOLO"

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- Top bar: grid summary + controls ----
        topbar = QFrame()
        topbar.setObjectName("detailTopBar")
        topbar.setFixedHeight(48)
        top_layout = QHBoxLayout(topbar)
        top_layout.setContentsMargins(T.PAD_LG, 0, T.PAD_LG, 0)
        top_layout.setSpacing(T.GAP_LG)

        self._format_label = StrongBodyLabel("目标: YOLO")
        top_layout.addWidget(self._format_label)

        self._grid_status = CaptionLabel("")
        top_layout.addWidget(self._grid_status)
        top_layout.addStretch(1)

        run_btn = PrimaryPushButton("执行流程")
        run_btn.setIcon(FIF.PLAY)
        run_btn.clicked.connect(self._on_run)
        self._run_btn = run_btn
        top_layout.addWidget(run_btn)

        root.addWidget(topbar)

        # ---- Canvas (full width — tools come from main sidebar) ----
        self._canvas = NodeCanvas()
        self._canvas.node_double_clicked.connect(self._on_node_double_clicked)
        root.addWidget(self._canvas, 1)

    # ---- API ----

    def set_dataset(self, dataset: Dataset | None) -> None:
        self._dataset = dataset
        self._run_btn.setEnabled(dataset is not None)
        self._refresh_grid()

    def set_task_type(self, task_type) -> None:
        self._task_type = task_type
        from core.task_types import TASK_REGISTRY
        info = TASK_REGISTRY.get(task_type)
        if info and info.export_formats:
            self._target_format = info.export_formats[0]
        self._refresh_grid()

    # ---- Internal ----

    def _add_node(self, node_name: str, display_name: str) -> None:
        """Add a node to the canvas at a smart position."""
        n = len(self._canvas.get_nodes())
        x = 100 + (n % 3) * 220
        y = 80 + (n // 3) * 120
        node = self._canvas.add_node(node_name, display_name, x, y)

        # Auto-connect to previous node if exists
        nodes = self._canvas.get_nodes()
        if len(nodes) >= 2:
            prev = nodes[-2]
            if prev.outputs and node.inputs:
                from gui.widgets.node_editor import ConnectionItem
                conn = ConnectionItem(prev.outputs[0], node.inputs[0])
                self._canvas._scene.addItem(conn)

    def _on_node_double_clicked(self, node_name: str) -> None:
        node = NODES.get(node_name)
        if node:
            InfoBar.info(
                node.display_name,
                node.description,
                parent=self.window(),
                duration=2000,
                position=InfoBarPosition.TOP,
            )

    def _refresh_grid(self) -> None:
        from core.format_grid import build_grid

        grid = build_grid(self._target_format, self._dataset)
        self._format_label.setText(f"目标: {grid.format_name}")

        if grid.ready:
            self._grid_status.setText(f"✓ 就绪 ({grid.progress_text})")
            self._grid_status.setObjectName("readinessOk")
        else:
            self._grid_status.setText(f"{grid.required_filled}/{grid.required_count} 就绪")
            self._grid_status.setObjectName("readinessGap")
        self._grid_status.style().unpolish(self._grid_status)
        self._grid_status.style().polish(self._grid_status)

    def _on_run(self) -> None:
        if not self._dataset or self._worker:
            return

        nodes = self._canvas.get_nodes()
        if not nodes:
            InfoBar.warning("", "画布上没有节点", parent=self.window(),
                          duration=2000, position=InfoBarPosition.TOP)
            return

        from core.pipeline import PipelineContext, PipelineEngine
        from core.task_types import TaskType
        from gui.dialogs.op_dialogs import ProgressDialog

        task_type = getattr(self, "_task_type", TaskType.DETECTION)
        ctx = PipelineContext.from_dataset(self._dataset, task_type)

        engine = PipelineEngine()
        for node_item in nodes:
            engine.add_step(node_item.node_name, {})

        self._progress = ProgressDialog("执行处理流程", parent=self.window())
        self._progress.show()
        self._run_btn.setEnabled(False)

        def task(progress_cb):
            return engine.execute(ctx, progress_cb=progress_cb)

        self._worker = BatchWorker(task)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_progress(self, done: int, total: int, name: str) -> None:
        if hasattr(self, "_progress") and self._progress:
            self._progress.set_progress(done, total, name)

    def _on_done(self, result) -> None:
        self._worker = None
        if hasattr(self, "_progress") and self._progress:
            self._progress.close()
            self._progress = None
        self._run_btn.setEnabled(True)

        # Update node statuses
        for record in result.step_results:
            for node_item in self._canvas.get_nodes():
                if node_item.node_name == record.node_name:
                    node_item.set_status(record.message)

        if result.success:
            InfoBar.success("完成", f"{result.steps_run} 个节点执行完成",
                          parent=self.window(), duration=3000,
                          position=InfoBarPosition.TOP)

    def _on_failed(self, msg: str) -> None:
        self._worker = None
        if hasattr(self, "_progress") and self._progress:
            self._progress.close()
            self._progress = None
        self._run_btn.setEnabled(True)
        InfoBar.error("失败", msg, parent=self.window(),
                      duration=5000, position=InfoBarPosition.TOP)
