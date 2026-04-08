"""数据处理 / 质量检查：检测模糊 / 过曝 / 空白 / 损坏图像。"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QListWidget, QListWidgetItem, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    DoubleSpinBox,
    InfoBar,
    InfoBarPosition,
    MessageBox,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
)

from core import fileops
from core.models import Dataset
from core.quality import QualityIssue, QualityOptions, check_images
from gui.theme import T
from gui.workers.batch_worker import BatchWorker

KIND_LABEL = {
    "corrupt": "损坏",
    "blank": "空白",
    "blur": "模糊",
    "over": "过曝",
    "under": "欠曝",
}


class QualityView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("qualityView")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._dataset: Dataset | None = None
        self._worker: BatchWorker | None = None
        self._progress = None

        root = QVBoxLayout(self)
        root.setContentsMargins(T.PAD_XL + 12, T.PAD_XL + 8, T.PAD_XL + 12, T.PAD_XL)
        root.setSpacing(T.GAP_LG)

        root.addWidget(SubtitleLabel("质量检查"))
        root.addWidget(CaptionLabel("检测模糊 / 空白 / 过曝 / 欠曝 / 损坏图像"))

        ctrl = QHBoxLayout()
        ctrl.setSpacing(T.GAP_LG)
        ctrl.addWidget(BodyLabel("模糊阈值"))
        self.blur_spin = DoubleSpinBox()
        self.blur_spin.setRange(1, 5000)
        self.blur_spin.setValue(100)
        self.blur_spin.setFixedWidth(120)
        ctrl.addWidget(self.blur_spin)
        ctrl.addWidget(CaptionLabel("Laplacian 方差，越小越模糊"))
        ctrl.addStretch(1)
        self.start_btn = PrimaryPushButton("开始检查")
        self.start_btn.clicked.connect(self._on_start)
        self.start_btn.setEnabled(False)
        ctrl.addWidget(self.start_btn)
        root.addLayout(ctrl)

        self.summary_label = BodyLabel("")
        root.addWidget(self.summary_label)

        self.result_list = QListWidget()
        self.result_list.setObjectName("qualityResultList")
        self.result_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        root.addWidget(self.result_list, 1)

        action_row = QHBoxLayout()
        action_row.addStretch(1)
        self.select_all_btn = PushButton("全选")
        self.select_all_btn.clicked.connect(self.result_list.selectAll)
        action_row.addWidget(self.select_all_btn)
        self.delete_btn = PushButton("删除选中(回收站)")
        self.delete_btn.clicked.connect(self._on_delete_selected)
        action_row.addWidget(self.delete_btn)
        root.addLayout(action_row)

    def set_dataset(self, dataset: Dataset | None) -> None:
        self._dataset = dataset
        if dataset is None:
            self.start_btn.setEnabled(False)
            self.summary_label.setText("请先加载数据集。")
            self.result_list.clear()
            return
        n = sum(c.image_count for c in dataset.categories)
        self.start_btn.setEnabled(n > 0)
        self.summary_label.setText(f"待检查：{n:,} 张图片")
        self.result_list.clear()

    def _on_start(self) -> None:
        if self._dataset is None or self._worker is not None:
            return
        all_images = [img for c in self._dataset.categories for img in c.images]
        opts = QualityOptions(blur_threshold=self.blur_spin.value())

        from gui.dialogs.op_dialogs import ProgressDialog
        self._progress = ProgressDialog("质量检查", parent=self.window())

        def task(progress_cb):
            return check_images(all_images, opts=opts, progress_cb=progress_cb)

        self._worker = BatchWorker(task)
        self._worker.progress.connect(
            lambda d, t, n: self._progress and self._progress.set_progress(d, t, n)
        )
        self._worker.finished_ok.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()
        self._progress.show()
        self.start_btn.setEnabled(False)

    def _on_done(self, issues: list[QualityIssue]) -> None:
        self._close_progress()
        self._worker = None
        self.start_btn.setEnabled(True)
        self.result_list.clear()
        if not issues:
            self.summary_label.setText("未发现质量问题 ✓")
            return
        self.summary_label.setText(f"发现 {len(issues)} 张存在问题的图片")
        for issue in issues:
            tags = " · ".join(KIND_LABEL.get(k, k) for k in issue.kinds)
            text = f"[{tags}]  {issue.image.category} / {issue.image.path.name}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, issue.image)
            self.result_list.addItem(item)

    def _on_failed(self, msg: str) -> None:
        self._close_progress()
        self._worker = None
        self.start_btn.setEnabled(True)
        self.summary_label.setText(f"检查失败：{msg}")

    def _on_delete_selected(self) -> None:
        items = self.result_list.selectedItems()
        if not items:
            return
        sel_imgs = [it.data(Qt.ItemDataRole.UserRole) for it in items]
        box = MessageBox(
            "确认删除",
            f"将 {len(sel_imgs)} 个图片+标注移至回收站,是否继续?",
            self.window(),
        )
        if not box.exec():
            return
        result = fileops.delete_pairs(sel_imgs, to_trash=True)
        # 从列表移除成功项
        ok_paths = set(result.succeeded)
        for it in items:
            img = it.data(Qt.ItemDataRole.UserRole)
            if img.path in ok_paths:
                self.result_list.takeItem(self.result_list.row(it))
        InfoBar.success(
            title="已删除", content=f"成功 {result.ok_count}  ·  失败 {result.fail_count}",
            isClosable=True, position=InfoBarPosition.TOP,
            duration=3000, parent=self.window(),
        )

    def _close_progress(self) -> None:
        if self._progress is not None:
            self._progress.accept()
            self._progress = None
