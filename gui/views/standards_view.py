"""数据规范视图 — 为甲方生成采集规范、校验入库数据。

设计思路：
  甲方视角 → "告诉我怎么拍照、怎么存文件" → 生成文档 + 空目录
  乙方视角 → "验证甲方交的数据合不合格" → 一键校验
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CheckBox,
    DoubleSpinBox,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    SpinBox,
    StrongBodyLabel,
    SubtitleLabel,
)

from core.models import Dataset
from core.standards import (
    CategorySpec,
    DataStandard,
    ValidationIssue,
    generate_empty_structure,
    generate_standard_doc,
    validate_against_standard,
)
from gui.theme import T


class StandardsView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("standardsView")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._dataset: Dataset | None = None

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

        root.addWidget(SubtitleLabel("数据采集规范"))

        # ============ 区域 1：类别定义 ============
        self._add_section(root, "① 定义数据类别", "")

        cat_frame = QFrame()
        cat_frame.setObjectName("chartFrame")
        cat_layout = QVBoxLayout(cat_frame)
        cat_layout.setContentsMargins(T.PAD_XL, T.PAD_LG, T.PAD_XL, T.PAD_LG)
        cat_layout.setSpacing(T.GAP)

        # 类别列表
        self.cat_list = QListWidget()
        self.cat_list.setMaximumHeight(150)
        self.cat_list.currentRowChanged.connect(self._on_cat_row_changed)
        cat_layout.addWidget(self.cat_list)

        cat_btn_row = QHBoxLayout()
        self.add_cat_btn = PushButton("添加类别")
        self.add_cat_btn.clicked.connect(self._on_add_category)
        self.rm_cat_btn = PushButton("删除")
        self.rm_cat_btn.clicked.connect(self._on_remove_category)
        self.import_cat_btn = PushButton("从当前数据集导入")
        self.import_cat_btn.clicked.connect(self._on_import_categories)
        cat_btn_row.addWidget(self.add_cat_btn)
        cat_btn_row.addWidget(self.rm_cat_btn)
        cat_btn_row.addWidget(self.import_cat_btn)
        cat_btn_row.addStretch(1)
        cat_layout.addLayout(cat_btn_row)

        # 选中类别的描述
        cat_layout.addWidget(CaptionLabel("类别说明（给采集方看的描述）："))
        self.cat_desc_edit = LineEdit()
        self.cat_desc_edit.setPlaceholderText("例如：表面裂纹，通常呈线性延伸；或：猫，四肢动物")
        self.cat_desc_edit.textChanged.connect(self._on_desc_changed)
        cat_layout.addWidget(self.cat_desc_edit)

        root.addWidget(cat_frame)

        # ============ 区域 2：图片要求 ============
        self._add_section(root, "② 图片采集要求", "")

        req_frame = QFrame()
        req_frame.setObjectName("chartFrame")
        req_layout = QGridLayout(req_frame)
        req_layout.setContentsMargins(T.PAD_XL, T.PAD_LG, T.PAD_XL, T.PAD_LG)
        req_layout.setHorizontalSpacing(T.GAP_XL)
        req_layout.setVerticalSpacing(T.GAP_LG)

        req_layout.addWidget(BodyLabel("图片格式"), 0, 0)
        self.formats_edit = LineEdit()
        self.formats_edit.setText(".jpg, .png")
        self.formats_edit.setPlaceholderText("如 .jpg, .png, .bmp")
        req_layout.addWidget(self.formats_edit, 0, 1)

        req_layout.addWidget(BodyLabel("最小分辨率"), 0, 2)
        res_row = QHBoxLayout()
        self.min_w_spin = SpinBox()
        self.min_w_spin.setRange(1, 10000); self.min_w_spin.setValue(640)
        res_row.addWidget(self.min_w_spin)
        res_row.addWidget(CaptionLabel("×"))
        self.min_h_spin = SpinBox()
        self.min_h_spin.setRange(1, 10000); self.min_h_spin.setValue(480)
        res_row.addWidget(self.min_h_spin)
        res_row.addWidget(CaptionLabel("像素"))
        req_layout.addLayout(res_row, 0, 3)

        req_layout.addWidget(BodyLabel("单张最大"), 1, 0)
        size_row = QHBoxLayout()
        self.max_size_spin = DoubleSpinBox()
        self.max_size_spin.setRange(0.1, 1000); self.max_size_spin.setValue(10.0)
        size_row.addWidget(self.max_size_spin)
        size_row.addWidget(CaptionLabel("MB"))
        req_layout.addLayout(size_row, 1, 1)

        req_layout.addWidget(BodyLabel("每类至少"), 1, 2)
        count_row = QHBoxLayout()
        self.min_count_spin = SpinBox()
        self.min_count_spin.setRange(1, 100000); self.min_count_spin.setValue(50)
        count_row.addWidget(self.min_count_spin)
        count_row.addWidget(CaptionLabel("张图片"))
        req_layout.addLayout(count_row, 1, 3)

        self.require_labels_chk = CheckBox("要求采集方同时提供标注文件")
        req_layout.addWidget(self.require_labels_chk, 2, 0, 1, 4)

        root.addWidget(req_frame)

        # ============ 操作区 ============
        self._add_section(root, "③ 生成与校验", "")

        action_frame = QFrame()
        action_frame.setObjectName("chartFrame")
        action_layout = QVBoxLayout(action_frame)
        action_layout.setContentsMargins(T.PAD_XL, T.PAD_LG, T.PAD_XL, T.PAD_LG)
        action_layout.setSpacing(T.GAP_LG)

        # 生成行
        gen_row = QHBoxLayout()
        gen_row.setSpacing(T.GAP_LG)
        self.gen_doc_btn = PrimaryPushButton("生成采集规范文档")
        self.gen_doc_btn.setFixedHeight(40)
        self.gen_doc_btn.clicked.connect(self._on_generate_doc)
        gen_row.addWidget(self.gen_doc_btn)

        self.gen_dirs_btn = PushButton("生成空目录模板")
        self.gen_dirs_btn.setFixedHeight(40)
        self.gen_dirs_btn.clicked.connect(self._on_generate_dirs)
        gen_row.addWidget(self.gen_dirs_btn)
        gen_row.addStretch(1)
        action_layout.addLayout(gen_row)

        self.gen_doc_btn.setToolTip("输出 Markdown 规范文档，发给采集方照着做")
        self.gen_dirs_btn.setToolTip("创建规范的空文件夹结构，采集方往里放图片即可")

        # 校验行
        validate_row = QHBoxLayout()
        self.validate_btn = PushButton("校验当前数据集")
        self.validate_btn.setFixedHeight(36)
        self.validate_btn.clicked.connect(self._on_validate)
        self.validate_btn.setEnabled(False)
        validate_row.addWidget(self.validate_btn)
        self.validate_result = CaptionLabel("")
        validate_row.addWidget(self.validate_result, 1)
        action_layout.addLayout(validate_row)

        root.addWidget(action_frame)

        # 校验结果列表
        self.issues_list = QListWidget()
        self.issues_list.setMaximumHeight(200)
        self.issues_list.hide()
        root.addWidget(self.issues_list)

        root.addStretch(1)

    @staticmethod
    def _add_section(layout: QVBoxLayout, title: str, desc: str) -> None:
        lbl = StrongBodyLabel(title)
        layout.addWidget(lbl)
        if desc:
            layout.addWidget(CaptionLabel(desc))

    # ---------- 外部接口 ----------

    def set_dataset(self, dataset: Dataset | None) -> None:
        self._dataset = dataset
        self.validate_btn.setEnabled(dataset is not None)

    def get_standard(self) -> DataStandard:
        cats = []
        for i in range(self.cat_list.count()):
            item = self.cat_list.item(i)
            cats.append(CategorySpec(
                name=item.text(),
                description=item.data(Qt.ItemDataRole.UserRole) or "",
            ))
        fmts = [f.strip() for f in self.formats_edit.text().split(",") if f.strip()]
        return DataStandard(
            categories=cats,
            image_formats=fmts or [".jpg", ".png"],
            min_resolution=(self.min_w_spin.value(), self.min_h_spin.value()),
            max_file_size_mb=self.max_size_spin.value(),
            min_images_per_category=self.min_count_spin.value(),
            require_labels=self.require_labels_chk.isChecked(),
        )

    def set_standard(self, standard: DataStandard) -> None:
        self.cat_list.clear()
        for cat in standard.categories:
            item = QListWidgetItem(cat.name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            item.setData(Qt.ItemDataRole.UserRole, cat.description)
            self.cat_list.addItem(item)
        self.formats_edit.setText(", ".join(standard.image_formats))
        self.min_w_spin.setValue(standard.min_resolution[0])
        self.min_h_spin.setValue(standard.min_resolution[1])
        self.max_size_spin.setValue(standard.max_file_size_mb)
        self.min_count_spin.setValue(standard.min_images_per_category)
        self.require_labels_chk.setChecked(standard.require_labels)

    # ---------- 类别操作 ----------

    def _on_add_category(self) -> None:
        item = QListWidgetItem("新类别")
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        item.setData(Qt.ItemDataRole.UserRole, "")
        self.cat_list.addItem(item)
        self.cat_list.editItem(item)

    def _on_remove_category(self) -> None:
        for item in self.cat_list.selectedItems():
            self.cat_list.takeItem(self.cat_list.row(item))

    def _on_import_categories(self) -> None:
        if not self._dataset:
            return
        existing = {self.cat_list.item(i).text() for i in range(self.cat_list.count())}
        added = 0
        for cat in self._dataset.categories:
            if cat.name not in existing:
                item = QListWidgetItem(cat.name)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                item.setData(Qt.ItemDataRole.UserRole, "")
                self.cat_list.addItem(item)
                added += 1
        if added:
            InfoBar.success(
                title=f"已导入 {added} 个类别",
                content="请为每个类别补充说明文字",
                isClosable=True, position=InfoBarPosition.TOP,
                duration=3000, parent=self.window(),
            )

    def _on_cat_row_changed(self, row: int) -> None:
        if row < 0:
            self.cat_desc_edit.clear()
            return
        item = self.cat_list.item(row)
        self.cat_desc_edit.setText(item.data(Qt.ItemDataRole.UserRole) or "")

    def _on_desc_changed(self, text: str) -> None:
        items = self.cat_list.selectedItems()
        if items:
            items[0].setData(Qt.ItemDataRole.UserRole, text)

    # ---------- 生成 ----------

    def _on_generate_doc(self) -> None:
        out = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if not out:
            return
        standard = self.get_standard()
        name = self._dataset.name if self._dataset else "数据集"
        try:
            doc_path = generate_standard_doc(standard, name, Path(out))
            import subprocess, sys
            bar = InfoBar.success(
                title="规范文档已生成",
                content=str(doc_path),
                isClosable=True, position=InfoBarPosition.TOP,
                duration=-1, parent=self.window(),
            )
            from qfluentwidgets import PushButton
            open_btn = PushButton("打开文件夹")
            open_btn.clicked.connect(
                lambda: subprocess.Popen(["explorer", out])
                if sys.platform == "win32" else None
            )
            bar.addWidget(open_btn)
        except Exception as e:
            InfoBar.error(
                title="生成失败", content=str(e),
                isClosable=True, position=InfoBarPosition.TOP,
                duration=5000, parent=self.window(),
            )

    def _on_generate_dirs(self) -> None:
        out = QFileDialog.getExistingDirectory(self, "选择根目录")
        if not out:
            return
        standard = self.get_standard()
        generate_empty_structure(standard, Path(out))
        InfoBar.success(
            title="空目录已创建",
            content=f"在 {out} 下创建了 {len(standard.categories)} 个类别文件夹",
            isClosable=True, position=InfoBarPosition.TOP,
            duration=4000, parent=self.window(),
        )

    def _on_validate(self) -> None:
        if not self._dataset:
            return
        standard = self.get_standard()
        issues = validate_against_standard(self._dataset, standard)

        self.issues_list.clear()
        if not issues:
            self.validate_result.setText("✓ 所有检查通过，数据集符合规范")
            self.issues_list.hide()
            return

        errors = [i for i in issues if i.severity == "error"]
        warnings = [i for i in issues if i.severity == "warning"]
        self.validate_result.setText(f"{len(errors)} 个不合格项 · {len(warnings)} 个建议")

        for issue in issues[:200]:
            prefix = "✗" if issue.severity == "error" else "!"
            self.issues_list.addItem(f"  {prefix}  {issue.message}")
        self.issues_list.show()
