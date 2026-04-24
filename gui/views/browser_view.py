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
    CaptionLabel,
    FluentIcon as FIF,
    IndeterminateProgressBar,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    MessageBox,
    PushButton,
    ToolButton,
)

from core import fileops, index_cache
from core.exporter.subset import export_subset
from core.models import Dataset, ImageInfo
from gui import i18n
from gui.dialogs.op_dialogs import (
    FailureDetailDialog,
    MoveToCategoryDialog,
    ProgressDialog,
)
from gui.theme import T
from gui.widgets.chips import FilterChip
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
    WORK_NEW = "work_new"          # workflow: new + prelabeled + annotating
    WORK_REVIEW = "work_review"    # workflow: review_pending
    WORK_FIX = "work_fix"          # workflow: needs_fix
    WORK_READY = "work_ready"      # workflow: ready + exported


class BrowserView(QWidget):
    image_activated = pyqtSignal(object, list)  # (current ImageInfo, full list)
    thumb_request = pyqtSignal(object)          # Path
    clear_thumb_queue = pyqtSignal()            # clear pending thumbnail requests
    add_to_split = pyqtSignal(str, list)        # (bucket name, list[ImageInfo])
    navigate_to = pyqtSignal(str)               # route key for readiness bar links
    dataset_changed = pyqtSignal()              # emitted after category rename/merge/split
    batch_status_requested = pyqtSignal(list, str)  # (images, new_status_str)
    # Bubbled from DatasetBar's 选择目录 button — DatasetBrowserView owns
    # the actual file dialog + scan plumbing.
    open_clicked = pyqtSignal()

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
        # Per-category image-list cache (review #8). Rebuilt on category
        # switch / dataset change; reused across filter + search typing
        # so a 50k-image dataset doesn't rebuild the full list on every
        # keystroke. Keyed by category name ("" = 全部).
        self._category_images_cache: list[ImageInfo] | None = None
        self._category_images_cache_key: tuple[str, int] | None = None
        # Quality issues now live in AppState (review #7) so other views
        # can read them without re-running the check. BrowserView just
        # subscribes to quality_changed below.
        self._state.quality_changed.connect(self._on_quality_changed)
        # Duplicates also come through AppState now (review #15) — needed
        # for the "重复" filter chip to light up after a dedup run.
        self._state.duplicates_changed.connect(self._on_duplicates_changed)
        # SampleSet-aware filter: "已标注"/"未标注" use actual region data.
        self._state.sample_set_changed.connect(self._on_sample_set_changed)
        self._annotated_cache: set[str] | None = None
        # Work-status cache: image_path str → WorkStatus.value
        self._work_status_cache: dict[str, str] | None = None

        # Single-column layout — viewer region per the design handoff.
        # The 4-column body (NavRail | Tools | Viewer | Catalog) lives in
        # DatasetBrowserView; BrowserView is just the viewer.
        right_layout = QVBoxLayout(self)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        # DatasetBar sits at the top of the viewer, full width.
        from gui.widgets.dataset_bar import DatasetBar
        self.dataset_bar = DatasetBar()
        self.dataset_bar.open_clicked.connect(self.open_clicked.emit)
        right_layout.addWidget(self.dataset_bar)

        # CategoryTree reference is set from outside by DatasetBrowserView
        # (it lives in CatalogPanel now). _do_rename / merge / split still
        # need to know the category list, so we read it from this handle.
        self._catalog_tree: "CategoryTree | None" = None

        # -- Viewer body (filter bar + grid + paging) has its own padding --
        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(T.PAD_XL, T.PAD, T.PAD_XL, T.GAP_LG)
        body_lay.setSpacing(T.PAD)
        right_layout.addWidget(body, 1)
        right_layout = body_lay  # rest of the init uses this name

        # 筛选栏
        filter_bar = QHBoxLayout()
        filter_bar.setSpacing(T.GAP)

        from PyQt6.QtCore import QTimer
        self.search = LineEdit()
        self.search.setPlaceholderText(i18n.t("filter.search_placeholder"))
        # Narrower default so filter chips keep their natural width when
        # the viewer is below ~1100px — previously 280 ate the chip budget.
        self.search.setFixedWidth(220)
        self.search.setFixedHeight(T.CONTROL_HEIGHT)
        # 300ms debounce — 不在每次按键时都重新过滤
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(lambda: self._on_search_changed(self.search.text()))
        self.search.textChanged.connect(lambda _: self._search_timer.start())
        filter_bar.addWidget(self.search)

        # Segmented chip group (Claude-web redesign): chips live inside a
        # single bg-subtle container rather than each carrying its own border.
        # Active chip gets a white bg + subtle shadow — much quieter baseline
        # with a single strong selection signal.
        self.chip_group = QButtonGroup(self)
        self.chip_group.setExclusive(True)
        self._chips: dict[FilterMode, FilterChip] = {}

        chip_container = QFrame()
        chip_container.setObjectName("filterChipGroup")
        # Minimum size policy horizontally — Qt can't shrink below
        # sizeHint, so the "全部/已标注/未标注/有问题/重复" row stays readable
        # even when the viewer tightens. Previously chips clipped to
        # "标/标/问" at narrow widths (Preferred default let Qt squeeze them).
        from PyQt6.QtWidgets import QSizePolicy
        chip_container.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed,
        )
        chip_lay = QHBoxLayout(chip_container)
        chip_lay.setContentsMargins(2, 2, 2, 2)
        chip_lay.setSpacing(1)

        self._chip_i18n = {
            FilterMode.ALL: "filter.all",
            FilterMode.LABELED: "filter.labeled",
            FilterMode.UNLABELED: "filter.unlabeled",
            FilterMode.ISSUES: "filter.issues",
            FilterMode.DUPLICATES: "filter.duplicates",
            FilterMode.WORK_NEW: "filter.work_new",
            FilterMode.WORK_REVIEW: "filter.work_review",
            FilterMode.WORK_FIX: "filter.work_fix",
            FilterMode.WORK_READY: "filter.work_ready",
        }
        for mode, key in self._chip_i18n.items():
            chip = FilterChip(i18n.t(key))
            chip.setProperty("filterKey", mode.value)
            chip.clicked.connect(
                lambda _c=False, m=mode: self._on_filter_changed(m))
            self.chip_group.addButton(chip)
            chip_lay.addWidget(chip)
            self._chips[mode] = chip
            if mode is FilterMode.ALL:
                chip.setChecked(True)
        # "有问题" / "重复" only meaningful after their respective run
        self._chips[FilterMode.ISSUES].setEnabled(False)
        self._chips[FilterMode.DUPLICATES].setEnabled(False)
        # Workflow chips hidden until a workflow is loaded
        self._work_chips = (FilterMode.WORK_NEW, FilterMode.WORK_REVIEW,
                            FilterMode.WORK_FIX, FilterMode.WORK_READY)
        for m in self._work_chips:
            self._chips[m].setVisible(False)
        self._state.workflow_summary_changed.connect(
            self._on_workflow_summary_changed)
        filter_bar.addWidget(chip_container)

        filter_bar.addStretch(1)

        self.selection_label = CaptionLabel("")
        filter_bar.addWidget(self.selection_label)

        # "多选" toggle — when on, a single click on a thumbnail toggles
        # selection (no Ctrl needed), ideal for touchpad / quick bulk picking.
        # Off = default desktop behavior (单选 + Ctrl/Shift 辅助).
        # NOTE: no setFixedWidth on these — English labels ("Select all",
        # "Multi", "Delete") are 7–11 chars and a fixed 80-90px clips them.
        # Letting the buttons size to content + QSS padding works for both zh/en.
        self._multi_btn = PushButton(i18n.t("filter.multi"))
        self._multi_btn.setCheckable(True)
        self._multi_btn.setFixedHeight(T.CONTROL_HEIGHT)
        self._multi_btn.toggled.connect(self._on_multi_toggle)
        filter_bar.addWidget(self._multi_btn)

        self._select_all_btn = PushButton(i18n.t("filter.select_all"))
        self._select_all_btn.setFixedHeight(T.CONTROL_HEIGHT)
        self._select_all_btn.setEnabled(False)
        self._select_all_btn.clicked.connect(self._on_select_all_toggle)
        filter_bar.addWidget(self._select_all_btn)

        self._delete_btn = PushButton(i18n.t("filter.delete"))
        self._delete_btn.setIcon(FIF.DELETE)
        self._delete_btn.setFixedHeight(T.CONTROL_HEIGHT)
        self._delete_btn.setEnabled(False)
        self._delete_btn.clicked.connect(self._on_delete_clicked)
        filter_bar.addWidget(self._delete_btn)

        # Re-text on language switch
        i18n.bus.language_changed.connect(self._retranslate)

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

        # Wrap grid + empty_hint in a QStackedWidget so swapping between
        # the two doesn't change the overall layout shape. Previously the
        # VBox redistributed freed space into readiness/filter chips when
        # grid hid on empty filter, rendering them as giant rectangles.
        from PyQt6.QtWidgets import QStackedWidget
        self._grid_stack = QStackedWidget()
        self._grid_stack.addWidget(self.grid)          # index 0
        self._empty_hint = CaptionLabel(
            "未发现匹配的图片\n\n"
            "请确认数据集目录结构：\n"
            "  <根目录>/<类别>/images/*.jpg\n"
            "  <根目录>/<类别>/labels/*.json\n\n"
            "或尝试调整筛选条件"
        )
        self._empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._grid_stack.addWidget(self._empty_hint)   # index 1
        right_layout.addWidget(self._grid_stack, 1)

        # 分页栏
        from PyQt6.QtGui import QIntValidator
        pager = QHBoxLayout()
        pager.setSpacing(T.GAP)
        self.prev_btn = ToolButton(FIF.LEFT_ARROW)
        self.prev_btn.clicked.connect(self._prev_page)
        self.next_btn = ToolButton(FIF.RIGHT_ARROW)
        self.next_btn.clicked.connect(self._next_page)
        # Plain LineEdit instead of SpinBox: the ▲▼ chevrons ate half the
        # input box on high page counts (user report: "/ 123 页" clipped
        # the actual value). Direct typing + Enter/blur commits the jump.
        self.page_input = LineEdit()
        self.page_input.setFixedWidth(64)
        self.page_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._page_validator = QIntValidator(1, 1, self)
        self.page_input.setValidator(self._page_validator)
        self.page_input.setText("1")
        self.page_input.editingFinished.connect(self._on_page_jump)
        self.page_total_label = CaptionLabel("/ 1")
        self.count_label = CaptionLabel("")
        self._pager_prefix = CaptionLabel(i18n.t("pager.prefix"))
        self._pager_suffix = CaptionLabel(i18n.t("pager.suffix"))
        pager.addStretch(1)
        pager.addWidget(self.count_label)
        pager.addSpacing(T.GAP_LG)
        pager.addWidget(self.prev_btn)
        pager.addWidget(self._pager_prefix)
        pager.addWidget(self.page_input)
        pager.addWidget(self.page_total_label)
        pager.addWidget(self._pager_suffix)
        pager.addWidget(self.next_btn)
        right_layout.addLayout(pager)

        # 缩略图加载进度条
        self._thumb_bar = IndeterminateProgressBar(self, start=False)
        self._thumb_bar.setFixedHeight(3)
        self._thumb_bar.hide()
        self._thumb_pending = 0
        right_layout.addWidget(self._thumb_bar)

    def _retranslate(self, _lang: str) -> None:
        """Refresh i18n-driven widget text after language switch."""
        self.search.setPlaceholderText(i18n.t("filter.search_placeholder"))
        for mode, chip in self._chips.items():
            chip.setText(i18n.t(self._chip_i18n[mode]))
        self._multi_btn.setText(i18n.t("filter.multi"))
        self._on_selection_changed(self.grid.selected_images())
        self._delete_btn.setText(i18n.t("filter.delete"))
        self._pager_prefix.setText(i18n.t("pager.prefix"))
        self._pager_suffix.setText(i18n.t("pager.suffix"))
        self._show_page()

    def set_catalog_tree(self, tree) -> None:
        """Give BrowserView a handle to the CategoryTree living in CatalogPanel.

        Rename / merge / split dialogs still need the category name list
        and the tree is the authoritative source. Called once from
        DatasetBrowserView after both widgets are constructed.
        """
        self._catalog_tree = tree

    # -- Public wrappers for private methods (consumed by controllers) --

    def select_category(self, category: str) -> None:
        self._on_category_selected(category)

    def rename_category(self, name: str) -> None:
        self._do_rename_category(name)

    def merge_category(self, name: str) -> None:
        self._do_merge_categories(name)

    def split_category(self, name: str) -> None:
        self._do_split_category(name)

    def _category_names(self) -> list[str]:
        """List of categories for dialog population. Prefers the live tree
        (keeps any user sort applied) but falls back to AppState if the
        tree handle hasn't been installed yet."""
        if self._catalog_tree is not None:
            return self._catalog_tree.get_category_names()
        ds = self._state.dataset
        return [c.name for c in ds.categories] if ds else []

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
        # Select category in the CatalogPanel tree (owned externally now)
        if self._current_category and self._catalog_tree is not None:
            tree = self._catalog_tree
            for i in range(tree.count()):
                item = tree.item(i)
                if item.data(Qt.ItemDataRole.UserRole) == self._current_category:
                    tree.setCurrentRow(i)
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
        # Tree + distribution now live in CatalogPanel (owned by the outer
        # DatasetBrowserView). We only drive the grid-side state here.
        self._apply_filter_and_show()

    def on_thumb_ready(self, path: str, jpeg_bytes: bytes, w: int, h: int) -> None:
        self.grid.on_thumb_ready(path, jpeg_bytes, w, h)
        self._thumb_pending = max(0, self._thumb_pending - 1)
        if self._thumb_pending == 0:
            self._thumb_bar.stop()
            self._thumb_bar.hide()

    # ---------- 内部 ----------

    def _all_images(self) -> list[ImageInfo]:
        """Images visible under the current category, cached per
        (category, id(dataset)) pair — review #8. Filter/search still
        runs linearly on top, but that scan is bounded by the category
        size, not the whole dataset, and doesn't rebuild on every
        keystroke of a search."""
        ds = self._state.dataset
        if not ds:
            return []
        key = (self._current_category, id(ds))
        if self._category_images_cache_key == key and self._category_images_cache is not None:
            return self._category_images_cache

        if self._current_category:
            cat = ds.category_by_name(self._current_category)
            images = list(cat.images) if cat else []
        else:
            images = []
            for cat in ds.categories:
                images.extend(cat.images)

        self._category_images_cache = images
        self._category_images_cache_key = key
        return images

    def _apply_filter_and_show(self) -> None:
        imgs = self._all_images()
        if self._filter_mode is FilterMode.LABELED:
            # SampleSet-aware: "labeled" = has actual regions (not just
            # a label file). Falls back to has_label flag when SS absent.
            annotated = self._annotated_paths()
            if annotated is not None:
                imgs = [i for i in imgs if str(i.path) in annotated]
            else:
                imgs = [i for i in imgs if i.has_label]
        elif self._filter_mode is FilterMode.UNLABELED:
            annotated = self._annotated_paths()
            if annotated is not None:
                imgs = [i for i in imgs if str(i.path) not in annotated]
            else:
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
        elif self._filter_mode in self._work_chips:
            imgs = self._filter_by_work_status(imgs)
        if self._search_text:
            q = self._search_text.lower()
            imgs = [i for i in imgs if q in i.path.name.lower()]
        self._filtered = imgs
        self._page = 0
        self._show_page()

    def _filter_by_work_status(self, imgs: list[ImageInfo]) -> list[ImageInfo]:
        """Filter images by workflow status (NEW/REVIEW/READY groups).

        Prefers the SampleSet-based ``_work_status_cache`` when
        available (O(1) lookup by image path). Falls back to
        WorkflowState-based path resolution otherwise.
        """
        from core.workflow import WorkStatus

        if self._filter_mode is FilterMode.WORK_NEW:
            accept_values = {"new", "prelabeled", "annotating"}
        elif self._filter_mode is FilterMode.WORK_REVIEW:
            accept_values = {"review_pending"}
        elif self._filter_mode is FilterMode.WORK_FIX:
            accept_values = {"needs_fix"}
        else:  # WORK_READY
            accept_values = {"ready", "exported"}

        # --- Fast path: SampleSet cache available ---
        cache = self._work_status_cache
        if cache is not None:
            return [i for i in imgs if cache.get(str(i.path), "") in accept_values]

        # --- Fallback: WorkflowState path resolution ---
        wf = self._state.workflow
        project = self._state.project
        if wf is None or project is None:
            return imgs
        status_map: dict[str, str] = {
            item.relative_path: item.status.value for item in wf.items
        }
        root = project.root_path
        result = []
        for img in imgs:
            try:
                rel = str(img.path.relative_to(root)).replace("\\", "/")
            except ValueError:
                continue
            if status_map.get(rel, "") in accept_values:
                result.append(img)
        return result

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

        # 空状态切换 — stack swap keeps the outer layout stable
        self._grid_stack.setCurrentIndex(1 if total == 0 else 0)

        # 更新分页控件
        self._page_validator.setTop(page_count)
        self.page_input.blockSignals(True)
        self.page_input.setText(str(self._page + 1))
        self.page_input.blockSignals(False)
        self.page_total_label.setText(i18n.t("pager.page_of", n=page_count))
        self.count_label.setText(
            i18n.t("pager.total", n=total) if total > 0
            else i18n.t("pager.empty")
        )
        self.prev_btn.setEnabled(self._page > 0)
        self.next_btn.setEnabled(self._page < page_count - 1)

    def _on_category_selected(self, category: str) -> None:
        # Reset filter to "全部" on category switch — users who click a
        # category while a filter is active would otherwise see empty pages
        # on fully-annotated categories and not realize the filter is still
        # engaged. 直觉:类别切换 = 看这类全部。
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

    def _on_sample_set_changed(self, ss) -> None:
        """Rebuild annotated-path + work-status caches when SampleSet changes."""
        if ss is not None and self._state.sample_set_ready:
            self._annotated_cache = {
                str(s.image_path) for s in ss.samples if s.regions
            }
            self._work_status_cache = {
                str(s.image_path): s.work_status
                for s in ss.samples if s.work_status
            }
        else:
            self._annotated_cache = None
            self._work_status_cache = None
        # Re-filter if currently on a filter that depends on SS data.
        if (self._filter_mode in (FilterMode.LABELED, FilterMode.UNLABELED)
                or self._filter_mode in self._work_chips):
            self._apply_filter_and_show()

    def _annotated_paths(self) -> set[str] | None:
        """Return cached set of paths with actual annotations, or None
        if SampleSet is not READY (caller should fall back to has_label)."""
        return self._annotated_cache

    def _on_workflow_summary_changed(self, summary) -> None:
        """Show/hide workflow filter chips based on active workflow."""
        active = summary is not None and summary.total > 0
        for m in self._work_chips:
            self._chips[m].setVisible(active)
        if not active and self._filter_mode in self._work_chips:
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
            self._select_all_btn.setText(i18n.t("filter.unselect_all"))
        else:
            self._select_all_btn.setText(i18n.t("filter.select_all"))

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
        # Same rule as the context menu — no mutations while scan is live.
        if not self._state.can_write:
            InfoBar.warning(
                title="数据集仍在加载",
                content="等后台扫描完成再删除，避免和索引构建产生冲突。",
                isClosable=True, position=InfoBarPosition.TOP,
                duration=3000, parent=self.window(),
            )
            return
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
        txt = self.page_input.text().strip()
        if not txt:
            # Blank → restore current page display without jumping.
            self.page_input.setText(str(self._page + 1))
            return
        try:
            n = int(txt)
        except ValueError:
            self.page_input.setText(str(self._page + 1))
            return
        # Validator bounds the value, but clamp again defensively in case
        # the text was set programmatically.
        n = max(1, min(self._page_validator.top(), n))
        self._page = n - 1
        self._show_page()

    # ---------- 右键菜单 / 批量操作 ----------

    def _on_context_menu(self, pos) -> None:
        sel = self.grid.selected_images()
        if not sel:
            return
        # Quick-open write gate.  Every action in this menu mutates the
        # filesystem or the workflow store — allowing any of them while
        # the ScanWorker is still building SampleSet in Phase 2/3 lets a
        # delete/move/status-flip race with the unify pass and leaves
        # the in-memory model permanently out of sync with disk.  Show a
        # single InfoBar and do not pop the menu at all; matches the
        # DetailView save-gate UX.
        if not self._state.can_write:
            InfoBar.warning(
                title="数据集仍在加载",
                content="等后台扫描完成再做批量操作，避免和索引构建产生冲突。",
                isClosable=True, position=InfoBarPosition.TOP,
                duration=3000, parent=self.window(),
            )
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
        # Workflow transitions
        wf_menu = menu.addMenu(i18n.t("wf.submit_review").split()[0] if i18n.lang() == "zh" else "Workflow")
        wf_menu.addAction(i18n.t("wf.submit_review"),
                          lambda: self.batch_status_requested.emit(sel, "review_pending"))
        wf_menu.addAction(i18n.t("wf.approve"),
                          lambda: self.batch_status_requested.emit(sel, "ready"))
        wf_menu.addAction(i18n.t("wf.reject"),
                          lambda: self.batch_status_requested.emit(sel, "needs_fix"))
        wf_menu.addAction(i18n.t("wf.mark_ready"),
                          lambda: self.batch_status_requested.emit(sel, "ready"))
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
        cats = self._category_names()
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
        cats = self._category_names()
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
        # Collect all images belonging to this category (O(1) via by_name idx)
        cat = self._state.dataset.category_by_name(name)
        cat_images = list(cat.images) if cat else []
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
        cats = self._category_names()
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
        # blocking dialog can't silently drop the log entry. Forward the
        # result's moves map (populated by fileops.move_to_category, empty
        # for other ops) so try_undo_last can locate files that landed
        # with _ensure_unique renames.
        self._record_history(
            ok=result.fail_count == 0,
            ok_count=getattr(result, "ok_count", 0),
            fail_count=getattr(result, "fail_count", 0),
            moves=getattr(result, "moves", None),
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
                         fail_count: int = 0, error: str = "",
                         moves: dict[str, str] | None = None) -> None:
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
        # Merge actual landed paths (review #11) so undo can find files
        # that _ensure_unique renamed on conflict.
        params = dict(hist.get("params", {}))
        if moves:
            params["moves"] = moves
        try:
            _hist.append(
                self._state.dataset.root_path,
                _hist.HistoryEntry.now(
                    action=hist.get("action", "unknown"),
                    params=params,
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
            try:
                self._worker.progress.disconnect()
                self._worker.finished_ok.disconnect()
                self._worker.failed.disconnect()
            except (TypeError, RuntimeError):
                pass
            self._worker.deleteLater()
            self._worker = None
