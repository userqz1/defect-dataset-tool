"""数据清洗 — 质量检查 + 重复检测 合并为一个紧凑页面。

上半区：质量检查（模糊/空白/过曝/损坏）
下半区：重复检测（pHash 相似度）
共享操作：选中结果 → 删除到回收站
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    DoubleSpinBox,
    InfoBar,
    InfoBarPosition,
    MessageBox,
    PrimaryPushButton,
    PushButton,
    SpinBox,
    StrongBodyLabel,
    SubtitleLabel,
)

from core import fileops
from core.dedup import DuplicateGroup, find_duplicates
from core.models import Dataset
from core.quality import QualityIssue, QualityOptions, check_images
from gui.theme import T
from gui.workers.batch_worker import BatchWorker

KIND_LABEL = {"corrupt": "损坏", "blank": "空白", "blur": "模糊", "over": "过曝", "under": "欠曝"}


class CleaningView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("cleaningView")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._dataset: Dataset | None = None
        self._quality_worker: BatchWorker | None = None
        self._dedup_worker: BatchWorker | None = None
        self._progress = None

        root = QVBoxLayout(self)
        root.setContentsMargins(T.PAD_2XL, T.PAD_2XL - 4, T.PAD_2XL, T.PAD_XL)
        root.setSpacing(T.GAP_LG)

        root.addWidget(SubtitleLabel("数据清洗"))

        splitter = QSplitter(Qt.Orientation.Vertical)

        # ============ 上半区：质量检查 ============
        quality_panel = QFrame()
        quality_panel.setObjectName("chartFrame")
        ql = QVBoxLayout(quality_panel)
        ql.setContentsMargins(T.PAD_XL, T.PAD_LG, T.PAD_XL, T.PAD_LG)
        ql.setSpacing(T.GAP)

        q_header = QHBoxLayout()
        q_header.addWidget(StrongBodyLabel("质量检查"))
        q_header.addStretch(1)

        q_header.addWidget(CaptionLabel("模糊阈值"))
        self.blur_spin = DoubleSpinBox()
        self.blur_spin.setRange(1, 5000)
        self.blur_spin.setValue(100)
        self.blur_spin.setFixedWidth(100)
        self.blur_spin.setToolTip("Laplacian 方差，越小越模糊")
        q_header.addWidget(self.blur_spin)

        self.quality_btn = PrimaryPushButton("开始检查")
        self.quality_btn.setFixedWidth(100)
        self.quality_btn.clicked.connect(self._on_quality_start)
        self.quality_btn.setEnabled(False)
        q_header.addWidget(self.quality_btn)
        ql.addLayout(q_header)

        self.quality_summary = CaptionLabel("")
        ql.addWidget(self.quality_summary)

        self.quality_list = QListWidget()
        self.quality_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        ql.addWidget(self.quality_list, 1)

        q_actions = QHBoxLayout()
        q_actions.addStretch(1)
        q_sel_btn = PushButton("全选")
        q_sel_btn.clicked.connect(self.quality_list.selectAll)
        q_actions.addWidget(q_sel_btn)
        q_del_btn = PushButton("删除选中")
        q_del_btn.clicked.connect(lambda: self._delete_selected(self.quality_list))
        q_actions.addWidget(q_del_btn)
        ql.addLayout(q_actions)

        splitter.addWidget(quality_panel)

        # ============ 下半区：重复检测 ============
        dedup_panel = QFrame()
        dedup_panel.setObjectName("chartFrame")
        dl = QVBoxLayout(dedup_panel)
        dl.setContentsMargins(T.PAD_XL, T.PAD_LG, T.PAD_XL, T.PAD_LG)
        dl.setSpacing(T.GAP)

        d_header = QHBoxLayout()
        d_header.addWidget(StrongBodyLabel("重复检测"))
        d_header.addStretch(1)

        d_header.addWidget(CaptionLabel("相似阈值"))
        self.threshold_spin = SpinBox()
        self.threshold_spin.setRange(0, 20)
        self.threshold_spin.setValue(5)
        self.threshold_spin.setFixedWidth(100)
        self.threshold_spin.setToolTip("0=完全相同  5=视觉近似  越大越宽松")
        d_header.addWidget(self.threshold_spin)

        self.dedup_btn = PrimaryPushButton("开始检测")
        self.dedup_btn.setFixedWidth(100)
        self.dedup_btn.clicked.connect(self._on_dedup_start)
        self.dedup_btn.setEnabled(False)
        d_header.addWidget(self.dedup_btn)
        dl.addLayout(d_header)

        self.dedup_summary = CaptionLabel("")
        dl.addWidget(self.dedup_summary)

        self.dedup_list = QListWidget()
        dl.addWidget(self.dedup_list, 1)

        splitter.addWidget(dedup_panel)

        root.addWidget(splitter, 1)

    def set_dataset(self, dataset: Dataset | None) -> None:
        self._dataset = dataset
        n = sum(c.image_count for c in dataset.categories) if dataset else 0
        on = n > 0
        self.quality_btn.setEnabled(on)
        self.dedup_btn.setEnabled(on)
        self.quality_summary.setText(f"待检查：{n:,} 张图片" if on else "")
        self.dedup_summary.setText(f"待检测：{n:,} 张图片" if on else "")
        self.quality_list.clear()
        self.dedup_list.clear()
        if on:
            self._add_placeholder(self.quality_list, "点击「执行流程」运行质量检测")
            self._add_placeholder(self.dedup_list, "点击「执行流程」查找重复图片")

    def set_results(self, input_data, step_result) -> None:
        """Display pipeline execution results (called after pipeline Run)."""
        if step_result is None:
            return
        issues = step_result.details
        if isinstance(issues, list) and all(hasattr(i, "kinds") for i in issues[:1]):
            # Quality check results
            self._on_quality_done(issues)

    @staticmethod
    def _add_placeholder(lst: QListWidget, text: str) -> None:
        item = QListWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        item.setForeground(QColor(T.TEXT_3))
        lst.addItem(item)

    # ---- 质量检查 ----

    def _on_quality_start(self) -> None:
        if self._dataset is None or self._quality_worker is not None:
            return
        all_images = [img for c in self._dataset.categories for img in c.images]
        opts = QualityOptions(blur_threshold=self.blur_spin.value())

        from gui.dialogs.op_dialogs import ProgressDialog
        self._progress = ProgressDialog("质量检查", parent=self.window())

        def task(cb):
            return check_images(all_images, opts=opts, progress_cb=cb)

        self._quality_worker = BatchWorker(task)
        self._quality_worker.progress.connect(self._on_progress)
        self._quality_worker.finished_ok.connect(self._on_quality_done)
        self._quality_worker.failed.connect(self._on_quality_failed)
        self._quality_worker.start()
        self._progress.show()
        self.quality_btn.setEnabled(False)

    def _on_quality_done(self, issues: list[QualityIssue]) -> None:
        self._close_progress()
        self._quality_worker = None
        self.quality_btn.setEnabled(True)
        self.quality_list.clear()
        if not issues:
            self.quality_summary.setText("未发现质量问题 ✓")
            return
        self.quality_summary.setText(f"发现 {len(issues)} 张问题图片")
        for issue in issues:
            tags = " · ".join(KIND_LABEL.get(k, k) for k in issue.kinds)
            text = f"[{tags}]  {issue.image.category} / {issue.image.path.name}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, issue.image)
            self.quality_list.addItem(item)

    def _on_quality_failed(self, msg: str) -> None:
        self._close_progress()
        self._quality_worker = None
        self.quality_btn.setEnabled(True)
        self.quality_summary.setText(f"检查失败：{msg}")

    # ---- 重复检测 ----

    def _on_dedup_start(self) -> None:
        if self._dataset is None or self._dedup_worker is not None:
            return
        all_images = [img for c in self._dataset.categories for img in c.images]
        threshold = self.threshold_spin.value()

        from gui.dialogs.op_dialogs import ProgressDialog
        self._progress = ProgressDialog("重复检测", parent=self.window())

        def task(cb):
            return find_duplicates(all_images, threshold=threshold, progress_cb=cb)

        self._dedup_worker = BatchWorker(task)
        self._dedup_worker.progress.connect(self._on_progress)
        self._dedup_worker.finished_ok.connect(self._on_dedup_done)
        self._dedup_worker.failed.connect(self._on_dedup_failed)
        self._dedup_worker.start()
        self._progress.show()
        self.dedup_btn.setEnabled(False)

    def _on_dedup_done(self, groups: list[DuplicateGroup]) -> None:
        self._close_progress()
        self._dedup_worker = None
        self.dedup_btn.setEnabled(True)
        self.dedup_list.clear()
        if not groups:
            self.dedup_summary.setText("未发现重复图片 ✓")
            return
        total = sum(g.size for g in groups)
        self.dedup_summary.setText(f"发现 {len(groups)} 组相似图片，共 {total} 张")
        for i, g in enumerate(groups, 1):
            head = QListWidgetItem(f"组 {i}  ·  {g.size} 张")
            head.setFlags(head.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            f = head.font()
            f.setBold(True)
            head.setFont(f)
            self.dedup_list.addItem(head)
            for img in g.images:
                self.dedup_list.addItem(f"    {img.category} / {img.path.name}")

    def _on_dedup_failed(self, msg: str) -> None:
        self._close_progress()
        self._dedup_worker = None
        self.dedup_btn.setEnabled(True)
        self.dedup_summary.setText(f"检测失败：{msg}")

    # ---- 共享 ----

    def _on_progress(self, done: int, total: int, name: str) -> None:
        if self._progress:
            self._progress.set_progress(done, total, name)

    def _close_progress(self) -> None:
        if self._progress is not None:
            self._progress.accept()
            self._progress = None

    def _delete_selected(self, list_widget: QListWidget) -> None:
        items = list_widget.selectedItems()
        if not items:
            return
        sel_imgs = [it.data(Qt.ItemDataRole.UserRole) for it in items
                    if it.data(Qt.ItemDataRole.UserRole) is not None]
        if not sel_imgs:
            return
        box = MessageBox(
            "确认删除",
            f"将 {len(sel_imgs)} 个图片+标注移至回收站？",
            self.window(),
        )
        if not box.exec():
            return
        result = fileops.delete_pairs(sel_imgs, to_trash=True)
        ok_paths = set(result.succeeded)
        for it in items:
            img = it.data(Qt.ItemDataRole.UserRole)
            if img and img.path in ok_paths:
                list_widget.takeItem(list_widget.row(it))
        InfoBar.success(
            title="已删除", content=f"成功 {result.ok_count} · 失败 {result.fail_count}",
            isClosable=True, position=InfoBarPosition.TOP,
            duration=3000, parent=self.window(),
        )
