"""数据处理 / 数据增强:生成新样本(不覆盖原图)。"""
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
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    PushButton,
    SpinBox,
    StrongBodyLabel,
    SubtitleLabel,
)

from core.augment import AugmentOptions, augment_batch, augment_in_memory
from core.models import Dataset
from gui.theme import T
from gui.widgets.preview_pane import PreviewPane
from gui.workers.batch_worker import BatchWorker


class AugmentView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("augmentView")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._dataset: Dataset | None = None
        self._node_item = None
        self._out_dir: Path | None = None
        self._selection_provider = None  # () -> list[ImageInfo]

        root = QVBoxLayout(self)
        root.setContentsMargins(T.PAD_2XL, T.PAD_2XL - 4, T.PAD_2XL, T.PAD_XL)
        root.setSpacing(T.GAP_LG)

        root.addWidget(SubtitleLabel("数据增强与变换"))

        # 模式选择
        mode_row = QHBoxLayout()
        mode_row.addWidget(BodyLabel("模式"))
        self.mode_combo = ComboBox()
        self.mode_combo.addItems(["增强（生成新样本）", "变换（原地修改）"])
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        mode_row.addWidget(self.mode_combo)
        mode_row.addStretch(1)
        root.addLayout(mode_row)

        # 几何变换
        root.addWidget(StrongBodyLabel("几何变换"))
        geo_grid = QGridLayout()
        geo_grid.setHorizontalSpacing(T.GAP_LG)
        self.flip_h_chk = CheckBox("随机水平翻转")
        self.flip_h_chk.setChecked(True)
        self.flip_v_chk = CheckBox("随机垂直翻转")
        self.rot_chk = CheckBox("随机旋转 90/180/270°")
        self.crop_chk = CheckBox("随机裁剪 (0.85x)")
        self.copy_paste_chk = CheckBox("Copy-Paste(复制标注目标到随机位置)")
        self.copy_paste_chk.setToolTip("从所有标注目标里随机抠一个,贴到新图的随机位置,标注同步")
        geo_grid.addWidget(self.flip_h_chk, 0, 0)
        geo_grid.addWidget(self.flip_v_chk, 0, 1)
        geo_grid.addWidget(self.rot_chk, 0, 2)
        geo_grid.addWidget(self.crop_chk, 0, 3)
        geo_grid.addWidget(self.copy_paste_chk, 1, 0, 1, 4)
        root.addLayout(geo_grid)

        # 光度变换
        root.addWidget(StrongBodyLabel("光度变换"))
        photo_grid = QGridLayout()
        photo_grid.setHorizontalSpacing(T.GAP_LG)
        self.bright_chk = CheckBox("亮度抖动")
        self.bright_chk.setChecked(True)
        self.contrast_chk = CheckBox("对比度抖动")
        self.contrast_chk.setChecked(True)
        self.color_chk = CheckBox("色彩抖动")
        self.blur_chk = CheckBox("高斯模糊")
        self.noise_chk = CheckBox("高斯噪声")
        photo_grid.addWidget(self.bright_chk, 0, 0)
        photo_grid.addWidget(self.contrast_chk, 0, 1)
        photo_grid.addWidget(self.color_chk, 0, 2)
        photo_grid.addWidget(self.blur_chk, 0, 3)
        photo_grid.addWidget(self.noise_chk, 0, 4)
        root.addLayout(photo_grid)

        # 数量（wrapped in QWidget for visibility toggle）
        self.n_row_widget = QWidget()
        n_row = QHBoxLayout(self.n_row_widget)
        n_row.setContentsMargins(0, 0, 0, 0)
        n_row.addWidget(BodyLabel("每张原图生成"))
        self.n_spin = SpinBox()
        self.n_spin.setRange(1, 50)
        self.n_spin.setValue(3)
        n_row.addWidget(self.n_spin)
        n_row.addWidget(BodyLabel("张"))
        n_row.addSpacing(T.GAP_LG)
        n_row.addWidget(BodyLabel("随机种子"))
        self.seed_spin = SpinBox()
        self.seed_spin.setRange(0, 999999)
        self.seed_spin.setValue(42)
        n_row.addWidget(self.seed_spin)
        n_row.addStretch(1)
        root.addWidget(self.n_row_widget)

        # 图片来源
        src_row = QHBoxLayout()
        src_row.addWidget(BodyLabel("图片来源"))
        self.source_combo = ComboBox()
        self.source_combo.addItems(["全部数据集", "浏览页中已选中的图片"])
        src_row.addWidget(self.source_combo)
        src_row.addStretch(1)
        root.addLayout(src_row)

        # 变换模式专用：缩放选项
        from qfluentwidgets import SpinBox as _SpinBox
        self.resize_frame = QWidget()
        rz_layout = QHBoxLayout(self.resize_frame)
        rz_layout.setContentsMargins(0, 0, 0, 0)
        rz_layout.addWidget(BodyLabel("统一缩放到"))
        self.w_spin = _SpinBox()
        self.w_spin.setRange(0, 8192); self.w_spin.setValue(640)
        rz_layout.addWidget(self.w_spin)
        rz_layout.addWidget(BodyLabel("×"))
        self.h_spin = _SpinBox()
        self.h_spin.setRange(0, 8192); self.h_spin.setValue(640)
        rz_layout.addWidget(self.h_spin)
        self.keep_ratio_chk = CheckBox("保持宽高比")
        self.keep_ratio_chk.setChecked(True)
        rz_layout.addWidget(self.keep_ratio_chk)
        self.inplace_chk = CheckBox("原地覆盖（否则生成新文件）")
        rz_layout.addWidget(self.inplace_chk)
        rz_layout.addStretch(1)
        self.resize_frame.hide()  # 增强模式下隐藏
        root.addWidget(self.resize_frame)

        # 输出（增强模式专用）
        self.out_row_widget = QWidget()
        out_row = QHBoxLayout(self.out_row_widget)
        out_row.setContentsMargins(0, 0, 0, 0)
        self.out_label = BodyLabel("输出目录:未选择")
        out_row.addWidget(self.out_label, 1)
        self.choose_btn = PushButton("选择…")
        self.choose_btn.clicked.connect(self._choose_dir)
        out_row.addWidget(self.choose_btn)
        root.addWidget(self.out_row_widget)

        # 预览
        self.preview = PreviewPane()
        root.addWidget(self.preview, 1)

        # 控制
        ctrl = QHBoxLayout()
        self.summary_label = BodyLabel("")
        ctrl.addWidget(self.summary_label, 1)
        self.preview_btn = PushButton("预览效果")
        self.preview_btn.clicked.connect(self._on_preview)
        ctrl.addWidget(self.preview_btn)
        root.addLayout(ctrl)

        self.result_label = CaptionLabel("")
        root.addWidget(self.result_label)

        # Wire all param controls → immediate write-back
        for chk in (self.flip_h_chk, self.flip_v_chk, self.rot_chk, self.crop_chk,
                     self.copy_paste_chk, self.bright_chk, self.contrast_chk,
                     self.color_chk, self.blur_chk, self.noise_chk):
            chk.stateChanged.connect(self._push_params)
        self.n_spin.valueChanged.connect(self._push_params)
        self.seed_spin.valueChanged.connect(self._push_params)

    def _on_mode_changed(self, idx: int) -> None:
        is_augment = idx == 0
        # 增强模式：显示数量/种子/输出目录，隐藏缩放
        self.n_row_widget.setVisible(is_augment)
        self.out_row_widget.setVisible(is_augment)
        self.resize_frame.setVisible(not is_augment)
        # 更新按钮文字
        pass  # mode switch only affects UI visibility

    # ---------- 接口 ----------

    def bind_node(self, node_item) -> None:
        """Bind to NodeItem — load params into UI, future edits write back."""
        self._node_item = node_item
        params = node_item.get_params() if node_item else {}
        _CHECKBOXES = [
            ("flip_h", self.flip_h_chk), ("flip_v", self.flip_v_chk),
            ("rotate", self.rot_chk), ("brightness", self.bright_chk),
            ("contrast", self.contrast_chk), ("color_jitter", self.color_chk),
            ("random_crop", self.crop_chk), ("copy_paste", self.copy_paste_chk),
        ]
        for key, chk in _CHECKBOXES:
            chk.blockSignals(True)
            chk.setChecked(bool(params.get(key, chk.isChecked())))
            chk.blockSignals(False)
        self.n_spin.blockSignals(True)
        self.n_spin.setValue(int(params.get("n_each", 3)))
        self.n_spin.blockSignals(False)
        self.seed_spin.blockSignals(True)
        self.seed_spin.setValue(int(params.get("seed", 42)))
        self.seed_spin.blockSignals(False)
        if params.get("out_dir"):
            self._out_dir = Path(params["out_dir"])
            self.out_label.setText(f"输出目录: {self._out_dir}")

    def _push_params(self) -> None:
        if self._node_item is None:
            return
        self._node_item.set_params({
            "flip_h": self.flip_h_chk.isChecked(),
            "flip_v": self.flip_v_chk.isChecked(),
            "rotate": self.rot_chk.isChecked(),
            "brightness": self.bright_chk.isChecked(),
            "contrast": self.contrast_chk.isChecked(),
            "color_jitter": self.color_chk.isChecked(),
            "random_crop": self.crop_chk.isChecked(),
            "copy_paste": self.copy_paste_chk.isChecked(),
            "n_each": self.n_spin.value(),
            "seed": self.seed_spin.value(),
            "out_dir": str(self._out_dir) if self._out_dir else "",
        })

    def set_dataset(self, dataset: Dataset | None) -> None:
        self._dataset = dataset
        if dataset is None:
            self.summary_label.setText("请先加载数据集。")
            return
        n = sum(c.image_count for c in dataset.categories)
        self.summary_label.setText(f"待增强:{n:,} 张图片")

    def set_results(self, input_data, step_result) -> None:
        """Display pipeline execution results."""
        if step_result is None:
            return
        self.summary_label.setText(
            f"增强完成: {step_result.ok_count} 张生成 · {step_result.fail_count} 张失败")

    # ---------- 内部 ----------

    def _choose_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if d:
            self._out_dir = Path(d)
            self.out_label.setText(f"输出目录:{d}")
            self._push_params()  # out_dir changed → write back immediately

    def _build_opts(self) -> AugmentOptions:
        return AugmentOptions(
            flip_h=self.flip_h_chk.isChecked(),
            flip_v=self.flip_v_chk.isChecked(),
            rotate90=self.rot_chk.isChecked(),
            random_crop=self.crop_chk.isChecked(),
            copy_paste=self.copy_paste_chk.isChecked(),
            brightness=self.bright_chk.isChecked(),
            contrast=self.contrast_chk.isChecked(),
            color_jitter=self.color_chk.isChecked(),
            gauss_blur=self.blur_chk.isChecked(),
            gauss_noise=self.noise_chk.isChecked(),
            n_per_image=self.n_spin.value(),
            seed=self.seed_spin.value(),
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
        opts = self._build_opts()
        path = paths[0]

        from io import BytesIO
        from gui.workers.batch_worker import BatchWorker
        from PIL import Image

        def _task(cb):
            with Image.open(path) as src:
                im = src.copy()
            after = augment_in_memory(im, opts)
            # 在 worker 线程转为 PNG bytes，避免 PIL Image 跨线程 GC 问题
            buf_before = BytesIO()
            im.convert("RGB").save(buf_before, format="PNG")
            buf_after = BytesIO()
            after.convert("RGB").save(buf_after, format="PNG")
            return (buf_before.getvalue(), buf_after.getvalue())

        self._preview_worker = BatchWorker(_task)
        self._preview_worker.finished_ok.connect(self._on_preview_done)
        self._preview_worker.failed.connect(self._on_preview_failed)
        self._preview_worker.start()

    def _on_preview_done(self, result) -> None:
        self.preview_btn.setEnabled(True)
        self.preview_btn.setText("预览效果")
        from PyQt6.QtGui import QPixmap
        before_bytes, after_bytes = result
        pix_before = QPixmap()
        pix_before.loadFromData(before_bytes, "PNG")
        pix_after = QPixmap()
        pix_after.loadFromData(after_bytes, "PNG")
        self.preview.before.image_label.setPixmap(
            pix_before.scaled(self.preview.before.image_label.size(),
                              Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
        )
        self.preview.after.image_label.setPixmap(
            pix_after.scaled(self.preview.after.image_label.size(),
                             Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        )

    def _on_preview_failed(self, msg: str) -> None:
        self.preview_btn.setEnabled(True)
        self.preview_btn.setText("预览效果")
        self.result_label.setText(f"预览失败: {msg}")

