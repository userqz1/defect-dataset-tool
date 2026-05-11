"""Dataset welcome — project launchpad (hero + 3 entries + recents grid).

Layout::

    ┌─────────────────────────────────────────────────────┐
    │  数据工坊 · DataForge                                  │   <- hero
    │  从原始图片到可训练数据集                                │
    │                                                     │
    │  ┌───────────┐  ┌───────────┐  ┌───────────┐         │   <- entry cards
    │  │ 新建项目   │  │ 打开项目   │  │ 打开普通   │         │
    │  │           │  │           │  │ 数据集    │         │
    │  └───────────┘  └───────────┘  └───────────┘         │
    │                                                     │
    │  最近项目 · 12                                        │
    │  ┌──────────────────┐  ┌──────────────────┐         │   <- 2-col grid
    │  │ 故障标注数据集    │  │ ...               │         │
    │  │ ...               │  │ ...               │         │
    │  └──────────────────┘  └──────────────────┘         │
    │  ...                                                │
    └─────────────────────────────────────────────────────┘

The three entry cards mirror the three real-world starting points:
fresh project, resume an existing DataForge project, or import a plain
image folder.  All three route through ``MainWindow._open_dataset`` /
``_create_project`` — auto-detect for the latter two means the user
never has to know which one applies.

Recent project cards are compact (≈220px tall) and lay out in a 2-col
grid so the page reads as a launchpad even on 1080p displays.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QMenu,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    Action,
    BodyLabel,
    CaptionLabel,
    FluentIcon as FIF,
    IconWidget,
    PushButton,
    RoundMenu,
    StrongBodyLabel,
    SubtitleLabel,
    TitleLabel,
    TransparentToolButton,
)

from core.project import ProjectSummary
from core.task_types import TASK_REGISTRY
from gui.theme import T


# Pretty-print the on-disk format string for card display.
_FMT_DISPLAY = {
    "labelme": "LabelMe",
    "yolo": "YOLO",
    "voc": "VOC",
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


def _next_action(s: ProjectSummary) -> tuple[str, str]:
    """Recommend the next stage and the matching intent key.

    Returns ``(label, intent)``.  ``intent`` is consumed by
    ``MainWindow._open_dataset`` to land the user on the right stage
    after the project loads — empty string falls back to the default
    (标注工作台).

    Priority order:
      1. Empty project (no images yet) → 导入新数据 → INBOX
      2. Pending annotation work → 继续标注 → ANNOTATE
      3. Review queue non-empty → 去审核 → REVIEW
      4. Items ready but no frozen version → 生成版本 → VERSIONS
      5. Frozen version exists → 去导出 → DELIVERY
      6. Default → 继续标注 → ANNOTATE
    """
    if not s.exists:
        return ("重新定位", "")
    if s.wf_total == 0:
        return ("导入数据", "inbox")
    if s.wf_new > 0 or s.wf_in_progress > 0:
        return ("继续标注", "annotate")
    if s.wf_review > 0:
        return ("去审核", "review")
    if s.wf_ready > 0:
        if s.version_count <= 0:
            return ("生成版本", "process")
        return ("去导出", "delivery")
    if s.version_count > 0:
        return ("去导出", "delivery")
    return ("继续标注", "annotate")


# ─────────────────────────────────────────────────────────────────────
# Top-level entry cards
# ─────────────────────────────────────────────────────────────────────

class _EntryCard(QFrame):
    """Large primary entry tile (新建 / 打开 / 普通数据集)."""

    clicked = pyqtSignal()

    def __init__(self, icon: FIF, title: str, body: str,
                 primary: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("welcomeEntryCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setProperty("primary", "true" if primary else "false")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(124)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(T.PAD_XL, T.PAD_LG, T.PAD_XL, T.PAD_LG)
        lay.setSpacing(T.GAP)

        icon_w = IconWidget(icon)
        icon_w.setFixedSize(20, 20)
        lay.addWidget(icon_w)

        title_lbl = StrongBodyLabel(title)
        title_lbl.setObjectName("welcomeEntryTitle")
        lay.addWidget(title_lbl)

        body_lbl = CaptionLabel(body)
        body_lbl.setObjectName("welcomeEntryBody")
        body_lbl.setWordWrap(True)
        lay.addWidget(body_lbl)

        lay.addStretch(1)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


# ─────────────────────────────────────────────────────────────────────
# Recent-project cards
# ─────────────────────────────────────────────────────────────────────

class _ProjectCard(QFrame):
    """Compact recent-project card — fits a 2-col grid at 1080p+."""

    # Payload: (root_path, intent).  ``intent`` is the stage key that
    # matches the recommended next action ("annotate" / "review" /
    # "delivery" / "inbox" / "" for default).  MainWindow routes the
    # post-open stage swap from this string.
    clicked = pyqtSignal(str, str)
    remove_requested = pyqtSignal(str)
    relocate_requested = pyqtSignal(str)
    # Delete the project's .dataforge/ metadata folder (project.json,
    # workflow, history, cache).  User images / labels stay untouched.
    delete_metadata_requested = pyqtSignal(str)

    def __init__(self, summary: ProjectSummary,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._root = str(summary.root_path)
        self._exists = summary.exists
        # Cache the recommended intent so card-body click + CTA-button
        # click both emit the same routing.
        _label, self._intent = _next_action(summary)
        self.setObjectName("projectCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setProperty("missing", "true" if not summary.exists else "false")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        if not summary.exists:
            self._build_missing(summary)
            return

        self.setMinimumHeight(100)
        self.setMaximumHeight(120)
        root = QVBoxLayout(self)
        root.setContentsMargins(T.PAD_XL, T.PAD_LG, T.PAD_XL, T.PAD_LG)
        root.setSpacing(T.GAP)

        # Row 1: title + kebab menu
        head = QHBoxLayout()
        head.setSpacing(T.GAP)
        title = StrongBodyLabel(summary.name)
        title.setObjectName("projectCardName")
        head.addWidget(title, 1)
        self._menu_btn = TransparentToolButton(FIF.MORE)
        self._menu_btn.setObjectName("projectCardMenu")
        self._menu_btn.setFixedSize(24, 24)
        self._menu_btn.clicked.connect(self._show_menu)
        head.addWidget(self._menu_btn)
        root.addLayout(head)

        # Row 2: minimal meta — count + classes, one line
        meta_parts: list[str] = []
        if summary.wf_total:
            meta_parts.append(f"{summary.wf_total:,} 张")
        if summary.class_count:
            meta_parts.append(f"{summary.class_count} 类")
        if summary.target_format:
            meta_parts.append(f"目标 {_format_label(summary.target_format)}")
        elif summary.annotation_format:
            meta_parts.append(
                f"主格式 {_format_label(summary.annotation_format)}")
        if summary.version_count:
            meta_parts.append(f"{summary.version_count} 个版本")
        if meta_parts:
            meta = CaptionLabel(" · ".join(meta_parts))
            meta.setObjectName("projectCardMeta")
            root.addWidget(meta)

        root.addStretch(1)

        # Row 3: prominent CTA — the only action the user needs
        cta_label, _intent = _next_action(summary)
        cta_row = QHBoxLayout()
        cta_row.addStretch(1)
        cta = PushButton(f"{cta_label} →")
        cta.setObjectName("projectCardCTA")
        cta.setFixedHeight(28)
        cta.clicked.connect(self._emit_clicked)
        cta_row.addWidget(cta)
        root.addLayout(cta_row)

    def _emit_clicked(self) -> None:
        """Emit the (path, intent) pair shared by the body + CTA paths."""
        self.clicked.emit(self._root, self._intent)

    def _build_missing(self, summary: ProjectSummary) -> None:
        """Compact greyed-out variant for entries whose dir is gone."""
        self.setMinimumHeight(64)
        self.setMaximumHeight(64)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(T.PAD_XL, T.GAP, T.PAD_LG, T.GAP)
        lay.setSpacing(T.GAP_LG)

        title = StrongBodyLabel(summary.name)
        title.setObjectName("projectCardName")
        lay.addWidget(title)
        gone = CaptionLabel("· 目录不存在")
        gone.setObjectName("hintWarn")
        lay.addWidget(gone)
        lay.addStretch(1)
        relocate = PushButton("重新定位")
        relocate.setFixedHeight(26)
        relocate.clicked.connect(
            lambda: self.relocate_requested.emit(self._root))
        lay.addWidget(relocate)
        remove = PushButton("移除")
        remove.setFixedHeight(26)
        remove.clicked.connect(
            lambda: self.remove_requested.emit(self._root))
        lay.addWidget(remove)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton and self._exists:
            child = self.childAt(event.pos())
            # CTA + relocate + remove + kebab buttons handle their own clicks.
            if child is not None and child.objectName() in (
                "projectCardCTA", "projectCardMenu",
            ):
                return super().mousePressEvent(event)
            # Direct hit on the kebab icon's child label / pixmap also
            # bubbles up; check ancestors so a click on the icon itself
            # doesn't open the project.
            anc = child
            while anc is not None:
                if anc is getattr(self, "_menu_btn", None):
                    return super().mousePressEvent(event)
                anc = anc.parentWidget()
            self._emit_clicked()
        super().mousePressEvent(event)

    def _show_menu(self) -> None:
        """Open the kebab menu anchored under the icon."""
        menu = RoundMenu(parent=self)
        if not self._exists:
            menu.addAction(Action(
                FIF.FOLDER, "重新定位…",
                triggered=lambda: self.relocate_requested.emit(self._root)))
            menu.addSeparator()
        menu.addAction(Action(
            FIF.CLOSE, "从列表移除",
            triggered=lambda: self.remove_requested.emit(self._root)))
        if self._exists:
            menu.addAction(Action(
                FIF.DELETE, "删除项目元信息",
                triggered=lambda: self.delete_metadata_requested.emit(
                    self._root)))
        pos = self._menu_btn.mapToGlobal(
            self._menu_btn.rect().bottomRight())
        menu.exec(pos)

    def contextMenuEvent(self, event) -> None:
        # Right-click stays as a power-user shortcut; reuses the same
        # menu shape as the kebab.
        menu = RoundMenu(parent=self)
        if not self._exists:
            menu.addAction(Action(
                FIF.FOLDER, "重新定位…",
                triggered=lambda: self.relocate_requested.emit(self._root)))
            menu.addSeparator()
        menu.addAction(Action(
            FIF.CLOSE, "从列表移除",
            triggered=lambda: self.remove_requested.emit(self._root)))
        if self._exists:
            menu.addAction(Action(
                FIF.DELETE, "删除项目元信息",
                triggered=lambda: self.delete_metadata_requested.emit(
                    self._root)))
        menu.exec(event.globalPos())


# ─────────────────────────────────────────────────────────────────────
# Page
# ─────────────────────────────────────────────────────────────────────

class DatasetWelcome(QWidget):
    """Project-launchpad home screen."""

    # Payload: ``(root_path, intent)``.  ``intent`` is empty string for
    # the file-picker entries (打开项目 / 打开普通数据集); recent-card
    # CTAs pass the stage key that matches the recommended next action.
    open_dataset = pyqtSignal(str, str)
    # (root, name, preset_id, task_type) — preset_id determines task_type
    # + caps for non-custom presets; task_type is only consulted under
    # the 自定义 preset where the user picks the task explicitly.
    create_project = pyqtSignal(str, str, str, object)

    # Two columns above ~960px viewport, single column below — set in
    # _layout_recent_grid based on the actual width on resize.
    _GRID_BREAKPOINT = 960
    # Cap the recents grid so the home page reads as a launchpad even
    # for users with many projects in the recent list. Overflow goes
    # behind a "查看全部 N 个项目" toggle.
    _RECENT_LIMIT = 6

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("datasetWelcome")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        body = QWidget()
        root = QVBoxLayout(body)
        root.setContentsMargins(
            T.PAD_3XL, T.PAD_2XL, T.PAD_3XL, T.PAD_2XL)
        root.setSpacing(T.PAD_XL)

        # Hero
        brand = TitleLabel("数据工坊 · DataForge")
        brand.setObjectName("welcomeBrand")
        tagline = CaptionLabel("从原始图片到可训练数据集 — 一个工具完成全流程")
        tagline.setObjectName("welcomeTagline")
        root.addWidget(brand)
        root.addWidget(tagline)
        root.addSpacing(T.GAP_LG)

        # Three entry cards
        entries = QHBoxLayout()
        entries.setSpacing(T.GAP_LG)
        self._entry_resume = _EntryCard(
            FIF.HISTORY, "继续最近项目",
            "恢复上次的 DataForge 项目与工作进度",
            primary=True)
        self._entry_resume.clicked.connect(self._on_resume_recent)
        self._entry_open = _EntryCard(
            FIF.FOLDER, "打开文件夹",
            "自动识别项目、数据集或图片目录")
        self._entry_open.clicked.connect(self._on_smart_open)
        self._entry_new = _EntryCard(
            FIF.ADD, "新建空项目",
            "先建项目壳，再导入图片")
        self._entry_new.clicked.connect(self._on_create_project)
        entries.addWidget(self._entry_resume, 1)
        entries.addWidget(self._entry_open, 1)
        entries.addWidget(self._entry_new, 1)
        root.addLayout(entries)

        # Recent projects header
        self._list_label = SubtitleLabel("最近项目")
        self._list_label.setObjectName("welcomeSectionTitle")
        root.addWidget(self._list_label)

        self._empty_hint = CaptionLabel(
            "尚无最近项目 — 点击上方"
            " 新建空项目 / 打开文件夹 开始"
        )
        self._empty_hint.setObjectName("welcomeEmptyHint")
        self._empty_hint.setWordWrap(True)
        self._empty_hint.hide()
        root.addWidget(self._empty_hint)

        # Recent project grid (2 columns above the breakpoint, 1 below).
        # Built fresh on every _load() so the column count tracks the
        # current viewport width.
        self._grid_host = QWidget()
        self._grid_host.setObjectName("welcomeGridHost")
        root.addWidget(self._grid_host)
        # Track the most recent summaries so resize re-layouts without
        # re-fetching disk state.
        self._summaries: list[ProjectSummary] = []
        # "查看全部 N 个项目" toggle — only shown when len(live) > limit.
        # When False the grid renders the first ``_RECENT_LIMIT``; True
        # renders all of them.  Lets the launchpad stay tight by
        # default while keeping the rest one click away.
        self._show_all: bool = False
        self._show_all_btn = PushButton("")
        self._show_all_btn.setObjectName("welcomeShowAllBtn")
        self._show_all_btn.setFixedHeight(32)
        self._show_all_btn.clicked.connect(self._toggle_show_all)
        self._show_all_btn.hide()
        show_all_row = QHBoxLayout()
        show_all_row.addStretch(1)
        show_all_row.addWidget(self._show_all_btn)
        show_all_row.addStretch(1)
        root.addLayout(show_all_row)

        # Missing-entries section, rendered below the grid as a tighter
        # secondary list. Built lazily so empty cases skip the header.
        self._missing_label = CaptionLabel("已失效项目")
        self._missing_label.setObjectName("welcomeSectionSubtitle")
        self._missing_label.hide()
        root.addWidget(self._missing_label)
        self._missing_lay = QVBoxLayout()
        self._missing_lay.setSpacing(T.GAP_XS)
        root.addLayout(self._missing_lay)

        root.addStretch(1)
        scroll.setWidget(body)
        self._scroll = scroll
        self._body = body

        self._load()

    # -- Public API --

    def refresh(self) -> None:
        self._load()

    # -- Internals --

    def resizeEvent(self, e):  # type: ignore[override]
        super().resizeEvent(e)
        self._layout_recent_grid()

    def _load(self) -> None:
        from core.project import list_known_projects
        self._summaries = list_known_projects()
        live = [s for s in self._summaries if s.exists]
        gone = [s for s in self._summaries if not s.exists]

        if live:
            self._list_label.setText(f"最近项目 · {len(live)}")
            self._list_label.show()
            self._empty_hint.hide()
        elif gone:
            self._list_label.hide()
            self._empty_hint.hide()
        else:
            self._list_label.hide()
            self._empty_hint.show()

        self._layout_recent_grid()

        # Show-all toggle visibility + label.  Hidden when there's no
        # overflow (≤ _RECENT_LIMIT live projects); otherwise reflects
        # the current expand/collapse state.
        overflow = max(0, len(live) - self._RECENT_LIMIT)
        if overflow == 0:
            self._show_all_btn.hide()
        else:
            self._show_all_btn.show()
            if self._show_all:
                self._show_all_btn.setText("收起")
            else:
                self._show_all_btn.setText(
                    f"查看全部 {len(live)} 个项目")

        # Missing entries — flat list under a small subtitle.
        while self._missing_lay.count():
            w = self._missing_lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        if gone:
            self._missing_label.show()
            for ps in gone:
                card = _ProjectCard(ps)
                card.remove_requested.connect(self._on_remove)
                card.relocate_requested.connect(self._on_relocate)
                card.delete_metadata_requested.connect(self._on_delete_metadata)
                self._missing_lay.addWidget(card)
        else:
            self._missing_label.hide()

    def _layout_recent_grid(self) -> None:
        """(Re-)build the live-projects grid against the current width."""
        # Tear down the old grid layout entirely — QLayout doesn't let
        # us swap column count on the fly cleanly.
        old_lay = self._grid_host.layout()
        if old_lay is not None:
            while old_lay.count():
                w = old_lay.takeAt(0).widget()
                if w:
                    w.deleteLater()
            QWidget().setLayout(old_lay)

        live = [s for s in self._summaries if s.exists]
        if not live:
            self._grid_host.setVisible(False)
            return
        self._grid_host.setVisible(True)

        # Honour the show-all toggle: collapsed = first _RECENT_LIMIT,
        # expanded = full list.  Live ordering is most-recent-first
        # (recent.json append order), so the cap surfaces the projects
        # the user is most likely to come back to.
        if not self._show_all:
            live = live[: self._RECENT_LIMIT]

        cols = 2 if self.width() >= self._GRID_BREAKPOINT else 1
        grid = QGridLayout(self._grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(T.GAP_LG)
        grid.setVerticalSpacing(T.GAP_LG)
        for c in range(cols):
            grid.setColumnStretch(c, 1)

        for i, ps in enumerate(live):
            card = _ProjectCard(ps)
            card.clicked.connect(self.open_dataset.emit)
            card.remove_requested.connect(self._on_remove)
            card.relocate_requested.connect(self._on_relocate)
            grid.addWidget(card, i // cols, i % cols)

    def _toggle_show_all(self) -> None:
        """Flip between collapsed (first _RECENT_LIMIT) and full grid."""
        self._show_all = not self._show_all
        self._load()

    def _on_create_project(self) -> None:
        from gui.dialogs.project_dialogs import CreateProjectDialog
        dlg = CreateProjectDialog(self.window())
        if not dlg.exec():
            return
        root = dlg.root_path()
        if root is None:
            return
        self.create_project.emit(
            str(root), dlg.project_name(),
            dlg.selected_preset_id(), dlg.selected_task_type())

    def _on_resume_recent(self) -> None:
        """继续最近项目 — open the most recent project directly.

        If there are recent projects, open the first one.
        Otherwise fall back to folder picker.
        """
        from core.recent import load_recent
        recent = load_recent()
        if recent:
            first = recent[0]
            if Path(first).is_dir():
                self.open_dataset.emit(first, "overview")
                return
        # No valid recent — fall back to smart open
        self._on_smart_open()

    def _on_smart_open(self) -> None:
        """打开文件夹 — system auto-detects what the directory is.

        Detection logic:
        1. Has .dataforge/project.json → open as DataForge project
        2. Has <category>/images/ structure → dataset, create project
        3. Contains images directly → open with inbox intent for import
        """
        from PyQt6.QtWidgets import QFileDialog
        d = QFileDialog.getExistingDirectory(
            self, "选择文件夹", str(Path.home()))
        if not d:
            return
        root = Path(d)

        # Case 1: existing DataForge project
        if (root / ".dataforge" / "project.json").is_file():
            self.open_dataset.emit(d, "overview")
            return

        # Case 2: looks like a structured dataset (has <sub>/images/)
        has_structure = any(
            (sub / "images").is_dir()
            for sub in root.iterdir()
            if sub.is_dir() and not sub.name.startswith(".")
        )
        if has_structure:
            from qfluentwidgets import InfoBar, InfoBarPosition
            InfoBar.info(
                "检测到数据集结构",
                "已识别为标准数据集目录，将创建项目并开始管理",
                parent=self.window(), duration=3000,
                position=InfoBarPosition.TOP)
            self.open_dataset.emit(d, "overview")
            return

        # Case 3: plain directory — open normally, land on inbox
        self.open_dataset.emit(d, "inbox")

    def _on_remove(self, path_str: str) -> None:
        import json
        from core.recent import RECENT_PATH, load_recent
        recent = [p for p in load_recent() if p != path_str]
        try:
            RECENT_PATH.write_text(
                json.dumps(recent, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass
        self._load()

    def _on_relocate(self, old_path: str) -> None:
        from PyQt6.QtWidgets import QFileDialog
        from core.recent import relocate
        start = (str(Path(old_path).parent)
                 if Path(old_path).parent.exists() else str(Path.home()))
        new_path = QFileDialog.getExistingDirectory(
            self, f"为 {Path(old_path).name} 选择新位置", start)
        if not new_path:
            return
        relocate(old_path, new_path)
        self._load()

    def _on_delete_metadata(self, path_str: str) -> None:
        """Delete the project's .dataforge/ folder after confirm.

        Images / labels in the project root stay intact — only the
        DataForge-managed metadata (project.json, workflow, history,
        cache) goes.  The recent-list entry is dropped at the same
        time since the project no longer exists from DataForge's view.
        """
        from qfluentwidgets import InfoBar, InfoBarPosition, MessageBox

        root = Path(path_str)
        meta = root / ".dataforge"
        if not meta.is_dir():
            # Nothing to delete — just remove from recents to clean up.
            self._on_remove(path_str)
            return
        box = MessageBox(
            "删除项目元信息",
            f"将删除 {root.name} 的 .dataforge/ 文件夹（项目配置、工作流、历史、缓存）。\n"
            f"图片与标注文件不受影响。该操作不可撤销。",
            self.window(),
        )
        box.yesButton.setText("删除")
        box.cancelButton.setText("取消")
        if not box.exec():
            return
        import shutil
        try:
            shutil.rmtree(meta)
        except OSError as e:
            InfoBar.error(
                "删除失败", str(e),
                parent=self.window(), duration=4000,
                position=InfoBarPosition.TOP,
            )
            return
        # Drop from recent + repaint.
        self._on_remove(path_str)
        InfoBar.success(
            "已删除", f"{root.name} · .dataforge/",
            parent=self.window(), duration=2500,
            position=InfoBarPosition.TOP,
        )
