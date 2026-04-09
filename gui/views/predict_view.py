"""数据处理 / AI 预标注:本地 YOLOv8 自动出框,生成 LabelMe JSON 待复核。"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CheckBox,
    ComboBox,
    DoubleSpinBox,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PrimaryPushButton,
    SubtitleLabel,
)

from core.models import Dataset
from core.predictor import YoloPredictor, predict_batch
from gui.theme import T
from gui.workers.batch_worker import BatchWorker


class PredictView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("predictView")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._dataset: Dataset | None = None
        self._worker: BatchWorker | None = None
        self._progress = None

        root = QVBoxLayout(self)
        root.setContentsMargins(T.PAD_XL + 12, T.PAD_XL + 8, T.PAD_XL + 12, T.PAD_XL)
        root.setSpacing(T.GAP_LG)

        root.addWidget(SubtitleLabel("AI 预标注 (本地)"))
        root.addWidget(CaptionLabel(
            "对未标注图片自动生成 LabelMe JSON 草稿,可在「浏览」/「详情」中复核。"
            "需要安装 ultralytics(pip install ultralytics)。"
        ))

        # 后端
        backend_row = QHBoxLayout()
        backend_row.addWidget(BodyLabel("后端"))
        self.backend_combo = ComboBox()
        self.backend_combo.addItem("YOLOv8 (本地)")
        backend_row.addWidget(self.backend_combo)
        backend_row.addSpacing(T.GAP_LG)
        backend_row.addWidget(BodyLabel("模型"))
        self.model_edit = LineEdit()
        self.model_edit.setText("yolov8n.pt")
        self.model_edit.setFixedWidth(180)
        self.model_edit.setToolTip("本地路径或 ultralytics 自动下载的模型名")
        backend_row.addWidget(self.model_edit)
        backend_row.addSpacing(T.GAP_LG)
        backend_row.addWidget(BodyLabel("置信阈值"))
        self.conf_spin = DoubleSpinBox()
        self.conf_spin.setRange(0.05, 0.95)
        self.conf_spin.setSingleStep(0.05)
        self.conf_spin.setValue(0.25)
        backend_row.addWidget(self.conf_spin)
        backend_row.addStretch(1)
        root.addLayout(backend_row)

        # 选项
        opt_row = QHBoxLayout()
        self.unlabeled_only_chk = CheckBox("仅未标注图片")
        self.unlabeled_only_chk.setChecked(True)
        opt_row.addWidget(self.unlabeled_only_chk)
        self.overwrite_chk = CheckBox("覆盖已有标注")
        opt_row.addWidget(self.overwrite_chk)
        opt_row.addStretch(1)
        root.addLayout(opt_row)

        # 控制
        ctrl = QHBoxLayout()
        self.summary_label = BodyLabel("")
        ctrl.addWidget(self.summary_label, 1)
        self.start_btn = PrimaryPushButton("开始预标注")
        self.start_btn.clicked.connect(self._on_start)
        self.start_btn.setEnabled(False)
        ctrl.addWidget(self.start_btn)
        root.addLayout(ctrl)

        self.result_label = CaptionLabel("")
        root.addWidget(self.result_label)
        root.addStretch(1)

    # ---------- 接口 ----------

    def set_dataset(self, dataset: Dataset | None) -> None:
        self._dataset = dataset
        if dataset is None:
            self.summary_label.setText("请先加载数据集。")
            self.start_btn.setEnabled(False)
            return
        n_un = sum(
            1 for c in dataset.categories for img in c.images if not img.has_label
        )
        n = sum(c.image_count for c in dataset.categories)
        # 环境状态
        env_hint = ""
        try:
            import ultralytics  # noqa: F401
            try:
                import torch
                env_hint = "  ·  GPU" if torch.cuda.is_available() else "  ·  CPU"
            except ImportError:
                env_hint = "  ·  缺少 PyTorch"
        except ImportError:
            env_hint = "  ·  需安装 ultralytics"
        self.summary_label.setText(f"未标注 {n_un:,} / 总计 {n:,}{env_hint}")
        self.start_btn.setEnabled(n > 0)

    # ---------- 内部 ----------

    def _on_start(self) -> None:
        if self._dataset is None or self._worker is not None:
            return
        predictor = YoloPredictor(
            model_name=self.model_edit.text().strip() or "yolov8n.pt",
            conf=self.conf_spin.value(),
        )
        if not predictor.is_available():
            # 具体诊断缺什么
            try:
                import ultralytics  # noqa: F401
                has_ul = True
            except ImportError:
                has_ul = False
            try:
                import torch
                has_torch = True
                gpu = torch.cuda.is_available()
            except ImportError:
                has_torch = False
                gpu = False

            if not has_ul:
                msg = "未安装 ultralytics\n请运行: pip install ultralytics"
            elif not has_torch:
                msg = "ultralytics 已安装但缺少 PyTorch\n请运行: pip install torch torchvision"
            else:
                msg = f"环境就绪（GPU: {'可用' if gpu else '不可用，将使用 CPU'}）\n但模型加载失败，请检查模型路径"

            InfoBar.error(
                title="后端不可用",
                content=msg,
                isClosable=True, position=InfoBarPosition.TOP,
                duration=8000, parent=self.window(),
            )
            return

        # 选图
        if self.unlabeled_only_chk.isChecked() and not self.overwrite_chk.isChecked():
            paths = [
                img.path for c in self._dataset.categories
                for img in c.images if not img.has_label
            ]
        else:
            paths = [img.path for c in self._dataset.categories for img in c.images]
        if not paths:
            InfoBar.warning(
                title="没有图片",
                content="当前筛选下没有可处理的图片",
                isClosable=True, position=InfoBarPosition.TOP,
                duration=3000, parent=self.window(),
            )
            return

        from gui.dialogs.op_dialogs import ProgressDialog
        self._progress = ProgressDialog("AI 预标注", parent=self.window())
        overwrite = self.overwrite_chk.isChecked()

        def task(progress_cb):
            return predict_batch(paths, predictor, overwrite=overwrite, progress_cb=progress_cb)

        self._worker = BatchWorker(task)
        self._worker.progress.connect(
            lambda d, t, n: self._progress and self._progress.set_progress(d, t, n)
        )
        self._worker.finished_ok.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()
        self._progress.show()
        self.start_btn.setEnabled(False)

    def _on_done(self, result) -> None:
        if self._progress is not None:
            self._progress.accept()
            self._progress = None
        self._worker = None
        self.start_btn.setEnabled(True)
        self.result_label.setText(
            f"完成:写入 {len(result.written)} 个 JSON  ·  跳过 {len(result.skipped)}  ·  失败 {len(result.failed)}"
        )
        InfoBar.success(
            title="预标注完成",
            content=f"写入 {len(result.written)} 个标注文件",
            isClosable=True, position=InfoBarPosition.TOP,
            duration=3000, parent=self.window(),
        )

    def _on_failed(self, msg: str) -> None:
        if self._progress is not None:
            self._progress.accept()
            self._progress = None
        self._worker = None
        self.start_btn.setEnabled(True)
        self.result_label.setText(f"失败:{msg}")
