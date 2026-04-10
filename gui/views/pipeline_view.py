"""Pipeline view — canvas + per-node workspace views.

Double-click a node → full-screen workspace replaces the canvas.
Back button → return to canvas.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
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


# ---------------------------------------------------------------------------
# Workspace wrapper — header with back button + content
# ---------------------------------------------------------------------------

class _WorkspaceWrapper(QWidget):
    """Wraps a node workspace view with a back-button header."""

    back_clicked = pyqtSignal()

    def __init__(self, title: str, content: QWidget, parent=None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Header bar
        header = QFrame()
        header.setObjectName("detailTopBar")
        header.setFixedHeight(44)
        h = QHBoxLayout(header)
        h.setContentsMargins(T.GAP, 0, T.PAD_LG, 0)
        h.setSpacing(T.GAP)

        back = TransparentToolButton(FIF.LEFT_ARROW)
        back.setFixedSize(32, 32)
        back.clicked.connect(self.back_clicked.emit)
        h.addWidget(back)

        lbl = StrongBodyLabel(title)
        h.addWidget(lbl)
        h.addStretch()

        lay.addWidget(header)
        lay.addWidget(content, 1)


# ---------------------------------------------------------------------------
# PipelineView
# ---------------------------------------------------------------------------

class PipelineView(QWidget):
    """Node canvas + stacked workspace views."""

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

        # Stacked: page 0 = canvas view, page 1+ = workspaces
        self._stack = QStackedWidget()
        root.addWidget(self._stack)

        # Page 0: Canvas with top bar
        canvas_page = QWidget()
        cp_lay = QVBoxLayout(canvas_page)
        cp_lay.setContentsMargins(0, 0, 0, 0)
        cp_lay.setSpacing(0)

        # Top bar
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
        cp_lay.addWidget(topbar)

        # Canvas
        self._canvas = NodeCanvas()
        self._canvas.node_double_clicked.connect(self._on_node_dblclick)
        cp_lay.addWidget(self._canvas, 1)

        # Zoom overlay
        self._zoom_frame = QFrame(self._canvas)
        self._zoom_frame.setObjectName("zoomOverlay")
        self._zoom_frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        z_lay = QVBoxLayout(self._zoom_frame)
        z_lay.setContentsMargins(4, 4, 4, 4)
        z_lay.setSpacing(2)
        for icon, tip, fn in [
            (FIF.ZOOM_IN, "放大", lambda: self._canvas.zoom_by(1.25)),
            (FIF.ZOOM_OUT, "缩小", lambda: self._canvas.zoom_by(1 / 1.25)),
            (FIF.FIT_PAGE, "适应", self._canvas.zoom_fit),
        ]:
            b = TransparentToolButton(icon)
            b.setFixedSize(28, 28)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            z_lay.addWidget(b)

        self._stack.addWidget(canvas_page)  # index 0

        # Workspace cache: node_name → (wrapper_widget, stack_index)
        self._workspaces: dict[str, tuple[_WorkspaceWrapper, int]] = {}

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
        node = NODES.get(node_name)
        step_type = node.step_type if node else ""
        n = len(self._canvas.get_nodes())
        x = 200 + (n % 4) * 200
        y = 60 + (n // 4) * 80
        self._canvas.add_node(node_name, display_name, x, y, step_type)

    def _on_node_dblclick(self, node_item) -> None:
        """Double-click → open workspace for this node type."""
        if not isinstance(node_item, NodeItem):
            return
        self._open_workspace(node_item)

    def _open_workspace(self, node_item: NodeItem) -> None:
        """Switch to the workspace view for this node."""
        name = node_item.node_name

        if name not in self._workspaces:
            content = self._create_workspace(name, node_item)
            if content is None:
                # No workspace — use fallback dialog
                self._open_dialog(node_item)
                return
            spec = NODES.get(name)
            title = spec.display_name if spec else name
            wrapper = _WorkspaceWrapper(title, content)
            wrapper.back_clicked.connect(self._back_to_canvas)
            idx = self._stack.addWidget(wrapper)
            self._workspaces[name] = (wrapper, idx)

        # Update workspace with current node data
        self._update_workspace(name, node_item)

        _, idx = self._workspaces[name]
        self._stack.setCurrentIndex(idx)

    def _create_workspace(self, name: str, node_item: NodeItem) -> QWidget | None:
        """Create the workspace content widget for a node type."""
        if name == "data_source":
            return self._make_datasource_ws()
        if name == "quality_check":
            from gui.views.cleaning_view import CleaningView
            view = CleaningView()
            if self._dataset:
                view.set_dataset(self._dataset)
            return view
        if name == "augment":
            from gui.views.augment_view import AugmentView
            view = AugmentView()
            if self._dataset:
                view.set_dataset(self._dataset)
            return view
        if name == "split":
            from gui.views.split_view import SplitView
            view = SplitView()
            if self._dataset:
                view.set_dataset(self._dataset)
            return view
        if name == "export":
            from gui.views.export_view import ExportView
            view = ExportView()
            if self._dataset:
                view.set_dataset(self._dataset)
            return view
        # Fallback: dialog
        return None

    def _update_workspace(self, name: str, node_item: NodeItem) -> None:
        """Push current data into the workspace."""
        wrapper, _ = self._workspaces[name]
        content = wrapper.findChild(QWidget)
        if self._dataset and hasattr(content, "set_dataset"):
            content.set_dataset(self._dataset)

    def _back_to_canvas(self) -> None:
        self._stack.setCurrentIndex(0)

    def _open_dialog(self, node_item: NodeItem) -> None:
        """Fallback: open config dialog for nodes without a workspace."""
        from gui.dialogs.node_config_dialog import NodeConfigDialog
        dlg = NodeConfigDialog(
            node_item.node_name, node_item.display_name,
            node_item.get_params(), parent=self.window(),
        )
        if dlg.exec():
            node_item.set_params(dlg.get_values())

    # ---- Data source workspace ----

    def _make_datasource_ws(self) -> QWidget:
        """Data source workspace — browse dataset with thumbnails."""
        from gui.views.browser_view import BrowserView
        from gui.views.detail_view import DetailView
        from gui.workers.thumbnail_worker import ThumbnailWorker

        container = QWidget()
        lay = QVBoxLayout(container)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        browser_stack = QStackedWidget()

        browser = BrowserView()
        detail = DetailView()

        # Thumbnail worker for this workspace
        thumb = ThumbnailWorker(size=170, parent=container)
        thumb.start()
        browser.thumb_request.connect(thumb.request)
        browser.clear_thumb_queue.connect(thumb.clear_queue)
        thumb.thumb_ready.connect(browser.on_thumb_ready)

        browser.image_activated.connect(
            lambda img, imgs: (detail.show_image(img, imgs),
                               browser_stack.setCurrentWidget(detail))
        )
        detail.back_requested.connect(lambda: browser_stack.setCurrentWidget(browser))

        browser_stack.addWidget(browser)
        browser_stack.addWidget(detail)
        lay.addWidget(browser_stack)

        if self._dataset:
            browser.load_dataset(self._dataset)

        # Store references for later updates
        container._browser = browser
        container._thumb = thumb

        return container

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

        from core.nodes import NODES as NODE_SPECS
        graph = self._canvas.build_graph()
        for ndef in graph:
            spec = NODE_SPECS.get(ndef["node_name"])
            if not spec:
                continue
            for pdef in getattr(spec, "ports", ()):
                if pdef.direction == "input" and pdef.name not in ndef["inputs"]:
                    node_item = self._canvas.node_by_id(ndef["id"])
                    if node_item:
                        node_item.set_state("error")
                    InfoBar.warning(
                        "连接不完整",
                        f"「{ndef['display_name']}」的输入未连接",
                        parent=self.window(), duration=3000,
                        position=InfoBarPosition.TOP,
                    )
                    return

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
        for node_item in self._canvas.get_nodes():
            node_item.set_state("")
        InfoBar.error("失败", msg, parent=self.window(),
                      duration=5000, position=InfoBarPosition.TOP)
