"""导出向导 — 卡片式格式选择 + 分步引导。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
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
    DoubleSpinBox,
    FluentIcon as FIF,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    PushButton,
    StrongBodyLabel,
    SubtitleLabel,
    TogglePushButton,
)

from core.exporter.coco import CocoExportOptions, export_coco
from core.exporter.csv_export import CsvExportOptions, export_csv_dataset
from core.exporter.jsonl import JsonlExportOptions, export_jsonl
from core.exporter.llava import LlavaExportOptions, export_llava
from core.exporter.sharegpt import ShareGptExportOptions, export_sharegpt
from core.exporter.swift import SwiftExportOptions, export_swift
from core.exporter.voc import VocExportOptions, export_voc
from core.exporter.yolo import YoloExportOptions, export_yolo
from core.models import Dataset
from core.splitter import SplitOptions, split_dataset
from gui.theme import T
from gui.workers.batch_worker import BatchWorker


# ---------- 格式定义 ----------

_FORMATS = [
    {
        "key": "YOLO",
        "name": "YOLO",
        "desc": "YOLOv5 / v8 目标检测",
        "detail": "适用于 Ultralytics YOLO 系列模型训练",
    },
    {
        "key": "COCO",
        "name": "COCO JSON",
        "desc": "通用目标检测标准",
        "detail": "适用于 Detectron2、mmdetection 等框架",
    },
    {
        "key": "Pascal VOC",
        "name": "Pascal VOC",
        "desc": "经典 XML 标注格式",
        "detail": "适用于 SSD、Faster R-CNN 等传统框架",
    },
    {
        "key": "JSON Lines",
        "name": "JSON Lines",
        "desc": "通用数据管线格式",
        "detail": "每行一条 JSON，适合自定义训练脚本和数据分析",
    },
    {
        "key": "ShareGPT",
        "name": "ShareGPT (LLaMA-Factory)",
        "desc": "视觉大模型通用微调",
        "detail": "LLaMA-Factory 标准格式，覆盖 LLaVA/Qwen-VL/InternVL/GLM-4V 等，附带 dataset_info.json",
    },
    {
        "key": "ms-swift",
        "name": "ms-swift (ModelScope)",
        "desc": "Qwen-VL / InternVL 微调",
        "detail": "ModelScope SWIFT 框架格式，直接用于 Qwen2.5-VL / InternVL 训练",
    },
    {
        "key": "LLaVA",
        "name": "LLaVA 原生",
        "desc": "LLaVA 原生对话格式",
        "detail": "对话 JSONL，适用于原版 LLaVA / LLaVA-NeXT 微调",
    },
    {
        "key": "CSV",
        "name": "CSV 表格",
        "desc": "数据分析友好",
        "detail": "扁平表格，可直接用 Pandas/Excel 打开分析",
    },
]


# ---------- 格式选择卡片 ----------

class _FormatCard(QFrame):
    """单个格式选择卡片。"""

    def __init__(self, fmt: dict, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("formatCard")
        self.fmt_key = fmt["key"]
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(72)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._selected = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(T.PAD_LG, T.PAD, T.PAD_LG, T.PAD)
        layout.setSpacing(2)

        name_row = QHBoxLayout()
        name_row.setSpacing(T.GAP)
        self.name_label = StrongBodyLabel(fmt["name"])
        self.name_label.setObjectName("formatCardName")
        name_row.addWidget(self.name_label)
        name_row.addStretch(1)
        self.tag_label = CaptionLabel(fmt["desc"])
        name_row.addWidget(self.tag_label)
        layout.addLayout(name_row)

        self.detail_label = CaptionLabel(fmt["detail"])
        layout.addWidget(self.detail_label)

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self.setProperty("selected", selected)
        self.name_label.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)
        self.name_label.style().unpolish(self.name_label)
        self.name_label.style().polish(self.name_label)
        self.update()

    def mousePressEvent(self, e):
        super().mousePressEvent(e)
        # 让父级 ExportView 处理选中逻辑
        p = self.parent()
        while p and not isinstance(p, ExportView):
            p = p.parent()
        if p:
            p._select_format(self.fmt_key)


# ---------- 主视图 ----------

class ExportView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("exportView")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._dataset: Dataset | None = None
        self._worker: BatchWorker | None = None
        self._progress = None
        self._selected_fmt = "YOLO"

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        root = QVBoxLayout(container)
        root.setContentsMargins(T.PAD_2XL, T.PAD_2XL - 4, T.PAD_2XL, T.PAD_XL)
        root.setSpacing(T.GAP_XL)
        scroll.setWidget(container)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        # ---- Step 1: 选择格式 ----
        root.addWidget(SubtitleLabel("导出向导"))

        step1 = StrongBodyLabel("① 选择导出格式")
        root.addWidget(step1)

        # 格式卡片网格（2列）
        cards_grid = QGridLayout()
        cards_grid.setSpacing(T.GAP)
        self._format_cards: dict[str, _FormatCard] = {}
        for i, fmt in enumerate(_FORMATS):
            card = _FormatCard(fmt)
            self._format_cards[fmt["key"]] = card
            cards_grid.addWidget(card, i // 2, i % 2)
        root.addLayout(cards_grid)

        # ---- Step 2: 配置参数 ----
        step2 = StrongBodyLabel("② 配置参数")
        root.addWidget(step2)

        param_frame = QFrame()
        param_frame.setObjectName("chartFrame")
        param_layout = QVBoxLayout(param_frame)
        param_layout.setContentsMargins(T.PAD_XL, T.PAD_LG, T.PAD_XL, T.PAD_LG)
        param_layout.setSpacing(T.GAP)

        ratio_row = QHBoxLayout()
        ratio_row.setSpacing(T.GAP_LG)
        ratio_row.addWidget(BodyLabel("训练集"))
        self.train_spin = DoubleSpinBox()
        self.train_spin.setRange(0, 1); self.train_spin.setValue(0.8); self.train_spin.setSingleStep(0.05)
        ratio_row.addWidget(self.train_spin)
        ratio_row.addWidget(BodyLabel("验证集"))
        self.val_spin = DoubleSpinBox()
        self.val_spin.setRange(0, 1); self.val_spin.setValue(0.1); self.val_spin.setSingleStep(0.05)
        ratio_row.addWidget(self.val_spin)
        ratio_row.addWidget(BodyLabel("测试集"))
        self.test_spin = DoubleSpinBox()
        self.test_spin.setRange(0, 1); self.test_spin.setValue(0.1); self.test_spin.setSingleStep(0.05)
        ratio_row.addWidget(self.test_spin)
        ratio_row.addStretch(1)
        param_layout.addLayout(ratio_row)

        self.copy_chk = CheckBox("复制图片到导出目录")
        self.copy_chk.setChecked(True)
        param_layout.addWidget(self.copy_chk)

        root.addWidget(param_frame)

        # ---- Step 3: 结构预览（可折叠） ----
        self._preview_btn = PushButton("查看输出结构")
        self._preview_btn.setFixedWidth(160)
        self._preview_btn.clicked.connect(self._toggle_preview)
        root.addWidget(self._preview_btn)

        self._preview_frame = QFrame()
        self._preview_frame.setObjectName("chartFrame")
        preview_layout = QVBoxLayout(self._preview_frame)
        preview_layout.setContentsMargins(T.PAD_XL, T.PAD_LG, T.PAD_XL, T.PAD_LG)
        self._structure_label = CaptionLabel("")
        self._structure_label.setWordWrap(True)
        preview_layout.addWidget(self._structure_label)
        self._preview_frame.hide()
        root.addWidget(self._preview_frame)

        # ---- 导出按钮 ----
        btn_row = QHBoxLayout()
        self.summary_label = BodyLabel("")
        btn_row.addWidget(self.summary_label, 1)
        self.start_btn = PrimaryPushButton("选择目录并导出")
        self.start_btn.setFixedHeight(40)
        self.start_btn.clicked.connect(self._on_start)
        self.start_btn.setEnabled(False)
        btn_row.addWidget(self.start_btn)
        root.addLayout(btn_row)

        # 结果区域
        self.detail_label = CaptionLabel("")
        root.addWidget(self.detail_label)

        root.addStretch(1)

        # 初始选中（所有控件已创建）
        self._select_format("YOLO")

    # ---------- 格式选择 ----------

    def _select_format(self, key: str) -> None:
        self._selected_fmt = key
        for k, card in self._format_cards.items():
            card.set_selected(k == key)
        self._update_structure_preview()

    def _toggle_preview(self) -> None:
        visible = not self._preview_frame.isVisible()
        self._preview_frame.setVisible(visible)
        self._preview_btn.setText("收起输出结构" if visible else "查看输出结构")

    # ---------- 状态持久化 ----------

    def save_state(self):
        from core.project import ExportConfig
        return ExportConfig(
            format=self._selected_fmt,
            copy_images=self.copy_chk.isChecked(),
        )

    def restore_state(self, state) -> None:
        if state is None:
            return
        if state.format in self._format_cards:
            self._select_format(state.format)
        self.copy_chk.setChecked(state.copy_images)

    def set_dataset(self, dataset: Dataset | None) -> None:
        self._dataset = dataset
        on = dataset is not None and sum(c.image_count for c in dataset.categories) > 0
        self.start_btn.setEnabled(on)
        if dataset is None:
            self.summary_label.setText("请先打开项目")
        else:
            n = sum(c.image_count for c in dataset.categories)
            self.summary_label.setText(f"将导出 {n:,} 张图片")

    # ---------- 结构预览 ----------

    def _update_structure_preview(self) -> None:
        fmt = self._selected_fmt
        structures = {
            "YOLO": (
                "<output>/\n"
                "  ├── images/{train,val,test}/   图片按 split 分目录\n"
                "  ├── labels/{train,val,test}/   每张图对应一个 .txt\n"
                "  ├── classes.txt                类别名列表\n"
                "  └── data.yaml                  训练配置文件"
            ),
            "COCO": (
                "<output>/\n"
                "  ├── {train,val,test}/           图片按 split 分目录\n"
                "  └── annotations/\n"
                "      └── instances_{split}.json  COCO 标准标注"
            ),
            "Pascal VOC": (
                "<output>/\n"
                "  ├── JPEGImages/                 所有图片\n"
                "  ├── Annotations/                每张图一个 .xml\n"
                "  └── ImageSets/Main/             train.txt / val.txt / test.txt"
            ),
            "JSON Lines": (
                "<output>/\n"
                "  ├── images/{train,val,test}/    图片（可选）\n"
                "  └── {train,val,test}.jsonl      每行一条 JSON 记录\n\n"
                "  字段：image, width, height, category, annotations[]"
            ),
            "ShareGPT": (
                "<output>/\n"
                "  ├── images/{train,val,test}/    图片\n"
                "  ├── sharegpt_{split}.json       ShareGPT 对话格式\n"
                "  └── dataset_info.json           LLaMA-Factory 注册文件\n\n"
                "  LLaMA-Factory 可直接识别，覆盖主流视觉大模型"
            ),
            "ms-swift": (
                "<output>/\n"
                "  ├── images/{train,val,test}/    图片\n"
                "  └── swift_{split}.jsonl         ms-swift 对话格式\n\n"
                "  适用于 swift sft 命令直接训练 Qwen2.5-VL / InternVL"
            ),
            "LLaVA": (
                "<output>/\n"
                "  ├── images/{train,val,test}/    图片（可选）\n"
                "  └── llava_{split}.jsonl         LLaVA 原生对话格式"
            ),
            "CSV": (
                "<output>/\n"
                "  ├── images/{train,val,test}/    图片（可选）\n"
                "  └── annotations.csv             扁平表格\n\n"
                "  列：image_path, category, label, x1, y1, x2, y2, split"
            ),
        }
        self._structure_label.setText(structures.get(fmt, ""))

    # ---------- 导出 ----------

    def _on_start(self) -> None:
        if self._dataset is None or self._worker is not None:
            return
        out = QFileDialog.getExistingDirectory(self, "选择导出目录")
        if not out:
            return
        self._last_export_dir = out
        self._last_export_fmt = self._selected_fmt

        split = split_dataset(
            self._dataset,
            SplitOptions(
                train=self.train_spin.value(),
                val=self.val_spin.value(),
                test=self.test_spin.value(),
                stratified=True,
            ),
        )

        from gui.dialogs.export_validation_dialog import ExportValidationDialog
        dlg = ExportValidationDialog(split, self._dataset, parent=self.window())
        if not dlg.exec():
            return

        fmt = self._selected_fmt
        copy = self.copy_chk.isChecked()
        out_path = Path(out)
        format_map = {
            "YOLO": (YoloExportOptions(out_dir=out_path, copy_images=copy), export_yolo),
            "COCO": (CocoExportOptions(out_dir=out_path, copy_images=copy), export_coco),
            "Pascal VOC": (VocExportOptions(out_dir=out_path, copy_images=copy), export_voc),
            "JSON Lines": (JsonlExportOptions(out_dir=out_path, copy_images=copy), export_jsonl),
            "ShareGPT": (ShareGptExportOptions(out_dir=out_path, copy_images=copy), export_sharegpt),
            "ms-swift": (SwiftExportOptions(out_dir=out_path, copy_images=copy), export_swift),
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
            f"导出完成：{report.written_images:,} 张图片 · {labels:,} 个标签"
        )
        if report.skipped:
            self.detail_label.setText(f"跳过 {len(report.skipped)} 个文件")
        else:
            self.detail_label.setText("")

        if out_dir:
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

        # 显示训练代码片段
        snippet = self._training_snippet(fmt, out_dir)
        if snippet:
            self._structure_label.setText(snippet)
            self._preview_frame.show()
            self._preview_btn.setText("收起训练代码")

    @staticmethod
    def _training_snippet(fmt: str, out_dir: str) -> str:
        path = out_dir.replace("\\", "/")
        snippets = {
            "YOLO": (
                "复制以下代码开始训练：\n\n"
                "from ultralytics import YOLO\n\n"
                f'model = YOLO("yolov8n.pt")\n'
                f'model.train(data=r"{path}/data.yaml", epochs=100, imgsz=640)'
            ),
            "COCO": (
                "复制以下代码加载数据：\n\n"
                "from detectron2.data.datasets import register_coco_instances\n\n"
                f'register_coco_instances("train", {{}},\n'
                f'    r"{path}/annotations/instances_train.json",\n'
                f'    r"{path}/train")'
            ),
            "Pascal VOC": (
                "复制以下代码加载数据：\n\n"
                "from torchvision.datasets import VOCDetection\n\n"
                f'dataset = VOCDetection(root=r"{path}",\n'
                f'    image_set="train", download=False)'
            ),
            "JSON Lines": (
                "复制以下代码加载数据：\n\n"
                "import json\n\n"
                f'with open(r"{path}/train.jsonl") as f:\n'
                "    for line in f:\n"
                "        sample = json.loads(line)"
            ),
            "ShareGPT": (
                "LLaMA-Factory 一行命令开始训练：\n\n"
                "llamafactory-cli train \\\n"
                f'    --dataset_dir r"{path}" \\\n'
                "    --dataset my_dataset_train \\\n"
                "    --template qwen2_vl \\\n"
                "    --model_name_or_path Qwen/Qwen2.5-VL-7B-Instruct \\\n"
                "    --finetuning_type lora\n\n"
                f"dataset_info.json 已生成，LLaMA-Factory 可直接识别"
            ),
            "ms-swift": (
                "ms-swift 一行命令开始训练：\n\n"
                "swift sft \\\n"
                "    --model Qwen/Qwen2.5-VL-7B-Instruct \\\n"
                f'    --dataset r"{path}/swift_train.jsonl" \\\n'
                "    --train_type lora"
            ),
            "LLaVA": (
                "用于 LLaVA 原生微调：\n\n"
                "python llava/train/train_mem.py \\\n"
                f'    --data_path r"{path}/llava_train.jsonl" \\\n'
                f'    --image_folder r"{path}"'
            ),
            "CSV": (
                "复制以下代码加载分析：\n\n"
                "import pandas as pd\n\n"
                f'df = pd.read_csv(r"{path}/annotations.csv")\n'
                "print(df['label'].value_counts())"
            ),
        }
        return snippets.get(fmt, "")

    def _on_failed(self, msg: str) -> None:
        self._close_progress()
        self._worker = None
        self.start_btn.setEnabled(True)
        self.summary_label.setText(f"导出失败：{msg}")

    def _close_progress(self) -> None:
        if self._progress is not None:
            self._progress.accept()
            self._progress = None
