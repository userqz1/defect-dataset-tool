"""Single-image detail view — viewer + image inspector (right ContextPanel).

Structure (IA v3.6 — P1.6 Inspector consolidation)::

    DetailView (canvas-only)
    ├── topbar (back / crumb / nav / zoom / edit / shape tools / save / move_cat)
    └── body
        └── ImageViewer (shape overlay + pan/zoom)

    ImageInspector (built by DetailView, reparented into ContextPanel)
    ├── File info (always visible)
    └── SegmentedWidget + QStackedWidget
        ├── AnnotationPane / ImageLabelPane  (shape list / chip workbench)
        ├── VlmPane                          (caption, conversations)
        └── StatusPane                       (workflow transitions)

The inspector is built inside DetailView (so all binding + save logic
keeps its existing pane refs) but is **not** added to DetailView's
body.  ``DetailView.inspector`` exposes the bare frame so the workbench
shell can register it as a page in the right :class:`ContextPanel`,
unifying the right-column space model: catalog while on the grid,
inspector while on a single image.

Which panes light up — and which sub-features each pane includes — is
driven by :class:`gui.views.detail_specs.TaskWorkbenchSpec`. Unused
panes are **not instantiated**: zero widgets created, zero signals
wired, zero retranslate subscribers. Classification / anomaly projects
never pay for the VLM tree; VLM-only projects won't pay for shape
editing.

The shell owns:

- Image I/O: ``_ImageLoader`` off-thread decode, prefetch, LRU cache.
- Region↔Shape bridge (bottom of the module).
- SampleSet / Annotation state — single source of truth for writes.
- Save conflict detection (label file mtime), write-gate while scan
  is still building SampleSet.
- All six public signals (back / change_category / work_status /
  caption / conversations / grounding).
- Keyboard shortcuts (A/D/H/E/R/P/Enter/Del/Ctrl+S/Esc).

Panes are thin: they present state and emit intent. The shell converts
intent + internal state → disk writes + signal emission on the
caller-visible API.
"""
from __future__ import annotations

from PyQt6.QtCore import QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QImage, QKeyEvent, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    EditableComboBox,
    FluentIcon as FIF,
    InfoBar,
    InfoBarPosition,
    MessageBox,
    PushButton,
    SegmentedWidget,
    ToolButton,
)

from core.annotation_writer import write_annotation
from core.models import Annotation, ImageInfo, Shape
from core.project import Project
from core.unified import BBox, Region, Sample, SampleSet
from gui import i18n
from gui.theme import T
from gui.views.detail_specs import (
    DetailSegment,
    ImageLabelKind,
    TaskWorkbenchSpec,
    spec_for,
)
from gui.views.panes.annotation_pane import AnnotationPane
from gui.views.panes.image_label_pane import ImageLabelPane
from gui.views.panes.status_pane import StatusPane, WF_STATUS_LABELS
from gui.views.panes.vlm_pane import VlmPane
from gui.widgets.image_viewer import ImageViewer


# ── Region ↔ Shape bridge (unified model ↔ legacy viewer model) ────

def _region_to_shape(r: Region) -> Shape:
    """Convert a unified Region to a legacy Shape for ImageViewer."""
    if r.shape_type == "rectangle" and r.bbox:
        pts = [(r.bbox.x1, r.bbox.y1), (r.bbox.x2, r.bbox.y2)]
    elif r.polygon:
        pts = list(r.polygon)
    elif r.bbox:
        pts = [(r.bbox.x1, r.bbox.y1), (r.bbox.x2, r.bbox.y2)]
    elif r.keypoints:
        pts = [(x, y) for x, y, _ in r.keypoints]
    else:
        pts = []
    return Shape(label=r.label, shape_type=r.shape_type, points=pts,
                 text=r.text)


def _shape_to_region(s: Shape) -> Region:
    """Convert a legacy Shape back to a unified Region."""
    region = Region(label=s.label, shape_type=s.shape_type, text=s.text)
    if s.shape_type == "rectangle" and len(s.points) >= 2:
        region.bbox = BBox.from_points(s.points)
    elif s.shape_type in ("polygon", "linestrip") and s.points:
        region.polygon = list(s.points)
        region.bbox = BBox.from_points(s.points)
    elif s.shape_type == "point" and s.points:
        region.keypoints = [(p[0], p[1], 2) for p in s.points]
        if s.points:
            region.bbox = BBox.from_points(s.points)
    else:
        if s.points:
            region.bbox = BBox.from_points(s.points)
    return region


def _sample_to_annotation(sample: Sample) -> Annotation:
    """Build a legacy Annotation from a unified Sample."""
    return Annotation(
        image_path=sample.image_path,
        shapes=[_region_to_shape(r) for r in sample.regions],
    )


def _annotation_to_regions(ann: Annotation) -> list[Region]:
    """Convert legacy Annotation shapes to unified Regions."""
    return [_shape_to_region(s) for s in ann.shapes]


class _ImageLoader(QThread):
    """Load image + parse annotation off the main thread.

    Emits QImage (thread-safe), NOT QPixmap. The main-thread slot
    must do QPixmap.fromImage() itself. Each loader carries a
    ``generation`` token so the slot can drop stale results — cancel()
    is best-effort (QImage(path) can't be interrupted mid-read) and a
    late ``done`` signal would otherwise clobber the viewer with the
    wrong image.

    ``prefetch=True`` makes the loader silent — it only fills the cache
    via the ``prefetched`` signal, never emits ``done``. Lets us warm
    the next/prev images in the background while the user looks at the
    current one.
    """

    # Payload: (QImage, Annotation|None, ImageInfo, generation)
    done = pyqtSignal(object, object, object, int)
    # Payload: (path_str, QImage, Annotation|None)
    prefetched = pyqtSignal(str, object, object)

    def __init__(self, img: ImageInfo, generation: int,
                 prefetch: bool = False, parent=None,
                 pre_annotation: Annotation | None = None) -> None:
        super().__init__(parent)
        self._img = img
        self._gen = generation
        self._prefetch = prefetch
        self._pre_annotation = pre_annotation
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        if self._cancelled:
            return
        image = QImage(str(self._img.path))
        if self._cancelled:
            return

        # Use pre-built annotation (from unified SampleSet) when available;
        # fall back to format_in (unified model) for disk parsing.
        annotation = self._pre_annotation
        if (annotation is None and not self._cancelled
                and self._img.has_label and self._img.label_path):
            try:
                from core.format_in import load_sample
                sample = load_sample(self._img)
                annotation = _sample_to_annotation(sample)
            except Exception:
                annotation = None

        if self._cancelled:
            return
        if self._prefetch:
            self.prefetched.emit(str(self._img.path), image, annotation)
        else:
            self.done.emit(image, annotation, self._img, self._gen)


class DetailView(QWidget):
    """Single-image detail shell. See module docstring."""

    back_requested = pyqtSignal()
    # Reassign the current image's category without returning to the grid.
    # Payload: (ImageInfo, new_category_name).  DatasetBrowserView owns
    # the fileops + rescan.
    change_category_requested = pyqtSignal(object, str)
    # Workflow status transition — (ImageInfo, new_status_value)
    work_status_changed = pyqtSignal(object, str)
    # VLM caption saved — (ImageInfo, caption_text)
    caption_saved = pyqtSignal(object, str)
    # VLM conversations saved — (ImageInfo, conversations_list)
    conversations_saved = pyqtSignal(object, object)
    # Grounding (region text) saved — (ImageInfo, grounding_list)
    grounding_saved = pyqtSignal(object, object)
    # Local shape-edit undo stack changed (push/pop/clear). The shell
    # listens so the global undo button on DatasetBar can light up
    # while the user is in DetailView and there's something to undo.
    undo_state_changed = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("detailView")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        # ---- Shell state ----
        self._images: list[ImageInfo] = []
        self._index: int = -1
        self._annotation: Annotation | None = None
        # Project's preferred annotation format for write-back; set from
        # DatasetBrowserView via ``set_annotation_format``.
        self._annotation_format: str = "labelme"
        # Write gate — DatasetBrowserView flips this from AppState
        # ``scan_active_changed``. While False, every save handler shows
        # a blocking InfoBar and returns early. Guards against the
        # quick-open race where a Ctrl+S lands on disk while Phase-2 of
        # the scan is still assembling the in-memory SampleSet.
        self._write_enabled: bool = True
        # Unified model — when populated, annotation loading reads from
        # pre-parsed Samples instead of re-parsing label files from disk.
        self._sample_set: SampleSet | None = None
        self._sample_index: dict[str, Sample] = {}  # path_str → Sample
        # Conflict-detection baseline (ns precision — float st_mtime plus
        # a 0.001s tolerance would be too fine for FAT32/NAS (2s) and
        # too fragile in general).
        self._label_mtime_at_load: int | None = None
        # Generation token — _on_image_loaded ignores stale ``done``
        # deliveries whose generation != current.
        self._load_generation: int = 0
        # LRU cache of decoded images — keyed by str(path). Each slot:
        # (QImage, Annotation|None). 3 slots ≈ 150 MB peak for 4K images
        # while covering the common A↔D ping-pong pattern.
        self._image_cache: dict[str, tuple] = {}
        self._image_cache_order: list[str] = []
        self._image_cache_max: int = 3
        # In-flight prefetch paths — without this, rapid A/D keypresses
        # spawn a new pair of 4K-decode threads per keystroke.
        self._inflight_prefetch: set[str] = set()
        # Dirty flag for unsaved-changes prompt on navigate-away.
        self._dirty: bool = False
        # Per-image local undo stack — captures shape state *before*
        # destructive edits so the global 撤销 button (and Ctrl+Z) can
        # restore it. Cleared whenever the user navigates to a
        # different image; lives only as long as the current view.
        self._undo_stack: list[tuple[str, list[Shape]]] = []
        self._undo_max: int = 50

        # Workbench spec — defaults to detection-like until
        # set_project_profile() fires after project_changed. Panes are
        # created against this spec in _rebuild_panes() below.
        self._spec: TaskWorkbenchSpec = spec_for(None)

        # Pane refs (re-assigned by _rebuild_panes; None when pane is
        # gated off by the current spec).
        self._annotation_pane: AnnotationPane | None = None
        self._image_label_pane: ImageLabelPane | None = None
        self._vlm_pane: VlmPane | None = None
        self._status_pane: StatusPane | None = None

        # The segmented control + stack get rebuilt on spec change;
        # keep the zone layout stable so sidebar geometry doesn't shift.
        self._segmented: SegmentedWidget | None = None
        self._pane_stack: QStackedWidget | None = None

        # ---- Layout ----
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_topbar())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self.viewer = ImageViewer()
        self.viewer.zoom_changed.connect(self._on_zoom_changed)
        self.viewer.shapes_changed.connect(self._on_shapes_changed)
        self.viewer.selection_changed.connect(self._on_selection_changed)
        self.toggle_anno_btn.toggled.connect(self.viewer.set_annotation_visible)
        body.addWidget(self.viewer, 1)

        # Inspector is built but NOT added to DetailView's own body.
        # The workbench shell registers it as a page in the right
        # ContextPanel so the workspace's right column carries either
        # the catalog (grid mode) or the inspector (detail mode) —
        # never both, never duplicated.
        self.inspector: QFrame = self._build_sidebar()

        root.addLayout(body, 1)

        # Build initial panes against the default (detection) spec.
        self._rebuild_panes()
        self._update_topbar_for_spec()

    # ════════════════════════════════════════════════════════════════
    # Construction helpers
    # ════════════════════════════════════════════════════════════════

    def _build_topbar(self) -> QFrame:
        topbar = QFrame()
        topbar.setObjectName("detailTopBar")
        topbar.setFixedHeight(48)
        lay = QHBoxLayout(topbar)
        lay.setContentsMargins(T.GAP_LG, 0, T.PAD_LG, 0)
        lay.setSpacing(T.GAP)

        self.back_btn = ToolButton(FIF.LEFT_ARROW)
        self.back_btn.setToolTip("返回浏览 (Esc)")
        self.back_btn.clicked.connect(self._on_back_clicked)
        lay.addWidget(self.back_btn)

        self.crumb_label = BodyLabel("—")
        lay.addWidget(self.crumb_label)
        # Scope marker — every save/edit/status flip in DetailView acts on
        # the current image. One badge in the breadcrumb covers the whole
        # surface so individual buttons don't need to repeat it.
        from gui.widgets.scope_badge import Scope, ScopeBadge
        self._scope_badge = ScopeBadge(
            i18n.t("scope.current_image"), Scope.NEUTRAL)
        lay.addWidget(self._scope_badge)
        lay.addStretch(1)

        # Navigation + zoom cluster.
        self.prev_btn = ToolButton(FIF.LEFT_ARROW)
        self.prev_btn.setToolTip("上一张 (A)")
        self.prev_btn.clicked.connect(self.prev_image)
        self.next_btn = ToolButton(FIF.RIGHT_ARROW)
        self.next_btn.setToolTip("下一张 (D)")
        self.next_btn.clicked.connect(self.next_image)
        # Skip directly to the next image still missing VLM data the
        # project signed up for (Caption / Conversations / Grounding).
        # Hidden when no VLM cap is on — see _update_topbar_for_spec.
        self.next_incomplete_btn = PushButton("下一张未完成")
        self.next_incomplete_btn.setToolTip(
            "跳到下一张缺 Caption / 对话 / Grounding 的图片 (Tab)")
        self.next_incomplete_btn.setFixedHeight(28)
        self.next_incomplete_btn.clicked.connect(self.next_incomplete_image)
        self.next_incomplete_btn.hide()
        self.zoom_out_btn = ToolButton(FIF.REMOVE)
        self.zoom_out_btn.setToolTip("缩小")
        self.zoom_out_btn.clicked.connect(lambda: self.viewer.zoom_out())
        self.zoom_in_btn = ToolButton(FIF.ADD)
        self.zoom_in_btn.setToolTip("放大")
        self.zoom_in_btn.clicked.connect(lambda: self.viewer.zoom_in())
        self.fit_btn = ToolButton(FIF.ZOOM)
        self.fit_btn.setToolTip("适应窗口")
        self.fit_btn.clicked.connect(lambda: self.viewer.reset_view())
        self.actual_btn = ToolButton(FIF.FULL_SCREEN)
        self.actual_btn.setToolTip("实际像素 1:1")
        self.actual_btn.clicked.connect(lambda: self.viewer.zoom_to_actual())
        self.toggle_anno_btn = ToolButton(FIF.VIEW)
        self.toggle_anno_btn.setCheckable(True)
        self.toggle_anno_btn.setChecked(True)
        self.toggle_anno_btn.setToolTip("显示 / 隐藏标注 (H)")
        # Swap icon on state change so the button reads as two distinct
        # states (eye-open vs eye-struck), not "same icon, maybe pressed".
        self.toggle_anno_btn.toggled.connect(
            lambda on: self.toggle_anno_btn.setIcon(
                FIF.VIEW if on else FIF.HIDE)
        )

        # Edit-mode cluster.
        self.edit_btn = ToolButton(FIF.EDIT)
        self.edit_btn.setCheckable(True)
        self.edit_btn.setToolTip("编辑标注 (E) — 拖拽绘制 / 点选删除")
        self.edit_btn.toggled.connect(self._on_edit_toggled)

        self.shape_rect_btn = ToolButton(FIF.LAYOUT)
        self.shape_rect_btn.setCheckable(True)
        self.shape_rect_btn.setChecked(True)
        self.shape_rect_btn.setToolTip("矩形 (R)")
        self.shape_poly_btn = ToolButton(FIF.IOT)
        self.shape_poly_btn.setCheckable(True)
        self.shape_poly_btn.setToolTip(
            "多边形 (P) — 左键加点, 双击/回车闭合, 右键取消")
        self.shape_rect_btn.clicked.connect(
            lambda: self._set_shape_type("rectangle"))
        self.shape_poly_btn.clicked.connect(
            lambda: self._set_shape_type("polygon"))
        self.shape_rect_btn.hide()
        self.shape_poly_btn.hide()

        self.label_combo = EditableComboBox()
        self.label_combo.setMinimumWidth(120)
        self.label_combo.setToolTip("绘制时使用的标签名")
        self.label_combo.currentTextChanged.connect(
            lambda t: self.viewer.set_draw_label(t))
        self.label_combo.hide()

        self.save_btn = ToolButton(FIF.SAVE)
        self.save_btn.setToolTip("保存标注 (Ctrl+S)")
        self.save_btn.clicked.connect(self._on_save)
        self.save_btn.hide()

        self.delete_shape_btn = ToolButton(FIF.DELETE)
        self.delete_shape_btn.setToolTip("删除选中标注 (Del)")
        self.delete_shape_btn.clicked.connect(self._delete_selected_shape)
        self.delete_shape_btn.hide()

        self.zoom_label = BodyLabel("100%")
        self.zoom_label.setMinimumWidth(48)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lay.addWidget(self.prev_btn)
        lay.addWidget(self.next_btn)
        lay.addWidget(self.next_incomplete_btn)
        lay.addWidget(self.zoom_out_btn)
        lay.addWidget(self.zoom_label)
        lay.addWidget(self.zoom_in_btn)
        lay.addWidget(self.fit_btn)
        lay.addWidget(self.actual_btn)
        lay.addWidget(self.toggle_anno_btn)
        lay.addWidget(self.edit_btn)
        lay.addWidget(self.shape_rect_btn)
        lay.addWidget(self.shape_poly_btn)
        lay.addWidget(self.label_combo)
        lay.addWidget(self.delete_shape_btn)
        lay.addWidget(self.save_btn)

        self.move_cat_btn = ToolButton(FIF.FOLDER)
        self.move_cat_btn.setToolTip("改分类 (把当前图移到其他类别)")
        self.move_cat_btn.clicked.connect(self._on_move_category)
        lay.addWidget(self.move_cat_btn)

        self.help_btn = ToolButton(FIF.HELP)
        self.help_btn.setToolTip("快捷键帮助")
        self.help_btn.clicked.connect(self._show_shortcuts)
        lay.addWidget(self.help_btn)

        return topbar

    def _build_sidebar(self) -> QFrame:
        # Renamed object name — the widget is now hosted inside the
        # workbench shell's right ContextPanel (P1.6) rather than as a
        # DetailView-internal column. Width is whatever the parent page
        # offers (CONTEXT_PANEL_WIDTH); no per-frame fixed width.
        sidebar = QFrame()
        sidebar.setObjectName("imageInspector")
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(
            T.PAD_XL, T.PAD_XL, T.PAD_XL, T.PAD_XL)
        side_layout.setSpacing(T.GAP_LG)

        # File info header — always visible regardless of task.
        side_layout.addWidget(self._section_label("文件信息"))
        self.info_name = self._meta_value("—")
        self.info_path = self._meta_value("—", small=True)
        self.info_size = self._meta_value("—")
        self.info_dim = self._meta_value("—")
        self.info_cat = self._meta_value("—")
        side_layout.addLayout(self._meta_row("文件名", self.info_name))
        side_layout.addLayout(self._meta_row("路径", self.info_path))
        side_layout.addLayout(self._meta_row("大小", self.info_size))
        side_layout.addLayout(self._meta_row("尺寸", self.info_dim))
        side_layout.addLayout(self._meta_row("类别", self.info_cat))

        side_layout.addSpacing(T.GAP)

        # Pane zone — sub-layout so _rebuild_panes can clear it without
        # disturbing the file-info header above.
        self._pane_zone = QVBoxLayout()
        self._pane_zone.setContentsMargins(0, 0, 0, 0)
        self._pane_zone.setSpacing(T.GAP)
        side_layout.addLayout(self._pane_zone, 1)

        return sidebar

    # ════════════════════════════════════════════════════════════════
    # Spec-driven pane rebuild
    # ════════════════════════════════════════════════════════════════

    def _rebuild_panes(self) -> None:
        """Tear down any existing panes and rebuild per ``self._spec``.

        Called once from ``__init__`` against the default spec, then
        again whenever ``set_project_profile`` sees a different spec.
        """
        # -- Tear down the old widgets.  Removing from the layout is
        # enough to stop Qt from laying them out; deleteLater frees the
        # C++ side on the next event loop turn.
        if self._segmented is not None:
            self._pane_zone.removeWidget(self._segmented)
            self._segmented.deleteLater()
            self._segmented = None
        if self._pane_stack is not None:
            self._pane_zone.removeWidget(self._pane_stack)
            self._pane_stack.deleteLater()
            self._pane_stack = None
        # Pane refs point at widgets that are children of the stack —
        # when the stack is deleteLater'd they'll cascade. Drop refs.
        self._annotation_pane = None
        self._image_label_pane = None
        self._vlm_pane = None
        self._status_pane = None

        spec = self._spec

        self._segmented = SegmentedWidget()
        self._pane_stack = QStackedWidget()

        # Build in fixed segment order so the tab ribbon reads the same
        # across task types: 标注 first, then VLM, then 状态.
        entries: list[tuple[DetailSegment, str, str, QWidget]] = []

        if spec.has_annotation:
            # Image-level tasks (classification / multi-label / anomaly)
            # get the chip-driven label workbench instead of a shape list.
            if spec.image_label_kind is not ImageLabelKind.NONE:
                self._image_label_pane = ImageLabelPane(spec.image_label_kind)
                self._image_label_pane.class_picked.connect(
                    self._on_class_picked)
                self._image_label_pane.labels_changed.connect(
                    self._on_image_labels_changed)
                entries.append((
                    DetailSegment.ANNOTATION, "annotation",
                    i18n.t("detail.seg.annotation"), self._image_label_pane,
                ))
            else:
                self._annotation_pane = AnnotationPane(
                    show_region_text=spec.show_region_text,
                )
                self._annotation_pane.save_grounding_requested.connect(
                    self._on_save_grounding)
                # List → canvas: clicking a row in the shape list
                # highlights the matching shape on the viewer. The
                # canvas → list direction is already wired below via
                # viewer.selection_changed → _on_selection_changed.
                self._annotation_pane.shape_selected.connect(
                    self._on_pane_shape_selected)
                # Right-click "删除此标注" on a list row.
                self._annotation_pane.delete_shape_requested.connect(
                    self._on_pane_delete_shape)
                entries.append((
                    DetailSegment.ANNOTATION, "annotation",
                    i18n.t("detail.seg.annotation"), self._annotation_pane,
                ))

        if spec.has_vlm:
            self._vlm_pane = VlmPane(
                has_caption=spec.has_caption,
                has_conversations=spec.has_conversations,
                has_grounding=spec.show_region_text,
            )
            self._vlm_pane.save_caption_requested.connect(
                self._on_save_caption)
            self._vlm_pane.save_conversations_requested.connect(
                self._on_save_conversations)
            entries.append((
                DetailSegment.VLM, "vlm",
                i18n.t("detail.seg.vlm"), self._vlm_pane,
            ))

        if spec.has_status:
            self._status_pane = StatusPane()
            self._status_pane.status_change_requested.connect(
                self._transition_work_status)
            entries.append((
                DetailSegment.STATUS, "status",
                i18n.t("detail.seg.status"), self._status_pane,
            ))

        for _seg, route_key, text, pane in entries:
            self._pane_stack.addWidget(pane)
            # Capture pane by default arg so every lambda binds its own.
            # ``*_`` swallows any positional args qfluentwidgets passes
            # to onClick (e.g. checked-state bool); without it, ``p``
            # gets overridden to True/False and ``setCurrentWidget``
            # raises TypeError.
            self._segmented.addItem(
                routeKey=route_key, text=text,
                onClick=lambda *_, p=pane: self._pane_stack.setCurrentWidget(p),
            )

        # Apply default segment. setCurrentItem emits currentItemChanged
        # but that signal isn't wired to the stack — do the stack switch
        # explicitly to keep the two in lockstep on first-show.
        default_key = spec.default_segment.value
        for _seg, key, _text, pane in entries:
            if key == default_key:
                self._segmented.setCurrentItem(default_key)
                self._pane_stack.setCurrentWidget(pane)
                break

        # Hide the ribbon when there's only one segment — the tab strip
        # would just be visual noise.
        self._segmented.setVisible(len(entries) > 1)

        self._pane_zone.addWidget(self._segmented)
        self._pane_zone.addWidget(self._pane_stack, 1)

        # If we rebuilt while an image was loaded, push its state into
        # the fresh panes so the user doesn't have to re-navigate.
        if 0 <= self._index < len(self._images):
            self._repaint_panes(self._images[self._index])

    def _update_topbar_for_spec(self) -> None:
        """Gate shape-edit controls by the current spec's ``shape_tools``.

        When a task has no shape tools (classification / anomaly /
        pair), edit mode is meaningless — hide the edit button so the
        user can't enter a state they can't act on.  Individual shape
        buttons (rect/poly) are only visible in edit mode and are
        further gated by which tools the spec allows.
        """
        has_tools = bool(self._spec.shape_tools)
        self.edit_btn.setVisible(has_tools)
        if not has_tools and self.edit_btn.isChecked():
            # Force edit mode off so orphaned shape-edit widgets don't
            # linger after a task switch.
            self.edit_btn.setChecked(False)
        self.next_incomplete_btn.setVisible(self._spec.has_vlm)

    # ════════════════════════════════════════════════════════════════
    # Public API
    # ════════════════════════════════════════════════════════════════

    def show_image(self, image: ImageInfo,
                   image_list: list[ImageInfo]) -> None:
        self._images = image_list
        try:
            self._index = image_list.index(image)
        except ValueError:
            self._index = 0
            self._images = [image]
        self._load_current()

    def prev_image(self) -> None:
        if not self._images:
            return
        if not self._confirm_discard():
            return
        self._index = (self._index - 1) % len(self._images)
        self._load_current()

    def next_image(self) -> None:
        if not self._images:
            return
        if not self._confirm_discard():
            return
        self._index = (self._index + 1) % len(self._images)
        self._load_current()

    def next_incomplete_image(self) -> None:
        """Jump to the next image still missing VLM data the project
        signed up for.  Wraps around once; if nothing in the whole
        list qualifies, surfaces an InfoBar and stays put.

        "Incomplete" is defined per the active spec:

        - ``has_caption``       → ``sample.caption`` empty
        - ``has_conversations`` → ``sample.conversations`` empty
        - ``show_region_text``  → any region with empty ``text``,
                                  OR no regions at all when the user
                                  is supposed to write region text
                                  (zero regions = nothing to anchor)
        """
        if not self._images:
            return
        if not self._confirm_discard():
            return

        n = len(self._images)
        # Walk forward from the current position, wrap exactly once.
        order = list(range(self._index + 1, n)) + list(range(0, self._index))
        for idx in order:
            img = self._images[idx]
            sample = self._sample_index.get(str(img.path))
            if sample is None:
                # No sample loaded yet (Phase 2 still pending) — skip.
                continue
            if self._is_sample_incomplete(sample):
                self._index = idx
                self._load_current()
                return

        InfoBar.success(
            "全部完成", "类目/筛选范围内已无缺失项",
            parent=self, duration=3000,
            position=InfoBarPosition.TOP,
        )

    def _is_sample_incomplete(self, sample: Sample) -> bool:
        """Capability-aware "未完成" predicate.  See ``next_incomplete_image``."""
        if self._spec.has_caption and not (sample.caption or "").strip():
            return True
        if self._spec.has_conversations and not sample.conversations:
            return True
        if self._spec.show_region_text:
            # No regions at all → can't write region text, but the user
            # opted into grounding so this image is still "todo" (they
            # need to draw + describe).
            if not sample.regions:
                return True
            if any(not (r.text or "").strip() for r in sample.regions):
                return True
        return False

    def set_sample_set(self, ss: SampleSet | None) -> None:
        """Inject unified SampleSet so annotation loading skips disk I/O."""
        self._sample_set = ss
        if ss is not None:
            self._sample_index = {str(s.image_path): s for s in ss.samples}
        else:
            self._sample_index = {}

    def set_annotation_format(self, fmt: str) -> None:
        """Set the project's preferred annotation format for write-back."""
        if fmt:
            self._annotation_format = fmt

    def set_write_enabled(self, enabled: bool) -> None:
        """Flip the write gate.  DatasetBrowserView drives this from
        ``AppState.scan_active_changed`` so save handlers refuse while
        Phase 2/3 of the scan is still loading labels into SampleSet.
        """
        self._write_enabled = bool(enabled)

    def set_project_profile(self, project: Project | None) -> None:
        """Rebuild panes for ``project``'s task type.

        VLM fields are always available; project capability flags are
        kept only for legacy project compatibility and do not gate the
        annotation surface.

        Passing ``None`` falls back to the DEFAULT_SPEC shape.
        """
        if project is None:
            new_spec = spec_for(None)
        else:
            new_spec = spec_for(project.task_type)
        if new_spec == self._spec:
            return
        self._spec = new_spec
        self._rebuild_panes()
        self._update_topbar_for_spec()

    # ════════════════════════════════════════════════════════════════
    # Image loading + cache + prefetch
    # ════════════════════════════════════════════════════════════════

    def _load_current(self) -> None:
        if not (0 <= self._index < len(self._images)):
            return
        img = self._images[self._index]

        # New image → drop any pending shape-undo state from the
        # previous one. The stack is per-image: snapshots of image A
        # would attempt to overwrite image B's shapes if we kept it.
        self._clear_shape_undo()

        # Update breadcrumb immediately — cheap, user feedback.
        self.crumb_label.setText(
            f"{img.category}  /  {img.path.name}   "
            f"{self._index + 1} / {len(self._images)}"
        )
        self.info_name.setText(img.path.name)
        self.info_path.setText(str(img.path.parent))

        self._load_generation += 1
        gen = self._load_generation

        # Cache hit → render, but defer to the next event-loop tick so
        # the UI mutations + prefetch QThread start happen OUTSIDE the
        # input-event dispatch that brought us here. Starting a thread
        # or triggering heavy widget layout while Qt is still dispatching
        # a mouse/double-click event can raise Windows COM exception
        # 0x8001010d (RPC_E_CANTCALLOUT_ININPUTSYNCCALL) and segfault.
        cached = self._cache_get(str(img.path))
        if cached is not None:
            qimage, annotation = cached
            QTimer.singleShot(0, lambda: (
                self._on_image_loaded(qimage, annotation, img, gen),
                self._schedule_prefetch(),
            ))
            return

        # Cache miss — abandon any in-flight loader and spawn a fresh
        # one.  generation token lets _on_image_loaded drop the stale
        # ``done``.
        old = getattr(self, "_loader", None)
        if old is not None:
            try:
                if old.isRunning():
                    # Cancel only — don't wait(). QImage(path) on a
                    # 3072×4096 TIFF can't be interrupted mid-read, so
                    # wait(500) would freeze the main thread on every
                    # Next press.
                    old.cancel()
            except RuntimeError:
                # Underlying C++ QThread already torn down (parent=self
                # chain destroyed it earlier). Nothing to cancel.
                pass
        # SampleSet is authoritative when available — even empty regions
        # means "no annotations" (not "go re-parse from disk").
        pre_ann = None
        sample = self._find_sample(img)
        if sample is not None:
            pre_ann = _sample_to_annotation(sample)
        self._loader = _ImageLoader(img, gen, parent=self,
                                    pre_annotation=pre_ann)
        self._loader.done.connect(self._on_image_loaded)
        self._loader.finished.connect(self._loader.deleteLater)
        # Defer .start() to the next tick — spawning a QThread during
        # input dispatch can trip RPC_E_CANTCALLOUT_ININPUTSYNCCALL.
        QTimer.singleShot(0, self._loader.start)

    def _cache_get(self, key: str):
        hit = self._image_cache.get(key)
        if hit is not None:
            # Move to most-recently-used position.
            try:
                self._image_cache_order.remove(key)
            except ValueError:
                pass
            self._image_cache_order.append(key)
        return hit

    def _cache_put(self, key: str, qimage: QImage, annotation) -> None:
        if key in self._image_cache:
            try:
                self._image_cache_order.remove(key)
            except ValueError:
                pass
        elif len(self._image_cache_order) >= self._image_cache_max:
            oldest = self._image_cache_order.pop(0)
            self._image_cache.pop(oldest, None)
        self._image_cache[key] = (qimage, annotation)
        self._image_cache_order.append(key)

    def _schedule_prefetch(self) -> None:
        """Kick off background loads for prev + next neighbors.

        Sequential browsing becomes instant once the warm-up round-trip
        completes."""
        if not self._images or len(self._images) < 2:
            return
        for offset in (1, -1):
            target = (self._index + offset) % len(self._images)
            if target == self._index:
                continue
            neighbor = self._images[target]
            key = str(neighbor.path)
            if key in self._image_cache or key in self._inflight_prefetch:
                continue
            self._inflight_prefetch.add(key)
            pre = None
            nb_sample = self._find_sample(neighbor)
            if nb_sample is not None:
                pre = _sample_to_annotation(nb_sample)
            loader = _ImageLoader(neighbor, self._load_generation,
                                  prefetch=True, parent=self,
                                  pre_annotation=pre)
            loader.prefetched.connect(self._on_prefetch_done)
            # finished fires on any thread exit (success/cancel/error),
            # so clear the flag here to avoid a permanent pin if
            # cancellation beat the prefetched signal.
            loader.finished.connect(
                lambda k=key: self._inflight_prefetch.discard(k))
            loader.finished.connect(loader.deleteLater)
            loader.start()

    def _on_prefetch_done(self, path: str, qimage: QImage, annotation) -> None:
        # This slot fires on the main thread via a queued signal from a
        # prefetch QThread.  If the view was torn down between emit and
        # delivery, silently drop instead of crashing.
        try:
            self._inflight_prefetch.discard(path)
            if qimage is None or qimage.isNull():
                return
            self._cache_put(path, qimage, annotation)
        except RuntimeError:
            # Wrapped C++ object of type DetailView has been deleted.
            return

    def _on_image_loaded(self, qimage: QImage, annotation,
                         img: ImageInfo, generation: int) -> None:
        """Worker 完成后在主线程设置 viewer。QImage→QPixmap 必须在主线程."""
        # Drop late deliveries: a slow load that finishes after the
        # user pressed next/prev would otherwise paint the wrong image.
        if generation != self._load_generation:
            return
        if not qimage.isNull():
            self.viewer.load_pixmap(QPixmap.fromImage(qimage))
            self._cache_put(str(img.path), qimage, annotation)
            # Defer prefetch to next tick — see matching comment in
            # _load_current about RPC_E_CANTCALLOUT_ININPUTSYNCCALL.
            QTimer.singleShot(0, self._schedule_prefetch)
        self._annotation = annotation
        self.viewer.set_annotation(self._annotation)

        # File info meta.
        try:
            size_kb = img.path.stat().st_size / 1024
            self.info_size.setText(
                f"{size_kb:.1f} KB" if size_kb < 1024
                else f"{size_kb / 1024:.2f} MB"
            )
        except OSError:
            self.info_size.setText("—")
        if self.viewer._pix_item is not None:
            r = self.viewer._pix_item.pixmap()
            self.info_dim.setText(f"{r.width()} × {r.height()} px")
        else:
            self.info_dim.setText("—")
        self.info_cat.setText(img.category)

        # Conflict-detection baseline — remember mtime at load so _on_save
        # can catch external edits.
        self._label_mtime_at_load = None
        try:
            if (img.has_label and img.label_path
                    and img.label_path.is_file()):
                self._label_mtime_at_load = img.label_path.stat().st_mtime_ns
        except OSError:
            self._label_mtime_at_load = None
        self._dirty = False

        # Refresh panes (shape list, caption, conversations, status).
        self._repaint_panes(img)

        # Load region texts from sidecar if shapes lack inline text.
        self._load_region_texts_from_sidecar(img)

    def _repaint_panes(self, img: ImageInfo) -> None:
        """Push current image state into whichever panes are alive.

        Safe to call any time — each pane is an ``Optional`` and we
        no-op when None. Called from _on_image_loaded (normal flow)
        and from _rebuild_panes (spec-change while an image is loaded).
        """
        if self._annotation_pane is not None:
            self._annotation_pane.refresh_shape_list(self._annotation)
            self._annotation_pane.clear_region_binding()
        if self._image_label_pane is not None:
            cats = sorted({i.category for i in self._images if i.category})
            self._image_label_pane.set_classes(cats)
            sample = self._find_sample(img)
            labels = sample.image_labels if sample else []
            # Sample may not have image_labels populated yet (sample-set
            # was scanned before the sidecar existed).  Fall back to
            # the on-disk sidecar so labels persist across app restarts.
            if not labels:
                from core.annotation_writer import read_image_labels
                labels = read_image_labels(img.path)
                if labels and sample is not None:
                    sample.image_labels = list(labels)
            self._image_label_pane.bind_image(img.category, labels)
        if self._vlm_pane is not None:
            self._update_caption_and_convos(img)
        if self._status_pane is not None:
            sample = self._find_sample(img)
            self._status_pane.set_status(
                sample.work_status if sample else "")

        # Rebuild label combo if edit mode is on — label set may have
        # changed across images.
        if self.edit_btn.isChecked():
            self._refresh_label_combo()

    # ════════════════════════════════════════════════════════════════
    # Navigation + confirm
    # ════════════════════════════════════════════════════════════════

    def _on_back_clicked(self) -> None:
        if not self._confirm_discard():
            return
        self.back_requested.emit()

    def _on_move_category(self) -> None:
        """Reassign the current image's category without leaving DetailView.

        Discovers existing categories from the image list we already
        have (avoids needing a direct AppState reference), then
        delegates fileops + rescan to the outer view via
        change_category_requested.
        """
        if not self._images or self._index < 0:
            return
        current = self._images[self._index]
        cats = sorted({img.category for img in self._images
                       if img.category and img.category != current.category})
        if not cats:
            box = MessageBox(
                "无其他类别", "当前数据集只有一个类别", self.window())
            box.cancelButton.hide()
            box.exec()
            return

        if not self._confirm_discard():
            return

        from gui.dialogs.op_dialogs import MoveToCategoryDialog
        dlg = MoveToCategoryDialog(cats, self.window())
        if not dlg.exec():
            return
        target = dlg.target()
        if not target or target == current.category:
            return
        self.change_category_requested.emit(current, target)

    def _confirm_discard(self) -> bool:
        """Return True if it's OK to discard unsaved changes (or none)."""
        if not self._dirty:
            return True
        box = MessageBox(
            "未保存的修改",
            "当前标注有未保存的修改，是否放弃？",
            self.window(),
        )
        box.yesButton.setText("放弃修改")
        box.cancelButton.setText("继续编辑")
        return bool(box.exec())

    def _block_write_if_scanning(self) -> bool:
        """Return True (and show InfoBar) when writes are gated off.

        Callers use it as an early-return guard:
        ``if self._block_write_if_scanning(): return``.
        """
        if self._write_enabled:
            return False
        InfoBar.warning(
            title="数据集仍在加载",
            content="等后台扫描完成再保存，避免和正在构建的索引产生冲突。",
            isClosable=True, position=InfoBarPosition.TOP,
            duration=3000, parent=self.window(),
        )
        return True

    def _find_sample(self, img: ImageInfo) -> Sample | None:
        return self._sample_index.get(str(img.path))

    # ════════════════════════════════════════════════════════════════
    # Viewer feedback (zoom / selection / shapes)
    # ════════════════════════════════════════════════════════════════

    def _on_zoom_changed(self, scale: float) -> None:
        self.zoom_label.setText(f"{scale * 100:.0f}%")

    def _on_edit_toggled(self, on: bool) -> None:
        self.viewer.set_edit_mode(on)
        # Visibility is the intersection of edit-mode + spec shape_tools.
        # Classification/anomaly/pair never reach here (edit_btn hidden),
        # but be defensive in case someone programmatically toggles it.
        tools = self._spec.shape_tools
        self.label_combo.setVisible(on)
        self.delete_shape_btn.setVisible(on)
        self.save_btn.setVisible(on)
        self.shape_rect_btn.setVisible(on and "rectangle" in tools)
        self.shape_poly_btn.setVisible(on and "polygon" in tools)
        if on:
            # No annotation yet → seed an empty one so drawn shapes have
            # somewhere to land.
            if (self._annotation is None
                    and 0 <= self._index < len(self._images)):
                img = self._images[self._index]
                self._annotation = Annotation(image_path=img.path, shapes=[])
                self.viewer.set_annotation(self._annotation)
            self._refresh_label_combo()
            self.viewer.set_draw_label(
                self.label_combo.currentText() or "object")
            # Default to the first tool this task allows so SEG starts
            # in polygon mode instead of forcing the user to pick.
            if tools:
                self._set_shape_type(tools[0])

    def _set_shape_type(self, st: str) -> None:
        self.shape_rect_btn.setChecked(st == "rectangle")
        self.shape_poly_btn.setChecked(st == "polygon")
        self.viewer.set_draw_shape_type(st)

    def _refresh_label_combo(self) -> None:
        existing = sorted({
            s.label for s in (self._annotation.shapes
                              if self._annotation else [])
        })
        current = self.label_combo.currentText()
        self.label_combo.blockSignals(True)
        self.label_combo.clear()
        if existing:
            self.label_combo.addItems(existing)
        else:
            self.label_combo.addItem("object")
        if current:
            self.label_combo.setCurrentText(current)
        self.label_combo.blockSignals(False)

    def _on_shapes_changed(self) -> None:
        self._dirty = True
        # Commit any in-flight region-text edit BEFORE we replace
        # self._annotation with the viewer's new state — otherwise the
        # editor's pending text is silently dropped along with the old
        # shape list.  Mirrors _on_selection_changed's behavior.
        self._commit_pane_region_text()

        # Snapshot existing shape text so it survives the annotation
        # swap.  ImageViewer.get_annotation() doesn't carry text — text
        # lives in self._annotation only — so without this carryover
        # any region text on existing shapes evaporates whenever the
        # user adds another shape.
        old_texts: list[str] = []
        if self._annotation is not None:
            old_texts = [s.text for s in self._annotation.shapes]

        self._annotation = self.viewer.get_annotation()

        # Re-apply text by index. Best-effort: correct for "add a new
        # shape" (the common case where viewer appends at the end);
        # a deletion in the middle would mis-attribute text from N+1
        # to N.  Acceptable trade-off vs silent total loss; ImageViewer
        # would need to emit a richer diff to do better.
        new_shapes = self._annotation.shapes
        for i, txt in enumerate(old_texts):
            if i < len(new_shapes) and txt:
                new_shapes[i].text = txt

        if self._annotation_pane is not None:
            self._annotation_pane.refresh_shape_list(self._annotation)
            # Shape indices may have shifted — drop any region-text binding.
            self._annotation_pane.clear_region_binding()
        self._refresh_label_combo()
        self.save_btn.setToolTip("保存标注 (Ctrl+S) — 有未保存修改")

    def _on_selection_changed(self, idx: int) -> None:
        if self._annotation_pane is None:
            return
        # Commit pending region text before switching selection so the
        # about-to-be-clobbered text lands on the right shape.
        self._commit_pane_region_text()
        self._annotation_pane.select_shape(idx)
        shapes = self._annotation.shapes if self._annotation else []
        if 0 <= idx < len(shapes):
            self._annotation_pane.bind_region_text(idx, shapes[idx].text)
        else:
            self._annotation_pane.bind_region_text(-1, "")

    def _on_pane_shape_selected(self, idx: int) -> None:
        """List → canvas mirror.

        AnnotationPane fires this when the user clicks a row in the
        shape list. We forward to ``viewer.select_shape`` so the
        canvas highlights the matching shape. ``viewer.select_shape``
        emits ``selection_changed`` back, but the pane's
        :meth:`AnnotationPane.select_shape` blocks signals around its
        ``setCurrentRow``, so the round-trip can't loop.
        """
        if not (0 <= idx < len(self._annotation.shapes if self._annotation else [])):
            return
        self.viewer.select_shape(idx)

    def _on_pane_delete_shape(self, idx: int) -> None:
        """Right-click "删除此标注" on a list row → drop that shape.

        Routes through :meth:`ImageViewer.delete_shape_at` so the
        canvas + shapes_changed path is identical to a Del-key delete.
        Guarded by the write gate so we don't mutate while the scan
        is still building SampleSet.
        """
        if self._block_write_if_scanning():
            return
        if self._annotation is None:
            return
        if not (0 <= idx < len(self._annotation.shapes)):
            return
        self._push_shape_undo("删除标注")
        self.viewer.delete_shape_at(idx)

    def _delete_selected_shape(self) -> None:
        """Delete-on-canvas wrapper that snapshots before the cut.

        Bound to the topbar Delete button + the Del shortcut so both
        feed the local undo stack (otherwise pressing Del would drop a
        shape with no way back).
        """
        if self._block_write_if_scanning():
            return
        if not self.viewer.has_selection():
            return
        self._push_shape_undo("删除标注")
        self.viewer.delete_selected()

    # ════════════════════════════════════════════════════════════════
    # Local shape-undo stack
    # ════════════════════════════════════════════════════════════════

    def _push_shape_undo(self, label: str) -> None:
        """Snapshot current shape state with a user-readable *label*."""
        if self._annotation is None:
            return
        snapshot = [
            Shape(label=s.label, shape_type=s.shape_type,
                  points=list(s.points), text=s.text)
            for s in self._annotation.shapes
        ]
        self._undo_stack.append((label, snapshot))
        if len(self._undo_stack) > self._undo_max:
            self._undo_stack.pop(0)
        self.undo_state_changed.emit()

    def _clear_shape_undo(self) -> None:
        """Reset the stack — called when navigating to another image."""
        if not self._undo_stack:
            return
        self._undo_stack.clear()
        self.undo_state_changed.emit()

    def can_undo(self) -> bool:
        """True when there's a shape edit on the local stack to revert."""
        return bool(self._undo_stack)

    def last_undo_label(self) -> str:
        return self._undo_stack[-1][0] if self._undo_stack else ""

    def undo(self) -> str | None:
        """Pop the most recent shape edit and restore the snapshot.

        Returns the label of the operation that was undone (for an
        InfoBar / tooltip), or ``None`` when the stack was empty.
        """
        if not self._undo_stack:
            return None
        if self._block_write_if_scanning():
            return None
        if self._annotation is None:
            self._undo_stack.clear()
            self.undo_state_changed.emit()
            return None
        label, snapshot = self._undo_stack.pop()
        self._annotation.shapes = snapshot
        self.viewer.set_annotation(self._annotation)
        self._dirty = True
        if self._annotation_pane is not None:
            self._annotation_pane.refresh_shape_list(self._annotation)
            self._annotation_pane.clear_region_binding()
        self._refresh_label_combo()
        self.undo_state_changed.emit()
        return label

    def _commit_pane_region_text(self) -> None:
        """Push the region-text editor's current content back to the shape.

        No-op when the annotation pane has no grounding editor (task
        spec didn't include ``show_region_text``) or the binding is
        stale.
        """
        if self._annotation_pane is None or self._annotation is None:
            return
        if not self._annotation_pane.has_region_text:
            return
        idx, text = self._annotation_pane.current_region_text()
        shapes = self._annotation.shapes
        if 0 <= idx < len(shapes):
            shapes[idx].text = text

    # ════════════════════════════════════════════════════════════════
    # Save: annotation (shapes)
    # ════════════════════════════════════════════════════════════════

    def _on_save(self) -> None:
        if self._block_write_if_scanning():
            return
        if not (0 <= self._index < len(self._images)):
            return
        img = self._images[self._index]
        if self._annotation is None:
            self._annotation = Annotation(image_path=img.path, shapes=[])
        # Inferred label_path: existing path wins (preserves format);
        # else use the project's preferred annotation format.
        label_path = img.label_path
        if label_path is None:
            from core.annotation_writer import label_path_for_format
            label_path = label_path_for_format(
                img.path, self._annotation_format)

        # Conflict check: if the label file changed since we loaded it,
        # ask before overwriting.  Common causes: external editor,
        # second DataForge instance, sync daemon. Ignore when we've
        # never loaded a label (new annotation) or the file vanished.
        if (self._label_mtime_at_load is not None
                and label_path.is_file()):
            try:
                disk_mtime = label_path.stat().st_mtime_ns
            except OSError:
                disk_mtime = self._label_mtime_at_load
            # 100 ms tolerance (ns) — bigger than any real filesystem's
            # noise, smaller than any interactive save interval.
            if disk_mtime > self._label_mtime_at_load + 100_000_000:
                box = MessageBox(
                    "文件已被外部修改",
                    f"{label_path.name} 在打开后被其他程序改动过。\n"
                    "继续保存会覆盖外部修改 — 是否继续?",
                    self.window(),
                )
                box.yesButton.setText("覆盖保存")
                box.cancelButton.setText("取消")
                if not box.exec():
                    return

        try:
            write_annotation(self._annotation, label_path, img.path)
        except Exception as e:  # noqa: BLE001
            InfoBar.error(
                title="保存失败", content=str(e),
                isClosable=True, position=InfoBarPosition.TOP,
                duration=4000, parent=self.window(),
            )
            return
        # Update ImageInfo status.
        img.has_label = True
        img.label_path = label_path
        self._dirty = False
        # Sync the cache with the just-saved annotation so navigating
        # away and back doesn't resurrect the pre-save version.
        key = str(img.path)
        if key in self._image_cache:
            qimage, _ = self._image_cache[key]
            self._image_cache[key] = (qimage, self._annotation)
        # Sync unified Sample so in-memory SampleSet stays current for
        # export and other consumers of the unified model.
        sample = self._find_sample(img)
        if sample is None and self._sample_set is not None:
            # Image was not in SampleSet (added after last full scan?) —
            # create a Sample so subsequent edits / export see it.
            w = h = 0
            if self.viewer._pix_item is not None:
                pm = self.viewer._pix_item.pixmap()
                w, h = pm.width(), pm.height()
            sample = Sample(
                image_path=img.path,
                image_width=w, image_height=h,
                category=img.category,
            )
            self._sample_set.samples.append(sample)
            self._sample_index[str(img.path)] = sample
        if sample is not None and self._annotation is not None:
            sample.regions = _annotation_to_regions(self._annotation)
            sample.has_label = True
            sample.label_path = label_path
        # Refresh conflict baseline to the file we just wrote — any
        # further external edits show up on the next save.
        try:
            self._label_mtime_at_load = label_path.stat().st_mtime_ns
        except OSError:
            pass
        # Auto-transition: saving annotation advances workflow status
        # (new/prelabeled → annotating — work has started).
        if (sample is not None
                and sample.work_status in ("new", "prelabeled")):
            sample.work_status = "annotating"
            self.work_status_changed.emit(img, "annotating")
            if self._status_pane is not None:
                self._status_pane.set_status("annotating")

        InfoBar.success(
            title="已保存", content=str(label_path.name),
            isClosable=True, position=InfoBarPosition.TOP,
            duration=2000, parent=self.window(),
        )

    # ════════════════════════════════════════════════════════════════
    # Save: image-level label (classification / multi-label / anomaly)
    # ════════════════════════════════════════════════════════════════

    def _on_class_picked(self, target_category: str) -> None:
        """ImageLabelPane SINGLE/ANOMALY → file move into the picked class.

        Re-uses the same path as the topbar's "改分类" button. The shell
        triggers fileops + rescan via change_category_requested upstream.
        """
        if self._block_write_if_scanning():
            return
        if not (0 <= self._index < len(self._images)):
            return
        current = self._images[self._index]
        if not target_category or target_category == current.category:
            return
        if not self._confirm_discard():
            return
        self.change_category_requested.emit(current, target_category)

    def _on_image_labels_changed(self, labels: object) -> None:
        """ImageLabelPane MULTI → update Sample + write sidecar.

        Persists the multi-label set to a ``<stem>.labels.json`` sidecar
        next to the image, matching the convention used by caption /
        conversations / grounding.  Earlier the in-memory Sample was
        updated but never written, so closing the app dropped every
        multi-label tag — see audit P0 #5.
        """
        if self._block_write_if_scanning():
            return
        if not (0 <= self._index < len(self._images)):
            return
        img = self._images[self._index]
        new_labels = list(labels) if isinstance(labels, list) else []
        sample = self._find_sample(img)
        if sample is not None:
            sample.image_labels = new_labels
        self._dirty = True

        # Disk write — best-effort.  A failure here shouldn't abort the
        # interactive flow; the in-memory state is already updated and
        # the next save attempt or sidecar reload will resync.
        try:
            from core.annotation_writer import write_image_labels
            write_image_labels(img.path, new_labels)
        except OSError:
            import logging
            logging.getLogger(__name__).exception(
                "image_labels write failed for %s", img.path)

    # ════════════════════════════════════════════════════════════════
    # Save: VLM caption + conversations (pane → disk via signals)
    # ════════════════════════════════════════════════════════════════

    def _update_caption_and_convos(self, img: ImageInfo) -> None:
        """Populate the VLM pane from Sample / disk sidecar fallback."""
        if self._vlm_pane is None:
            return
        sample = self._find_sample(img)

        caption = sample.caption if sample else ""
        if not caption:
            from core.annotation_writer import read_caption
            caption = read_caption(img.path)
        self._vlm_pane.set_caption(caption)

        convos = sample.conversations if sample else []
        if not convos:
            from core.annotation_writer import read_conversations
            convos = read_conversations(img.path)
        self._vlm_pane.set_conversations(convos)

    def _on_save_caption(self, text: str) -> None:
        """Persist caption text to the current Sample and emit signal."""
        if self._block_write_if_scanning():
            return
        if not (0 <= self._index < len(self._images)):
            return
        img = self._images[self._index]
        sample = self._find_sample(img)
        if sample is not None:
            sample.caption = text
        self.caption_saved.emit(img, text)
        InfoBar.success(
            "", "Caption saved",
            parent=self.window(), duration=1500,
            position=InfoBarPosition.TOP,
        )

    def _on_save_conversations(self, convos: list) -> None:
        """Persist conversations to the current Sample and emit signal."""
        if self._block_write_if_scanning():
            return
        if not (0 <= self._index < len(self._images)):
            return
        img = self._images[self._index]
        sample = self._find_sample(img)
        if sample is not None:
            sample.conversations = convos
        self.conversations_saved.emit(img, convos)
        InfoBar.success(
            "", "Conversations saved",
            parent=self.window(), duration=1500,
            position=InfoBarPosition.TOP,
        )

    # ════════════════════════════════════════════════════════════════
    # Save: grounding (per-shape region text)
    # ════════════════════════════════════════════════════════════════

    def _on_save_grounding(self) -> None:
        """Commit region text, update Sample, emit signal.

        Triggered by AnnotationPane's save_grounding_requested signal.
        """
        if self._block_write_if_scanning():
            return
        self._commit_pane_region_text()
        if not (0 <= self._index < len(self._images)):
            return
        img = self._images[self._index]
        shapes = self._annotation.shapes if self._annotation else []
        grounding: list[dict] = []
        for s in shapes:
            if not s.text:
                continue
            entry: dict = {"label": s.label, "text": s.text}
            if s.shape_type == "rectangle" and len(s.points) >= 2:
                bb = BBox.from_points(s.points)
                entry["bbox"] = [bb.x1, bb.y1, bb.x2, bb.y2]
            grounding.append(entry)
        # Sync text back to unified Sample.regions.
        sample = self._find_sample(img)
        if sample is not None:
            for i, region in enumerate(sample.regions):
                if i < len(shapes):
                    region.text = shapes[i].text
        self.grounding_saved.emit(img, grounding)
        InfoBar.success(
            "", "Grounding saved",
            parent=self.window(), duration=1500,
            position=InfoBarPosition.TOP,
        )

    def _load_region_texts_from_sidecar(self, img: ImageInfo) -> None:
        """If annotation has shapes but no text, try loading from sidecar.

        Matches grounding sidecar entries to shapes by label first, then
        bbox proximity as a tiebreaker.
        """
        shapes = self._annotation.shapes if self._annotation else []
        if not shapes:
            return
        if any(s.text for s in shapes):
            return
        from core.annotation_writer import read_grounding
        gnd = read_grounding(img.path)
        if not gnd:
            return
        for entry in gnd:
            label = entry.get("label", "")
            text = entry.get("text", "")
            bbox = entry.get("bbox")
            if not text:
                continue
            best_idx = -1
            for i, s in enumerate(shapes):
                if s.text:
                    continue  # already assigned
                if s.label != label:
                    continue
                if (bbox and s.shape_type == "rectangle"
                        and len(s.points) >= 2):
                    sb = BBox.from_points(s.points)
                    dx = abs(sb.x1 - bbox[0]) + abs(sb.y1 - bbox[1])
                    if dx < 5:  # close enough (pixel tolerance)
                        best_idx = i
                        break
                elif best_idx < 0:
                    best_idx = i  # first label match
            if best_idx >= 0:
                shapes[best_idx].text = text

    # ════════════════════════════════════════════════════════════════
    # Workflow transitions
    # ════════════════════════════════════════════════════════════════

    def _transition_work_status(self, new_status: str) -> None:
        """Change current image's work status and emit signal.

        Workflow transitions count as writes: they persist into the
        workflow store and mutate the in-memory Sample.work_status,
        which the SampleSet unify pass also writes during scan —
        letting the user flip status while the worker is still
        assembling SampleSet would leave two writers racing on the
        same field.  Same scan_active gate as file-level saves.
        """
        if self._block_write_if_scanning():
            return
        if not (0 <= self._index < len(self._images)):
            return
        img = self._images[self._index]
        sample = self._find_sample(img)
        if sample is not None:
            sample.work_status = new_status
        self.work_status_changed.emit(img, new_status)
        if self._status_pane is not None:
            self._status_pane.set_status(new_status)
        InfoBar.success(
            "", WF_STATUS_LABELS.get(new_status, new_status),
            parent=self.window(), duration=1500,
            position=InfoBarPosition.TOP,
        )

    # ════════════════════════════════════════════════════════════════
    # Shortcuts + misc
    # ════════════════════════════════════════════════════════════════

    def _show_shortcuts(self) -> None:
        from gui.dialogs.op_dialogs import ShortcutsDialog
        ShortcutsDialog(self.window()).exec()

    def keyPressEvent(self, e: QKeyEvent) -> None:  # type: ignore[override]
        if e.key() in (Qt.Key.Key_A, Qt.Key.Key_Left):
            self.prev_image()
        elif e.key() in (Qt.Key.Key_D, Qt.Key.Key_Right):
            self.next_image()
        elif (e.key() == Qt.Key.Key_Tab
              and self.next_incomplete_btn.isVisible()):
            # Tab = 下一张未完成 (gated on VLM cap visibility so the
            # shortcut doesn't shadow Tab in projects that don't use it).
            self.next_incomplete_image()
        elif e.key() == Qt.Key.Key_H:
            self.toggle_anno_btn.toggle()
        elif e.key() == Qt.Key.Key_E:
            # Only meaningful when edit is actually available.
            if self.edit_btn.isVisible():
                self.edit_btn.toggle()
        elif (e.key() == Qt.Key.Key_R
              and self.edit_btn.isChecked()
              and "rectangle" in self._spec.shape_tools):
            self._set_shape_type("rectangle")
        elif (e.key() == Qt.Key.Key_P
              and self.edit_btn.isChecked()
              and "polygon" in self._spec.shape_tools):
            self._set_shape_type("polygon")
        elif (e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
              and self.edit_btn.isChecked()):
            self.viewer.finish_polygon()
        elif e.key() == Qt.Key.Key_Delete and self.edit_btn.isChecked():
            self._delete_selected_shape()
        elif (e.key() == Qt.Key.Key_Z
              and (e.modifiers() & Qt.KeyboardModifier.ControlModifier)
              and not (e.modifiers() & Qt.KeyboardModifier.ShiftModifier)):
            # Ctrl+Z — pop the local shape-edit stack.  Same handler the
            # global 撤销 button calls into when DetailView is on top.
            self.undo()
        elif (e.key() == Qt.Key.Key_S
              and (e.modifiers() & Qt.KeyboardModifier.ControlModifier)):
            if self.edit_btn.isChecked():
                self._on_save()
        elif e.key() == Qt.Key.Key_Escape:
            self._on_back_clicked()
        else:
            super().keyPressEvent(e)

    # ---------- sidebar layout helpers ----------

    def _section_label(self, text: str) -> CaptionLabel:
        # Dedicated section-header style (see QSS: QLabel#sectionHeader).
        # CaptionLabel gives a smaller, muted tracked-uppercase header
        # that matches the sidebar's `toolSidebarSection` pattern.
        lbl = CaptionLabel(text.upper())
        lbl.setObjectName("sectionHeader")
        return lbl

    def _meta_value(self, text: str, small: bool = False):
        lbl = CaptionLabel(text) if small else BodyLabel(text)
        lbl.setWordWrap(True)
        return lbl

    def _meta_row(self, label: str, value_widget) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(T.GAP)
        key = CaptionLabel(label)
        key.setFixedWidth(48)
        key.setAlignment(Qt.AlignmentFlag.AlignTop)
        row.addWidget(key)
        row.addWidget(value_widget, 1)
        return row
