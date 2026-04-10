"""Pipeline view — visual step-by-step data processing editor.

Users add processing nodes (clean, augment, split) as step cards,
configure each step's parameters, and execute the pipeline.
Backed by core/nodes.py ProcessingNode abstraction.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CheckBox,
    ComboBox,
    DoubleSpinBox,
    FluentIcon as FIF,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    PushButton,
    SpinBox,
    StrongBodyLabel,
    SubtitleLabel,
    ToolButton,
)

from core.models import Dataset
from core.nodes import NODES, ProcessingNode, StepResult
from gui.theme import T
from gui.workers.batch_worker import BatchWorker


# ---------- Step Card ----------

class _StepCard(QFrame):
    """A single processing step in the pipeline."""

    removed = pyqtSignal(object)  # self

    def __init__(self, node: ProcessingNode, index: int, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("chartFrame")
        self.node = node
        self._index = index
        self._options: dict = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(T.PAD_LG, T.PAD, T.PAD_LG, T.PAD)
        layout.setSpacing(T.GAP)

        # Header: index + name + remove button
        header = QHBoxLayout()
        header.setSpacing(T.GAP)
        self._title = StrongBodyLabel(f"{index}. {node.display_name}")
        header.addWidget(self._title)
        self._status = CaptionLabel("")
        header.addWidget(self._status)
        header.addStretch(1)

        remove_btn = ToolButton(FIF.DELETE)
        remove_btn.setToolTip("移除此步骤")
        remove_btn.clicked.connect(lambda: self.removed.emit(self))
        header.addWidget(remove_btn)
        layout.addLayout(header)

        # Parameters (node-specific)
        self._build_params(layout)

    def set_index(self, idx: int) -> None:
        self._index = idx
        self._title.setText(f"{idx}. {self.node.display_name}")

    def set_status(self, text: str) -> None:
        self._status.setText(text)

    def get_options(self) -> dict:
        return dict(self._options)

    def _build_params(self, layout: QVBoxLayout) -> None:
        name = self.node.name

        if name == "quality_check":
            row = QHBoxLayout()
            row.addWidget(CaptionLabel("模糊阈值"))
            spin = DoubleSpinBox()
            spin.setRange(1, 5000)
            spin.setValue(100)
            spin.setFixedWidth(100)
            spin.setToolTip("Laplacian 方差，越小越模糊")
            spin.valueChanged.connect(lambda v: self._options.update(blur_threshold=v))
            self._options["blur_threshold"] = 100
            row.addWidget(spin)
            row.addStretch(1)
            layout.addLayout(row)

        elif name == "dedup":
            row = QHBoxLayout()
            row.addWidget(CaptionLabel("相似阈值"))
            spin = SpinBox()
            spin.setRange(0, 20)
            spin.setValue(5)
            spin.setFixedWidth(100)
            spin.setToolTip("0=完全相同 5=视觉近似 越大越宽松")
            spin.valueChanged.connect(lambda v: self._options.update(threshold=v))
            self._options["threshold"] = 5
            row.addWidget(spin)
            row.addStretch(1)
            layout.addLayout(row)

        elif name == "augment":
            # Geometric transforms
            geo = QHBoxLayout()
            geo.setSpacing(T.GAP_LG)
            self._flip_h = CheckBox("水平翻转")
            self._flip_h.setChecked(True)
            self._flip_v = CheckBox("垂直翻转")
            self._rot = CheckBox("旋转90°")
            self._crop = CheckBox("随机裁剪")
            geo.addWidget(self._flip_h)
            geo.addWidget(self._flip_v)
            geo.addWidget(self._rot)
            geo.addWidget(self._crop)
            geo.addStretch(1)
            layout.addLayout(geo)

            # Count
            n_row = QHBoxLayout()
            n_row.addWidget(CaptionLabel("每张生成"))
            self._n_spin = SpinBox()
            self._n_spin.setRange(1, 50)
            self._n_spin.setValue(3)
            self._n_spin.setFixedWidth(80)
            n_row.addWidget(self._n_spin)
            n_row.addWidget(CaptionLabel("张"))
            n_row.addStretch(1)
            layout.addLayout(n_row)

        elif name == "split":
            row = QHBoxLayout()
            row.setSpacing(T.GAP_LG)
            row.addWidget(CaptionLabel("Train"))
            self._train = DoubleSpinBox()
            self._train.setRange(0, 1)
            self._train.setValue(0.8)
            self._train.setSingleStep(0.05)
            self._train.setFixedWidth(80)
            row.addWidget(self._train)
            row.addWidget(CaptionLabel("Val"))
            self._val = DoubleSpinBox()
            self._val.setRange(0, 1)
            self._val.setValue(0.1)
            self._val.setSingleStep(0.05)
            self._val.setFixedWidth(80)
            row.addWidget(self._val)
            row.addWidget(CaptionLabel("Test"))
            self._test = DoubleSpinBox()
            self._test.setRange(0, 1)
            self._test.setValue(0.1)
            self._test.setSingleStep(0.05)
            self._test.setFixedWidth(80)
            row.addWidget(self._test)
            row.addStretch(1)
            layout.addLayout(row)

    def collect_options(self) -> dict:
        """Gather current parameter values from UI widgets."""
        name = self.node.name
        if name == "quality_check":
            return dict(self._options)
        elif name == "dedup":
            return dict(self._options)
        elif name == "augment":
            return {
                "flip_h": self._flip_h.isChecked(),
                "flip_v": self._flip_v.isChecked(),
                "rotate90": self._rot.isChecked(),
                "random_crop": self._crop.isChecked(),
                "n_per_image": self._n_spin.value(),
            }
        elif name == "split":
            return {
                "train": self._train.value(),
                "val": self._val.value(),
                "test": self._test.value(),
            }
        return {}


# ---------- Arrow connector ----------

class _Arrow(QWidget):
    """Thin vertical arrow between step cards."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(24)

    def paintEvent(self, event):
        from PyQt6.QtGui import QPainter, QPen, QColor
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(T.BORDER), 2)
        p.setPen(pen)
        cx = self.width() // 2
        p.drawLine(cx, 0, cx, self.height() - 6)
        # Arrow head
        p.drawLine(cx - 4, self.height() - 10, cx, self.height() - 4)
        p.drawLine(cx + 4, self.height() - 10, cx, self.height() - 4)
        p.end()


# ---------- Pipeline View ----------

class PipelineView(QWidget):
    """Visual pipeline editor — add/remove/configure processing steps."""

    dataset_changed = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("pipelineView")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._dataset: Dataset | None = None
        self._steps: list[_StepCard] = []
        self._worker: BatchWorker | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        self._root = QVBoxLayout(container)
        self._root.setContentsMargins(T.PAD_2XL, T.PAD_2XL - 4, T.PAD_2XL, T.PAD_XL)
        self._root.setSpacing(0)
        scroll.setWidget(container)
        outer.addWidget(scroll)

        # Title
        self._root.addWidget(SubtitleLabel("数据处理"))

        # ---- 格子：目标格式需要什么 ----
        self._grid_frame = QFrame()
        self._grid_frame.setObjectName("chartFrame")
        grid_layout = QVBoxLayout(self._grid_frame)
        grid_layout.setContentsMargins(T.PAD_LG, T.PAD, T.PAD_LG, T.PAD)
        grid_layout.setSpacing(T.GAP)

        grid_header = QHBoxLayout()
        self._format_label = StrongBodyLabel("目标格式")
        grid_header.addWidget(self._format_label)
        grid_header.addStretch(1)
        self._grid_status = CaptionLabel("")
        grid_header.addWidget(self._grid_status)
        grid_layout.addLayout(grid_header)

        self._grid_slots_layout = QVBoxLayout()
        self._grid_slots_layout.setSpacing(T.GAP_XS)
        grid_layout.addLayout(self._grid_slots_layout)
        self._grid_slot_widgets: list[QWidget] = []

        self._root.addWidget(self._grid_frame)
        self._root.addSpacing(T.GAP_XL)

        # ---- 节点：往格子里塞东西 ----
        self._root.addWidget(StrongBodyLabel("处理节点"))

        # Add step button
        add_row = QHBoxLayout()
        add_row.setSpacing(T.GAP)
        self._add_combo = ComboBox()
        self._add_combo.addItems([n.display_name for n in NODES.values()])
        add_row.addWidget(self._add_combo)
        add_btn = PushButton("添加步骤")
        add_btn.setIcon(FIF.ADD)
        add_btn.clicked.connect(self._on_add_step)
        add_row.addWidget(add_btn)
        add_row.addStretch(1)
        self._root.addLayout(add_row)

        # Steps container
        self._steps_layout = QVBoxLayout()
        self._steps_layout.setSpacing(0)
        self._steps_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._root.addLayout(self._steps_layout)

        # Bottom controls
        self._root.addSpacing(T.GAP_XL)
        ctrl = QHBoxLayout()
        self._summary = CaptionLabel("")
        ctrl.addWidget(self._summary, 1)
        self._run_btn = PrimaryPushButton("执行全部")
        self._run_btn.setIcon(FIF.PLAY)
        self._run_btn.setEnabled(False)
        self._run_btn.clicked.connect(self._on_run_all)
        ctrl.addWidget(self._run_btn)
        self._root.addLayout(ctrl)

        self._root.addStretch(1)

    def set_dataset(self, dataset: Dataset | None) -> None:
        self._dataset = dataset
        self._run_btn.setEnabled(dataset is not None and len(self._steps) > 0)
        if dataset:
            n = sum(c.image_count for c in dataset.categories)
            self._summary.setText(f"数据集: {n:,} 张图片")
        else:
            self._summary.setText("")
        self._refresh_grid()

    def set_task_type(self, task_type) -> None:
        self._task_type = task_type
        # Determine default format for this task type
        from core.task_types import TASK_REGISTRY
        info = TASK_REGISTRY.get(task_type)
        if info and info.export_formats:
            self._target_format = info.export_formats[0]
        else:
            self._target_format = "YOLO"
        self._refresh_grid()

    def _refresh_grid(self) -> None:
        """Rebuild the grid slots display based on current dataset + target format."""
        from core.format_grid import build_grid

        fmt = getattr(self, "_target_format", "YOLO")
        grid = build_grid(fmt, self._dataset)

        # Update header
        self._format_label.setText(f"目标: {grid.format_name}")
        if grid.ready:
            self._grid_status.setText(f"✓ 就绪 ({grid.progress_text})")
            self._grid_status.setObjectName("readinessOk")
        else:
            self._grid_status.setText(f"✗ {grid.progress_text} 项就绪")
            self._grid_status.setObjectName("readinessGap")
        self._grid_status.style().unpolish(self._grid_status)
        self._grid_status.style().polish(self._grid_status)

        # Rebuild slot rows
        for w in self._grid_slot_widgets:
            self._grid_slots_layout.removeWidget(w)
            w.deleteLater()
        self._grid_slot_widgets.clear()

        for slot in grid.slots:
            row = QHBoxLayout()
            icon = CaptionLabel(slot.icon)
            icon.setObjectName("readinessOk" if slot.filled else "readinessGap")
            icon.setFixedWidth(20)
            row.addWidget(icon)

            name = CaptionLabel(slot.name)
            name.setFixedWidth(160)
            row.addWidget(name)

            status = CaptionLabel(slot.status_text)
            row.addWidget(status)
            row.addStretch(1)

            wrapper = QWidget()
            wrapper.setLayout(row)
            self._grid_slots_layout.addWidget(wrapper)
            self._grid_slot_widgets.append(wrapper)

    def _on_add_step(self) -> None:
        idx = self._add_combo.currentIndex()
        node_name = list(NODES.keys())[idx]
        node = NODES[node_name]
        self._add_step_card(node)

    def _add_step_card(self, node: ProcessingNode) -> None:
        # Add arrow if not first step
        if self._steps:
            arrow = _Arrow()
            self._steps_layout.addWidget(arrow, alignment=Qt.AlignmentFlag.AlignHCenter)

        card = _StepCard(node, len(self._steps) + 1)
        card.removed.connect(self._on_remove_step)
        self._steps.append(card)
        self._steps_layout.addWidget(card)
        self._run_btn.setEnabled(self._dataset is not None)

    def _on_remove_step(self, card: _StepCard) -> None:
        idx = self._steps.index(card)
        self._steps.remove(card)

        # Remove card and its arrow from layout
        # Each step (except first) has an arrow before it
        # Layout order: [arrow0, card0, arrow1, card1, ...]
        # For step i>0: arrow at position 2*i-1, card at 2*i
        # For step 0: card at 0
        while self._steps_layout.count():
            item = self._steps_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Rebuild
        for i, s in enumerate(self._steps):
            if i > 0:
                self._steps_layout.addWidget(_Arrow(), alignment=Qt.AlignmentFlag.AlignHCenter)
            s.set_index(i + 1)
            self._steps_layout.addWidget(s)

        self._run_btn.setEnabled(self._dataset is not None and len(self._steps) > 0)

    def _on_run_all(self) -> None:
        if not self._dataset or not self._steps or self._worker:
            return

        from core.pipeline import PipelineContext, PipelineEngine
        from core.task_types import TaskType
        from gui.dialogs.op_dialogs import ProgressDialog

        task_type = getattr(self, "_task_type", TaskType.DETECTION)
        ctx = PipelineContext.from_dataset(self._dataset, task_type)

        engine = PipelineEngine()
        for card in self._steps:
            engine.add_step(card.node.name, card.collect_options())

        self._progress = ProgressDialog("执行处理流程", parent=self.window())
        self._progress.show()
        self._run_btn.setEnabled(False)

        def task(progress_cb):
            return engine.execute(ctx, progress_cb=progress_cb)

        self._worker = BatchWorker(task)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_pipeline_done)
        self._worker.failed.connect(self._on_pipeline_failed)
        self._worker.start()

    def _on_progress(self, done: int, total: int, name: str) -> None:
        if hasattr(self, "_progress") and self._progress:
            self._progress.set_progress(done, total, name)

    def _on_pipeline_done(self, result) -> None:
        self._worker = None
        if hasattr(self, "_progress") and self._progress:
            self._progress.close()
            self._progress = None
        self._run_btn.setEnabled(True)

        # Update step cards with results
        for record in result.step_results:
            for card in self._steps:
                if card.node.name == record.node_name:
                    card.set_status(record.message)

        if result.success:
            InfoBar.success(
                "完成",
                f"全部 {result.steps_run} 个步骤执行完成",
                parent=self.window(),
                duration=5000,
                position=InfoBarPosition.TOP,
            )
        else:
            InfoBar.error(
                "中断",
                result.error,
                parent=self.window(),
                duration=5000,
                position=InfoBarPosition.TOP,
            )

    def _on_pipeline_failed(self, msg: str) -> None:
        self._worker = None
        if hasattr(self, "_progress") and self._progress:
            self._progress.close()
            self._progress = None
        self._run_btn.setEnabled(True)
        InfoBar.error("执行失败", msg, parent=self.window(),
                      duration=5000, position=InfoBarPosition.TOP)
