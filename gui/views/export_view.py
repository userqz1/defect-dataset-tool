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
from core.exporter.csv_export import CsvExportOptions, export_csv_dataset
from core.exporter.jsonl import JsonlExportOptions, export_jsonl
from core.exporter.llava import LlavaExportOptions, export_llava
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
        self.fmt_combo.addItems(["YOLO", "COCO", "Pascal VOC", "JSON Lines", "LLaVA", "CSV"])
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

        # 输出结构预览
        from PyQt6.QtWidgets import QFrame
        preview_frame = QFrame()
        preview_frame.setObjectName("chartFrame")  # 复用卡片样式
        preview_layout = QVBoxLayout(preview_frame)
        preview_layout.setContentsMargins(T.PAD_XL, T.PAD_LG, T.PAD_XL, T.PAD_LG)
        preview_layout.setSpacing(T.GAP)
        preview_layout.addWidget(CaptionLabel("输出结构预览"))
        self._structure_label = BodyLabel("")
        self._structure_label.setWordWrap(True)
        preview_layout.addWidget(self._structure_label)
        root.addWidget(preview_frame)
        self.fmt_combo.currentTextChanged.connect(self._update_structure_preview)
        self._update_structure_preview(self.fmt_combo.currentText())

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

    def _update_structure_preview(self, fmt: str) -> None:
        """根据选中格式显示输出目录结构和命名示例。"""
        structures = {
            "YOLO": (
                "<output>/\n"
                "  ├── images/\n"
                "  │   ├── train/\n"
                "  │   │   ├── crack_001.jpg\n"
                "  │   │   └── scratch_042.jpg\n"
                "  │   ├── val/\n"
                "  │   └── test/\n"
                "  ├── labels/\n"
                "  │   ├── train/\n"
                "  │   │   ├── crack_001.txt        ← 类别ID cx cy w h (归一化)\n"
                "  │   │   └── scratch_042.txt\n"
                "  │   ├── val/\n"
                "  │   └── test/\n"
                "  ├── classes.txt                   ← 每行一个类别名\n"
                "  └── data.yaml                     ← path/train/val/nc/names"
            ),
            "COCO": (
                "<output>/\n"
                "  ├── train/\n"
                "  │   ├── crack_001.jpg\n"
                "  │   └── scratch_042.jpg\n"
                "  ├── val/\n"
                "  ├── test/\n"
                "  └── annotations/\n"
                "      ├── instances_train.json      ← COCO 标准格式\n"
                "      ├── instances_val.json        ← {images, annotations, categories}\n"
                "      └── instances_test.json"
            ),
            "Pascal VOC": (
                "<output>/\n"
                "  ├── JPEGImages/\n"
                "  │   ├── crack_001.jpg\n"
                "  │   └── scratch_042.jpg\n"
                "  ├── Annotations/\n"
                "  │   ├── crack_001.xml             ← Pascal VOC XML 格式\n"
                "  │   └── scratch_042.xml\n"
                "  └── ImageSets/\n"
                "      └── Main/\n"
                "          ├── train.txt             ← 每行一个文件名（无扩展名）\n"
                "          ├── val.txt\n"
                "          └── test.txt"
            ),
            "JSON Lines": (
                "<output>/\n"
                "  ├── images/\n"
                "  │   ├── train/\n"
                "  │   │   └── crack_001.jpg\n"
                "  │   ├── val/\n"
                "  │   └── test/\n"
                "  ├── train.jsonl                    ← 每行一条 JSON 记录\n"
                "  ├── val.jsonl                      ← {image, width, height, annotations}\n"
                "  └── test.jsonl\n\n"
                "每行格式：\n"
                '  {"image": "images/train/crack_001.jpg", "width": 1920, "height": 1080,\n'
                '   "category": "crack", "annotations": [{"label": "crack", "bbox": [x1,y1,x2,y2]}]}'
            ),
            "LLaVA": (
                "<output>/\n"
                "  ├── images/\n"
                "  │   ├── train/\n"
                "  │   │   └── crack_001.jpg\n"
                "  │   ├── val/\n"
                "  │   └── test/\n"
                "  ├── llava_train.jsonl              ← 对话格式，可直接微调 LLaVA/Qwen-VL\n"
                "  ├── llava_val.jsonl\n"
                "  └── llava_test.jsonl\n\n"
                "每行格式：\n"
                '  {"id": "train_000001", "image": "images/train/crack_001.jpg",\n'
                '   "conversations": [{"from": "human", "value": "<image>\\n有什么缺陷？"},\n'
                '                     {"from": "gpt", "value": "存在1处裂纹缺陷..."}]}'
            ),
            "CSV": (
                "<output>/\n"
                "  ├── images/\n"
                "  │   ├── train/\n"
                "  │   │   └── crack_001.jpg\n"
                "  │   ├── val/\n"
                "  │   └── test/\n"
                "  └── annotations.csv                ← 扁平表格，每行一个标注框\n\n"
                "CSV 列：\n"
                "  image_path, category, label, x1, y1, x2, y2, shape_type, split"
            ),
        }
        self._structure_label.setText(structures.get(fmt, ""))

    def _on_start(self) -> None:
        if self._dataset is None or self._worker is not None:
            return
        out = QFileDialog.getExistingDirectory(self, "选择导出目录")
        if not out:
            return
        self._last_export_dir = out
        self._last_export_fmt = self.fmt_combo.currentText()

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
        out_path = Path(out)
        format_map = {
            "YOLO": (YoloExportOptions(out_dir=out_path, copy_images=copy), export_yolo),
            "COCO": (CocoExportOptions(out_dir=out_path, copy_images=copy), export_coco),
            "Pascal VOC": (VocExportOptions(out_dir=out_path, copy_images=copy), export_voc),
            "JSON Lines": (JsonlExportOptions(out_dir=out_path, copy_images=copy), export_jsonl),
            "LLaVA": (LlavaExportOptions(out_dir=out_path, copy_images=copy), export_llava),
            "CSV": (CsvExportOptions(out_dir=out_path, copy_images=copy), export_csv_dataset),
        }
        opts, export_fn = format_map[fmt]
        title = f"导出 {fmt}"

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
        fmt = getattr(self, "_last_export_fmt", "")

        self.summary_label.setText(
            f"导出完成：图片 {report.written_images:,}  ·  标签 {labels:,}"
        )
        if report.skipped:
            self.detail_label.setText(f"跳过 {len(report.skipped)} 个文件")
        else:
            self.detail_label.setText("")

        # 显示输出路径 + 打开文件夹 + 训练代码片段
        if out_dir:
            import subprocess, sys
            from qfluentwidgets import InfoBar, InfoBarPosition, PushButton
            bar = InfoBar.success(
                title="导出成功",
                content=f"输出目录：{out_dir}",
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=-1,
                parent=self.window(),
            )
            open_btn = PushButton("打开文件夹")
            open_btn.clicked.connect(
                lambda: subprocess.Popen(["explorer", out_dir])
                if sys.platform == "win32" else None
            )
            bar.addWidget(open_btn)

        # 更新结构预览区域为训练代码片段
        snippet = self._training_snippet(fmt, out_dir)
        if snippet:
            self._structure_label.setText(snippet)

    @staticmethod
    def _training_snippet(fmt: str, out_dir: str) -> str:
        """生成导出后可直接粘贴的训练代码片段。"""
        path = out_dir.replace("\\", "/")
        if fmt == "YOLO":
            return (
                "导出完成，可直接用于训练。复制以下代码开始：\n\n"
                "# YOLOv8 训练\n"
                "from ultralytics import YOLO\n\n"
                f'model = YOLO("yolov8n.pt")\n'
                f'model.train(data=r"{path}/data.yaml", epochs=100, imgsz=640)\n\n'
                "# YOLOv5 训练\n"
                f'python train.py --data "{path}/data.yaml" --weights yolov5s.pt --epochs 100'
            )
        elif fmt == "COCO":
            return (
                "导出完成，可直接用于训练。复制以下代码开始：\n\n"
                "# Detectron2\n"
                "from detectron2.data.datasets import register_coco_instances\n\n"
                f'register_coco_instances("train", {{}},\n'
                f'    r"{path}/annotations/instances_train.json",\n'
                f'    r"{path}/train")\n\n'
                "# mmdetection\n"
                f'data_root = r"{path}"\n'
                "# 在 config 中设置 data_root 和 ann_file 路径即可"
            )
        elif fmt == "Pascal VOC":
            return (
                "导出完成，可直接用于训练。复制以下代码开始：\n\n"
                "# torchvision VOC 加载\n"
                "from torchvision.datasets import VOCDetection\n\n"
                f'dataset = VOCDetection(root=r"{path}",\n'
                f'    image_set="train", download=False)\n\n'
                f"# 图片目录：{path}/JPEGImages/\n"
                f"# 标注目录：{path}/Annotations/\n"
                f"# 划分列表：{path}/ImageSets/Main/"
            )
        elif fmt == "JSON Lines":
            return (
                "导出完成。可用 Python 直接加载：\n\n"
                "import json\n\n"
                f'with open(r"{path}/train.jsonl") as f:\n'
                "    for line in f:\n"
                "        sample = json.loads(line)\n"
                '        img_path = sample["image"]\n'
                '        annots = sample["annotations"]\n\n'
                "# 或用 pandas:\n"
                "import pandas as pd\n"
                f'df = pd.read_json(r"{path}/train.jsonl", lines=True)'
            )
        elif fmt == "LLaVA":
            return (
                "导出完成。可用于 LLaVA / Qwen-VL / InternVL 微调：\n\n"
                "# LLaVA 微调命令\n"
                "python llava/train/train_mem.py \\\n"
                f'    --data_path r"{path}/llava_train.jsonl" \\\n'
                f'    --image_folder r"{path}" \\\n'
                "    --model_name_or_path liuhaotian/llava-v1.5-7b \\\n"
                "    --output_dir ./checkpoints/my_model\n\n"
                "# Qwen-VL 微调\n"
                f'# 将 {path}/llava_train.jsonl 转为 Qwen 格式后使用'
            )
        elif fmt == "CSV":
            return (
                "导出完成。可直接用 Pandas 加载分析：\n\n"
                "import pandas as pd\n\n"
                f'df = pd.read_csv(r"{path}/annotations.csv")\n'
                "train_df = df[df['split'] == 'train']\n"
                "print(f'训练集: {{len(train_df)}} 条标注')\n"
                "print(df['label'].value_counts())"
            )
        return ""

    def _on_failed(self, msg: str) -> None:
        self._close_progress()
        self._worker = None
        self.start_btn.setEnabled(True)
        self.summary_label.setText(f"导出失败：{msg}")

    def _close_progress(self) -> None:
        if self._progress is not None:
            self._progress.accept()
            self._progress = None
