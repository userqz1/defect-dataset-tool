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
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    Action,
    BodyLabel,
    CaptionLabel,
    FluentIcon as FIF,
    IndeterminateProgressBar,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    MessageBox,
    PushButton,
    RoundMenu,
    TransparentToolButton,
)

from core import fileops, index_cache
from core.exporter.subset import export_subset
from core.models import Dataset, ImageInfo
from core.target_readiness import (
    completed_paths_for_target,
    target_format_is_exportable,
    target_format_for_schema_key,
)
from gui import i18n
from gui.dialogs.op_dialogs import (
    FailureDetailDialog,
    MoveToCategoryDialog,
    ProgressDialog,
)
from gui.theme import T
from gui.widgets.chips import FilterChip
from gui.widgets.scope_badge import Scope, ScopeBadge
from gui.widgets.thumbnail_grid import ThumbnailGrid
from gui.workers.batch_worker import BatchWorker

# Infinite-scroll chunk size — how many thumbs to materialize on the
# initial render and on each "scrolled near bottom" trigger.  80 fits
# ~5 fully-visible rows on a 1080p workbench at the standard 200px card
# width, so the first paint already overshoots the viewport (avoids
# "blank then pop in"); 80-at-a-time keeps the thumb worker queue
# manageable on the way down.
CHUNK_SIZE = 80
# How close to the bottom (in pixels) the user must be before we
# trigger the next-chunk load. One row of cards is ~222px so 240 gives
# a one-row look-ahead.
SCROLL_LOAD_AHEAD_PX = 240
# How long to keep the "加载中…" indicator visible after a chunk has
# been appended.  Long enough that the user perceives the trigger,
# short enough that it doesn't feel sticky.
LOAD_INDICATOR_HOLD_MS = 800


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
    target_format_changed = pyqtSignal(str)     # concrete target format selected

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
        # Infinite-scroll state — _filtered is the full filter result;
        # _visible_count caps how many of those are materialized into
        # the grid right now. Bumped by CHUNK_SIZE whenever the user
        # scrolls near the bottom; reset to CHUNK_SIZE on filter /
        # category / search change so the user sees the new top.
        self._visible_count: int = CHUNK_SIZE
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
        self._target_format: str = ""
        self._target_task_type = None
        self._target_format_options: list[tuple[str, str]] = []
        # Work-status cache: image_path str → WorkStatus.value
        self._work_status_cache: dict[str, str] | None = None

        # Single-column layout — viewer region per the design handoff.
        # DatasetBar and the stage nav now live on DatasetBrowserView
        # (above the stage_stack that hosts this view), so BrowserView
        # is just the "grid/filter/selection" body of the 标注 stage.
        right_layout = QVBoxLayout(self)
        right_layout.setContentsMargins(T.PAD_XL, T.PAD, T.PAD_XL, T.GAP_LG)
        right_layout.setSpacing(T.PAD)

        # CategoryTree reference is set from outside by DatasetBrowserView
        # (it lives in CatalogPanel now). _do_rename / merge / split still
        # need to know the category list, so we read it from this handle.
        self._catalog_tree: "CategoryTree | None" = None

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

        # 目标格式选择器已从标注页移除：标注阶段不绑定导出格式（内容驱动），
        # 交付格式改在「导出」阶段选。内部 _target_format 仍由 set_target_format()
        # 从项目默认值同步，仅供已标注/未标注统计使用，不再暴露为可点选控件。

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

        # Filter bar carries scope only: search, filter chips, and the
        # 全选 toggle. Multi-select doesn't need its own button — every
        # thumbnail card now ships with a top-right checkbox that
        # toggles that one card without affecting others, so users can
        # build a multi-selection by clicking the checkboxes directly
        # (see ThumbnailGrid.mousePressEvent).
        self._select_all_btn = PushButton(i18n.t("filter.select_all"))
        self._select_all_btn.setFixedHeight(T.CONTROL_HEIGHT)
        self._select_all_btn.setEnabled(False)
        self._select_all_btn.clicked.connect(self._on_select_all_toggle)
        filter_bar.addWidget(self._select_all_btn)

        # Re-text on language switch
        i18n.bus.language_changed.connect(self._retranslate)

        right_layout.addLayout(filter_bar)

        # 缩略图网格 — constructed BEFORE the selection-action bar because
        # the bar's "清空选择" button wires ``clicked → grid.clearSelection``
        # and Qt resolves the signal target at connect time, not at emit
        # time.  Layout insertion still happens below via ``_grid_stack``.
        self.grid = ThumbnailGrid()
        self.grid.item_activated.connect(self._on_item_activated)
        self.grid.selection_changed.connect(self._on_selection_changed)
        self.grid.request_thumb.connect(lambda p: self.thumb_request.emit(p))

        # -- Selection action bar (scope: "当前选中") ---------------------
        # Hidden at count == 0 so it doesn't claim layout space. All write
        # ops targeting the current selection live here — delete,
        # move-to-category, add-to-split, workflow transition, export
        # subset. This replaces the previous right-click-menu surface as
        # the primary entry point so discoverability doesn't depend on the
        # user remembering a hidden menu.
        self._selection_bar = self._build_selection_bar()
        right_layout.addWidget(self._selection_bar)
        # Right-click menu intentionally absent — every write op it used
        # to carry (delete, move, split, workflow, export subset) is now
        # a button on the selection action bar so the scope is visible at
        # a glance instead of hidden behind a right-click.
        self._worker: BatchWorker | None = None
        self._progress: ProgressDialog | None = None

        # Wrap grid + empty_hint in a QStackedWidget so swapping between
        # the two doesn't change the overall layout shape. Previously the
        # VBox redistributed freed space into readiness/filter chips when
        # grid hid on empty filter, rendering them as giant rectangles.
        from PyQt6.QtWidgets import QStackedWidget
        self._grid_stack = QStackedWidget()
        self._grid_stack.addWidget(self.grid)          # index 0
        # Empty-state copy is set per-render in _refresh_empty_hint
        # so the user gets distinct messaging for "dataset empty" vs
        # "filter excluded everything".
        self._empty_hint = CaptionLabel("")
        self._empty_hint.setObjectName("browserEmptyHint")
        self._empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_hint.setWordWrap(True)
        self._grid_stack.addWidget(self._empty_hint)   # index 1
        right_layout.addWidget(self._grid_stack, 1)

        # Footer — infinite-scroll status row.  Renders one of:
        #   "加载中…" + "已显示 80 / 1,114"   (mid-stream)
        #   "已全部显示 4,900 张"              (every chunk landed)
        #   "未发现匹配的图片"                 (filter-empty; same widget)
        # plus a "回到顶部" shortcut once the user has scrolled past
        # the first chunk.
        footer = QHBoxLayout()
        footer.setSpacing(T.GAP)
        self.count_label = CaptionLabel("")
        self.count_label.setObjectName("browserFooterCount")
        self._loading_more_label = CaptionLabel("")
        self._loading_more_label.setObjectName("browserFooterLoading")
        self._loading_more_label.setVisible(False)
        self._scroll_top_btn = PushButton(i18n.t("pager.top"))
        self._scroll_top_btn.setIcon(FIF.UP)
        self._scroll_top_btn.setFixedHeight(28)
        self._scroll_top_btn.setToolTip(i18n.t("pager.top"))
        self._scroll_top_btn.setVisible(False)
        self._scroll_top_btn.clicked.connect(self._scroll_to_top)
        footer.addStretch(1)
        footer.addWidget(self._loading_more_label)
        footer.addWidget(self.count_label)
        footer.addSpacing(T.GAP_LG)
        footer.addWidget(self._scroll_top_btn)
        right_layout.addLayout(footer)

        # Wire scroll-to-bottom detection now that the grid + scrollbar
        # exist. SCROLL_LOAD_AHEAD_PX gives us a one-row look-ahead so
        # the next chunk is materializing before the user hits the
        # absolute bottom.  ``_load_pending`` debounces against rapid
        # scroll-event bursts.
        self._load_pending: bool = False
        self.grid.verticalScrollBar().valueChanged.connect(
            self._on_grid_scrolled)

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
        # Recompute selection-bar labels via the usual handler — it sets
        # count + select-all state from the current selection.
        self._on_selection_changed(self.grid.selected_images())
        # Selection action bar static text
        self._sel_clear_btn.setToolTip(i18n.t("sel.clear"))
        self._sel_delete_btn.setText(i18n.t("sel.delete"))
        self._sel_move_btn.setText(i18n.t("sel.move"))
        self._sel_split_btn.setText(i18n.t("sel.split"))
        self._sel_workflow_btn.setText(i18n.t("sel.workflow"))
        self._sel_export_btn.setText(i18n.t("sel.export"))
        self._sel_export_scope.setText(i18n.t("scope.readonly"))
        self._scroll_top_btn.setText(i18n.t("pager.top"))
        self._scroll_top_btn.setToolTip(i18n.t("pager.top"))
        # Repaint the grid so the footer + empty-state copy
        # retranslates against the active language.
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

    def active_category(self) -> str:
        """Return the currently-filtered category (``""`` = all).

        Read by sibling dialogs (大模型标注向导 / 批量填入区域文本 /
        导出向导) so that picking "Loose" once in the catalog tree
        propagates as the default scope through the rest of the
        workflow — instead of forcing the user to re-pick at every
        step.
        """
        return self._current_category or ""

    def set_target_format(self, project) -> None:
        """Refresh the target-format selector for the annotation stage."""
        self._target_format = getattr(project, "target_format", "") if project else ""
        self._target_task_type = getattr(project, "task_type", None) if project else None
        self._target_format_options = self._schema_options_for_project(project)
        self._rebuild_annotated_cache()
        if self._filter_mode in (FilterMode.LABELED, FilterMode.UNLABELED):
            self._apply_filter_and_show()

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

    def _schema_options_for_project(self, project) -> list[tuple[str, str]]:
        if project is None:
            return []
        try:
            from core.schema import schemas_for_task
            schemas = schemas_for_task(project.task_type)
        except Exception:
            schemas = []
        if schemas:
            return [
                (schema.key, schema.display_name)
                for schema in schemas
                if target_format_is_exportable(schema.key)
            ]
        try:
            from core.task_types import TASK_REGISTRY
            info = TASK_REGISTRY.get(project.task_type)
            return [
                (fmt, fmt)
                for fmt in (info.export_formats if info else ())
                if target_format_is_exportable(fmt)
            ]
        except Exception:
            return []

    # 目标格式选择器 UI 已移除（标注不绑定导出格式）。_target_format 仅作为
    # 已标注/未标注统计的内部依据，由 set_target_format() 从项目默认值同步；
    # 不再有可点选的按钮 / 菜单，也不再对外发 target_format_changed。

    # ---------- 状态持久化 ----------

    def save_state(self):
        from core.project import BrowseState
        return BrowseState(
            category=self._current_category,
            # Persist as plain string so BrowseState stays JSON-clean
            filter=self._filter_mode.value,
            search=self._search_text,
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
        # Pagination retired — restoring lands the grid at the top of
        # the freshly-applied filter. Users who want to resume "where
        # I was" rely on the queue queue (Review) or the recent-action
        # log instead.
        self._apply_filter_and_show()

    # ---------- 外部接口 ----------

    def load_dataset(self, dataset: Dataset) -> None:
        """Re-render tree + grid for the given dataset.

        Does NOT store the dataset — AppState owns it. The caller
        (typically ``DatasetBrowserView._on_dataset_changed``) has
        already pushed *dataset* into AppState, so subsequent reads
        via ``self._state.dataset`` see the same object.

        Preserves the active category selection across a rescan so a
        delete (or other in-place mutation) doesn't snap the user back
        to "All". Falls back to "All" only when the previously-selected
        category was itself removed (e.g. last image of "Loose" deleted
        and the empty folder cleaned up).
        """
        valid_names = {c.name for c in dataset.categories}
        if self._current_category and self._current_category not in valid_names:
            # Category was removed by the just-finished operation; bail
            # back to "All" rather than show an empty page rooted on a
            # ghost category.
            self._current_category = ""
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
        # _show_page resets _visible_count + scrolls to top; no separate
        # page reset needed.
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
        """Render the first chunk of the active filter result.

        Name is kept for legacy retranslate / save-state callers; this
        is now the "reset to top + render initial chunk" entry. Use
        :meth:`_load_more` for incremental appends.
        """
        total = len(self._filtered)
        self._visible_count = min(CHUNK_SIZE, total)
        # A filter / category / search change is a hard reset of the
        # infinite-scroll state — clear the in-flight indicator and
        # the debounce gate so a load that was queued under the old
        # filter doesn't ghost into the new view. The 800ms timer
        # behind ``_end_load_more`` would eventually clear them too,
        # but doing it eagerly keeps the footer copy honest.
        self._load_pending = False
        self._loading_more_label.setVisible(False)
        self.clear_thumb_queue.emit()   # cancel stale thumbnail requests
        first_chunk = self._filtered[:self._visible_count]
        self._thumb_pending = len(first_chunk)
        if self._thumb_pending > 0:
            self._thumb_bar.show()
            self._thumb_bar.start()
        self.grid.set_images(
            first_chunk,
            quality_map=self._state.quality_issue_paths,
            target_complete_paths=self._annotated_cache,
        )
        # Reset scroll position so a freshly-applied filter shows from
        # the top, not wherever the previous selection was scrolled to.
        self.grid.verticalScrollBar().setValue(0)

        # Empty-state swap — keeps the outer layout stable.
        if total == 0:
            self._refresh_empty_hint()
            self._grid_stack.setCurrentIndex(1)
        else:
            self._grid_stack.setCurrentIndex(0)

        self._refresh_footer()

    def _refresh_empty_hint(self) -> None:
        """Pick the right empty-state copy for the current view.

        Two cases:
          - Dataset itself has zero images → 数据集为空 (no scan / no
            files / pre-import).
          - Dataset has images but the active filter / search excluded
            them all → 当前筛选无结果.
        """
        # ``_all_images`` walks the active category; for the
        # "dataset empty" check we want the truly-global count.
        ds = self._state.dataset
        global_total = sum(len(cat.images) for cat in ds.categories) \
            if ds is not None else 0
        if global_total == 0:
            self._empty_hint.setText(i18n.t("pager.empty_dataset"))
        else:
            self._empty_hint.setText(i18n.t("pager.empty_filter"))

    def _load_more(self) -> None:
        """Append the next chunk after a scroll-near-bottom trigger.

        Guarded by ``_load_pending`` against rapid valueChanged bursts
        from a fast scroll: while a chunk is being appended, further
        scroll events early-return.  Reset on the same QTimer that
        hides the loading indicator.
        """
        if self._load_pending:
            return
        total = len(self._filtered)
        if self._visible_count >= total:
            return
        start = self._visible_count
        end = min(start + CHUNK_SIZE, total)
        chunk = self._filtered[start:end]
        if not chunk:
            return
        self._load_pending = True
        self._loading_more_label.setText(i18n.t("pager.loading_more"))
        self._loading_more_label.setVisible(True)
        self._thumb_pending += len(chunk)
        if self._thumb_pending > 0:
            self._thumb_bar.show()
            self._thumb_bar.start()
        self.grid.append_images(
            chunk,
            quality_map=self._state.quality_issue_paths,
            target_complete_paths=self._annotated_cache,
        )
        self._visible_count = end
        self._refresh_footer()
        # Keep the indicator visible long enough that a fast scroll
        # doesn't make it flash; release the debounce gate at the same
        # time so the next chunk can fire.
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(LOAD_INDICATOR_HOLD_MS, self._end_load_more)

    def _end_load_more(self) -> None:
        """Hide the in-flight indicator + release the debounce gate."""
        self._loading_more_label.setVisible(False)
        self._load_pending = False
        # If the user kept scrolling while the indicator was held, the
        # bottom may have crept back into the trigger window. Re-check
        # so the next chunk loads automatically without waiting for a
        # fresh scroll event.
        sb = self.grid.verticalScrollBar()
        if sb.maximum() > 0 and sb.value() >= sb.maximum() - max(
                SCROLL_LOAD_AHEAD_PX, sb.pageStep() // 2):
            self._load_more()

    def _refresh_footer(self) -> None:
        """Update count label + scroll-to-top button visibility.

        Three visual states:
          - 数据集为空 / 当前筛选无结果: empty-state hint card is
            already covering the grid; the footer count goes blank.
          - 流程中: "已显示 X / Y" while more chunks remain.
          - 全量已加载: "已全部显示 Y 张" (terminal state).
        """
        total = len(self._filtered)
        if total == 0:
            self.count_label.setText("")
        elif self._visible_count >= total:
            self.count_label.setText(
                i18n.t("pager.shown_all", total=total))
        else:
            self.count_label.setText(i18n.t(
                "pager.shown", shown=self._visible_count, total=total))
        self._scroll_top_btn.setVisible(self._visible_count > CHUNK_SIZE)

    def _on_grid_scrolled(self, value: int) -> None:
        """Trigger the next chunk load when within SCROLL_LOAD_AHEAD_PX.

        Bound to the grid's verticalScrollBar valueChanged signal.  The
        debounce gate (``_load_pending``) lives on ``_load_more``; this
        handler stays as a thin "is the user near the bottom" check.
        """
        sb = self.grid.verticalScrollBar()
        if sb.maximum() <= 0:
            return
        # ``value`` is page-relative; pageStep is the visible viewport.
        # Trigger when the next-chunk look-ahead window has been
        # entered.  Using max(SCROLL_LOAD_AHEAD_PX, pageStep/2) means
        # very tall viewports still get a sane pre-load distance.
        if value >= sb.maximum() - max(SCROLL_LOAD_AHEAD_PX, sb.pageStep() // 2):
            self._load_more()

    def _scroll_to_top(self) -> None:
        self.grid.verticalScrollBar().setValue(0)

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
            self._rebuild_annotated_cache(ss)
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

    def _rebuild_annotated_cache(self, ss=None) -> None:
        if ss is None:
            ss = self._state.sample_set
        if ss is None or not self._state.sample_set_ready:
            self._annotated_cache = None
            return
        if self._target_format:
            self._annotated_cache = completed_paths_for_target(
                ss.samples,
                self._target_format,
                self._target_task_type,
            )
        else:
            self._annotated_cache = {
                str(s.image_path) for s in ss.samples if s.regions
            }

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
        # Selection action bar is the primary surface for batch writes —
        # show it only when a selection exists, so the chrome doesn't
        # claim layout space on every dataset open.
        self._selection_bar.setVisible(n > 0)
        if n > 0:
            self._sel_count_label.setText(i18n.t("sel.count", n=n))
        # Toggle select-all button label + enabled state (stays on the
        # filter bar — this is a selection-mode control, not a write op).
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

    # ---------- Selection action bar ----------

    def _build_selection_bar(self) -> QFrame:
        """Contextual action bar — visible only when count > 0.

        Exposes every write op targeting the current selection so they're
        no longer buried in the right-click menu. Layout: count/clear on
        the left, write actions right-aligned so the buttons sit near the
        mouse after a rubber-band or ctrl-click gesture.
        """
        bar = QFrame()
        bar.setObjectName("selectionActionBar")
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        bar.hide()  # shown on first selection_changed with n > 0

        lay = QHBoxLayout(bar)
        lay.setContentsMargins(T.PAD_LG, T.GAP, T.PAD_LG, T.GAP)
        lay.setSpacing(T.GAP)

        # Count label — BodyLabel (semantic, rule-5 happy) with objectName
        # so app.qss can tone it down to TEXT_2 + font-weight 500.
        self._sel_count_label = BodyLabel("")
        self._sel_count_label.setObjectName("selectionCountLabel")
        lay.addWidget(self._sel_count_label)

        self._sel_clear_btn = TransparentToolButton(FIF.CLOSE)
        self._sel_clear_btn.setToolTip(i18n.t("sel.clear"))
        self._sel_clear_btn.setFixedSize(24, 24)
        self._sel_clear_btn.clicked.connect(self.grid.clearSelection)
        lay.addWidget(self._sel_clear_btn)

        lay.addStretch(1)

        self._sel_delete_btn = PushButton(i18n.t("sel.delete"))
        self._sel_delete_btn.setIcon(FIF.DELETE)
        self._sel_delete_btn.setFixedHeight(T.CONTROL_HEIGHT)
        self._sel_delete_btn.clicked.connect(self._on_delete_clicked)
        lay.addWidget(self._sel_delete_btn)

        self._sel_move_btn = PushButton(i18n.t("sel.move"))
        self._sel_move_btn.setIcon(FIF.TAG)
        self._sel_move_btn.setFixedHeight(T.CONTROL_HEIGHT)
        self._sel_move_btn.clicked.connect(self._on_move_clicked)
        lay.addWidget(self._sel_move_btn)

        # Split picker — create the popup lazily. Pre-creating RoundMenu at
        # startup registers hidden top-level windows on Windows, which can
        # flicker as tiny orphan popups before the main window appears.
        self._sel_split_btn = PushButton(i18n.t("sel.split"))
        self._sel_split_btn.setIcon(FIF.SHARE)
        self._sel_split_btn.setFixedHeight(T.CONTROL_HEIGHT)
        self._sel_split_btn.clicked.connect(self._show_split_menu)
        lay.addWidget(self._sel_split_btn)

        # Workflow transition picker — 4 states from the old right-click menu.
        self._sel_workflow_btn = PushButton(i18n.t("sel.workflow"))
        self._sel_workflow_btn.setIcon(FIF.FLAG)
        self._sel_workflow_btn.setFixedHeight(T.CONTROL_HEIGHT)
        self._sel_workflow_btn.clicked.connect(self._show_workflow_menu)
        lay.addWidget(self._sel_workflow_btn)

        self._sel_export_btn = PushButton(i18n.t("sel.export"))
        self._sel_export_btn.setIcon(FIF.DOWNLOAD)
        self._sel_export_btn.setFixedHeight(T.CONTROL_HEIGHT)
        self._sel_export_btn.clicked.connect(self._on_export_subset_clicked)
        lay.addWidget(self._sel_export_btn)
        # Export is the one selection-bar action that doesn't mutate the
        # project — flag it explicitly so the user knows the rest do.
        self._sel_export_scope = ScopeBadge(
            i18n.t("scope.readonly"), Scope.READONLY)
        lay.addWidget(self._sel_export_scope)

        return bar

    def _show_split_menu(self) -> None:
        menu = RoundMenu(parent=self._sel_split_btn)
        menu.addAction(Action(
            i18n.t("sel.split.train"),
            triggered=lambda: self._emit_add_to_split("train")))
        menu.addAction(Action(
            i18n.t("sel.split.val"),
            triggered=lambda: self._emit_add_to_split("val")))
        menu.addAction(Action(
            i18n.t("sel.split.test"),
            triggered=lambda: self._emit_add_to_split("test")))
        menu.exec(self._sel_split_btn.mapToGlobal(
            self._sel_split_btn.rect().bottomLeft()))

    def _show_workflow_menu(self) -> None:
        menu = RoundMenu(parent=self._sel_workflow_btn)
        menu.addAction(Action(
            i18n.t("wf.submit_review"),
            triggered=lambda: self._emit_workflow("ready")))
        menu.addAction(Action(
            i18n.t("wf.mark_review"),
            triggered=lambda: self._emit_workflow("review_pending")))
        menu.addAction(Action(
            i18n.t("wf.reject"),
            triggered=lambda: self._emit_workflow("needs_fix")))
        menu.exec(self._sel_workflow_btn.mapToGlobal(
            self._sel_workflow_btn.rect().bottomLeft()))

    def _guard_write(self) -> bool:
        """Gate any selection-bar write against the Phase 2 scan.

        Returns True when the write may proceed, False otherwise (and
        surfaces an InfoBar). Mirrors the existing behavior formerly
        embedded in ``_on_delete_clicked`` + ``_on_context_menu`` so we
        keep one rule: the moment ScanWorker flips ``can_write`` back
        on, all buttons come alive at the same time.
        """
        if self._state.can_write:
            return True
        InfoBar.warning(
            title="数据集仍在加载",
            content="等后台扫描完成再做批量操作，避免和索引构建产生冲突。",
            isClosable=True, position=InfoBarPosition.TOP,
            duration=3000, parent=self.window(),
        )
        return False

    def _on_delete_clicked(self) -> None:
        if not self._guard_write():
            return
        sel = self.grid.selected_images()
        if sel:
            self._do_delete(sel)

    def _on_move_clicked(self) -> None:
        if not self._guard_write():
            return
        sel = self.grid.selected_images()
        if sel:
            self._do_move(sel)

    def _on_export_subset_clicked(self) -> None:
        if not self._guard_write():
            return
        sel = self.grid.selected_images()
        if sel:
            self._do_export_subset(sel)

    def _emit_add_to_split(self, bucket: str) -> None:
        if not self._guard_write():
            return
        sel = self.grid.selected_images()
        if sel:
            self.add_to_split.emit(bucket, sel)

    def _emit_workflow(self, status: str) -> None:
        if not self._guard_write():
            return
        sel = self.grid.selected_images()
        if sel:
            self.batch_status_requested.emit(sel, status)

    def _on_item_activated(self, img: ImageInfo) -> None:
        self.image_activated.emit(img, self._filtered)

    # ---------- 批量操作 ----------
    # Entry points are on the selection action bar (_build_selection_bar).
    # No right-click context menu — hidden surfaces duplicated actions and
    # let the user lose track of what's reachable at a given scope.

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
        body = self.tr(
            "将永久删除以下内容，删除后无法恢复，确认继续？\n\n"
        ) + "\n".join(parts)
        box = MessageBox(self.tr("确认永久删除"), body, self.window())
        box.yesButton.setText(self.tr("永久删除"))
        if not box.exec():
            return
        self._run(
            lambda cb: fileops.delete_pairs(sel, progress_cb=cb),
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
