"""项目概览 hub — project console (status card + class tree).

Read-only dashboard. No file management, no structural changes.
Those belong in 数据处理 / 标注 stages.

Layout::

    ┌─────────────────────────────────────────────────┐
    │  项目概览                                         │
    │                                                 │
    │  ┌─ Status card ──────────────────────────────┐  │
    │  │ 故障标注数据集          目标检测 · LabelMe  │  │
    │  │ 4,796  12   4,796  0   0                   │  │
    │  │ 图片   类别 待处理 待审核 可导出             │  │
    │  │                            [继续标注 →]    │  │
    │  └────────────────────────────────────────────┘  │
    │                                                 │
    │  类别概览                              12 类     │
    │  ┌ Loose       2,176 张    ✓ 已标注 ──────────┐  │
    │  │  ▸ images/ (2,176 张) — click file → dialog│  │
    │  │  ▸ labels/ (2,176 个)                      │  │
    │  │ Lose        1,038 张    ✓ 已标注           │  │
    │  └────────────────────────────────────────────┘  │
    └─────────────────────────────────────────────────┘
"""
from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QScrollArea,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    FluentIcon as FIF,
    PrimaryPushButton,
    StrongBodyLabel,
    SubtitleLabel,
    TitleLabel,
    TreeWidget,
)

from core.project import Project
from core.task_types import TASK_REGISTRY
from gui import i18n
from gui.theme import T

# ── Tree node roles / kinds ────────────────────────────────────────
_ROLE_KIND = Qt.ItemDataRole.UserRole
_ROLE_CAT = Qt.ItemDataRole.UserRole + 1
_ROLE_IMG = Qt.ItemDataRole.UserRole + 2     # ImageInfo reference
_ROLE_LOADED = Qt.ItemDataRole.UserRole + 3  # bool — children populated

_KIND_CATEGORY = "category"
_KIND_IMAGES = "images"
_KIND_LABELS = "labels"
_KIND_FILE = "file"


# Pretty-print annotation format.
_FMT_DISPLAY = {
    "labelme": "LabelMe JSON",
    "yolo": "YOLO",
    "voc": "Pascal VOC",
    "coco": "COCO",
    "coco-seg": "COCO-seg",
    "imagefolder": "ImageFolder",
    "mvtec": "MVTec",
    "llava": "LLaVA",
    "sharegpt": "ShareGPT",
    "swift": "Swift",
    "caption jsonl": "Caption JSONL",
    "coco-keypoints": "COCO-keypoints",
    "dota": "DOTA",
    "pairedfolder": "PairedFolder",
}


def _format_label(fmt: str) -> str:
    key = (fmt or "").strip().lower()
    return _FMT_DISPLAY.get(key, fmt or "—")


# ── Stat pill ──────────────────────────────────────────────────────

class _StatPill(QWidget):
    """Compact vertical stat: big number on top, muted label below."""

    def __init__(self, value: str, label: str, parent: QWidget | None = None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self._value = StrongBodyLabel(value)
        self._value.setObjectName("overviewStatValue")
        self._label = CaptionLabel(label)
        self._label.setObjectName("overviewStatLabel")
        lay.addWidget(self._value)
        lay.addWidget(self._label)

    def set_value(self, v: str) -> None:
        self._value.setText(v)

    def set_warn(self, warn: bool) -> None:
        self._value.setProperty("warn", "true" if warn else "false")
        self._value.style().unpolish(self._value)
        self._value.style().polish(self._value)


# ── Status card ────────────────────────────────────────────────────

class _StatusCard(QFrame):
    """Top card: project identity + workflow stats + next-step CTA."""

    cta_clicked = pyqtSignal(int)  # emits StageIndex

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chartFrame")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        root = QVBoxLayout(self)
        root.setContentsMargins(T.PAD_XL, T.PAD_LG, T.PAD_XL, T.PAD_LG)
        root.setSpacing(T.GAP_LG)

        # Row 1: name + task/format
        head = QHBoxLayout()
        self._name = SubtitleLabel("—")
        self._name.setObjectName("overviewProjectName")
        head.addWidget(self._name)
        head.addStretch(1)
        self._subtitle = CaptionLabel("")
        self._subtitle.setObjectName("overviewProjectSub")
        head.addWidget(self._subtitle)
        root.addLayout(head)

        # Row 2: stat pills
        stats_row = QHBoxLayout()
        stats_row.setSpacing(T.PAD_XL)
        self._pill_images = _StatPill("—", i18n.t("overview.stat.images"))
        self._pill_classes = _StatPill("—", i18n.t("overview.stat.classes"))
        self._pill_pending = _StatPill("—", i18n.t("overview.stat.pending"))
        self._pill_review = _StatPill("—", i18n.t("overview.stat.review"))
        self._pill_ready = _StatPill("—", i18n.t("overview.stat.ready"))
        for pill in (self._pill_images, self._pill_classes,
                     self._pill_pending, self._pill_review,
                     self._pill_ready):
            stats_row.addWidget(pill)
        stats_row.addStretch(1)
        root.addLayout(stats_row)

        # Row 3: CTA — the ONE thing the user should do next
        cta_row = QHBoxLayout()
        cta_row.addStretch(1)
        self._cta = PrimaryPushButton("—")
        self._cta.setFixedHeight(36)
        self._cta.setObjectName("overviewCTA")
        self._cta.clicked.connect(self._on_cta)
        cta_row.addWidget(self._cta)
        root.addLayout(cta_row)

        self._cta_stage: int = 3  # default: ANNOTATE

    def set_project_info(self, name: str, task_type: object,
                         target_format: str) -> None:
        self._name.setText(name or "—")
        parts: list[str] = []
        if task_type is not None:
            info = TASK_REGISTRY.get(task_type)
            if info:
                parts.append(info.display_name)
        if target_format:
            parts.append(f"目标 {_format_label(target_format)}")
        self._subtitle.setText(" · ".join(parts) if parts else "")

    def set_stats(self, images: int, classes: int,
                  pending: int, review: int, ready: int) -> None:
        self._pill_images.set_value(f"{images:,}" if images else "—")
        self._pill_classes.set_value(str(classes) if classes else "—")
        self._pill_pending.set_value(f"{pending:,}" if pending else "0")
        self._pill_review.set_value(f"{review:,}" if review else "0")
        self._pill_review.set_warn(review > 0)
        self._pill_ready.set_value(f"{ready:,}" if ready else "0")

    def set_cta(self, label: str, stage_index: int) -> None:
        self._cta.setText(f"{label} →")
        self._cta_stage = stage_index

    def _on_cta(self) -> None:
        self.cta_clicked.emit(self._cta_stage)


# ── Lightweight class tree (read-only, one level of expansion) ─────

def _label_status(img_count: int, lbl_count: int) -> str:
    if lbl_count >= img_count and img_count > 0:
        return "✓ 已标注"
    if lbl_count > 0:
        return f"部分标注 {lbl_count}/{img_count}"
    return "未标注"


def _right_align(item: QTreeWidgetItem, col: int) -> None:
    item.setTextAlignment(
        col, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)


# ── Hub ────────────────────────────────────────────────────────────

class ProjectOverviewHub(QWidget):
    """Project console — status, next step, class overview, quick nav.

    Read-only dashboard. Structural changes (move, delete, rename)
    belong in 数据处理 stage.
    """

    navigate_stage = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("projectOverviewHub")

        self._project: Project | None = None
        self._dataset = None
        self._wf_summary = None
        self._root_path: Path | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(T.PAD_2XL, T.PAD_XL, T.PAD_2XL, T.PAD_XL)
        lay.setSpacing(T.GAP_LG)

        # Title
        self._title = TitleLabel(i18n.t("overview.title"))
        self._title.setObjectName("overviewTitle")
        lay.addWidget(self._title)

        # Status card
        self._status = _StatusCard()
        self._status.cta_clicked.connect(self.navigate_stage.emit)
        lay.addWidget(self._status)

        # Class summary header
        cls_header = QHBoxLayout()
        self._cls_title = StrongBodyLabel(
            i18n.t("overview.classes.title"))
        self._cls_title.setObjectName("hubSectionTitle")
        cls_header.addWidget(self._cls_title)
        cls_header.addStretch(1)
        self._cls_count = CaptionLabel("")
        cls_header.addWidget(self._cls_count)
        lay.addLayout(cls_header)

        # Class tree — expandable to images/ + labels/ + file names.
        # No own scrollbar; the outer QScrollArea handles page scroll.
        self._cls_tree = TreeWidget()
        self._cls_tree.setHeaderHidden(True)
        self._cls_tree.setColumnCount(2)
        self._cls_tree.setIndentation(18)
        self._cls_tree.setRootIsDecorated(True)
        self._cls_tree.setUniformRowHeights(True)
        self._cls_tree.setAlternatingRowColors(False)
        self._cls_tree.setFrameShape(QFrame.Shape.NoFrame)
        self._cls_tree.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._cls_tree.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._cls_tree.header().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self._cls_tree.header().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents)
        self._cls_tree.itemExpanded.connect(self._on_tree_expanded)
        self._cls_tree.itemExpanded.connect(self._fit_tree_height)
        self._cls_tree.itemCollapsed.connect(self._fit_tree_height)
        self._cls_tree.itemClicked.connect(self._on_tree_clicked)
        lay.addWidget(self._cls_tree)

        self._cls_empty = CaptionLabel(
            i18n.t("overview.classes.empty"))
        self._cls_empty.setObjectName("welcomeEmptyHint")
        self._cls_empty.setWordWrap(True)
        self._cls_empty.hide()
        lay.addWidget(self._cls_empty)

        lay.addStretch(1)
        scroll.setWidget(body)

        i18n.bus.language_changed.connect(self._retranslate)

    # ── Public API ──────────────────────────────────────────────────

    def set_project(self, project: Project | None) -> None:
        self._project = project
        self._root_path = (
            getattr(project, "root_path", None) if project else None)
        self._refresh_status()

    def set_dataset(self, dataset) -> None:
        self._dataset = dataset
        self._refresh_status()
        self._refresh_classes()

    def set_workflow_summary(self, summary) -> None:
        self._wf_summary = summary
        self._refresh_status()

    # ── Internals ───────────────────────────────────────────────────

    def _refresh_status(self) -> None:
        from gui.widgets.workspace_sidebar import StageIndex

        proj = self._project
        ds = self._dataset
        wf = self._wf_summary

        # Identity
        name = (getattr(proj, "name", None)
                or getattr(ds, "name", None) or "—")
        task_type = getattr(proj, "task_type", None) if proj else None
        target_format = (
            getattr(proj, "target_format", "") or "") if proj else ""
        self._status.set_project_info(name, task_type, target_format)

        # Stats
        images = getattr(ds, "total_images", 0) if ds else 0
        classes = len(getattr(ds, "categories", []) or []) if ds else 0
        pending = getattr(wf, "new", 0) if wf else 0
        review = ((getattr(wf, "review_pending", 0) or 0)
                  + (getattr(wf, "needs_fix", 0) or 0)) if wf else 0
        ready = getattr(wf, "ready", 0) if wf else 0
        self._status.set_stats(images, classes, pending, review, ready)

        # CTA — single recommended action
        total = getattr(wf, "total", 0) if wf else 0
        annotating = getattr(wf, "annotating", 0) if wf else 0
        version_count = self._version_count(proj)
        if total == 0:
            self._status.set_cta(
                i18n.t("overview.cta.import"), StageIndex.INBOX)
        elif pending > 0 or annotating > 0:
            self._status.set_cta(
                i18n.t("overview.cta.annotate"), StageIndex.ANNOTATE)
        elif review > 0:
            self._status.set_cta(
                i18n.t("overview.cta.review"), StageIndex.REVIEW)
        elif ready > 0:
            if version_count <= 0:
                self._status.set_cta(
                    i18n.t("overview.cta.version"), StageIndex.PROCESS)
            else:
                self._status.set_cta(
                    i18n.t("overview.cta.export"), StageIndex.DELIVERY)
        elif version_count > 0:
            self._status.set_cta(
                i18n.t("overview.cta.export"), StageIndex.DELIVERY)
        else:
            self._status.set_cta(
                i18n.t("overview.cta.annotate"), StageIndex.ANNOTATE)

    @staticmethod
    def _version_count(project: Project | None) -> int:
        if project is None:
            return 0
        try:
            from core.version_builder import list_training_versions
            return len(list_training_versions(project.root_path))
        except Exception:
            return 0

    def _refresh_classes(self) -> None:
        tree = self._cls_tree
        tree.blockSignals(True)
        tree.clear()
        tree.blockSignals(False)

        ds = self._dataset
        cats = sorted(
            getattr(ds, "categories", []) or [],
            key=lambda c: c.image_count, reverse=True,
        ) if ds else []

        if not cats:
            self._cls_count.setText("")
            tree.setFixedHeight(0)
            tree.hide()
            self._cls_empty.show()
            return

        self._cls_empty.hide()
        tree.show()
        total = sum(c.image_count for c in cats)
        self._cls_count.setText(f"{len(cats)} 类 · {total:,} 张")

        ann_fmt = self._ann_fmt()

        for cat in cats:
            item = QTreeWidgetItem(tree)
            item.setText(0, cat.name)
            item.setIcon(0, FIF.FOLDER.icon())
            item.setText(1, _label_status(cat.image_count, cat.label_count))
            _right_align(item, 1)
            item.setData(0, _ROLE_KIND, _KIND_CATEGORY)
            item.setData(0, _ROLE_CAT, cat)

            # images/ node — expandable to show sample filenames
            img_child = QTreeWidgetItem(item)
            img_child.setText(0, "images/")
            img_child.setIcon(0, FIF.PHOTO.icon())
            img_child.setText(1, f"{cat.image_count:,} 张")
            _right_align(img_child, 1)
            img_child.setData(0, _ROLE_KIND, _KIND_IMAGES)
            img_child.setData(0, _ROLE_CAT, cat)
            img_child.setData(0, _ROLE_LOADED, False)
            QTreeWidgetItem(img_child)  # placeholder for expand arrow

            # labels/ node — expandable
            lbl_child = QTreeWidgetItem(item)
            lbl_child.setText(0, "labels/")
            lbl_child.setIcon(0, FIF.DOCUMENT.icon())
            lbl_child.setText(
                1, f"{cat.label_count:,} 个 · {ann_fmt}"
                if cat.label_count else "空")
            _right_align(lbl_child, 1)
            lbl_child.setData(0, _ROLE_KIND, _KIND_LABELS)
            lbl_child.setData(0, _ROLE_CAT, cat)
            lbl_child.setData(0, _ROLE_LOADED, False)
            if cat.label_count:
                QTreeWidgetItem(lbl_child)  # placeholder

        self._fit_tree_height()

    def _fit_tree_height(self, _item=None) -> None:
        """Resize tree to exactly fit visible rows (no inner scroll)."""
        tree = self._cls_tree
        if tree.topLevelItemCount() == 0:
            tree.setFixedHeight(0)
            return

        def _count_visible(item: QTreeWidgetItem) -> int:
            n = 1  # the item itself
            if item.isExpanded():
                for i in range(item.childCount()):
                    n += _count_visible(item.child(i))
            return n

        total_rows = 0
        for i in range(tree.topLevelItemCount()):
            total_rows += _count_visible(tree.topLevelItem(i))

        row_h = tree.sizeHintForRow(0) if tree.sizeHintForRow(0) > 0 else 28
        margin = 4
        tree.setFixedHeight(total_rows * row_h + margin)

    def _on_tree_expanded(self, item: QTreeWidgetItem) -> None:
        """Lazy-populate file samples on first expand of images/labels."""
        kind = item.data(0, _ROLE_KIND)
        if kind not in (_KIND_IMAGES, _KIND_LABELS):
            return  # category nodes have pre-built children
        if item.data(0, _ROLE_LOADED):
            return
        cat = item.data(0, _ROLE_CAT)
        if cat is None:
            return

        # Remove placeholder
        while item.childCount():
            item.removeChild(item.child(0))

        from PyQt6.QtGui import QBrush, QColor
        muted = QBrush(QColor(T.TEXT_3))

        names: list[tuple[str, object]] = []
        if kind == _KIND_IMAGES:
            for img in cat.images:
                names.append((img.path.name, img))
        elif kind == _KIND_LABELS:
            for img in cat.images:
                if img.has_label and img.label_path is not None:
                    names.append((img.label_path.name, img))

        if not names:
            empty = QTreeWidgetItem(item)
            empty.setText(0, "(空)")
            empty.setForeground(0, muted)
        else:
            for fname, img_info in names:
                f_item = QTreeWidgetItem(item)
                f_item.setText(0, fname)
                f_item.setIcon(0, FIF.DOCUMENT.icon())
                f_item.setForeground(0, muted)
                f_item.setData(0, _ROLE_KIND, _KIND_FILE)
                f_item.setData(0, _ROLE_IMG, img_info)

        item.setData(0, _ROLE_LOADED, True)

    def _on_tree_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        """Show file detail dialog when a file node is clicked."""
        if item.data(0, _ROLE_KIND) != _KIND_FILE:
            return
        img = item.data(0, _ROLE_IMG)
        if img is None:
            return
        self._show_file_detail(img)

    # ── JSON syntax highlighter ─────────────────────────────────────

    @staticmethod
    def _make_highlighter(text_edit):
        """Attach a lightweight JSON/XML syntax highlighter."""
        import re
        from PyQt6.QtGui import (
            QColor, QFont, QSyntaxHighlighter, QTextCharFormat,
        )

        class _JsonHL(QSyntaxHighlighter):
            def __init__(self, parent=None):
                super().__init__(parent)
                # Formats
                self._f_key = QTextCharFormat()
                self._f_key.setForeground(QColor(T.ACCENT))
                self._f_key.setFontWeight(QFont.Weight.DemiBold)

                self._f_str = QTextCharFormat()
                self._f_str.setForeground(QColor(T.SUCCESS))

                self._f_num = QTextCharFormat()
                self._f_num.setForeground(QColor(T.NODE_CAT_INPUT))

                self._f_const = QTextCharFormat()
                self._f_const.setForeground(QColor(T.WARNING))
                self._f_const.setFontWeight(QFont.Weight.DemiBold)

                self._f_brace = QTextCharFormat()
                self._f_brace.setForeground(QColor(T.TEXT_3))

                # Patterns (order matters)
                self._rules = [
                    # key: "word":
                    (re.compile(r'"([^"\\]|\\.)*"\s*(?=:)'), self._f_key),
                    # string value
                    (re.compile(r'"([^"\\]|\\.)*"'), self._f_str),
                    # number
                    (re.compile(r'\b-?(?:0|[1-9]\d*)(?:\.\d+)?'
                                r'(?:[eE][+-]?\d+)?\b'), self._f_num),
                    # true / false / null
                    (re.compile(r'\b(?:true|false|null)\b'), self._f_const),
                    # braces / brackets
                    (re.compile(r'[\[\]{}]'), self._f_brace),
                ]

            def highlightBlock(self, text: str) -> None:
                for pat, fmt in self._rules:
                    for m in pat.finditer(text):
                        self.setFormat(m.start(), m.end() - m.start(), fmt)

        return _JsonHL(text_edit.document())

    # ── File detail dialog ──────────────────────────────────────────

    def _show_file_detail(self, img) -> None:
        """Pop up a dialog: image preview (with optional shape overlay)
        + raw annotation file content with syntax highlighting."""
        import json
        from PyQt6.QtGui import (
            QColor, QPainter, QPen, QPixmap, QPolygonF,
        )
        from PyQt6.QtCore import QPointF
        from PyQt6.QtWidgets import (
            QHBoxLayout as _HBox, QLabel,
            QPlainTextEdit, QSizePolicy, QVBoxLayout as _VBox,
            QWidget as _Widget,
        )
        from qfluentwidgets import (
            BodyLabel, CaptionLabel as _Cap, CheckBox, MessageBoxBase,
            StrongBodyLabel as _Strong, SubtitleLabel as _Subtitle,
        )
        from gui.widgets.image_viewer import PALETTE

        img_path: Path = img.path
        has_label = img.has_label and img.label_path is not None

        # ── Load original pixmap ──
        pix_orig: QPixmap | None = None
        img_w, img_h = 0, 0
        if img_path.is_file():
            pix_orig = QPixmap(str(img_path))
            if pix_orig.isNull():
                pix_orig = None
            else:
                img_w, img_h = pix_orig.width(), pix_orig.height()

        # ── Parse shapes from annotation ──
        shapes: list[dict] = []
        lbl_raw = ""
        lbl_suffix = ""
        if has_label:
            lbl_path = img.label_path
            lbl_suffix = lbl_path.suffix.lower()
            try:
                if lbl_path.is_file():
                    lbl_raw = lbl_path.read_text("utf-8")
                    if lbl_suffix == ".json":
                        try:
                            data = json.loads(lbl_raw)
                            shapes = data.get("shapes", [])
                            lbl_raw = json.dumps(
                                data, indent=2, ensure_ascii=False)
                        except Exception:
                            pass
            except Exception as e:
                lbl_raw = f"(读取失败: {e})"

        # ── Helper: draw shapes onto a pixmap copy ──
        def _render_pixmap(draw_shapes: bool) -> QPixmap | None:
            if pix_orig is None:
                return None
            pix = pix_orig.copy()
            if draw_shapes and shapes:
                painter = QPainter(pix)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                for s in shapes:
                    label = s.get("label", "")
                    pts = s.get("points", [])
                    stype = s.get("shape_type", "polygon")
                    if len(pts) < 2:
                        continue
                    ci = abs(hash(label)) % len(PALETTE)
                    color = QColor(PALETTE[ci])
                    pen = QPen(color, max(2, img_w // 400))
                    painter.setPen(pen)
                    fill = QColor(color)
                    fill.setAlpha(35)
                    painter.setBrush(fill)
                    if stype == "rectangle" and len(pts) >= 2:
                        x0, y0 = pts[0]
                        x1, y1 = pts[1]
                        from PyQt6.QtCore import QRectF
                        painter.drawRect(QRectF(x0, y0, x1 - x0, y1 - y0))
                    else:
                        poly = QPolygonF(
                            [QPointF(p[0], p[1]) for p in pts])
                        painter.drawPolygon(poly)
                    if label:
                        painter.setPen(QPen(color))
                        font = painter.font()
                        font.setPixelSize(max(12, img_w // 60))
                        painter.setFont(font)
                        painter.drawText(
                            int(pts[0][0]) + 2, int(pts[0][1]) - 4,
                            label)
                painter.end()
            return pix

        # ── Dialog ──
        dlg = MessageBoxBase(parent=self.window())
        dlg.widget.setMinimumSize(920, 580)
        dlg.widget.setMaximumWidth(1100)
        dlg.titleLabel = _Subtitle(f"文件详情 — {img_path.name}", dlg)
        dlg.viewLayout.addWidget(dlg.titleLabel)

        content = _Widget()
        root = _HBox(content)
        root.setContentsMargins(0, T.GAP, 0, 0)
        root.setSpacing(20)

        # ── Left: image preview ──
        left = _VBox()
        left.setSpacing(8)

        img_label = QLabel()
        img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        img_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        img_label.setMinimumSize(360, 320)
        img_label.setObjectName("overviewImagePreview")

        preview_size = (440, 400)

        def _update_preview(show_shapes: bool) -> None:
            pix = _render_pixmap(show_shapes)
            if pix is not None:
                scaled = pix.scaled(
                    *preview_size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)
                img_label.setPixmap(scaled)
            elif pix_orig is None:
                img_label.setText(
                    "文件不存在" if not img_path.is_file()
                    else "无法加载图片")

        _update_preview(bool(shapes))
        left.addWidget(img_label)

        # Meta line
        meta_parts: list[str] = [img_path.name]
        try:
            if img_path.is_file():
                sz = img_path.stat().st_size
                if sz < 1024:
                    meta_parts.append(f"{sz} B")
                elif sz < 1024 * 1024:
                    meta_parts.append(f"{sz / 1024:.1f} KB")
                else:
                    meta_parts.append(f"{sz / 1024 / 1024:.1f} MB")
                if img_w:
                    meta_parts.append(f"{img_w}×{img_h}")
        except Exception:
            pass
        meta_lbl = _Cap(" · ".join(meta_parts))
        meta_lbl.setWordWrap(True)
        left.addWidget(meta_lbl)

        # Shape overlay toggle
        if shapes:
            chk = CheckBox(f"显示标注 ({len(shapes)} 个)")
            chk.setChecked(True)
            chk.checkStateChanged.connect(
                lambda _: _update_preview(chk.isChecked()))
            left.addWidget(chk)

        root.addLayout(left, stretch=1)

        # ── Right: annotation content ──
        right = _VBox()
        right.setSpacing(8)

        if has_label:
            lbl_path = img.label_path

            # Header
            lbl_meta_parts = [lbl_path.name]
            try:
                if lbl_path.is_file():
                    lsz = lbl_path.stat().st_size
                    if lsz < 1024:
                        lbl_meta_parts.append(f"{lsz} B")
                    elif lsz < 1024 * 1024:
                        lbl_meta_parts.append(f"{lsz / 1024:.1f} KB")
                    else:
                        lbl_meta_parts.append(f"{lsz / 1024 / 1024:.1f} MB")
            except Exception:
                pass
            header = _Strong(" · ".join(lbl_meta_parts))
            right.addWidget(header)

            # Shape summary
            if shapes:
                types: dict[str, int] = {}
                for s in shapes:
                    t = s.get("shape_type", "?")
                    types[t] = types.get(t, 0) + 1
                summary_parts = [f"{v} {k}" for k, v in types.items()]
                right.addWidget(
                    _Cap(f"{len(shapes)} 个标注: {', '.join(summary_parts)}"))

            # Code viewer with syntax highlighting
            text_edit = QPlainTextEdit()
            text_edit.setReadOnly(True)
            text_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
            text_edit.setTabStopDistance(20.0)
            text_edit.setObjectName("overviewAnnotationCode")
            text_edit.setPlainText(lbl_raw)

            # Attach syntax highlighter for JSON
            if lbl_suffix == ".json":
                self._make_highlighter(text_edit)

            right.addWidget(text_edit)
        else:
            no_lbl = BodyLabel("该图片暂无标注文件")
            no_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            right.addStretch(1)
            right.addWidget(no_lbl)
            right.addStretch(1)

        root.addLayout(right, stretch=1)

        dlg.viewLayout.addWidget(content)
        dlg.yesButton.setText("关闭")
        dlg.cancelButton.hide()

        dlg.exec()

    def _ann_fmt(self) -> str:
        return (
            (getattr(self._project, "annotation_format", "labelme")
             or "labelme")
            if self._project is not None else "labelme"
        ).upper()

    def _open_in_explorer(self) -> None:
        if self._root_path and self._root_path.is_dir():
            os.startfile(str(self._root_path))

    def _retranslate(self, _lang: str) -> None:
        self._title.setText(i18n.t("overview.title"))
        self._cls_title.setText(i18n.t("overview.classes.title"))
        self._cls_empty.setText(i18n.t("overview.classes.empty"))
        self._refresh_status()
