"""Pipeline view — OdenGraphQt node editor as the central workspace.

Uses OdenGraphQt for the canvas (zoom/pan/connections/properties)
and wraps it in a QWidget for integration with FluentWindow.
"""
from __future__ import annotations

import os
os.environ.setdefault("QT_API", "pyqt6")

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from qfluentwidgets import (
    FluentIcon as FIF,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    StrongBodyLabel,
)

from core.models import Dataset
from gui.theme import T


class PipelineView(QWidget):
    """Node canvas workspace backed by OdenGraphQt."""

    dataset_changed = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("pipelineView")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._dataset: Dataset | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- Top bar ----
        topbar = QWidget()
        topbar.setFixedHeight(44)
        top_layout = QHBoxLayout(topbar)
        top_layout.setContentsMargins(T.PAD_LG, 0, T.PAD_LG, 0)
        top_layout.setSpacing(T.GAP_LG)

        self._title = StrongBodyLabel("工作台")
        top_layout.addWidget(self._title)
        top_layout.addStretch(1)

        run_btn = PrimaryPushButton("执行")
        run_btn.setIcon(FIF.PLAY)
        run_btn.clicked.connect(self._on_run)
        top_layout.addWidget(run_btn)
        root.addWidget(topbar)

        # ---- Node Graph (OdenGraphQt) ----
        from gui.widgets.node_editor import create_graph
        self._graph = create_graph()

        # Embed the graph viewer widget into our layout
        graph_widget = self._graph.widget
        root.addWidget(graph_widget, 1)

        # Connect signals
        self._graph.node_double_clicked.connect(self._on_node_double_clicked)

    # ---- Public API ----

    def set_dataset(self, dataset: Dataset | None) -> None:
        self._dataset = dataset

    def set_task_type(self, task_type) -> None:
        self._task_type = task_type

    def add_node(self, node_id: str) -> None:
        """Add a node to the canvas from the sidebar."""
        from gui.widgets.node_editor import NODE_ID_TO_TYPE
        type_str = NODE_ID_TO_TYPE.get(node_id)
        if not type_str:
            return
        n = len(self._graph.all_nodes())
        self._graph.create_node(
            type_str,
            pos=[150 + n * 260, 200],
        )

    def clear(self) -> None:
        self._graph.clear_session()

    # ---- Internal ----

    def _on_node_double_clicked(self, node_id) -> None:
        node = self._graph.get_node_by_id(node_id)
        if node:
            InfoBar.info(node.name(), "", parent=self.window(),
                         duration=1500, position=InfoBarPosition.TOP)

    def _on_run(self) -> None:
        nodes = self._graph.all_nodes()
        if not nodes:
            InfoBar.warning("", "画布上没有节点", parent=self.window(),
                            duration=2000, position=InfoBarPosition.TOP)
            return
        names = [n.name() for n in nodes]
        InfoBar.success("执行", f"{len(names)} 个节点: {' → '.join(names)}",
                        parent=self.window(), duration=3000,
                        position=InfoBarPosition.TOP)
