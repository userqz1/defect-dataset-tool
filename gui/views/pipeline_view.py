"""Pipeline view — node editor canvas + right inspector panel.

Central workspace: drag tools from sidebar onto the canvas,
click a node to configure in the right panel, run the pipeline.
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
    TransparentToolButton,
)

from core.models import Dataset
from core.nodes import NODES
from gui.theme import T
from gui.widgets.node_editor import NodeCanvas, NodeItem
from gui.widgets.node_inspector import NodeInspector
from gui.workers.batch_worker import BatchWorker


class PipelineView(QWidget):
    """Node-based pipeline editor with right-side inspector."""

    dataset_changed = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("pipelineView")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._dataset: Dataset | None = None
        self._worker: BatchWorker | None = None
        self._target_format = "YOLO"
        self._selected_node: NodeItem | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- Top bar ----
        topbar = QFrame()
        topbar.setObjectName("detailTopBar")
        topbar.setFixedHeight(44)
        top_lay = QHBoxLayout(topbar)
        top_lay.setContentsMargins(T.PAD_LG, 0, T.PAD_LG, 0)
        top_lay.setSpacing(T.GAP_LG)

        self._format_label = StrongBodyLabel("目标: YOLO")
        top_lay.addWidget(self._format_label)
        self._grid_status = CaptionLabel("")
        top_lay.addWidget(self._grid_status)
        top_lay.addStretch(1)

        run_btn = PrimaryPushButton("执行流程")
        run_btn.setIcon(FIF.PLAY)
        run_btn.clicked.connect(self._on_run)
        self._run_btn = run_btn
        top_lay.addWidget(run_btn)
        root.addWidget(topbar)

        # ---- Body: canvas + inspector ----
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self._canvas = NodeCanvas()
        self._canvas.node_double_clicked.connect(self._on_node_clicked)
        # Also handle single-click selection
        self._canvas._scene.selectionChanged.connect(self._on_selection_changed)
        body.addWidget(self._canvas, 1)

        self._inspector = NodeInspector()
        self._inspector.params_changed.connect(self._on_params_changed)
        self._inspector.closed.connect(self._on_inspector_closed)
        body.addWidget(self._inspector)

        root.addLayout(body, 1)

        # ---- Zoom controls (overlay, top-right of canvas) ----
        self._zoom_frame = QFrame(self._canvas)
        self._zoom_frame.setObjectName("zoomOverlay")
        self._zoom_frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        z_lay = QVBoxLayout(self._zoom_frame)
        z_lay.setContentsMargins(4, 4, 4, 4)
        z_lay.setSpacing(2)

        zi = TransparentToolButton(FIF.ZOOM_IN)
        zi.setFixedSize(28, 28)
        zi.setToolTip("放大")
        zi.clicked.connect(lambda: self._canvas.zoom_by(1.25))
        z_lay.addWidget(zi)

        zo = TransparentToolButton(FIF.ZOOM_OUT)
        zo.setFixedSize(28, 28)
        zo.setToolTip("缩小")
        zo.clicked.connect(lambda: self._canvas.zoom_by(1 / 1.25))
        z_lay.addWidget(zo)

        zf = TransparentToolButton(FIF.FIT_PAGE)
        zf.setFixedSize(28, 28)
        zf.setToolTip("适应窗口")
        zf.clicked.connect(self._canvas.zoom_fit)
        z_lay.addWidget(zf)

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

    # ---- Layout ----

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._zoom_frame.move(self._canvas.width() - self._zoom_frame.width() - 8, 8)

    # ---- Node interaction ----

    def _add_node(self, node_name: str, display_name: str) -> None:
        """Add a node to the canvas (sidebar click)."""
        node = NODES.get(node_name)
        step_type = node.step_type if node else ""
        n = len(self._canvas.get_nodes())
        x = 200 + (n % 4) * 200
        y = 60 + (n // 4) * 80
        self._canvas.add_node(node_name, display_name, x, y, step_type)

    def _on_node_clicked(self, node_name: str) -> None:
        """Double-click a node → open inspector."""
        for item in self._canvas.get_nodes():
            if item.node_name == node_name:
                self._selected_node = item
                self._inspector.show_node(node_name, item.get_params())
                return

    def _on_selection_changed(self) -> None:
        """Scene selection changed → update inspector."""
        selected = [i for i in self._canvas._scene.selectedItems()
                    if isinstance(i, NodeItem)]
        if len(selected) == 1:
            node = selected[0]
            self._selected_node = node
            self._inspector.show_node(node.node_name, node.get_params())
        elif not selected:
            self._selected_node = None
            self._inspector.hide_node()

    def _on_params_changed(self, node_name: str, values: dict) -> None:
        """Inspector value changed → update node."""
        if self._selected_node and self._selected_node.node_name == node_name:
            self._selected_node.set_params(values)

    def _on_inspector_closed(self) -> None:
        self._selected_node = None
        # Clear selection on canvas
        self._canvas._scene.clearSelection()

    # ---- Grid status ----

    def _refresh_grid(self) -> None:
        from core.format_grid import build_grid
        grid = build_grid(self._target_format, self._dataset)
        self._format_label.setText(f"目标: {grid.format_name}")
        if grid.ready:
            self._grid_status.setText(f"\u2713 就绪 ({grid.progress_text})")
            self._grid_status.setObjectName("readinessOk")
        else:
            self._grid_status.setText(f"{grid.required_filled}/{grid.required_count} 就绪")
            self._grid_status.setObjectName("readinessGap")
        self._grid_status.style().unpolish(self._grid_status)
        self._grid_status.style().polish(self._grid_status)

    # ---- Pipeline execution ----

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
            engine.add_step(node_item.node_name, node_item.get_params())

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
