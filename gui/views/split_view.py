"""数据处理 / 数据集划分：比例 / 数量 / 手动。"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QStackedWidget,
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
    PushButton,
    SpinBox,
    SubtitleLabel,
)

from core.models import Dataset, ImageInfo
from core.splitter import (
    SplitOptions,
    manual_split,
    split_dataset,
    write_split_lists,
)
from gui.theme import T
from gui.widgets.node_workspace import NodeWorkspace


class SplitView(NodeWorkspace):
    go_export = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("splitView")
        self._node_item = None
        self._last_result = None

        root = QVBoxLayout(self)
        root.setContentsMargins(T.PAD_2XL, T.PAD_2XL - 4, T.PAD_2XL, T.PAD_XL)
        root.setSpacing(T.GAP_LG)

        root.addWidget(SubtitleLabel("数据集划分"))

        # 模式选择
        mode_row = QHBoxLayout()
        mode_row.addWidget(BodyLabel("模式"))
        self.mode_combo = ComboBox()
        self.mode_combo.addItems(["按比例", "按数量", "手动选择"])
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        mode_row.addWidget(self.mode_combo)
        mode_row.addSpacing(T.GAP_LG)

        self.stratified_chk = CheckBox("按类别均衡")
        self.stratified_chk.setChecked(True)
        mode_row.addWidget(self.stratified_chk)
        mode_row.addStretch(1)
        root.addLayout(mode_row)

        # 各模式参数面板
        self.param_stack = QStackedWidget()
        self.param_stack.addWidget(self._build_ratio_page())
        self.param_stack.addWidget(self._build_count_page())
        self.param_stack.addWidget(self._build_manual_page())
        root.addWidget(self.param_stack)

        # 公共控制
        ctrl = QHBoxLayout()
        self.preview_btn = PushButton("预览划分结果")
        self.preview_btn.clicked.connect(self._on_preview)
        self.preview_btn.setEnabled(False)
        ctrl.addWidget(self.preview_btn)

        self.export_btn = PrimaryPushButton("写入 train/val/test.txt")
        self.export_btn.clicked.connect(self._on_export)
        self.export_btn.setEnabled(False)
        ctrl.addWidget(self.export_btn)

        self.go_export_btn = PushButton("划分并跳转到导出 →")
        self.go_export_btn.clicked.connect(self._on_go_export)
        self.go_export_btn.setEnabled(False)
        ctrl.addWidget(self.go_export_btn)
        ctrl.addStretch(1)
        root.addLayout(ctrl)

        self.summary_label = BodyLabel("")
        root.addWidget(self.summary_label)
        self.detail_label = CaptionLabel("")
        root.addWidget(self.detail_label)
        root.addStretch(1)

        # Wire controls → immediate write-back
        self.train_spin.valueChanged.connect(self._push_params)
        self.val_spin.valueChanged.connect(self._push_params)
        self.test_spin.valueChanged.connect(self._push_params)
        self.stratified_chk.stateChanged.connect(self._push_params)

    # ---------- 子页 ----------

    def _build_ratio_page(self) -> QWidget:
        page = QWidget()
        grid = QGridLayout(page)
        grid.setHorizontalSpacing(T.GAP_LG)
        grid.setVerticalSpacing(T.GAP)

        grid.addWidget(BodyLabel("Train"), 0, 0)
        self.train_spin = DoubleSpinBox()
        self.train_spin.setRange(0, 1)
        self.train_spin.setSingleStep(0.05)
        self.train_spin.setValue(0.8)
        grid.addWidget(self.train_spin, 0, 1)

        grid.addWidget(BodyLabel("Val"), 0, 2)
        self.val_spin = DoubleSpinBox()
        self.val_spin.setRange(0, 1)
        self.val_spin.setSingleStep(0.05)
        self.val_spin.setValue(0.1)
        grid.addWidget(self.val_spin, 0, 3)

        grid.addWidget(BodyLabel("Test"), 0, 4)
        self.test_spin = DoubleSpinBox()
        self.test_spin.setRange(0, 1)
        self.test_spin.setSingleStep(0.05)
        self.test_spin.setValue(0.1)
        grid.addWidget(self.test_spin, 0, 5)

        grid.addWidget(BodyLabel("随机种子"), 1, 0)
        self.seed_spin = SpinBox()
        self.seed_spin.setRange(0, 999999)
        self.seed_spin.setValue(42)
        grid.addWidget(self.seed_spin, 1, 1)
        return page

    def _build_count_page(self) -> QWidget:
        page = QWidget()
        grid = QGridLayout(page)
        grid.setHorizontalSpacing(T.GAP_LG)
        grid.setVerticalSpacing(T.GAP)

        grid.addWidget(BodyLabel("Train 张数"), 0, 0)
        self.train_n_spin = SpinBox()
        self.train_n_spin.setRange(0, 10_000_000)
        self.train_n_spin.setValue(0)
        self.train_n_spin.setToolTip("0 = 剩余全部")
        grid.addWidget(self.train_n_spin, 0, 1)

        grid.addWidget(BodyLabel("Val 张数"), 0, 2)
        self.val_n_spin = SpinBox()
        self.val_n_spin.setRange(0, 10_000_000)
        self.val_n_spin.setValue(100)
        grid.addWidget(self.val_n_spin, 0, 3)

        grid.addWidget(BodyLabel("Test 张数"), 0, 4)
        self.test_n_spin = SpinBox()
        self.test_n_spin.setRange(0, 10_000_000)
        self.test_n_spin.setValue(100)
        grid.addWidget(self.test_n_spin, 0, 5)

        grid.addWidget(CaptionLabel("Train=0 表示剩余全部归 train"), 1, 0, 1, 6)
        return page

    def _build_manual_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(T.GAP)

        layout.addWidget(CaptionLabel(
            "在「浏览」页用 Ctrl/Shift 多选,然后右键 → 加入 Train/Val/Test。"
        ))

        # 三个桶
        buckets = QHBoxLayout()
        for name in ("train", "val", "test"):
            col = QVBoxLayout()
            col.addWidget(BodyLabel(name.upper()))
            lst = QListWidget()
            lst.setObjectName(f"manual_{name}_list")
            lst.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
            setattr(self, f"manual_{name}_list", lst)
            col.addWidget(lst, 1)
            row = QHBoxLayout()
            clear_btn = PushButton("清空")
            clear_btn.clicked.connect(lambda _=False, n=name: self._manual_clear(n))
            remove_btn = PushButton("移除选中")
            remove_btn.clicked.connect(lambda _=False, n=name: self._manual_remove(n))
            row.addWidget(remove_btn)
            row.addWidget(clear_btn)
            row.addStretch(1)
            col.addLayout(row)
            buckets.addLayout(col, 1)
        layout.addLayout(buckets, 1)
        return page

    # ---------- 接口 ----------

    def save_state(self):
        from core.project import SplitState
        mode_map = {0: "ratio", 1: "count", 2: "manual"}
        # Collect manual bucket paths
        manual_train = [self.manual_train_list.item(i).data(Qt.ItemDataRole.UserRole)
                        for i in range(self.manual_train_list.count())]
        manual_val = [self.manual_val_list.item(i).data(Qt.ItemDataRole.UserRole)
                      for i in range(self.manual_val_list.count())]
        manual_test = [self.manual_test_list.item(i).data(Qt.ItemDataRole.UserRole)
                       for i in range(self.manual_test_list.count())]
        return SplitState(
            mode=mode_map.get(self.mode_combo.currentIndex(), "ratio"),
            train=self.train_spin.value(),
            val=self.val_spin.value(),
            test=self.test_spin.value(),
            stratified=self.stratified_chk.isChecked(),
            manual_train=manual_train,
            manual_val=manual_val,
            manual_test=manual_test,
        )

    def restore_state(self, state) -> None:
        if state is None:
            return
        mode_map = {"ratio": 0, "count": 1, "manual": 2}
        self.mode_combo.setCurrentIndex(mode_map.get(state.mode, 0))
        self.train_spin.setValue(state.train)
        self.val_spin.setValue(state.val)
        self.test_spin.setValue(state.test)
        self.stratified_chk.setChecked(state.stratified)

    def set_dataset(self, dataset: Dataset | None) -> None:
        self._dataset = dataset
        on = dataset is not None and sum(c.image_count for c in dataset.categories) > 0
        self.preview_btn.setEnabled(on)
        self.export_btn.setEnabled(False)
        self._last_result = None
        if dataset is None:
            self.summary_label.setText("请先加载数据集。")
        else:
            n = sum(c.image_count for c in dataset.categories)
            self.summary_label.setText(f"共 {n:,} 张图片，{len(dataset.categories)} 类")
        for n in ("train", "val", "test"):
            getattr(self, f"manual_{n}_list").clear()

    def bind_node(self, node_item) -> None:
        self._node_item = node_item
        params = node_item.get_params() if node_item else {}
        for name, default in [("train_ratio", 0.8), ("val_ratio", 0.1), ("test_ratio", 0.1)]:
            spin = getattr(self, f"{name.split('_')[0]}_spin")
            spin.blockSignals(True)
            spin.setValue(float(params.get(name, default)))
            spin.blockSignals(False)
        self.stratified_chk.blockSignals(True)
        self.stratified_chk.setChecked(bool(params.get("stratified", True)))
        self.stratified_chk.blockSignals(False)

    def _push_params(self) -> None:
        if self._node_item is None:
            return
        self._node_item.set_params({
            "train_ratio": self.train_spin.value(),
            "val_ratio": self.val_spin.value(),
            "test_ratio": self.test_spin.value(),
            "stratified": self.stratified_chk.isChecked(),
        })


    def add_to_manual_bucket(self, bucket: str, images: list[ImageInfo]) -> None:
        """供 BrowserView 右键菜单调用,把多选图片塞进 manual 桶。"""
        if bucket not in ("train", "val", "test"):
            return
        lst: QListWidget = getattr(self, f"manual_{bucket}_list")
        existing = {lst.item(i).data(Qt.ItemDataRole.UserRole) for i in range(lst.count())}
        for img in images:
            key = str(img.path)
            if key in existing:
                continue
            item = QListWidgetItem(f"{img.category} / {img.path.name}")
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setData(Qt.ItemDataRole.UserRole + 1, img)
            lst.addItem(item)
        # 自动切到 manual 模式
        self.mode_combo.setCurrentIndex(2)

    # ---------- 内部 ----------

    def _on_mode_changed(self, idx: int) -> None:
        self.param_stack.setCurrentIndex(idx)
        self.stratified_chk.setEnabled(idx != 2)  # manual 不需要均衡

    def _manual_clear(self, name: str) -> None:
        getattr(self, f"manual_{name}_list").clear()

    def _manual_remove(self, name: str) -> None:
        lst: QListWidget = getattr(self, f"manual_{name}_list")
        for it in lst.selectedItems():
            lst.takeItem(lst.row(it))

    def _build_opts(self) -> SplitOptions:
        modes = ["ratio", "count", "manual"]
        return SplitOptions(
            mode=modes[self.mode_combo.currentIndex()],
            train=self.train_spin.value(),
            val=self.val_spin.value(),
            test=self.test_spin.value(),
            train_n=self.train_n_spin.value(),
            val_n=self.val_n_spin.value(),
            test_n=self.test_n_spin.value(),
            seed=self.seed_spin.value(),
            stratified=self.stratified_chk.isChecked(),
        )

    def _collect_manual(self):
        out = {}
        for n in ("train", "val", "test"):
            lst: QListWidget = getattr(self, f"manual_{n}_list")
            out[n] = [
                lst.item(i).data(Qt.ItemDataRole.UserRole + 1)
                for i in range(lst.count())
            ]
        return out

    def _on_preview(self) -> None:
        if self._dataset is None:
            return
        opts = self._build_opts()
        if opts.mode == "manual":
            buckets = self._collect_manual()
            result = manual_split(buckets["train"], buckets["val"], buckets["test"])
        else:
            result = split_dataset(self._dataset, opts)
        self._last_result = result
        n_tr, n_va, n_te = result.counts
        self.summary_label.setText(
            f"train {n_tr:,}  ·  val {n_va:,}  ·  test {n_te:,}"
        )
        self.detail_label.setText("点击「写入」将路径列表保存到指定目录")
        self.export_btn.setEnabled(n_tr + n_va + n_te > 0)
        self.go_export_btn.setEnabled(n_tr + n_va + n_te > 0)

    def _on_export(self) -> None:
        if self._last_result is None:
            return
        out = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if not out:
            return
        written = write_split_lists(self._last_result, Path(out))
        names = " · ".join(p.name for p in written.values())
        self.detail_label.setText(f"已写入：{out}  ({names})")

    def _on_go_export(self) -> None:
        """预览划分 → 跳转到导出向导。"""
        if self._last_result is None:
            self._on_preview()
        if self._last_result:
            self.go_export.emit()
