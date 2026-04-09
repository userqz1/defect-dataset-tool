"""导出 / 导出向导：当前支持 YOLO。"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CheckBox,
    ComboBox,
    DoubleSpinBox,
    PrimaryPushButton,
    SubtitleLabel,
)

from core.exporter.coco import CocoExportOptions, export_coco
from core.exporter.voc import VocExportOptions, export_voc
from core.exporter.yolo import YoloExportOptions, export_yolo
from core.models import Dataset
from core.splitter import SplitOptions, split_dataset
from gui.theme import T
from gui.workers.batch_worker import BatchWorker


class ExportView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("exportView")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._dataset: Dataset | None = None
        self._worker: BatchWorker | None = None
        self._progress = None

        root = QVBoxLayout(self)
        root.setContentsMargins(T.PAD_XL + 12, T.PAD_XL + 8, T.PAD_XL + 12, T.PAD_XL)
        root.setSpacing(T.GAP_LG)

        root.addWidget(SubtitleLabel("导出向导"))
        root.addWidget(CaptionLabel("将当前数据集导出为训练框架可直接消费的格式"))

        grid = QGridLayout()
        grid.setHorizontalSpacing(T.GAP_LG)
        grid.setVerticalSpacing(T.GAP)

        grid.addWidget(BodyLabel("目标格式"), 0, 0)
        self.fmt_combo = ComboBox()
        self.fmt_combo.addItems(["YOLO", "COCO", "Pascal VOC"])
        grid.addWidget(self.fmt_combo, 0, 1)

        grid.addWidget(BodyLabel("Train / Val / Test"), 1, 0)
        ratio_row = QHBoxLayout()
        self.train_spin = DoubleSpinBox(); self.train_spin.setRange(0, 1); self.train_spin.setValue(0.8); self.train_spin.setSingleStep(0.05)
        self.val_spin = DoubleSpinBox(); self.val_spin.setRange(0, 1); self.val_spin.setValue(0.1); self.val_spin.setSingleStep(0.05)
        self.test_spin = DoubleSpinBox(); self.test_spin.setRange(0, 1); self.test_spin.setValue(0.1); self.test_spin.setSingleStep(0.05)
        for w in (self.train_spin, self.val_spin, self.test_spin):
            ratio_row.addWidget(w)
        ratio_row.addStretch(1)
        grid.addLayout(ratio_row, 1, 1)

        self.copy_chk = CheckBox("复制图片到导出目录（取消则只生成 labels）")
        self.copy_chk.setChecked(True)
        grid.addWidget(self.copy_chk, 2, 0, 1, 2)

        root.addLayout(grid)

        ctrl = QHBoxLayout()
        ctrl.addStretch(1)
        self.start_btn = PrimaryPushButton("选择目录并导出")
        self.start_btn.clicked.connect(self._on_start)
        self.start_btn.setEnabled(False)
        ctrl.addWidget(self.start_btn)
        root.addLayout(ctrl)

        self.summary_label = BodyLabel("")
        root.addWidget(self.summary_label)
        self.detail_label = CaptionLabel("")
        root.addWidget(self.detail_label)
        root.addStretch(1)

    def save_state(self):
        from core.project import ExportConfig
        return ExportConfig(
            format=self.fmt_combo.currentText(),
            copy_images=self.copy_chk.isChecked(),
        )

    def restore_state(self, state) -> None:
        if state is None:
            return
        idx = self.fmt_combo.findText(state.format)
        if idx >= 0:
            self.fmt_combo.setCurrentIndex(idx)
        self.copy_chk.setChecked(state.copy_images)

    def set_dataset(self, dataset: Dataset | None) -> None:
        self._dataset = dataset
        on = dataset is not None and sum(c.image_count for c in dataset.categories) > 0
        self.start_btn.setEnabled(on)
        if dataset is None:
            self.summary_label.setText("请先加载数据集。")
        else:
            n = sum(c.image_count for c in dataset.categories)
            self.summary_label.setText(f"将导出 {n:,} 张图片")

    def _on_start(self) -> None:
        if self._dataset is None or self._worker is not None:
            return
        out = QFileDialog.getExistingDirectory(self, "选择导出目录")
        if not out:
            return
        self._last_export_dir = out

        split = split_dataset(
            self._dataset,
            SplitOptions(
                train=self.train_spin.value(),
                val=self.val_spin.value(),
                test=self.test_spin.value(),
                stratified=True,
            ),
        )

        # Pre-export validation
        from gui.dialogs.export_validation_dialog import ExportValidationDialog
        dlg = ExportValidationDialog(split, self._dataset, parent=self.window())
        if not dlg.exec():
            return

        fmt = self.fmt_combo.currentText()
        copy = self.copy_chk.isChecked()
        if fmt == "YOLO":
            opts = YoloExportOptions(out_dir=Path(out), copy_images=copy)
            export_fn = export_yolo
            title = "导出 YOLO"
        elif fmt == "COCO":
            opts = CocoExportOptions(out_dir=Path(out), copy_images=copy)
            export_fn = export_coco
            title = "导出 COCO"
        else:
            opts = VocExportOptions(out_dir=Path(out), copy_images=copy)
            export_fn = export_voc
            title = "导出 Pascal VOC"

        from gui.dialogs.op_dialogs import ProgressDialog
        self._progress = ProgressDialog(title, parent=self.window())

        def task(progress_cb):
            return export_fn(split, opts, progress_cb=progress_cb)

        self._worker = BatchWorker(task)
        self._worker.progress.connect(
            lambda d, t, n: self._progress and self._progress.set_progress(d, t, n)
        )
        self._worker.finished_ok.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()
        self._progress.show()
        self.start_btn.setEnabled(False)

    def _on_done(self, report) -> None:
        self._close_progress()
        self._worker = None
        self.start_btn.setEnabled(True)
        labels = (
            getattr(report, "written_labels", None)
            or getattr(report, "written_xml", None)
            or getattr(report, "written_annotations", 0)
        )
        out_dir = getattr(self, "_last_export_dir", "")
        self.summary_label.setText(
            f"导出完成：图片 {report.written_images:,}  ·  标签 {labels:,}"
        )
        if report.skipped:
            self.detail_label.setText(f"跳过 {len(report.skipped)} 个文件")
        else:
            self.detail_label.setText("")

        # 显示输出路径 + 打开文件夹按钮
        if out_dir:
            import subprocess, sys
            from qfluentwidgets import InfoBar, InfoBarPosition, PushButton
            bar = InfoBar.success(
                title="导出成功",
                content=f"输出目录：{out_dir}",
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=-1,  # 不自动关闭
                parent=self.window(),
            )
            open_btn = PushButton("打开文件夹")
            open_btn.clicked.connect(
                lambda: subprocess.Popen(["explorer", out_dir])
                if sys.platform == "win32" else None
            )
            bar.addWidget(open_btn)

    def _on_failed(self, msg: str) -> None:
        self._close_progress()
        self._worker = None
        self.start_btn.setEnabled(True)
        self.summary_label.setText(f"导出失败：{msg}")

    def _close_progress(self) -> None:
        if self._progress is not None:
            self._progress.accept()
            self._progress = None
