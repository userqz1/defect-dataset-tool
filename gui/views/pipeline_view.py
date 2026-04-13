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
        self.content = content  # direct reference for _update_workspace
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
    save_requested = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("pipelineView")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._dataset: Dataset | None = None
        self._worker: BatchWorker | None = None
        self._target_format = "YOLO"
        self._task_type = None
        self._progress = None
        # Pipeline execution results: node python id() → NodeResult
        self._node_results: dict[int, object] = {}
        # Track which NodeItem is associated with each workspace
        self._workspace_node_items: dict[str, NodeItem] = {}

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

        # Top bar: scheme name + save + run
        topbar = QFrame()
        topbar.setObjectName("detailTopBar")
        topbar.setFixedHeight(44)
        top_lay = QHBoxLayout(topbar)
        top_lay.setContentsMargins(T.PAD_LG, 0, T.PAD_LG, 0)
        top_lay.setSpacing(T.GAP)

        from qfluentwidgets import LineEdit
        self._scheme_name = LineEdit()
        self._scheme_name.setFixedWidth(180)
        self._scheme_name.setFixedHeight(28)
        self._scheme_name.setClearButtonEnabled(False)
        self._scheme_name.setObjectName("taskNameEdit")
        self._scheme_name.setText("未命名方案")
        top_lay.addWidget(self._scheme_name)

        save_btn = TransparentToolButton(FIF.SAVE)
        save_btn.setFixedSize(28, 28)
        save_btn.setToolTip("保存方案")
        save_btn.clicked.connect(self._on_save_clicked)
        top_lay.addWidget(save_btn)

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

    def set_scheme_name(self, name: str) -> None:
        self._scheme_name.setText(name)

    def get_scheme_name(self) -> str:
        return self._scheme_name.text()

    def clear_workspaces(self) -> None:
        """Remove cached workspaces (called when switching schemes)."""
        for _name, (wrapper, idx) in list(self._workspaces.items()):
            # Stop background workers before deletion to avoid segfault
            content = wrapper.content if hasattr(wrapper, "content") else None
            if content is not None:
                # Data source workspace stores refs on the container
                thumb = getattr(content, "_thumb", None)
                if thumb is not None:
                    thumb.stop()
                scan_w = getattr(content, "_scan_worker", None)
                if scan_w is not None:
                    scan_w.quit()
                    scan_w.wait(1000)
            self._stack.removeWidget(wrapper)
            wrapper.deleteLater()
        self._workspaces.clear()
        self._workspace_node_items.clear()
        self._node_results.clear()

    def _on_save_clicked(self) -> None:
        # Sync all workspace params back to NodeItems before saving
        self._sync_all_workspace_params()
        self.save_requested.emit()

    def _sync_all_workspace_params(self) -> None:
        """Push params from all open workspace views back to their NodeItems."""
        for name, node_item in self._workspace_node_items.items():
            if name not in self._workspaces:
                continue
            wrapper, _ = self._workspaces[name]
            content = wrapper.content
            if hasattr(content, "get_params"):
                node_item.set_params(content.get_params())

    def set_dataset(self, dataset: Dataset | None) -> None:
        self._dataset = dataset

    def set_task_type(self, task_type) -> None:
        self._task_type = task_type

    # ---- Layout ----

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reposition_zoom()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._reposition_zoom()

    def _reposition_zoom(self) -> None:
        cw = self._canvas.viewport().width()
        ch = self._canvas.viewport().height()
        fw = self._zoom_frame.sizeHint().width()
        fh = self._zoom_frame.sizeHint().height()
        self._zoom_frame.move(cw - fw - 12, ch - fh - 12)

    # ---- Node interaction ----

    def _add_node(self, node_name: str, display_name: str) -> None:
        """Add node at the center of the current viewport."""
        node = NODES.get(node_name)
        step_type = node.step_type if node else ""
        # Place at viewport center with slight random offset to avoid stacking
        center = self._canvas.mapToScene(
            self._canvas.viewport().width() // 2,
            self._canvas.viewport().height() // 2,
        )
        n = len(self._canvas.get_nodes())
        offset = (n % 5) * 30  # slight stagger so nodes don't overlap exactly
        self._canvas.add_node(
            node_name, display_name,
            center.x() - 80 + offset, center.y() - 24 + offset,
            step_type,
        )

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

        # Track which node_item is shown in this workspace
        self._workspace_node_items[name] = node_item
        # Update workspace with current node data + results
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
        if name == "predict":
            from gui.views.predict_view import PredictView
            view = PredictView()
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
        """Push current data + execution results into the workspace."""
        wrapper, _ = self._workspaces[name]
        content = wrapper.content

        # Restore params from NodeItem into workspace UI controls
        params = node_item.get_params()
        if params and hasattr(content, "set_params"):
            content.set_params(params)

        if self._dataset and hasattr(content, "set_dataset"):
            content.set_dataset(self._dataset)

        # Inject pipeline execution results if available
        nid = id(node_item)
        node_result = self._node_results.get(nid)
        if node_result and hasattr(content, "set_results"):
            content.set_results(node_result.input_data, node_result.step_result)

    def _back_to_canvas(self) -> None:
        # Sync current workspace params back to NodeItem
        for name, node_item in self._workspace_node_items.items():
            if name not in self._workspaces:
                continue
            wrapper, idx = self._workspaces[name]
            if self._stack.currentIndex() == idx:
                content = wrapper.content
                if hasattr(content, "get_params"):
                    node_item.set_params(content.get_params())
                break
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
        """Data source workspace — select directory, scan, browse."""
        from PyQt6.QtWidgets import QFileDialog
        from pathlib import Path
        from gui.views.browser_view import BrowserView
        from gui.views.detail_view import DetailView
        from gui.workers.scan_worker import ScanWorker
        from gui.workers.thumbnail_worker import ThumbnailWorker

        container = QWidget()
        lay = QVBoxLayout(container)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Top bar: directory picker + stats
        topbar = QFrame()
        topbar.setObjectName("detailTopBar")
        topbar.setFixedHeight(44)
        tb_lay = QHBoxLayout(topbar)
        tb_lay.setContentsMargins(T.PAD_LG, 0, T.PAD_LG, 0)
        tb_lay.setSpacing(T.GAP)

        path_label = CaptionLabel("未选择目录")
        tb_lay.addWidget(path_label, 1)

        stats_label = CaptionLabel("")
        tb_lay.addWidget(stats_label)

        open_btn = PrimaryPushButton("选择目录")
        open_btn.setIcon(FIF.FOLDER)
        open_btn.setFixedWidth(120)
        tb_lay.addWidget(open_btn)

        lay.addWidget(topbar)

        # Browser + Detail stack
        browser_stack = QStackedWidget()
        browser = BrowserView()
        detail = DetailView()

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
        lay.addWidget(browser_stack, 1)

        # Store refs
        container._browser = browser
        container._thumb = thumb
        container._scan_worker = None

        def _on_open():
            d = QFileDialog.getExistingDirectory(container, "选择数据集目录", str(Path.home()))
            if not d:
                return
            root = Path(d)
            path_label.setText(str(root))
            open_btn.setEnabled(False)
            stats_label.setText("扫描中…")

            from gui.dialogs.op_dialogs import ProgressDialog
            progress = ProgressDialog("扫描数据集", parent=self.window())
            progress.show()

            worker = ScanWorker(root, parent=container)
            container._scan_worker = worker

            def on_progress(done, total, name):
                progress.set_progress(done, total, name)

            def on_done(result):
                container._scan_worker = None
                progress.accept()
                open_btn.setEnabled(True)

                from gui.workers.scan_worker import ScanResult
                ds = result.dataset if isinstance(result, ScanResult) else result
                self._dataset = ds
                browser.load_dataset(ds)
                stats_label.setText(f"{ds.total_images} 图片 · {len(ds.categories)} 类")

                # Push dataset to all existing workspaces
                for name_key, (wrapper, _) in self._workspaces.items():
                    if name_key != "data_source":
                        for child in wrapper.findChildren(QWidget):
                            if hasattr(child, "set_dataset"):
                                child.set_dataset(ds)

            def on_fail(msg):
                container._scan_worker = None
                progress.accept()
                open_btn.setEnabled(True)
                stats_label.setText(f"失败: {msg}")

            worker.progress.connect(on_progress)
            worker.finished_ok.connect(on_done)
            worker.failed.connect(on_fail)
            worker.start()

        open_btn.clicked.connect(_on_open)

        def _rescan():
            """Re-scan the current directory after file ops (delete/rename/move)."""
            if not self._dataset:
                return
            root = self._dataset.root_path
            worker = ScanWorker(root, parent=container)
            container._scan_worker = worker

            def _done(result):
                container._scan_worker = None
                from gui.workers.scan_worker import ScanResult
                ds = result.dataset if isinstance(result, ScanResult) else result
                self._dataset = ds
                browser.load_dataset(ds)
                stats_label.setText(f"{ds.total_images} 图片 · {len(ds.categories)} 类")
                for name_key, (wrapper, _) in self._workspaces.items():
                    if name_key != "data_source":
                        for child in wrapper.findChildren(QWidget):
                            if hasattr(child, "set_dataset"):
                                child.set_dataset(ds)

            def _fail(msg):
                container._scan_worker = None

            worker.finished_ok.connect(_done)
            worker.failed.connect(_fail)
            worker.start()

        browser.dataset_changed.connect(_rescan)

        if self._dataset:
            browser.load_dataset(self._dataset)
            path_label.setText(str(self._dataset.root_path))
            stats_label.setText(f"{self._dataset.total_images} 图片 · {len(self._dataset.categories)} 类")

        return container

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

        # Cache results for workspace views
        self._node_results = result.node_results

        for nid, record in result.node_results.items():
            node_item = self._canvas.node_by_id(nid)
            if node_item:
                node_item.set_state("done" if record.success else "error")
                # Show concise result on the node
                sr = record.step_result
                if sr and record.success:
                    parts = []
                    if sr.ok_count:
                        parts.append(f"{sr.ok_count} 通过")
                    if sr.fail_count:
                        parts.append(f"{sr.fail_count} 问题")
                    node_item.set_status(" · ".join(parts) if parts else record.message)
                else:
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
