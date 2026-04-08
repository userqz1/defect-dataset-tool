"""数据处理 / 重复检测：基于 pHash 找出重复 / 近似图片。

UI 布局：
    顶部：标题 + 副标题 + 阈值滑块 + 「开始检测」按钮
    主体：分组结果列表（每组一行：组内图片数 + 文件路径列表）
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    PrimaryPushButton,
    SpinBox,
    StrongBodyLabel,
    SubtitleLabel,
)

from core.dedup import DuplicateGroup, find_duplicates
from core.models import Dataset
from gui.theme import T
from gui.workers.batch_worker import BatchWorker


class DedupView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("dedupView")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._dataset: Dataset | None = None
        self._worker: BatchWorker | None = None
        self._progress = None  # ProgressDialog

        root = QVBoxLayout(self)
        root.setContentsMargins(T.PAD_XL + 12, T.PAD_XL + 8, T.PAD_XL + 12, T.PAD_XL)
        root.setSpacing(T.GAP_LG)

        # 标题
        root.addWidget(SubtitleLabel("重复检测"))
        root.addWidget(CaptionLabel("基于感知哈希 (pHash) 发现重复或近似的图片"))

        # 控制条
        controls = QFrame()
        controls.setObjectName("dedupControls")
        ctrl_layout = QHBoxLayout(controls)
        ctrl_layout.setContentsMargins(0, T.GAP_LG, 0, T.GAP_LG)
        ctrl_layout.setSpacing(T.GAP_LG)

        ctrl_layout.addWidget(BodyLabel("相似度阈值"))
        self.threshold_spin = SpinBox()
        self.threshold_spin.setRange(0, 20)
        self.threshold_spin.setValue(5)
        self.threshold_spin.setFixedWidth(120)
        ctrl_layout.addWidget(self.threshold_spin)
        ctrl_layout.addWidget(
            CaptionLabel("0 = 完全相同  ·  5 = 视觉近似  ·  越大越宽松")
        )
        ctrl_layout.addStretch(1)

        self.start_btn = PrimaryPushButton("开始检测")
        self.start_btn.clicked.connect(self._on_start)
        self.start_btn.setEnabled(False)
        ctrl_layout.addWidget(self.start_btn)

        root.addWidget(controls)

        # 结果区
        self.summary_label = BodyLabel("")
        root.addWidget(self.summary_label)

        self.result_list = QListWidget()
        self.result_list.setObjectName("dedupResultList")
        root.addWidget(self.result_list, 1)

    # ---------- 接口 ----------

    def set_dataset(self, dataset: Dataset | None) -> None:
        self._dataset = dataset
        if dataset is None:
            self.start_btn.setEnabled(False)
            self.summary_label.setText("请先从顶部加载数据集。")
            self.result_list.clear()
            return
        n = sum(c.image_count for c in dataset.categories)
        self.start_btn.setEnabled(n > 0)
        self.summary_label.setText(f"待检测：{n:,} 张图片  ·  点击「开始检测」运行")
        self.result_list.clear()

    # ---------- 内部 ----------

    def _on_start(self) -> None:
        if self._dataset is None or self._worker is not None:
            return
        all_images = [img for c in self._dataset.categories for img in c.images]
        threshold = self.threshold_spin.value()

        from gui.dialogs.op_dialogs import ProgressDialog
        self._progress = ProgressDialog("重复检测", parent=self.window())
        self._progress.label.setText("计算 pHash …")

        def task(progress_cb):
            return find_duplicates(all_images, threshold=threshold, progress_cb=progress_cb)

        self._worker = BatchWorker(task)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()
        self._progress.show()
        self.start_btn.setEnabled(False)

    def _on_progress(self, done: int, total: int, name: str) -> None:
        if self._progress is not None:
            self._progress.set_progress(done, total, name)

    def _on_done(self, groups: list[DuplicateGroup]) -> None:
        self._close_progress()
        self._worker = None
        self.start_btn.setEnabled(True)
        self._render_groups(groups)

    def _on_failed(self, msg: str) -> None:
        self._close_progress()
        self._worker = None
        self.start_btn.setEnabled(True)
        self.summary_label.setText(f"检测失败：{msg}")

    def _close_progress(self) -> None:
        if self._progress is not None:
            self._progress.accept()
            self._progress = None

    def _render_groups(self, groups: list[DuplicateGroup]) -> None:
        self.result_list.clear()
        if not groups:
            self.summary_label.setText("未发现重复或近似图片。")
            return
        total_dup = sum(g.size for g in groups)
        self.summary_label.setText(
            f"发现 {len(groups)} 组相似图片，共 {total_dup} 张"
        )
        for i, g in enumerate(groups, 1):
            head = QListWidgetItem(f"组 {i}  ·  {g.size} 张  ·  hash={g.hash_value}")
            head.setFlags(head.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            f = head.font()
            f.setBold(True)
            head.setFont(f)
            self.result_list.addItem(head)
            for img in g.images:
                item = QListWidgetItem(f"    {img.category}  /  {img.path.name}")
                item.setData(Qt.ItemDataRole.UserRole, img)
                self.result_list.addItem(item)
