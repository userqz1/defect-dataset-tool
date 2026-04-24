"""Single-image detail view: large viewer + meta sidebar + A/D navigation."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QImage, QKeyEvent, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
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
    EditableComboBox,
    FluentIcon as FIF,
    InfoBar,
    InfoBarPosition,
    MessageBox,
    PlainTextEdit,
    ToolButton,
)

from core.annotation_writer import write_annotation
from core.models import Annotation, ImageInfo, Shape
from core.unified import BBox, Region, Sample, SampleSet
from gui.theme import T
from gui.widgets.image_viewer import ImageViewer, color_for_label


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
    wrong image. Review #9.

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
                 pre_annotation: Annotation | None = None):
        super().__init__(parent)
        self._img = img
        self._gen = generation
        self._prefetch = prefetch
        self._pre_annotation = pre_annotation
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        if self._cancelled:
            return
        image = QImage(str(self._img.path))
        if self._cancelled:
            return

        # Use pre-built annotation (from unified SampleSet) when available;
        # fall back to format_in (unified model) for disk parsing.
        annotation = self._pre_annotation
        if annotation is None and not self._cancelled and self._img.has_label and self._img.label_path:
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


class _ConvTurnWidget(QFrame):
    """Single conversation turn — role badge + text editor + delete."""
    removed = pyqtSignal(object)

    def __init__(self, role: str = "human", text: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("convTurnFrame")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(T.GAP_XS, T.GAP_XS, T.GAP_XS, T.GAP_XS)
        lay.setSpacing(2)

        top = QHBoxLayout()
        top.setSpacing(T.GAP_XS)
        self._role_label = CaptionLabel(role.upper())
        self._role_label.setObjectName("convRole")
        self._role_label.setFixedWidth(52)
        self._role_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._role_label.mousePressEvent = lambda _e: self._toggle_role()
        top.addWidget(self._role_label)
        top.addStretch()

        del_btn = ToolButton(FIF.CLOSE)
        del_btn.setFixedSize(20, 20)
        del_btn.clicked.connect(lambda: self.removed.emit(self))
        top.addWidget(del_btn)
        lay.addLayout(top)

        self._text_edit = PlainTextEdit()
        self._text_edit.setObjectName("convTurnText")
        self._text_edit.setPlainText(text)
        self._text_edit.setFixedHeight(56)
        lay.addWidget(self._text_edit)

        self._role = role

    def _toggle_role(self) -> None:
        self._role = "gpt" if self._role == "human" else "human"
        self._role_label.setText(self._role.upper())

    def to_dict(self) -> dict[str, str]:
        return {"from": self._role,
                "value": self._text_edit.toPlainText().strip()}


class DetailView(QWidget):
    back_requested = pyqtSignal()  # 用户点返回
    # Review #21: change the current image's category without returning
    # to the grid. Emits (ImageInfo, new_category_name). The outer view
    # (DatasetBrowserView) owns fileops + rescan.
    change_category_requested = pyqtSignal(object, str)
    # Workflow status transition — (ImageInfo, new_status_value)
    work_status_changed = pyqtSignal(object, str)
    # VLM caption saved — (ImageInfo, caption_text)
    caption_saved = pyqtSignal(object, str)
    # VLM conversations saved — (ImageInfo, conversations_list)
    conversations_saved = pyqtSignal(object, object)
    # Grounding (region text) saved — (ImageInfo, grounding_list)
    grounding_saved = pyqtSignal(object, object)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("detailView")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._images: list[ImageInfo] = []
        self._index: int = -1
        self._annotation: Annotation | None = None
        # Project's preferred annotation format for write-back.
        # Set by DatasetBrowserView from Project.annotation_format.
        self._annotation_format: str = "labelme"
        # Write gate — DatasetBrowserView flips this from AppState
        # ``scan_active_changed``.  While False, every save handler
        # shows a blocking InfoBar and returns early.  Guards against
        # the quick-open race: user opens a cache-hit dataset, sees
        # the grid render at scan_finished, jumps into DetailView, and
        # hits Ctrl+S before Phase 2 finishes — the old save would
        # land on disk while the worker was still reading labels to
        # build the SampleSet, leaving the in-memory SampleSet
        # permanently out of sync with the file they just wrote.
        self._write_enabled: bool = True
        # Unified model: when populated, annotation loading reads from
        # pre-parsed Samples instead of re-parsing label files from disk.
        self._sample_set: SampleSet | None = None
        self._sample_index: dict[str, Sample] = {}  # path_str → Sample
        # mtime baseline for review #22 conflict check; per-method annotation
        # had no runtime effect (PEP 526 only applies at class/module scope).
        # Nanosecond precision (st_mtime_ns) — review #5: float st_mtime
        # + 0.001s tolerance is too fine for FAT32/NAS (2s precision)
        # and too fragile in general. ns rounds away sub-microsecond
        # noise while still catching real external edits.
        self._label_mtime_at_load: int | None = None
        # review #9: increments on every _load_current; _on_image_loaded
        # ignores any (stale) result whose generation != current.
        self._load_generation: int = 0
        # LRU cache of recently decoded images — keyed by str(path) so
        # Path object identity doesn't matter. Each slot: (QImage, Annotation|None).
        # 3 slots is the sweet spot for 4K images (~48MB each → ~150MB peak)
        # while still covering the common A←→D ping-pong navigation pattern.
        self._image_cache: dict[str, tuple] = {}
        self._image_cache_order: list[str] = []
        self._image_cache_max: int = 3
        # In-flight prefetch paths. Without this, rapid A/D keypresses
        # spawn a new pair of 4K-decode threads per keystroke (each
        # _on_image_loaded re-triggers prefetch), saturating the CPU.
        self._inflight_prefetch: set[str] = set()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 顶部条
        topbar = QFrame()
        topbar.setObjectName("detailTopBar")
        topbar.setFixedHeight(48)
        top_layout = QHBoxLayout(topbar)
        top_layout.setContentsMargins(T.GAP_LG, 0, T.PAD_LG, 0)
        top_layout.setSpacing(T.GAP)

        self.back_btn = ToolButton(FIF.LEFT_ARROW)
        self.back_btn.setToolTip("返回浏览 (Esc)")
        self.back_btn.clicked.connect(self._on_back_clicked)
        top_layout.addWidget(self.back_btn)

        self.crumb_label = BodyLabel("—")
        top_layout.addWidget(self.crumb_label)
        top_layout.addStretch(1)

        self.prev_btn = ToolButton(FIF.LEFT_ARROW)
        self.prev_btn.setToolTip("上一张 (A)")
        self.prev_btn.clicked.connect(self.prev_image)
        self.next_btn = ToolButton(FIF.RIGHT_ARROW)
        self.next_btn.setToolTip("下一张 (D)")
        self.next_btn.clicked.connect(self.next_image)
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
        # states, not "same icon, maybe pressed". FIF.VIEW = eye-open
        # (annotations shown), FIF.HIDE = eye-struck (hidden).
        self.toggle_anno_btn.toggled.connect(
            lambda on: self.toggle_anno_btn.setIcon(FIF.VIEW if on else FIF.HIDE)
        )

        # 编辑模式
        self.edit_btn = ToolButton(FIF.EDIT)
        self.edit_btn.setCheckable(True)
        self.edit_btn.setToolTip("编辑标注 (E) — 拖拽绘制矩形 / 点选删除")
        self.edit_btn.toggled.connect(self._on_edit_toggled)

        self.shape_rect_btn = ToolButton(FIF.LAYOUT)
        self.shape_rect_btn.setCheckable(True)
        self.shape_rect_btn.setChecked(True)
        self.shape_rect_btn.setToolTip("矩形 (R)")
        self.shape_poly_btn = ToolButton(FIF.IOT)
        self.shape_poly_btn.setCheckable(True)
        self.shape_poly_btn.setToolTip("多边形 (P) — 左键加点，双击/回车闭合，右键取消")
        self.shape_rect_btn.clicked.connect(lambda: self._set_shape_type("rectangle"))
        self.shape_poly_btn.clicked.connect(lambda: self._set_shape_type("polygon"))
        self.shape_rect_btn.hide()
        self.shape_poly_btn.hide()

        self.label_combo = EditableComboBox()
        self.label_combo.setMinimumWidth(120)
        self.label_combo.setToolTip("绘制时使用的标签名")
        self.label_combo.currentTextChanged.connect(
            lambda t: self.viewer.set_draw_label(t)
        )
        self.label_combo.hide()

        self.save_btn = ToolButton(FIF.SAVE)
        self.save_btn.setToolTip("保存标注 (Ctrl+S)")
        self.save_btn.clicked.connect(self._on_save)
        self.save_btn.hide()

        self.delete_shape_btn = ToolButton(FIF.DELETE)
        self.delete_shape_btn.setToolTip("删除选中标注 (Del)")
        self.delete_shape_btn.clicked.connect(lambda: self.viewer.delete_selected())
        self.delete_shape_btn.hide()

        self.zoom_label = BodyLabel("100%")
        self.zoom_label.setMinimumWidth(48)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        top_layout.addWidget(self.prev_btn)
        top_layout.addWidget(self.next_btn)
        top_layout.addWidget(self.zoom_out_btn)
        top_layout.addWidget(self.zoom_label)
        top_layout.addWidget(self.zoom_in_btn)
        top_layout.addWidget(self.fit_btn)
        top_layout.addWidget(self.actual_btn)
        top_layout.addWidget(self.toggle_anno_btn)
        top_layout.addWidget(self.edit_btn)
        top_layout.addWidget(self.shape_rect_btn)
        top_layout.addWidget(self.shape_poly_btn)
        top_layout.addWidget(self.label_combo)
        top_layout.addWidget(self.delete_shape_btn)
        top_layout.addWidget(self.save_btn)

        # "改分类" — inline category reassign for the current image
        self.move_cat_btn = ToolButton(FIF.FOLDER)
        self.move_cat_btn.setToolTip("改分类(把当前图移到其他类别)")
        self.move_cat_btn.clicked.connect(self._on_move_category)
        top_layout.addWidget(self.move_cat_btn)

        self.help_btn = ToolButton(FIF.HELP)
        self.help_btn.setToolTip("快捷键帮助")
        self.help_btn.clicked.connect(self._show_shortcuts)
        top_layout.addWidget(self.help_btn)

        root.addWidget(topbar)

        # 主体：viewer + sidebar
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self.viewer = ImageViewer()
        self.viewer.zoom_changed.connect(self._on_zoom_changed)
        self.viewer.shapes_changed.connect(self._on_shapes_changed)
        self.viewer.selection_changed.connect(self._on_selection_changed)
        self.toggle_anno_btn.toggled.connect(self.viewer.set_annotation_visible)
        body.addWidget(self.viewer, 1)
        self._dirty: bool = False

        # 右侧元信息
        sidebar = QFrame()
        sidebar.setObjectName("detailSidebar")
        sidebar.setFixedWidth(T.DETAIL_SIDEBAR_WIDTH)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(T.PAD_XL, T.PAD_XL, T.PAD_XL, T.PAD_XL)
        side_layout.setSpacing(T.GAP_LG)

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
        side_layout.addWidget(self._section_label("标注列表"))
        self.shape_list = QListWidget()
        self.shape_list.setObjectName("shapeList")
        side_layout.addWidget(self.shape_list, 1)

        # -- Region text / Caption / Conversation imports --
        from gui import i18n as _i18n
        from qfluentwidgets import PushButton as _PB

        # -- Region text editor (per-shape grounding text) --
        self._region_text_header = self._section_label(
            _i18n.t("vlm.region_text").upper())
        side_layout.addSpacing(T.GAP_XS)
        side_layout.addWidget(self._region_text_header)

        self._region_text_edit = PlainTextEdit()
        self._region_text_edit.setObjectName("regionTextEdit")
        self._region_text_edit.setFixedHeight(56)
        self._region_text_edit.setEnabled(False)
        side_layout.addWidget(self._region_text_edit)

        self._region_text_save_btn = _PB(_i18n.t("vlm.region_text.save"))
        self._region_text_save_btn.setFixedHeight(28)
        self._region_text_save_btn.clicked.connect(self._on_save_grounding)
        side_layout.addWidget(self._region_text_save_btn)

        # Track which shape index is bound to the text editor so we can
        # commit the current text before switching to a new selection.
        self._region_text_bound_idx: int = -1

        # -- Caption / VLM editing --
        self._caption_header = self._section_label(_i18n.t("vlm.caption").upper())
        side_layout.addSpacing(T.GAP)
        side_layout.addWidget(self._caption_header)

        self._caption_edit = PlainTextEdit()
        self._caption_edit.setObjectName("captionEdit")
        self._caption_edit.setPlaceholderText(_i18n.t("vlm.caption.placeholder"))
        self._caption_edit.setFixedHeight(80)
        side_layout.addWidget(self._caption_edit)

        self._caption_save_btn = _PB(_i18n.t("vlm.caption.save"))
        self._caption_save_btn.setFixedHeight(28)
        self._caption_save_btn.clicked.connect(self._on_save_caption)
        side_layout.addWidget(self._caption_save_btn)

        # -- Conversation editor --
        self._conv_turns: list[_ConvTurnWidget] = []

        side_layout.addSpacing(T.GAP)
        self._conv_header = self._section_label(
            _i18n.t("vlm.conv").upper())
        side_layout.addWidget(self._conv_header)

        self._conv_scroll = QScrollArea()
        self._conv_scroll.setObjectName("convScroll")
        self._conv_scroll.setWidgetResizable(True)
        self._conv_scroll.setMaximumHeight(220)
        self._conv_scroll.setMinimumHeight(0)
        self._conv_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._conv_container = QWidget()
        self._conv_layout = QVBoxLayout(self._conv_container)
        self._conv_layout.setContentsMargins(0, 0, 0, 0)
        self._conv_layout.setSpacing(T.GAP_XS)
        self._conv_layout.addStretch()

        self._conv_scroll.setWidget(self._conv_container)
        side_layout.addWidget(self._conv_scroll)

        conv_btns = QHBoxLayout()
        conv_btns.setSpacing(T.GAP_XS)
        self._conv_add_btn = ToolButton(FIF.ADD)
        self._conv_add_btn.setToolTip(_i18n.t("vlm.conv.add"))
        self._conv_add_btn.setFixedHeight(28)
        self._conv_add_btn.clicked.connect(self._on_conv_add_turn)
        conv_btns.addWidget(self._conv_add_btn)
        self._conv_save_btn = _PB(_i18n.t("vlm.conv.save"))
        self._conv_save_btn.setFixedHeight(28)
        self._conv_save_btn.clicked.connect(self._on_save_conversations)
        conv_btns.addWidget(self._conv_save_btn)
        side_layout.addLayout(conv_btns)

        # -- Workflow status + actions --
        from qfluentwidgets import PrimaryPushButton, PushButton

        side_layout.addSpacing(T.GAP)
        side_layout.addWidget(self._section_label("工作状态"))

        self._wf_status_label = CaptionLabel("—")
        self._wf_status_label.setObjectName("statValue")
        side_layout.addWidget(self._wf_status_label)

        wf_actions = QHBoxLayout()
        wf_actions.setSpacing(T.GAP_XS)
        self._wf_submit_btn = PrimaryPushButton(_i18n.t("wf.submit_review"))
        self._wf_submit_btn.setFixedHeight(28)
        self._wf_submit_btn.clicked.connect(self._on_wf_submit_review)
        wf_actions.addWidget(self._wf_submit_btn)

        self._wf_approve_btn = PushButton(_i18n.t("wf.approve"))
        self._wf_approve_btn.setFixedHeight(28)
        self._wf_approve_btn.clicked.connect(self._on_wf_approve)
        wf_actions.addWidget(self._wf_approve_btn)

        self._wf_reject_btn = PushButton(_i18n.t("wf.reject"))
        self._wf_reject_btn.setFixedHeight(28)
        self._wf_reject_btn.clicked.connect(self._on_wf_reject)
        wf_actions.addWidget(self._wf_reject_btn)
        side_layout.addLayout(wf_actions)

        # Initially hidden — shown when workflow is active
        self._wf_widgets = [self._wf_status_label, self._wf_submit_btn,
                            self._wf_approve_btn, self._wf_reject_btn]
        for w in self._wf_widgets:
            w.setVisible(False)

        body.addWidget(sidebar)
        root.addLayout(body, 1)

    # ---------- 接口 ----------

    def show_image(self, image: ImageInfo, image_list: list[ImageInfo]) -> None:
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

    def _on_back_clicked(self) -> None:
        if not self._confirm_discard():
            return
        self.back_requested.emit()

    def _on_move_category(self) -> None:
        """Reassign the current image's category without leaving DetailView.

        Discovers existing categories from the image list we already have
        (avoids needing a direct AppState reference), then delegates
        fileops + rescan to the outer view via change_category_requested.
        """
        if not self._images or self._index < 0:
            return
        current = self._images[self._index]
        # Categories = unique set from the in-view image list, minus the
        # current one (moving to self is a no-op).
        cats = sorted({img.category for img in self._images
                        if img.category and img.category != current.category})
        if not cats:
            from qfluentwidgets import MessageBox as _MB
            box = _MB("无其他类别", "当前数据集只有一个类别", self.window())
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

    def _block_write_if_scanning(self) -> bool:
        """Return True (and show an InfoBar) when writes are gated off.
        Callers use it as an early-return guard: ``if self._block_write_if_scanning(): return``.
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

    # ---------- 内部 ----------

    def _load_current(self) -> None:
        if not (0 <= self._index < len(self._images)):
            return
        img = self._images[self._index]

        # 立即更新面包屑（轻量，不阻塞）
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

        # Cache miss: abandon any in-flight loader and spawn a fresh one.
        # generation token lets _on_image_loaded drop the stale ``done``.
        old = getattr(self, "_loader", None)
        if old is not None:
            try:
                if old.isRunning():
                    # Cancel only — don't wait(). QImage(path) on a
                    # 3072×4096 TIFF can't be interrupted mid-read, so
                    # wait(500) used to freeze the main thread on every
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

    # ---------- LRU cache + prefetch ----------

    def _cache_get(self, key: str):
        hit = self._image_cache.get(key)
        if hit is not None:
            # Move to most-recently-used position
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
        """Kick off background loads for the neighbors (prev + next)
        if they're not already cached or in flight. Sequential browsing
        becomes instant once the warm-up round-trip completes."""
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
            # SampleSet is authoritative for prefetch too.
            pre = None
            nb_sample = self._find_sample(neighbor)
            if nb_sample is not None:
                pre = _sample_to_annotation(nb_sample)
            loader = _ImageLoader(neighbor, self._load_generation,
                                   prefetch=True, parent=self,
                                   pre_annotation=pre)
            loader.prefetched.connect(self._on_prefetch_done)
            # finished fires on *any* thread exit (success, cancel, error),
            # so clear the in-flight flag here to avoid a permanent pin
            # if cancellation beat the prefetched signal.
            loader.finished.connect(
                lambda k=key: self._inflight_prefetch.discard(k)
            )
            loader.finished.connect(loader.deleteLater)
            loader.start()

    def _on_prefetch_done(self, path: str, qimage: QImage, annotation) -> None:
        # Defensive: this slot fires on the main thread via a queued
        # signal from a prefetch QThread. If the view was torn down
        # between emit and delivery, silently drop instead of crashing.
        try:
            self._inflight_prefetch.discard(path)
            if qimage is None or qimage.isNull():
                return
            self._cache_put(path, qimage, annotation)
        except RuntimeError:
            # Wrapped C++ object of type DetailView has been deleted.
            return

    def _on_image_loaded(self, qimage: QImage, annotation, img: ImageInfo,
                          generation: int) -> None:
        """Worker 完成后在主线程设置 viewer。QImage→QPixmap 必须在主线程."""
        # Drop late deliveries: a slow load that finishes after the user
        # pressed next/prev would otherwise paint the wrong image.
        if generation != self._load_generation:
            return
        if not qimage.isNull():
            self.viewer.load_pixmap(QPixmap.fromImage(qimage))
            # Cache the freshly loaded image so the reverse-direction
            # click (D, then A) hits instantly. Skip the cache on null
            # decodes — corrupted files shouldn't pin memory.
            self._cache_put(str(img.path), qimage, annotation)
            # Defer prefetch to next tick — see the matching comment in
            # _load_current about RPC_E_CANTCALLOUT_ININPUTSYNCCALL.
            QTimer.singleShot(0, self._schedule_prefetch)
        self._annotation = annotation
        self.viewer.set_annotation(self._annotation)
        try:
            size_kb = img.path.stat().st_size / 1024
            self.info_size.setText(
                f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb / 1024:.2f} MB"
            )
        except OSError:
            self.info_size.setText("—")
        # 尺寸从 viewer 拿
        if self.viewer._pix_item is not None:
            r = self.viewer._pix_item.pixmap()
            self.info_dim.setText(f"{r.width()} × {r.height()} px")
        else:
            self.info_dim.setText("—")
        self.info_cat.setText(img.category)

        # 标注列表
        self._refresh_shape_list()
        if self.edit_btn.isChecked():
            self._refresh_label_combo()
        # Remember the label file's mtime at load-time so _on_save can
        # detect conflict: if the file changed externally (another editor,
        # another DataForge instance) between load and save, we warn
        # before overwriting. Review #22.
        self._label_mtime_at_load = None
        try:
            if img.has_label and img.label_path and img.label_path.is_file():
                self._label_mtime_at_load = img.label_path.stat().st_mtime_ns
        except OSError:
            self._label_mtime_at_load = None
        self._dirty = False
        self._update_wf_status(img)
        self._update_caption(img)
        self._update_conversations(img)
        # Load region texts from sidecar if shapes lack text
        self._load_region_texts_from_sidecar(img)
        # Reset region text editor
        self._region_text_bound_idx = -1
        self._region_text_edit.setPlainText("")
        self._region_text_edit.setEnabled(False)

    def _show_shortcuts(self) -> None:
        from gui.dialogs.op_dialogs import ShortcutsDialog
        ShortcutsDialog(self.window()).exec()

    def _on_zoom_changed(self, scale: float) -> None:
        self.zoom_label.setText(f"{scale * 100:.0f}%")

    # ---------- 编辑 ----------

    def _on_edit_toggled(self, on: bool) -> None:
        self.viewer.set_edit_mode(on)
        self.label_combo.setVisible(on)
        self.delete_shape_btn.setVisible(on)
        self.save_btn.setVisible(on)
        self.shape_rect_btn.setVisible(on)
        self.shape_poly_btn.setVisible(on)
        if on:
            # 无标注图片 → 自动创建空 Annotation，这样绘制的新 shape 有地方存
            if self._annotation is None and 0 <= self._index < len(self._images):
                img = self._images[self._index]
                self._annotation = Annotation(image_path=img.path, shapes=[])
                self.viewer.set_annotation(self._annotation)
            self._refresh_label_combo()
            self.viewer.set_draw_label(self.label_combo.currentText() or "object")

    def _set_shape_type(self, st: str) -> None:
        self.shape_rect_btn.setChecked(st == "rectangle")
        self.shape_poly_btn.setChecked(st == "polygon")
        self.viewer.set_draw_shape_type(st)

    def _refresh_label_combo(self) -> None:
        existing = sorted({s.label for s in (self._annotation.shapes if self._annotation else [])})
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
        self._annotation = self.viewer.get_annotation()
        self._refresh_shape_list()
        self._refresh_label_combo()
        self.save_btn.setToolTip("保存标注 (Ctrl+S) — 有未保存修改")
        # Reset region text binding — shape indices may have shifted
        self._region_text_bound_idx = -1
        self._region_text_edit.setPlainText("")
        self._region_text_edit.setEnabled(False)

    def _on_selection_changed(self, idx: int) -> None:
        # Commit pending region text before switching selection
        self._commit_region_text()
        self.shape_list.blockSignals(True)
        if 0 <= idx < self.shape_list.count():
            self.shape_list.setCurrentRow(idx)
        else:
            self.shape_list.clearSelection()
        self.shape_list.blockSignals(False)
        self._bind_region_text(idx)

    def _refresh_shape_list(self) -> None:
        self.shape_list.clear()
        if self._annotation and self._annotation.shapes:
            for shape in self._annotation.shapes:
                item = QListWidgetItem(f"●  {shape.label}   ({shape.shape_type})")
                color = color_for_label(shape.label)
                item.setForeground(color)
                self.shape_list.addItem(item)
        else:
            self.shape_list.addItem(QListWidgetItem("（无标注）"))

    def _on_save(self) -> None:
        if self._block_write_if_scanning():
            return
        if not (0 <= self._index < len(self._images)):
            return
        img = self._images[self._index]
        if self._annotation is None:
            self._annotation = Annotation(image_path=img.path, shapes=[])
        # 推断 label_path：已有就用原路径（保持原格式）；
        # 没有则使用项目首选标注格式。
        label_path = img.label_path
        if label_path is None:
            from core.annotation_writer import label_path_for_format
            label_path = label_path_for_format(
                img.path, self._annotation_format)

        # Review #22: if the label file changed since we loaded it, ask
        # before overwriting. Common causes: external editor, a second
        # DataForge instance, or sync daemon. Ignore when we've never
        # loaded a label (new annotation) or the file vanished.
        if (self._label_mtime_at_load is not None
                and label_path.is_file()):
            try:
                disk_mtime = label_path.stat().st_mtime_ns
            except OSError:
                disk_mtime = self._label_mtime_at_load
            # 100 ms tolerance (in ns) — bigger than any real filesystem's
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
        # 更新 ImageInfo 状态
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
        # Refresh the conflict-detection baseline to the file we just
        # wrote — any further external edits show up on the next save.
        try:
            self._label_mtime_at_load = label_path.stat().st_mtime_ns
        except OSError:
            pass
        # Auto-transition: saving annotation advances workflow status.
        # new/prelabeled → annotating (work has started).
        if sample is not None and sample.work_status in ("new", "prelabeled"):
            sample.work_status = "annotating"
            self.work_status_changed.emit(img, "annotating")
            self._update_wf_status(img)

        InfoBar.success(
            title="已保存", content=str(label_path.name),
            isClosable=True, position=InfoBarPosition.TOP,
            duration=2000, parent=self.window(),
        )

    # ---------- 助手 ----------

    def _section_label(self, text: str) -> CaptionLabel:
        # Dedicated section-header style (see QSS: QLabel#sectionHeader).
        # CaptionLabel gives us a smaller, muted tracked-uppercase header
        # that matches the sidebar's `toolSidebarSection` pattern, instead
        # of the heavier default StrongBodyLabel body weight.
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

    # ---------- 工作流状态 ----------

    _WF_STATUS_LABELS = {
        "new": "● 新建",
        "prelabeled": "● 预标注",
        "annotating": "● 标注中",
        "review_pending": "● 待审核",
        "needs_fix": "● 需修补",
        "ready": "✓ 就绪",
        "exported": "✓ 已导出",
    }

    def _update_wf_status(self, img: ImageInfo) -> None:
        """Show/hide workflow widgets and set status for current image."""
        sample = self._find_sample(img)
        status = sample.work_status if sample else ""
        has_wf = bool(status)
        for w in self._wf_widgets:
            w.setVisible(has_wf)
        if not has_wf:
            return
        self._wf_status_label.setText(
            self._WF_STATUS_LABELS.get(status, status))
        # Button visibility by current status
        # 待标注 (new/prelabeled/annotating) → "提交审核"
        # 待审核 (review_pending) → "通过" / "需修补"
        # needs_fix → "提交审核" (re-submit after fix)
        # ready/exported → all hidden
        self._wf_submit_btn.setVisible(
            status in ("new", "prelabeled", "annotating", "needs_fix"))
        self._wf_approve_btn.setVisible(status == "review_pending")
        self._wf_reject_btn.setVisible(status == "review_pending")

    def _on_wf_submit_review(self) -> None:
        self._transition_work_status("review_pending")

    def _on_wf_approve(self) -> None:
        self._transition_work_status("ready")

    def _on_wf_reject(self) -> None:
        self._transition_work_status("needs_fix")

    def _transition_work_status(self, new_status: str) -> None:
        """Change current image's work status and emit signal.

        Workflow transitions count as writes: they persist into the
        workflow store and mutate the in-memory Sample.work_status,
        which the SampleSet unify pass also writes during scan —
        letting the user flip status while the worker is still
        assembling SampleSet would leave two writers racing on the
        same field. Same scan_active gate as file-level saves.
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
        self._update_wf_status(img)
        InfoBar.success(
            "", self._WF_STATUS_LABELS.get(new_status, new_status),
            parent=self.window(), duration=1500,
            position=InfoBarPosition.TOP,
        )

    # ---------- VLM caption ----------

    def _update_caption(self, img: ImageInfo) -> None:
        """Populate caption editor from the current image's Sample.

        Falls back to reading the sidecar ``.txt`` file when the Sample
        has no caption (e.g. caption was saved previously but SampleSet
        wasn't rebuilt yet).
        """
        sample = self._find_sample(img)
        caption = sample.caption if sample else ""
        if not caption:
            from core.annotation_writer import read_caption
            caption = read_caption(img.path)
        self._caption_edit.setPlainText(caption)

    def _on_save_caption(self) -> None:
        """Persist caption text to the current Sample and emit signal."""
        if self._block_write_if_scanning():
            return
        if not (0 <= self._index < len(self._images)):
            return
        img = self._images[self._index]
        text = self._caption_edit.toPlainText().strip()
        sample = self._find_sample(img)
        if sample is not None:
            sample.caption = text
        self.caption_saved.emit(img, text)
        InfoBar.success(
            "", "Caption saved",
            parent=self.window(), duration=1500,
            position=InfoBarPosition.TOP,
        )

    # ---------- VLM conversations ----------

    def _update_conversations(self, img: ImageInfo) -> None:
        """Populate conversation editor from Sample or disk sidecar."""
        sample = self._find_sample(img)
        convos = sample.conversations if sample else []
        if not convos:
            from core.annotation_writer import read_conversations
            convos = read_conversations(img.path)
        self._populate_conv_turns(convos)

    def _populate_conv_turns(self, convos: list[dict[str, str]]) -> None:
        """Clear and rebuild conversation turn widgets."""
        for w in self._conv_turns:
            self._conv_layout.removeWidget(w)
            w.deleteLater()
        self._conv_turns.clear()

        for turn in convos:
            role = turn.get("from", "human")
            text = turn.get("value", "")
            self._add_turn_widget(role, text)

    def _add_turn_widget(self, role: str = "human", text: str = "") -> _ConvTurnWidget:
        """Create a turn widget and insert before the stretch."""
        tw = _ConvTurnWidget(role, text)
        tw.removed.connect(self._on_conv_turn_removed)
        insert_idx = self._conv_layout.count() - 1  # before stretch
        self._conv_layout.insertWidget(insert_idx, tw)
        self._conv_turns.append(tw)
        return tw

    def _on_conv_add_turn(self) -> None:
        """Add a new empty turn. Alternates role based on last turn."""
        if self._conv_turns:
            last = self._conv_turns[-1].to_dict()
            role = "gpt" if last["from"] == "human" else "human"
        else:
            role = "human"
        self._add_turn_widget(role, "")

    def _on_conv_turn_removed(self, widget: _ConvTurnWidget) -> None:
        """Remove a turn widget from the editor."""
        if widget in self._conv_turns:
            self._conv_turns.remove(widget)
        self._conv_layout.removeWidget(widget)
        widget.deleteLater()

    def _on_save_conversations(self) -> None:
        """Persist conversations to the current Sample and emit signal."""
        if self._block_write_if_scanning():
            return
        if not (0 <= self._index < len(self._images)):
            return
        img = self._images[self._index]
        convos = [tw.to_dict() for tw in self._conv_turns
                  if tw.to_dict()["value"]]  # skip empty turns
        sample = self._find_sample(img)
        if sample is not None:
            sample.conversations = convos
        self.conversations_saved.emit(img, convos)
        InfoBar.success(
            "", "Conversations saved",
            parent=self.window(), duration=1500,
            position=InfoBarPosition.TOP,
        )

    # ---------- Region text (grounding) ----------

    def _bind_region_text(self, idx: int) -> None:
        """Load text from shape[idx] into the region text editor."""
        shapes = self._annotation.shapes if self._annotation else []
        if 0 <= idx < len(shapes):
            self._region_text_bound_idx = idx
            self._region_text_edit.setPlainText(shapes[idx].text)
            self._region_text_edit.setEnabled(True)
        else:
            self._region_text_bound_idx = -1
            self._region_text_edit.setPlainText("")
            self._region_text_edit.setEnabled(False)

    def _commit_region_text(self) -> None:
        """Write the current text editor content back to the bound shape."""
        idx = self._region_text_bound_idx
        shapes = self._annotation.shapes if self._annotation else []
        if 0 <= idx < len(shapes):
            shapes[idx].text = self._region_text_edit.toPlainText().strip()

    def _on_save_grounding(self) -> None:
        """Commit region text, update Sample, write sidecar, emit signal."""
        if self._block_write_if_scanning():
            return
        self._commit_region_text()
        if not (0 <= self._index < len(self._images)):
            return
        img = self._images[self._index]
        # Build grounding list from shapes that have text
        shapes = self._annotation.shapes if self._annotation else []
        grounding: list[dict] = []
        for s in shapes:
            if not s.text:
                continue
            entry: dict = {"label": s.label, "text": s.text}
            if s.shape_type == "rectangle" and len(s.points) >= 2:
                from core.unified import BBox
                bb = BBox.from_points(s.points)
                entry["bbox"] = [bb.x1, bb.y1, bb.x2, bb.y2]
            grounding.append(entry)
        # Sync text back to unified Sample.regions
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
        """If annotation has shapes but no text, try loading from sidecar."""
        shapes = self._annotation.shapes if self._annotation else []
        if not shapes:
            return
        # Already have text? Skip.
        if any(s.text for s in shapes):
            return
        from core.annotation_writer import read_grounding
        gnd = read_grounding(img.path)
        if not gnd:
            return
        # Match grounding entries to shapes by label + bbox proximity
        for entry in gnd:
            label = entry.get("label", "")
            text = entry.get("text", "")
            bbox = entry.get("bbox")
            if not text:
                continue
            # Find the best matching shape
            best_idx = -1
            for i, s in enumerate(shapes):
                if s.text:
                    continue  # already assigned
                if s.label != label:
                    continue
                if bbox and s.shape_type == "rectangle" and len(s.points) >= 2:
                    # Spatial match — check bbox overlap
                    from core.unified import BBox
                    sb = BBox.from_points(s.points)
                    dx = abs(sb.x1 - bbox[0]) + abs(sb.y1 - bbox[1])
                    if dx < 5:  # close enough (pixel tolerance)
                        best_idx = i
                        break
                elif best_idx < 0:
                    best_idx = i  # first label match
            if best_idx >= 0:
                shapes[best_idx].text = text

    # ---------- 快捷键 ----------

    def keyPressEvent(self, e: QKeyEvent) -> None:  # type: ignore[override]
        if e.key() in (Qt.Key.Key_A, Qt.Key.Key_Left):
            self.prev_image()
        elif e.key() in (Qt.Key.Key_D, Qt.Key.Key_Right):
            self.next_image()
        elif e.key() == Qt.Key.Key_H:
            self.toggle_anno_btn.toggle()
        elif e.key() == Qt.Key.Key_E:
            self.edit_btn.toggle()
        elif e.key() == Qt.Key.Key_R and self.edit_btn.isChecked():
            self._set_shape_type("rectangle")
        elif e.key() == Qt.Key.Key_P and self.edit_btn.isChecked():
            self._set_shape_type("polygon")
        elif e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.edit_btn.isChecked():
            self.viewer.finish_polygon()
        elif e.key() == Qt.Key.Key_Delete and self.edit_btn.isChecked():
            self.viewer.delete_selected()
        elif e.key() == Qt.Key.Key_S and (e.modifiers() & Qt.KeyboardModifier.ControlModifier):
            if self.edit_btn.isChecked():
                self._on_save()
        elif e.key() == Qt.Key.Key_Escape:
            self._on_back_clicked()
        else:
            super().keyPressEvent(e)
