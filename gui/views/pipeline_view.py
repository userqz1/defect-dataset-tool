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

        # ---- Canvas (full width) ----
        self._canvas = NodeCanvas()
        self._canvas.node_double_clicked.connect(self._on_node_dblclick)  # receives NodeItem
        root.addWidget(self._canvas, 1)

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

    def _on_node_dblclick(self, node_item) -> None:
        """Double-click a node → open config dialog."""
        from gui.dialogs.node_config_dialog import NodeConfigDialog
        from gui.widgets.node_editor import NodeItem

        if not isinstance(node_item, NodeItem):
            return

        dlg = NodeConfigDialog(
            node_item.node_name, node_item.display_name,
            node_item.get_params(), parent=self.window(),
        )
        if dlg.exec():
            node_item.set_params(dlg.get_values())

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

    # ---- Pipeline execution (graph-based) ----

    def _on_run(self) -> None:
        if self._worker:
            return
        nodes = self._canvas.get_nodes()
        if not nodes:
            InfoBar.warning("", "画布上没有节点", parent=self.window(),
                            duration=2000, position=InfoBarPosition.TOP)
            return

        # Validate: check disconnected required inputs
        from core.nodes import NODES as NODE_SPECS
        graph = self._canvas.build_graph()
        for ndef in graph:
            spec = NODE_SPECS.get(ndef["node_name"])
            if not spec:
                continue
            for pdef in getattr(spec, "ports", ()):
                if pdef.direction == "input" and pdef.name not in ndef["inputs"]:
                    # Mark the node as error
                    node_item = self._canvas.node_by_id(ndef["id"])
                    if node_item:
                        node_item.set_state("error")
                    InfoBar.warning(
                        "连接不完整",
                        f"「{ndef['display_name']}」的输入端口未连接",
                        parent=self.window(), duration=3000,
                        position=InfoBarPosition.TOP,
                    )
                    return

        # Mark all nodes as running
        for node_item in nodes:
            node_item.set_state("running")

        from core.pipeline import GraphEngine
        from gui.dialogs.op_dialogs import ProgressDialog

        self._graph = graph
        self._progress = ProgressDialog("执行处理流程", parent=self.window())
        self._progress.show()
        self._run_btn.setEnabled(False)

        engine = GraphEngine()
        dataset = self._dataset

        def task(progress_cb):
            return engine.execute(graph, dataset, progress_cb=progress_cb)

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

        # Update node states from results
        for nid, record in result.node_results.items():
            node_item = self._canvas.node_by_id(nid)
            if node_item:
                node_item.set_state("done" if record.success else "error")
                node_item.set_status(record.message)

        if result.success:
            InfoBar.success("完成", f"{result.steps_run} 个节点执行完成",
                            parent=self.window(), duration=3000,
                            position=InfoBarPosition.TOP)
        elif result.error:
            InfoBar.error("执行错误", result.error,
                          parent=self.window(), duration=5000,
                          position=InfoBarPosition.TOP)

    def _on_failed(self, msg: str) -> None:
        self._worker = None
        if hasattr(self, "_progress") and self._progress:
            self._progress.close()
            self._progress = None
        self._run_btn.setEnabled(True)
        # Reset all nodes to idle
        for node_item in self._canvas.get_nodes():
            node_item.set_state("")
        InfoBar.error("失败", msg, parent=self.window(),
                      duration=5000, position=InfoBarPosition.TOP)
