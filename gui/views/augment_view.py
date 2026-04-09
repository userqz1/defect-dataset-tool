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
        self._worker: BatchWorker | None = None
        self._progress = None
        self._out_dir: Path | None = None
        self._selection_provider = None  # () -> list[ImageInfo]

        root = QVBoxLayout(self)
        root.setContentsMargins(T.PAD_XL + 12, T.PAD_XL + 8, T.PAD_XL + 12, T.PAD_XL)
        root.setSpacing(T.GAP_LG)

        root.addWidget(SubtitleLabel("数据增强"))
        root.addWidget(CaptionLabel("生成新样本到指定目录,标注同步更新,原图不变"))

        # 几何变换
        root.addWidget(BodyLabel("几何变换"))
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
        root.addWidget(BodyLabel("光度变换"))
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

        # 数量
        n_row = QHBoxLayout()
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
        root.addLayout(n_row)

        # 图片来源
        src_row = QHBoxLayout()
        src_row.addWidget(BodyLabel("图片来源"))
        self.source_combo = ComboBox()
        self.source_combo.addItems(["全部数据集", "浏览页中已选中的图片"])
        src_row.addWidget(self.source_combo)
        src_row.addStretch(1)
        root.addLayout(src_row)

        # 输出
        out_row = QHBoxLayout()
        self.out_label = BodyLabel("输出目录:未选择")
        out_row.addWidget(self.out_label, 1)
        self.choose_btn = PushButton("选择…")
        self.choose_btn.clicked.connect(self._choose_dir)
        out_row.addWidget(self.choose_btn)
        root.addLayout(out_row)

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
        self.start_btn = PrimaryPushButton("开始增强")
        self.start_btn.clicked.connect(self._on_start)
        self.start_btn.setEnabled(False)
        ctrl.addWidget(self.start_btn)
        root.addLayout(ctrl)

        self.result_label = CaptionLabel("")
        root.addWidget(self.result_label)

    # ---------- 接口 ----------

    def set_dataset(self, dataset: Dataset | None) -> None:
        self._dataset = dataset
        if dataset is None:
            self.summary_label.setText("请先加载数据集。")
            self.start_btn.setEnabled(False)
            return
        n = sum(c.image_count for c in dataset.categories)
        self.summary_label.setText(f"待增强:{n:,} 张图片")
        self._refresh_start()

    # ---------- 内部 ----------

    def _choose_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if d:
            self._out_dir = Path(d)
            self.out_label.setText(f"输出目录:{d}")
            self._refresh_start()

    def _refresh_start(self) -> None:
        ok = self._dataset is not None and self._out_dir is not None
        self.start_btn.setEnabled(bool(ok))

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

        from gui.workers.batch_worker import BatchWorker
        from PIL import Image

        def _task(cb):
            with Image.open(path) as src:
                im = src.copy()
            after = augment_in_memory(im, opts)
            return (im, after)

        self._preview_worker = BatchWorker(_task)
        self._preview_worker.finished_ok.connect(self._on_preview_done)
        self._preview_worker.failed.connect(self._on_preview_failed)
        self._preview_worker.start()

    def _on_preview_done(self, result) -> None:
        self.preview_btn.setEnabled(True)
        self.preview_btn.setText("预览效果")
        im, after = result
        self.preview.set_before_after(im, after)

    def _on_preview_failed(self, msg: str) -> None:
        self.preview_btn.setEnabled(True)
        self.preview_btn.setText("预览效果")
        self.result_label.setText(f"预览失败: {msg}")

    def _on_start(self) -> None:
        if self._dataset is None or self._out_dir is None or self._worker is not None:
            return
        paths = self._collect_paths()
        if not paths:
            InfoBar.warning(
                title="无图片", content="请先选择来源",
                isClosable=True, position=InfoBarPosition.TOP,
                duration=2500, parent=self.window(),
            )
            return
        opts = self._build_opts()
        out_dir = self._out_dir

        from gui.dialogs.op_dialogs import ProgressDialog
        self._progress = ProgressDialog("数据增强", parent=self.window())

        def task(progress_cb):
            return augment_batch(paths, out_dir, opts, progress_cb=progress_cb)

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
            f"完成:生成 {result.count} 张新图片,标注 {len(result.written_labels)} 个,失败 {len(result.failed)}"
        )

    def _on_failed(self, msg: str) -> None:
        if self._progress is not None:
            self._progress.accept()
            self._progress = None
        self._worker = None
        self.start_btn.setEnabled(True)
        self.result_label.setText(f"失败:{msg}")
