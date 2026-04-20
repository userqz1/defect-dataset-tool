"""Browser view: category tree + filter bar + thumbnail grid + pagination."""
from __future__ import annotations

import logging
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)

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
    PushButton,
    ToolButton,
)

from core import fileops, index_cache
from core.exporter.subset import export_subset
from core.models import Dataset, ImageInfo
from gui.dialogs.op_dialogs import (
    FailureDetailDialog,
    MoveToCategoryDialog,
    ProgressDialog,
)
from gui.theme import T
from gui.widgets.category_tree import CategoryTree
from gui.widgets.chips import FilterChip, GhostButton
from gui.widgets.thumbnail_grid import ThumbnailGrid
from gui.workers.batch_worker import BatchWorker

PAGE_SIZE = 40


class FilterMode(str, Enum):
    """Which subset of the dataset the grid shows. Stored as its string
    value in BrowseState for project.json round-tripping."""
    ALL = "all"
    LABELED = "labeled"
    UNLABELED = "unlabeled"
    ISSUES = "issues"          # only meaningful after a quality check
    DUPLICATES = "duplicates"  # only meaningful after dedup ran (review #15)


class BrowserView(QWidget):
    image_activated = pyqtSignal(object, list)  # (current ImageInfo, full list)
    thumb_request = pyqtSignal(object)          # Path
    clear_thumb_queue = pyqtSignal()            # clear pending thumbnail requests
    add_to_split = pyqtSignal(str, list)        # (bucket name, list[ImageInfo])
    navigate_to = pyqtSignal(str)               # route key for readiness bar links
    dataset_changed = pyqtSignal()              # emitted after category rename/merge/split

    def __init__(self, app_state) -> None:
        """BrowserView requires an AppState — construction with None used to
        auto-build a fresh AppState "for tests", but that masked production
        bugs where two AppStates existed simultaneously (review #9). Tests
        now must inject an explicit AppState fixture.
        """
        super().__init__()
        self.setObjectName("browserView")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        if app_state is None:
            raise ValueError("BrowserView requires an AppState instance; "
                             "construct one explicitly (e.g. AppState()) "
                             "instead of passing None")
        self._state = app_state
        self._current_category: str = ""
        self._filter_mode: FilterMode = FilterMode.ALL
        self._search_text: str = ""
        self._page: int = 0
        self._filtered: list[ImageInfo] = []
        # Quality issues now live in AppState (review #7) so other views
        # can read them without re-running the check. BrowserView just
        # subscribes to quality_changed below.
        self._state.quality_changed.connect(self._on_quality_changed)
        # Duplicates also come through AppState now (review #15) — needed
        # for the "重复" filter chip to light up after a dedup run.
        self._state.duplicates_changed.connect(self._on_duplicates_changed)

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
        self._chips: dict[FilterMode, FilterChip] = {}
        for mode, label in [
            (FilterMode.ALL, self.tr("全部")),
            (FilterMode.LABELED, self.tr("已标注")),
            (FilterMode.UNLABELED, self.tr("未标注")),
            (FilterMode.ISSUES, self.tr("有问题")),
            (FilterMode.DUPLICATES, self.tr("重复")),
        ]:
            chip = FilterChip(label)
            chip.setProperty("filterKey", mode.value)
            chip.clicked.connect(
                lambda _c=False, m=mode: self._on_filter_changed(m))
            self.chip_group.addButton(chip)
            filter_bar.addWidget(chip)
            self._chips[mode] = chip
            if mode is FilterMode.ALL:
                chip.setChecked(True)
        # "有问题" / "重复" only meaningful after their respective run
        self._chips[FilterMode.ISSUES].setEnabled(False)
        self._chips[FilterMode.DUPLICATES].setEnabled(False)

        filter_bar.addStretch(1)

        self.selection_label = CaptionLabel("")
        filter_bar.addWidget(self.selection_label)

        # "多选" toggle — when on, a single click on a thumbnail toggles
        # selection (no Ctrl needed), ideal for touchpad / quick bulk picking.
        # Off = default desktop behavior (单选 + Ctrl/Shift 辅助).
        self._multi_btn = PushButton(self.tr("多选"))
        self._multi_btn.setCheckable(True)
        self._multi_btn.setFixedWidth(80)
        self._multi_btn.setFixedHeight(32)
        self._multi_btn.toggled.connect(self._on_multi_toggle)
        filter_bar.addWidget(self._multi_btn)

        # "全选 / 取消全选" toggle — current page scope; for cross-page bulk
        # use the filter chips first, then 全选.
        self._select_all_btn = PushButton(self.tr("全选"))
        self._select_all_btn.setFixedWidth(80)
        self._select_all_btn.setFixedHeight(32)
        self._select_all_btn.setEnabled(False)
        self._select_all_btn.clicked.connect(self._on_select_all_toggle)
        filter_bar.addWidget(self._select_all_btn)

        # Visible delete entry — right-click menu alone was too hidden.
        # Enabled only when at least one thumbnail is selected.
        self._delete_btn = PushButton(self.tr("删除"))
        self._delete_btn.setIcon(FIF.DELETE)
        self._delete_btn.setFixedWidth(80)
        self._delete_btn.setFixedHeight(32)
        self._delete_btn.setEnabled(False)
        self._delete_btn.clicked.connect(self._on_delete_clicked)
        filter_bar.addWidget(self._delete_btn)

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
            # Persist as plain string so BrowseState stays JSON-clean
            filter=self._filter_mode.value,
            search=self._search_text,
            page=self._page,
        )

    def restore_state(self, state) -> None:
        if state is None:
            return
        self._current_category = state.category or ""
        # Accept unknown values gracefully (old project.json from future builds)
        try:
            self._filter_mode = FilterMode(state.filter or "all")
        except ValueError:
            self._filter_mode = FilterMode.ALL
        self._search_text = state.search or ""
        self._page = state.page or 0
        # Update UI widgets
        self.search.setText(self._search_text)
        for btn in self.chip_group.buttons():
            if btn.property("filterKey") == self._filter_mode.value:
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
        # Derived artifacts (quality / dedup) are cleared by AppState when
        # dataset changes; we just reset the dependent chips visually.
        self._chips[FilterMode.ISSUES].setEnabled(bool(self._state.quality_issue_paths))
        self._chips[FilterMode.DUPLICATES].setEnabled(bool(self._state.duplicate_groups))
        if self._filter_mode is FilterMode.ISSUES and not self._state.quality_issue_paths:
            self._filter_mode = FilterMode.ALL
            self._chips[FilterMode.ALL].setChecked(True)
        elif self._filter_mode is FilterMode.DUPLICATES and not self._state.duplicate_groups:
            self._filter_mode = FilterMode.ALL
            self._chips[FilterMode.ALL].setChecked(True)
        self.tree.load_dataset(dataset)
        self._update_readiness(dataset)
        self._apply_filter_and_show()

    def _update_readiness(self, dataset: Dataset) -> None:
        """Compact readiness chips — short label + value, pill color by status.

        ``short`` comes from ``ReadinessCheck.short`` now, not a GUI-side
        lookup table — that way a new core check automatically supplies a
        pill label rather than silently falling back to a long Chinese name.
        """
        for w in self._readiness_items:
            self._readiness_bar.removeWidget(w)
            w.deleteLater()
        self._readiness_items.clear()

        from core.task_readiness import check_task_readiness
        task_type = self._state.task_type
        if task_type is None:
            from core.task_types import TaskType
            task_type = TaskType.DETECTION

        report = check_task_readiness(dataset, task_type)

        for check in report.checks:
            short = check.short
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
        if self._filter_mode is FilterMode.LABELED:
            imgs = [i for i in imgs if i.has_label]
        elif self._filter_mode is FilterMode.UNLABELED:
            imgs = [i for i in imgs if not i.has_label]
        elif self._filter_mode is FilterMode.ISSUES:
            qmap = self._state.quality_issue_paths
            imgs = [i for i in imgs if str(i.path) in qmap]
        elif self._filter_mode is FilterMode.DUPLICATES:
            # Include every image that appears in any DuplicateGroup
            # (review #15) — not just the "to delete" tail.
            groups = self._state.duplicate_groups or []
            dup_paths = {str(img.path) for g in groups for img in g.images}
            imgs = [i for i in imgs if str(i.path) in dup_paths]
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
        self.grid.set_images(page_imgs,
                             quality_map=self._state.quality_issue_paths)

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
        # Reset filter when switching categories — otherwise a user who
        # clicked "未标注" while viewing one category sees an empty page
        # on every subsequent category that happens to be fully annotated,
        # and can't tell the filter is still active. 直觉:类别切换 = 看这类全部。
        self._current_category = category
        if self._filter_mode is not FilterMode.ALL:
            self._filter_mode = FilterMode.ALL
            self._chips[FilterMode.ALL].setChecked(True)
        self._apply_filter_and_show()

    def _on_filter_changed(self, mode: FilterMode) -> None:
        self._filter_mode = mode
        self._apply_filter_and_show()

    def _on_quality_changed(self, issues) -> None:
        """AppState.quality_changed handler — re-enable ISSUES chip + refresh grid.

        Called when quality check finishes (issues = list[QualityIssue]) or
        when the dataset changes (issues = None from _clear_derived).
        """
        has_issues = bool(issues)
        self._chips[FilterMode.ISSUES].setEnabled(has_issues)
        if not has_issues and self._filter_mode is FilterMode.ISSUES:
            self._filter_mode = FilterMode.ALL
            self._chips[FilterMode.ALL].setChecked(True)
        self._apply_filter_and_show()

    def _on_duplicates_changed(self, groups) -> None:
        """AppState.duplicates_changed handler — toggles 重复 chip."""
        has_dupes = bool(groups)
        self._chips[FilterMode.DUPLICATES].setEnabled(has_dupes)
        if not has_dupes and self._filter_mode is FilterMode.DUPLICATES:
            self._filter_mode = FilterMode.ALL
            self._chips[FilterMode.ALL].setChecked(True)
        self._apply_filter_and_show()

    def _on_search_changed(self, text: str) -> None:
        self._search_text = text.strip()
        self._apply_filter_and_show()

    def get_selected_images(self) -> list[ImageInfo]:
        return list(self.grid.selected_images())

    def _on_selection_changed(self, selected: list[ImageInfo]) -> None:
        n = len(selected)
        total_on_page = self.grid.count()
        self.selection_label.setText(
            self.tr("已选 {n} 张").format(n=n) if n else ""
        )
        self._delete_btn.setEnabled(n > 0)
        # Toggle select-all button label + enabled state
        self._select_all_btn.setEnabled(total_on_page > 0)
        if total_on_page > 0 and n >= total_on_page:
            self._select_all_btn.setText(self.tr("取消全选"))
        else:
            self._select_all_btn.setText(self.tr("全选"))

    def _on_select_all_toggle(self) -> None:
        """Toggle between select-all-on-current-page and clear-selection."""
        total_on_page = self.grid.count()
        if total_on_page == 0:
            return
        if len(self.grid.selectedItems()) >= total_on_page:
            self.grid.clearSelection()
        else:
            self.grid.selectAll()

    def _on_multi_toggle(self, checked: bool) -> None:
        """Switch grid between Extended (default, Ctrl/Shift) and Multi (click-toggle).

        Extended selection is the desktop convention — click one, Ctrl+click
        to add, Shift+click for range. Some users expect phone-like toggling
        (single click selects/unselects without a modifier) so this button
        flips the grid to MultiSelection while pressed. Clearing on exit
        avoids a mixed state (half the selection from one mode, half the
        other) that would confuse the delete confirmation.
        """
        from PyQt6.QtWidgets import QAbstractItemView
        if checked:
            self.grid.setSelectionMode(
                QAbstractItemView.SelectionMode.MultiSelection)
        else:
            self.grid.setSelectionMode(
                QAbstractItemView.SelectionMode.ExtendedSelection)
            self.grid.clearSelection()

    def _on_delete_clicked(self) -> None:
        sel = self.grid.selected_images()
        if sel:
            self._do_delete(sel)

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
        menu.addAction(self.tr("移动到类别…"), lambda: self._do_move(sel))
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
        labeled = sum(1 for i in sel if i.has_label)
        unlabeled = len(sel) - labeled
        parts = [f"{len(sel)} 张图片"]
        if labeled and unlabeled:
            parts.append(f"其中 {labeled} 张带标注、{unlabeled} 张未标注")
        elif labeled:
            parts.append(f"含 {labeled} 份标注文件")
        # 未标注情况下,第二行是冗余的 ("XX 张图片" 已经说明),不再补
        body = self.tr("将以下内容移至回收站，确认？\n\n") + "\n".join(parts)
        box = MessageBox(self.tr("确认删除"), body, self.window())
        if not box.exec():
            return
        self._run(
            lambda cb: fileops.delete_pairs(sel, to_trash=True, progress_cb=cb),
            self.tr("正在删除…"),
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
        # original_categories captures per-image source category so
        # try_undo_last can move each file back, not just "some category".
        original_categories = {str(i.path): i.category for i in sel}
        self._run(
            lambda cb: fileops.move_to_category(sel, root, target, progress_cb=cb),
            self.tr("正在移动到 {target}…").format(target=target),
            history={
                "action": "move-to-category",
                "params": {
                    "target": target,
                    "image_count": len(sel),
                    "images": [str(i.path) for i in sel],
                    "original_categories": original_categories,
                },
                "summary": f"移动 {len(sel)} 张到 {target}",
                "undoable": True,
            },
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
            history={
                "action": "rename-category",
                "params": {"old": name, "new": new_name},
                "summary": f"重命名类别 {name} → {new_name}",
                "undoable": True,
            },
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
            history={
                "action": "merge-categories",
                "params": {"sources": list(sources), "target": target},
                "summary": f"合并 {'、'.join(sources)} → {target}",
            },
        )

    def _do_split_category(self, name: str) -> None:
        """Right-click → 拆分类别. Dialog now embeds its own picker
        (review #13) so the user doesn't have to pre-select in the grid.
        Any current grid selection is preselected in the list for
        convenience.
        """
        if not self._state.dataset:
            return
        # Collect all images belonging to this category
        cat_images: list[ImageInfo] = []
        for c in self._state.dataset.categories:
            if c.name == name:
                cat_images = list(c.images)
                break
        if not cat_images:
            box = MessageBox(
                self.tr("拆分类别"),
                self.tr("该类别没有图片可拆分"),
                self.window(),
            )
            box.cancelButton.hide()
            box.exec()
            return

        from gui.dialogs.category_dialogs import SplitCategoryDialog
        cats = self.tree.get_category_names()
        preselected = self.get_selected_images()
        dlg = SplitCategoryDialog(
            name, cat_images, cats,
            preselected=preselected, parent=self.window(),
        )
        if not dlg.exec():
            return
        new_name = dlg.new_name()
        sel = dlg.selected_images()
        if not sel:
            return  # defensive; the dialog's OK button is disabled without selection
        root = self._state.dataset.root_path
        self._run(
            lambda cb: fileops.split_category(root, name, new_name, sel, progress_cb=cb),
            self.tr("正在拆分类别…"),
            rescan=True,
            history={
                "action": "split-category",
                "params": {
                    "source": name, "new": new_name,
                    "image_count": len(sel),
                    "images": [str(i.path) for i in sel],
                },
                "summary": f"从 {name} 拆出 {len(sel)} 张到 {new_name}",
            },
        )

    # ---- 通用 worker 驱动 ----

    def _run(self, fn, title: str, rescan: bool = False,
             history: dict | None = None) -> None:
        """Run a batch operation.

        Args:
            history: Optional ``{"action": str, "params": dict, "summary": str}``
                describing a metadata operation. When present, both success
                and failure append to ``.dataforge/history.jsonl`` via
                core.history — the only gateway for metadata audit logging.
        """
        if self._worker is not None:
            box = MessageBox(
                self.tr("请稍候"), self.tr("已有操作正在执行"), self.window()
            )
            box.cancelButton.hide()
            box.exec()
            return
        self._pending_rescan = rescan
        self._pending_history = history
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
                logger.exception("index cache clear failed")
        # Append to operation history BEFORE surfacing UI feedback, so a
        # blocking dialog can't silently drop the log entry.
        self._record_history(
            ok=result.fail_count == 0,
            ok_count=getattr(result, "ok_count", 0),
            fail_count=getattr(result, "fail_count", 0),
        )
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
        self._record_history(ok=False, error=msg)
        box = MessageBox(self.tr("操作失败"), msg, self.window())
        box.cancelButton.hide()
        box.exec()

    def _record_history(self, ok: bool, ok_count: int = 0,
                         fail_count: int = 0, error: str = "") -> None:
        """Append a single JSONL entry for the just-finished metadata op.

        No-op when the caller didn't pass ``history=`` to _run (pure image
        transforms / exports don't need an audit trail — only things that
        move or rename belong in history).
        """
        hist = getattr(self, "_pending_history", None)
        self._pending_history = None
        if hist is None or not self._state.dataset:
            return
        from core import history as _hist
        summary = hist.get("summary", "")
        if error:
            summary = f"{summary}（失败：{error}）"
        elif fail_count:
            summary = f"{summary}（{ok_count} 成功 / {fail_count} 失败）"
        try:
            _hist.append(
                self._state.dataset.root_path,
                _hist.HistoryEntry.now(
                    action=hist.get("action", "unknown"),
                    params=hist.get("params", {}),
                    ok=ok,
                    summary=summary,
                    # undo MVP (#6): caller flags whether this op is
                    # reversible by try_undo_last. Default False keeps
                    # current behavior for merge/split/delete/etc.
                    undoable=bool(hist.get("undoable", False)) and ok,
                ),
            )
        except Exception:
            logger.exception("history record failed for %s",
                             hist.get("action"))

    def _cleanup_worker(self) -> None:
        if self._progress:
            self._progress.close()
            self._progress = None
        if self._worker:
            self._worker.deleteLater()
            self._worker = None
