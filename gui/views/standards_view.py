"""数据规范视图 — 配置采集标准、生成规范文档、校验数据合规性。"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
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
    SubtitleLabel,
    TextEdit,
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
        self._standard: DataStandard = DataStandard()

        root = QVBoxLayout(self)
        root.setContentsMargins(T.PAD_XL + 12, T.PAD_XL + 8, T.PAD_XL + 12, T.PAD_XL)
        root.setSpacing(T.GAP_LG)

        root.addWidget(SubtitleLabel("数据采集规范"))
        root.addWidget(CaptionLabel("定义数据标准 → 生成规范文档发给甲方 → 校验入库数据是否合规"))

        # ---- 类别定义 ----
        root.addWidget(BodyLabel("类别定义"))
        cat_row = QHBoxLayout()
        self.cat_list = QListWidget()
        self.cat_list.setMaximumHeight(160)
        cat_row.addWidget(self.cat_list, 1)

        cat_btns = QVBoxLayout()
        self.add_cat_btn = PushButton("添加类别")
        self.add_cat_btn.clicked.connect(self._on_add_category)
        self.rm_cat_btn = PushButton("删除选中")
        self.rm_cat_btn.clicked.connect(self._on_remove_category)
        self.import_cat_btn = PushButton("从数据集导入")
        self.import_cat_btn.clicked.connect(self._on_import_categories)
        cat_btns.addWidget(self.add_cat_btn)
        cat_btns.addWidget(self.rm_cat_btn)
        cat_btns.addWidget(self.import_cat_btn)
        cat_btns.addStretch(1)
        cat_row.addLayout(cat_btns)
        root.addLayout(cat_row)

        # 类别描述编辑
        desc_row = QHBoxLayout()
        desc_row.addWidget(CaptionLabel("选中类别描述："))
        self.cat_desc_edit = LineEdit()
        self.cat_desc_edit.setPlaceholderText("输入该缺陷类别的定义说明（给甲方看）")
        self.cat_desc_edit.textChanged.connect(self._on_desc_changed)
        desc_row.addWidget(self.cat_desc_edit, 1)
        root.addLayout(desc_row)

        # ---- 图片要求 ----
        root.addWidget(BodyLabel("图片要求"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(T.GAP_XL)
        grid.setVerticalSpacing(T.GAP)

        grid.addWidget(CaptionLabel("格式"), 0, 0)
        self.formats_edit = LineEdit()
        self.formats_edit.setText(".jpg, .png")
        self.formats_edit.setToolTip("逗号分隔，如 .jpg, .png, .bmp")
        grid.addWidget(self.formats_edit, 0, 1)

        grid.addWidget(CaptionLabel("最小分辨率"), 0, 2)
        self.min_w_spin = SpinBox()
        self.min_w_spin.setRange(1, 10000)
        self.min_w_spin.setValue(640)
        grid.addWidget(self.min_w_spin, 0, 3)
        grid.addWidget(CaptionLabel("×"), 0, 4)
        self.min_h_spin = SpinBox()
        self.min_h_spin.setRange(1, 10000)
        self.min_h_spin.setValue(480)
        grid.addWidget(self.min_h_spin, 0, 5)

        grid.addWidget(CaptionLabel("最大文件大小 (MB)"), 1, 0)
        self.max_size_spin = DoubleSpinBox()
        self.max_size_spin.setRange(0.1, 1000)
        self.max_size_spin.setValue(10.0)
        grid.addWidget(self.max_size_spin, 1, 1)

        grid.addWidget(CaptionLabel("每类最少图片数"), 1, 2)
        self.min_count_spin = SpinBox()
        self.min_count_spin.setRange(1, 100000)
        self.min_count_spin.setValue(50)
        grid.addWidget(self.min_count_spin, 1, 3)

        self.require_labels_chk = CheckBox("要求甲方提供标注文件")
        grid.addWidget(self.require_labels_chk, 2, 0, 1, 4)

        root.addLayout(grid)

        # ---- 命名规则 ----
        naming_row = QHBoxLayout()
        naming_row.addWidget(CaptionLabel("命名规则（正则）："))
        self.naming_edit = LineEdit()
        self.naming_edit.setText(r"[a-zA-Z0-9_\-]+")
        naming_row.addWidget(self.naming_edit, 1)
        naming_row.addWidget(CaptionLabel("示例："))
        self.naming_example_edit = LineEdit()
        self.naming_example_edit.setText("crack_001.jpg")
        naming_row.addWidget(self.naming_example_edit)
        root.addLayout(naming_row)

        # ---- 操作按钮 ----
        btn_row = QHBoxLayout()
        self.gen_doc_btn = PrimaryPushButton("生成采集规范文档")
        self.gen_doc_btn.clicked.connect(self._on_generate_doc)
        self.gen_dirs_btn = PushButton("生成空目录结构")
        self.gen_dirs_btn.clicked.connect(self._on_generate_dirs)
        self.validate_btn = PushButton("校验当前数据集")
        self.validate_btn.clicked.connect(self._on_validate)
        self.validate_btn.setEnabled(False)
        btn_row.addWidget(self.gen_doc_btn)
        btn_row.addWidget(self.gen_dirs_btn)
        btn_row.addWidget(self.validate_btn)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

        # ---- 校验结果 ----
        self.result_label = BodyLabel("")
        root.addWidget(self.result_label)
        self.issues_list = QListWidget()
        self.issues_list.setMaximumHeight(200)
        self.issues_list.hide()
        root.addWidget(self.issues_list)

        root.addStretch(1)

    # ---------- 外部接口 ----------

    def set_dataset(self, dataset: Dataset | None) -> None:
        self._dataset = dataset
        self.validate_btn.setEnabled(dataset is not None)

    def get_standard(self) -> DataStandard:
        """Collect current form values into a DataStandard."""
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
            naming_pattern=self.naming_edit.text(),
            naming_example=self.naming_example_edit.text(),
            min_images_per_category=self.min_count_spin.value(),
            require_labels=self.require_labels_chk.isChecked(),
        )

    def set_standard(self, standard: DataStandard) -> None:
        """Populate form from a DataStandard (e.g., loaded from project)."""
        self._standard = standard
        self.cat_list.clear()
        for cat in standard.categories:
            item = QListWidgetItem(cat.name)
            item.setData(Qt.ItemDataRole.UserRole, cat.description)
            self.cat_list.addItem(item)
        self.formats_edit.setText(", ".join(standard.image_formats))
        self.min_w_spin.setValue(standard.min_resolution[0])
        self.min_h_spin.setValue(standard.min_resolution[1])
        self.max_size_spin.setValue(standard.max_file_size_mb)
        self.min_count_spin.setValue(standard.min_images_per_category)
        self.require_labels_chk.setChecked(standard.require_labels)
        self.naming_edit.setText(standard.naming_pattern)
        self.naming_example_edit.setText(standard.naming_example)

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
        for cat in self._dataset.categories:
            if cat.name not in existing:
                item = QListWidgetItem(cat.name)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                item.setData(Qt.ItemDataRole.UserRole, "")
                self.cat_list.addItem(item)

    def _on_desc_changed(self, text: str) -> None:
        items = self.cat_list.selectedItems()
        if items:
            items[0].setData(Qt.ItemDataRole.UserRole, text)

    # ---------- 生成/校验 ----------

    def _on_generate_doc(self) -> None:
        out = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if not out:
            return
        standard = self.get_standard()
        name = self._dataset.name if self._dataset else "数据集"
        doc_path = generate_standard_doc(standard, name, Path(out))
        InfoBar.success(
            title="规范文档已生成",
            content=str(doc_path),
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=5000,
            parent=self.window(),
        )

    def _on_generate_dirs(self) -> None:
        out = QFileDialog.getExistingDirectory(self, "选择根目录（将在此目录下创建文件夹）")
        if not out:
            return
        standard = self.get_standard()
        generate_empty_structure(standard, Path(out))
        InfoBar.success(
            title="空目录结构已创建",
            content=f"在 {out} 下创建了 {len(standard.categories)} 个类别文件夹",
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=4000,
            parent=self.window(),
        )

    def _on_validate(self) -> None:
        if not self._dataset:
            return
        standard = self.get_standard()
        issues = validate_against_standard(self._dataset, standard)

        self.issues_list.clear()
        if not issues:
            self.result_label.setText("所有检查通过，数据集符合规范。")
            self.issues_list.hide()
            return

        errors = [i for i in issues if i.severity == "error"]
        warnings = [i for i in issues if i.severity == "warning"]
        self.result_label.setText(f"发现 {len(errors)} 个错误、{len(warnings)} 个警告")

        for issue in issues[:200]:
            prefix = "❌" if issue.severity == "error" else "⚠"
            self.issues_list.addItem(f"{prefix} {issue.message}")
        self.issues_list.show()
