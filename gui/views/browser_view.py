"""Browser view: category tree + filter bar + thumbnail grid + pagination."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QMenu,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    FluentIcon as FIF,
    IndeterminateProgressBar,
    LineEdit,
    MessageBox,
    ToolButton,
)

from core import fileops, index_cache, transform as tx
from core.convert import convert_batch
from core.exporter.subset import export_subset
from core.models import Dataset, ImageInfo
from gui.dialogs.op_dialogs import (
    ConvertDialog,
    CropDialog,
    FailureDetailDialog,
    FlipDialog,
    MoveToCategoryDialog,
    ProgressDialog,
    RenameDialog,
    ResizeDialog,
    RotateDialog,
)
from gui.theme import T
from gui.widgets.category_tree import CategoryTree
from gui.widgets.chips import FilterChip, GhostButton
from gui.widgets.thumbnail_grid import ThumbnailGrid
from gui.workers.batch_worker import BatchWorker

PAGE_SIZE = 40


class BrowserView(QWidget):
    image_activated = pyqtSignal(object, list)  # (current ImageInfo, full list)
    thumb_request = pyqtSignal(object)          # Path
    clear_thumb_queue = pyqtSignal()            # clear pending thumbnail requests
    add_to_split = pyqtSignal(str, list)        # (bucket name, list[ImageInfo])
    navigate_to = pyqtSignal(str)               # route key for readiness bar links
    dataset_changed = pyqtSignal()              # emitted after category rename/merge/split

    def __init__(self, app_state=None) -> None:
        super().__init__()
        self.setObjectName("browserView")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        # AppState is the single source of truth for the current Dataset.
        # Injected from DatasetBrowserView. A fallback minimal stub keeps
        # the view constructable in isolation (tests) but never stores a
        # dataset itself.
        if app_state is None:
            from gui.app_state import AppState
            app_state = AppState(parent=self)
        self._state = app_state
        self._current_category: str = ""
        self._filter_mode: str = "all"   # all / labeled / unlabeled / issues
        self._search_text: str = ""
        self._page: int = 0
        self._filtered: list[ImageInfo] = []
        # Quality issues map: path str → list of kinds — ephemeral UI state
        # that never outlives the session, kept here (not in AppState) on
        # purpose so reloading the dataset clears it.
        self._quality_map: dict[str, list[str]] = {}

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 左侧类别树
        left = QFrame()
        left.setObjectName("categorySidebar")
        left.setFixedWidth(T.SIDEBAR_WIDTH)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        header = CaptionLabel("  " + self.tr("类别"))
        header.setObjectName("sectionHeader")
        header.setFixedHeight(44)
        left_layout.addWidget(header)

        self.tree = CategoryTree()
        self.tree.category_selected.connect(self._on_category_selected)
        self.tree.rename_requested.connect(self._do_rename_category)
        self.tree.merge_requested.connect(self._do_merge_categories)
        self.tree.split_requested.connect(self._do_split_category)
        left_layout.addWidget(self.tree)

        root.addWidget(left)

        # 右侧主区
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(T.PAD_XL, T.PAD_LG, T.PAD_XL, T.GAP_LG)
        right_layout.setSpacing(T.PAD)

        # 就绪检查条（替代独立概览页 — 核心设计：输出是已知格子，缺什么补什么）
        self._readiness_bar = QHBoxLayout()
        self._readiness_bar.setSpacing(T.GAP_LG)
        self._readiness_items: list[QWidget] = []
        right_layout.addLayout(self._readiness_bar)

        # 筛选栏
        filter_bar = QHBoxLayout()
        filter_bar.setSpacing(T.GAP)

        from PyQt6.QtCore import QTimer
        self.search = LineEdit()
        self.search.setPlaceholderText(self.tr("搜索文件名…"))
        self.search.setFixedWidth(280)
        self.search.setFixedHeight(32)
        # 300ms debounce — 不在每次按键时都重新过滤
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(lambda: self._on_search_changed(self.search.text()))
        self.search.textChanged.connect(lambda _: self._search_timer.start())
        filter_bar.addWidget(self.search)

        self.chip_group = QButtonGroup(self)
        self.chip_group.setExclusive(True)
        self._chips: dict[str, FilterChip] = {}
        for key, label in [
            ("all", self.tr("全部")),
            ("labeled", self.tr("已标注")),
            ("unlabeled", self.tr("未标注")),
            ("issues", self.tr("有问题")),
        ]:
            chip = FilterChip(label)
            chip.setProperty("filterKey", key)
            chip.clicked.connect(lambda _c=False, k=key: self._on_filter_changed(k))
            self.chip_group.addButton(chip)
            filter_bar.addWidget(chip)
            self._chips[key] = chip
            if key == "all":
                chip.setChecked(True)
        # "有问题" only meaningful after a quality check ran
        self._chips["issues"].setEnabled(False)

        filter_bar.addStretch(1)

        self.selection_label = CaptionLabel("")
        filter_bar.addWidget(self.selection_label)

        right_layout.addLayout(filter_bar)

        # 缩略图网格
        self.grid = ThumbnailGrid()
        self.grid.item_activated.connect(self._on_item_activated)
        self.grid.selection_changed.connect(self._on_selection_changed)
        self.grid.request_thumb.connect(lambda p: self.thumb_request.emit(p))
        self.grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self._on_context_menu)
        self._worker: BatchWorker | None = None
        self._progress: ProgressDialog | None = None
        right_layout.addWidget(self.grid, 1)

        # 分页栏
        from qfluentwidgets import SpinBox
        pager = QHBoxLayout()
        pager.setSpacing(T.GAP)
        self.prev_btn = ToolButton(FIF.LEFT_ARROW)
        self.prev_btn.clicked.connect(self._prev_page)
        self.next_btn = ToolButton(FIF.RIGHT_ARROW)
        self.next_btn.clicked.connect(self._next_page)
        self.page_spin = SpinBox()
        self.page_spin.setFixedWidth(80)
        self.page_spin.setRange(1, 1)
        self.page_spin.editingFinished.connect(self._on_page_jump)
        self.page_total_label = CaptionLabel("/ 1")
        self.count_label = CaptionLabel("")
        pager.addStretch(1)
        pager.addWidget(self.count_label)
        pager.addSpacing(T.GAP_LG)
        pager.addWidget(self.prev_btn)
        pager.addWidget(CaptionLabel("第"))
        pager.addWidget(self.page_spin)
        pager.addWidget(self.page_total_label)
        pager.addWidget(CaptionLabel("页"))
        pager.addWidget(self.next_btn)
        right_layout.addLayout(pager)

        # 空状态提示（覆盖在网格上）
        self._empty_hint = CaptionLabel(
            "未发现匹配的图片\n\n"
            "请确认数据集目录结构：\n"
            "  <根目录>/<类别>/images/*.jpg\n"
            "  <根目录>/<类别>/labels/*.json\n\n"
            "或尝试调整筛选条件"
        )
        self._empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_hint.hide()
        right_layout.addWidget(self._empty_hint)

        # 缩略图加载进度条
        self._thumb_bar = IndeterminateProgressBar(self, start=False)
        self._thumb_bar.setFixedHeight(3)
        self._thumb_bar.hide()
        self._thumb_pending = 0
        right_layout.addWidget(self._thumb_bar)

        root.addWidget(right, 1)

    # ---------- 状态持久化 ----------

    def save_state(self):
        from core.project import BrowseState
        return BrowseState(
            category=self._current_category,
            filter=self._filter_mode,
            search=self._search_text,
            page=self._page,
        )

    def restore_state(self, state) -> None:
        if state is None:
            return
        self._current_category = state.category or ""
        self._filter_mode = state.filter or "all"
        self._search_text = state.search or ""
        self._page = state.page or 0
        # Update UI widgets
        self.search.setText(self._search_text)
        for btn in self.chip_group.buttons():
            if btn.property("filterKey") == self._filter_mode:
                btn.setChecked(True)
                break
        # Select category in tree
        if self._current_category:
            for i in range(self.tree.count()):
                item = self.tree.item(i)
                if item.data(Qt.ItemDataRole.UserRole) == self._current_category:
                    self.tree.setCurrentRow(i)
                    break
        self._apply_filter_and_show()
        # Restore page after filter
        self._page = state.page or 0
        self._show_page()

    # ---------- 外部接口 ----------

    def load_dataset(self, dataset: Dataset) -> None:
        """Re-render tree + grid for the given dataset.

        Does NOT store the dataset — AppState owns it. The caller
        (typically ``DatasetBrowserView._on_dataset_changed``) has
        already pushed *dataset* into AppState, so subsequent reads
        via ``self._state.dataset`` see the same object.
        """
        self._current_category = ""
        self._page = 0
        # New dataset → quality results from prior run are stale
        self._quality_map = {}
        self._chips["issues"].setEnabled(False)
        if self._filter_mode == "issues":
            self._filter_mode = "all"
            self._chips["all"].setChecked(True)
        self.tree.load_dataset(dataset)
        self._update_readiness(dataset)
        self._apply_filter_and_show()

    # Compact labels — compliance checker uses verbose Chinese names.
    # Here we collapse them into short pill-style chips.
    _READINESS_LABEL = {
        "图片数量": "图片",
        "分类数": "分类",
        "标注覆盖": "标注",
        "类别平衡": "平衡",
        "每类最少张数": "最少",
    }

    def _update_readiness(self, dataset: Dataset) -> None:
        """Compact readiness chips — short label + value, pill color by status."""
        for w in self._readiness_items:
            self._readiness_bar.removeWidget(w)
            w.deleteLater()
        self._readiness_items.clear()

        from core.compliance import check_compliance
        task_type = self._state.task_type
        if task_type is None:
            from core.task_types import TaskType
            task_type = TaskType.DETECTION

        report = check_compliance(dataset, task_type)

        for check in report.checks:
            short = self._READINESS_LABEL.get(check.item, check.item)
            value = self._format_readiness_value(check.item, check.current)
            # Pass: short label + value (e.g. "图片 5,098")
            # Fail: action when available, else short+value
            if check.passed:
                text = f"{short} {value}"
            else:
                text = check.action or f"{short} {value}"
            lbl = CaptionLabel(text)
            lbl.setObjectName("readinessOk" if check.passed else "readinessGap")
            # Tooltip always shows the full detail — the chip stays short
            lbl.setToolTip(f"{check.item}: {check.current}"
                           + (f" · 需求 {check.required}" if check.required else "")
                           + (f"\n{check.action}" if check.action else ""))
            self._readiness_bar.addWidget(lbl)
            self._readiness_items.append(lbl)

        self._readiness_bar.addStretch(1)

    @staticmethod
    def _format_readiness_value(item: str, current: str) -> str:
        """Strip verbose prefixes so the chip reads "图片 5,098" not "图片 5,098 张"."""
        # "5,098 张" → "5,098"
        if current.endswith(" 张"):
            return current[:-2]
        # "15 个" → "15"
        if current.endswith(" 个"):
            return current[:-2]
        # "4,906/5,098 (96%)" → "96%"
        if "(" in current and current.endswith(")"):
            return current[current.rindex("(") + 1:-1]
        # "最少: OverLimit (4张)" → "OverLimit 4"
        if current.startswith("最少:"):
            return current[3:].replace("(", "").replace(")", "").replace("张", "").strip()
        return current

    def on_thumb_ready(self, path: str, jpeg_bytes: bytes, w: int, h: int) -> None:
        self.grid.on_thumb_ready(path, jpeg_bytes, w, h)
        self._thumb_pending = max(0, self._thumb_pending - 1)
        if self._thumb_pending == 0:
            self._thumb_bar.stop()
            self._thumb_bar.hide()

    # ---------- 内部 ----------

    def _all_images(self) -> list[ImageInfo]:
        if not self._state.dataset:
            return []
        if self._current_category:
            for cat in self._state.dataset.categories:
                if cat.name == self._current_category:
                    return list(cat.images)
            return []
        # 全部
        out: list[ImageInfo] = []
        for cat in self._state.dataset.categories:
            out.extend(cat.images)
        return out

    def _apply_filter_and_show(self) -> None:
        imgs = self._all_images()
        if self._filter_mode == "labeled":
            imgs = [i for i in imgs if i.has_label]
        elif self._filter_mode == "unlabeled":
            imgs = [i for i in imgs if not i.has_label]
        elif self._filter_mode == "issues":
            imgs = [i for i in imgs if str(i.path) in self._quality_map]
        if self._search_text:
            q = self._search_text.lower()
            imgs = [i for i in imgs if q in i.path.name.lower()]
        self._filtered = imgs
        self._page = 0
        self._show_page()

    def _show_page(self) -> None:
        total = len(self._filtered)
        page_count = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        self._page = max(0, min(self._page, page_count - 1))
        start = self._page * PAGE_SIZE
        end = min(start + PAGE_SIZE, total)
        page_imgs = self._filtered[start:end]
        self.clear_thumb_queue.emit()  # cancel stale thumbnail requests
        self._thumb_pending = len(page_imgs)
        if self._thumb_pending > 0:
            self._thumb_bar.show()
            self._thumb_bar.start()
        self.grid.set_images(page_imgs, quality_map=self._quality_map)

        # 空状态切换
        if total == 0:
            self._empty_hint.show()
            self.grid.hide()
        else:
            self._empty_hint.hide()
            self.grid.show()

        # 更新分页控件
        self.page_spin.blockSignals(True)
        self.page_spin.setRange(1, page_count)
        self.page_spin.setValue(self._page + 1)
        self.page_spin.blockSignals(False)
        self.page_total_label.setText(f"/ {page_count}")
        self.count_label.setText(f"共 {total:,} 张" if total > 0 else "没有匹配的图片")
        self.prev_btn.setEnabled(self._page > 0)
        self.next_btn.setEnabled(self._page < page_count - 1)

    def _on_category_selected(self, category: str) -> None:
        self._current_category = category
        self._apply_filter_and_show()

    def _on_filter_changed(self, mode: str) -> None:
        self._filter_mode = mode
        self._apply_filter_and_show()

    def set_quality_issues(self, issues_map: dict[str, list[str]]) -> None:
        """Apply quality-check results: red corner badges + enable "有问题" filter.

        Pass an empty dict to clear (e.g. on dataset change). Map key must
        be ``str(image.path)`` matching what the grid stores.
        """
        self._quality_map = dict(issues_map)
        has_issues = bool(self._quality_map)
        self._chips["issues"].setEnabled(has_issues)
        if not has_issues and self._filter_mode == "issues":
            # Auto-revert to "all" when issues cleared
            self._filter_mode = "all"
            self._chips["all"].setChecked(True)
        self._apply_filter_and_show()

    def _on_search_changed(self, text: str) -> None:
        self._search_text = text.strip()
        self._apply_filter_and_show()

    def get_selected_images(self) -> list[ImageInfo]:
        return list(self.grid.selected_images())

    def _on_selection_changed(self, selected: list[ImageInfo]) -> None:
        n = len(selected)
        self.selection_label.setText(
            self.tr("已选 {n} 张").format(n=n) if n else ""
        )

    def _on_item_activated(self, img: ImageInfo) -> None:
        self.image_activated.emit(img, self._filtered)

    def _prev_page(self) -> None:
        self._page -= 1
        self._show_page()

    def _next_page(self) -> None:
        self._page += 1
        self._show_page()

    def _on_page_jump(self) -> None:
        self._page = self.page_spin.value() - 1
        self._show_page()

    # ---------- 右键菜单 / 批量操作 ----------

    def _on_context_menu(self, pos) -> None:
        sel = self.grid.selected_images()
        if not sel:
            return
        menu = QMenu(self)
        menu.addAction(
            self.tr("已选 {n} 张").format(n=len(sel))
        ).setEnabled(False)
        menu.addSeparator()
        menu.addAction(self.tr("删除 (回收站)"), lambda: self._do_delete(sel))
        menu.addAction(self.tr("批量重命名…"), lambda: self._do_rename(sel))
        menu.addAction(self.tr("移动到类别…"), lambda: self._do_move(sel))
        menu.addSeparator()
        menu.addAction(self.tr("格式转换…"), lambda: self._do_convert(sel))
        menu.addAction(self.tr("缩放…"), lambda: self._do_transform(sel, tx.resize_one, ResizeDialog))
        menu.addAction(self.tr("裁剪…"), lambda: self._do_transform(sel, tx.crop_one, CropDialog))
        menu.addAction(self.tr("旋转…"), lambda: self._do_transform(sel, tx.rotate_one, RotateDialog))
        menu.addAction(self.tr("翻转…"), lambda: self._do_transform(sel, tx.flip_one, FlipDialog))
        menu.addSeparator()
        split_menu = menu.addMenu(self.tr("加入手动划分"))
        split_menu.addAction(self.tr("→ Train"), lambda: self.add_to_split.emit("train", sel))
        split_menu.addAction(self.tr("→ Val"), lambda: self.add_to_split.emit("val", sel))
        split_menu.addAction(self.tr("→ Test"), lambda: self.add_to_split.emit("test", sel))
        menu.addSeparator()
        menu.addAction(self.tr("导出为子集数据集…"), lambda: self._do_export_subset(sel))
        menu.exec(self.grid.viewport().mapToGlobal(pos))

    # ---- 各操作 ----

    def _do_delete(self, sel: list[ImageInfo]) -> None:
        box = MessageBox(
            self.tr("确认删除"),
            self.tr("将 {n} 个图片+标注移至回收站，确认？").format(n=len(sel)),
            self.window(),
        )
        if not box.exec():
            return
        self._run(
            lambda cb: fileops.delete_pairs(sel, to_trash=True),
            self.tr("正在删除…"),
        )

    def _do_rename(self, sel: list[ImageInfo]) -> None:
        dlg = RenameDialog(self.window())
        if not dlg.exec():
            return
        pattern = dlg.pattern.text()
        start = dlg.start.value()
        self._run(
            lambda cb: fileops.batch_rename(sel, pattern=pattern, start=start),
            self.tr("正在重命名…"),
        )

    def _do_move(self, sel: list[ImageInfo]) -> None:
        if not self._state.dataset:
            return
        cats = [c.name for c in self._state.dataset.categories]
        dlg = MoveToCategoryDialog(cats, self.window())
        if not dlg.exec():
            return
        target = dlg.target()
        if not target:
            return
        root = self._state.dataset.root_path
        self._run(
            lambda cb: fileops.move_to_category(sel, root, target),
            self.tr("正在移动到 {target}…").format(target=target),
        )

    def _do_convert(self, sel: list[ImageInfo]) -> None:
        dlg = ConvertDialog(self.window())
        if not dlg.exec():
            return
        opts = dlg.options()
        paths = [i.path for i in sel]
        self._run(
            lambda cb: convert_batch(paths, opts, progress_cb=cb),
            self.tr("正在转换…"),
        )

    def _do_transform(self, sel: list[ImageInfo], op_fn, DlgCls) -> None:
        dlg = DlgCls(self.window())
        if not dlg.exec():
            return
        opts = dlg.options()
        paths = [i.path for i in sel]
        self._run(
            lambda cb: tx.batch_apply(paths, op_fn, opts, progress_cb=cb),
            self.tr("处理中…"),
        )

    def _do_export_subset(self, sel: list[ImageInfo]) -> None:
        out = QFileDialog.getExistingDirectory(self, self.tr("选择导出目录"))
        if not out:
            return
        from pathlib import Path as _P
        out_path = _P(out)
        self._run(
            lambda cb: export_subset(sel, out_path, progress_cb=cb),
            self.tr("正在导出子集…"),
        )

    # ---- 类别管理 ----

    def _do_rename_category(self, name: str) -> None:
        if not self._state.dataset:
            return
        from gui.dialogs.category_dialogs import RenameCategoryDialog
        cats = self.tree.get_category_names()
        dlg = RenameCategoryDialog(name, cats, parent=self.window())
        if not dlg.exec():
            return
        new_name = dlg.new_name()
        root = self._state.dataset.root_path
        self._run(
            lambda cb: fileops.rename_category(root, name, new_name, progress_cb=cb),
            self.tr("正在重命名类别…"),
            rescan=True,
        )

    def _do_merge_categories(self, name: str) -> None:
        if not self._state.dataset:
            return
        from gui.dialogs.category_dialogs import MergeCategoriesDialog
        cats = self.tree.get_category_names()
        dlg = MergeCategoriesDialog(cats, current=name, parent=self.window())
        if not dlg.exec():
            return
        sources = dlg.sources()
        target = dlg.target()
        root = self._state.dataset.root_path
        self._run(
            lambda cb: fileops.merge_categories(root, sources, target, progress_cb=cb),
            self.tr("正在合并类别…"),
            rescan=True,
        )

    def _do_split_category(self, name: str) -> None:
        if not self._state.dataset:
            return
        sel = self.get_selected_images()
        if not sel:
            box = MessageBox(
                self.tr("拆分类别"),
                self.tr("请先在网格中勾选要拆出的图片"),
                self.window(),
            )
            box.cancelButton.hide()
            box.exec()
            return
        from gui.dialogs.category_dialogs import SplitCategoryDialog
        cats = self.tree.get_category_names()
        dlg = SplitCategoryDialog(name, len(sel), cats, parent=self.window())
        if not dlg.exec():
            return
        new_name = dlg.new_name()
        root = self._state.dataset.root_path
        self._run(
            lambda cb: fileops.split_category(root, name, new_name, sel, progress_cb=cb),
            self.tr("正在拆分类别…"),
            rescan=True,
        )

    # ---- 通用 worker 驱动 ----

    def _run(self, fn, title: str, rescan: bool = False) -> None:
        if self._worker is not None:
            box = MessageBox(
                self.tr("请稍候"), self.tr("已有操作正在执行"), self.window()
            )
            box.cancelButton.hide()
            box.exec()
            return
        self._pending_rescan = rescan
        self._progress = ProgressDialog(title, self.window())
        self._progress.show()

        self._worker = BatchWorker(fn)
        self._worker.progress.connect(self._on_op_progress)
        self._worker.finished_ok.connect(self._on_op_done)
        self._worker.failed.connect(self._on_op_failed)
        self._worker.start()

    def _on_op_progress(self, done: int, total: int, name: str) -> None:
        if not self._progress:
            return
        self._progress.set_progress(done, total, name)

    def _on_op_done(self, result) -> None:
        self._cleanup_worker()
        # 清索引缓存，下次打开重新扫描
        if self._state.dataset:
            try:
                index_cache.clear(self._state.dataset.root_path)
            except Exception:
                pass
        if result.fail_count:
            details = "\n".join(f"{p}\n  → {err}" for p, err in result.failed[:200])
            FailureDetailDialog(
                result.ok_count, result.fail_count, details, self.window()
            ).exec()
        else:
            box = MessageBox(
                self.tr("完成"),
                self.tr("成功 {ok} 个").format(ok=result.ok_count),
                self.window(),
            )
            box.cancelButton.hide()
            box.exec()
        # 文件系统已变更 → 统一触发重扫描，保证 UI 和磁盘一致
        self.dataset_changed.emit()

    def _on_op_failed(self, msg: str) -> None:
        self._cleanup_worker()
        box = MessageBox(self.tr("操作失败"), msg, self.window())
        box.cancelButton.hide()
        box.exec()

    def _cleanup_worker(self) -> None:
        if self._progress:
            self._progress.close()
            self._progress = None
        if self._worker:
            self._worker.deleteLater()
            self._worker = None
