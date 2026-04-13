"""数据处理 / 批量变换：旋转 / 翻转 / 缩放（同步更新 LabelMe 坐标）。"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
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
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    PushButton,
    SpinBox,
    SubtitleLabel,
)

from core.models import Dataset
from core.transform import (
    FlipOptions,
    ResizeOptions,
    RotateOptions,
    apply_in_memory,
    batch_apply,
    flip_one,
    resize_one,
    rotate_one,
)
from gui.theme import T
from gui.widgets.preview_pane import PreviewPane
from gui.workers.batch_worker import BatchWorker


class TransformView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("transformView")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._dataset: Dataset | None = None
        self._selection_provider = None  # () -> list[ImageInfo]

        root = QVBoxLayout(self)
        root.setContentsMargins(T.PAD_2XL, T.PAD_2XL - 4, T.PAD_2XL, T.PAD_XL)
        root.setSpacing(T.GAP_LG)

        root.addWidget(SubtitleLabel("批量变换"))

        # 操作类型
        form = QFrame()
        form.setObjectName("transformForm")
        grid = QGridLayout(form)
        grid.setContentsMargins(0, T.GAP_LG, 0, T.GAP_LG)
        grid.setHorizontalSpacing(T.GAP_LG)
        grid.setVerticalSpacing(T.GAP)

        grid.addWidget(BodyLabel("操作"), 0, 0)
        self.op_combo = ComboBox()
        self.op_combo.addItems(["旋转", "翻转", "缩放"])
        self.op_combo.currentIndexChanged.connect(self._on_op_changed)
        grid.addWidget(self.op_combo, 0, 1)

        # 旋转角度
        grid.addWidget(BodyLabel("旋转角度"), 1, 0)
        self.angle_combo = ComboBox()
        self.angle_combo.addItems(["90°", "180°", "270°"])
        grid.addWidget(self.angle_combo, 1, 1)

        # 翻转方向
        grid.addWidget(BodyLabel("翻转方向"), 2, 0)
        self.flip_combo = ComboBox()
        self.flip_combo.addItems(["水平", "垂直"])
        grid.addWidget(self.flip_combo, 2, 1)

        # 缩放尺寸
        grid.addWidget(BodyLabel("目标宽 / 高"), 3, 0)
        size_row = QHBoxLayout()
        self.w_spin = SpinBox()
        self.w_spin.setRange(0, 8192)
        self.w_spin.setValue(640)
        self.h_spin = SpinBox()
        self.h_spin.setRange(0, 8192)
        self.h_spin.setValue(640)
        self.keep_ratio_chk = CheckBox("保持宽高比")
        self.keep_ratio_chk.setChecked(True)
        size_row.addWidget(self.w_spin)
        size_row.addWidget(BodyLabel("×"))
        size_row.addWidget(self.h_spin)
        size_row.addSpacing(T.GAP_LG)
        size_row.addWidget(self.keep_ratio_chk)
        size_row.addStretch(1)
        grid.addLayout(size_row, 3, 1)

        # 图片来源
        grid.addWidget(BodyLabel("图片来源"), 4, 0)
        self.source_combo = ComboBox()
        self.source_combo.addItems(["全部数据集", "浏览页中已选中的图片"])
        grid.addWidget(self.source_combo, 4, 1)

        # 输出方式
        grid.addWidget(BodyLabel("输出"), 5, 0)
        self.inplace_chk = CheckBox("原地覆盖（否则在原文件旁生成新文件）")
        grid.addWidget(self.inplace_chk, 5, 1)

        root.addWidget(form)

        # 预览
        self.preview = PreviewPane()
        root.addWidget(self.preview, 1)

        # 操作栏
        ctrl = QHBoxLayout()
        self.summary_label = BodyLabel("")
        ctrl.addWidget(self.summary_label, 1)
        self.preview_btn = PushButton("预览效果")
        self.preview_btn.clicked.connect(self._on_preview)
        ctrl.addWidget(self.preview_btn)
        # Execution via pipeline "执行流程" only
        root.addLayout(ctrl)

        self.result_label = CaptionLabel("")
        root.addWidget(self.result_label)

        self._on_op_changed(0)

    # ---------- 接口 ----------

    def set_dataset(self, dataset: Dataset | None) -> None:
        self._dataset = dataset
        if dataset is None:
            self.summary_label.setText("请先加载数据集。")
            return
        n = sum(c.image_count for c in dataset.categories)
        self.summary_label.setText(f"将处理 {n:,} 张图片")

    # ---------- 内部 ----------

    def _on_op_changed(self, idx: int) -> None:
        # 0=旋转 1=翻转 2=缩放
        self.angle_combo.setEnabled(idx == 0)
        self.flip_combo.setEnabled(idx == 1)
        self.w_spin.setEnabled(idx == 2)
        self.h_spin.setEnabled(idx == 2)
        self.keep_ratio_chk.setEnabled(idx == 2)

    def _build_op(self):
        idx = self.op_combo.currentIndex()
        inplace = self.inplace_chk.isChecked()
        if idx == 0:
            angle = [90, 180, 270][self.angle_combo.currentIndex()]
            return rotate_one, RotateOptions(angle=angle, inplace=inplace)
        if idx == 1:
            d = ["horizontal", "vertical"][self.flip_combo.currentIndex()]
            return flip_one, FlipOptions(direction=d, inplace=inplace)
        return resize_one, ResizeOptions(
            width=self.w_spin.value() or None,
            height=self.h_spin.value() or None,
            keep_ratio=self.keep_ratio_chk.isChecked(),
            inplace=inplace,
        )

    def set_selection_provider(self, provider) -> None:
        self._selection_provider = provider

    def _collect_paths(self):
        if self._dataset is None:
            return []
        if self.source_combo.currentIndex() == 1 and self._selection_provider:
            sel = self._selection_provider() or []
            return [img.path for img in sel]
        return [img.path for c in self._dataset.categories for img in c.images]

    def _on_preview(self) -> None:
        paths = self._collect_paths()
        if not paths:
            InfoBar.warning(
                title="无图片", content="请先选择来源(浏览页中需先选中图片)",
                isClosable=True, position=InfoBarPosition.TOP,
                duration=2500, parent=self.window(),
            )
            return
        self.preview_btn.setEnabled(False)
        self.preview_btn.setText("生成预览中…")

        idx = self.op_combo.currentIndex()
        kind = ["rotate", "flip", "resize"][idx]
        _, opts = self._build_op()
        path = paths[0]

        from gui.workers.batch_worker import BatchWorker
        from PIL import Image

        import io

        def _task(cb):
            with Image.open(path) as src:
                im = src.copy()
            after = apply_in_memory(im, kind, opts)
            # Convert to PNG bytes to avoid PIL cross-thread GC crash
            buf_before = io.BytesIO()
            im.save(buf_before, "PNG")
            buf_after = io.BytesIO()
            after.save(buf_after, "PNG")
            return (buf_before.getvalue(), buf_after.getvalue())

        self._preview_worker = BatchWorker(_task)
        self._preview_worker.finished_ok.connect(self._on_preview_done)
        self._preview_worker.failed.connect(self._on_preview_failed)
        self._preview_worker.start()

    def _on_preview_done(self, result) -> None:
        self.preview_btn.setEnabled(True)
        self.preview_btn.setText("预览效果")
        import io
        from PIL import Image
        im = Image.open(io.BytesIO(result[0]))
        after = Image.open(io.BytesIO(result[1]))
        self.preview.set_before_after(im, after)

    def _on_preview_failed(self, msg: str) -> None:
        self.preview_btn.setEnabled(True)
        self.preview_btn.setText("预览效果")
        self.result_label.setText(f"预览失败: {msg}")

    # Execution via pipeline "执行流程" only — no independent execution.
