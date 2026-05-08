"""项目设置 hub — project configuration and project-mutating operations.

Sections::

    [ 项目元信息 ]   name · task · format · class count
    [ 类别管理 ]    per-class row with rename / merge / split popup
    [ 数据集预设 ]  task preset / default workflow
    [ 主格式 ]      migrate primary annotation format
    [ 历史记录 ]    "打开历史" button (audit log)

Class-management actions fire ``rename_category_requested`` /
``merge_category_requested`` / ``split_category_requested`` (with the
category name) — the shell forwards each into the existing
:class:`BrowserView` rename / merge / split methods so the dialogs that
already work on the catalog right-click context menu are reused
unchanged.

The action surface gates on "dataset loaded with images" via
:meth:`set_actions_enabled`.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    Action,
    BodyLabel,
    CaptionLabel,
    FluentIcon as FIF,
    PushButton,
    RoundMenu,
    StrongBodyLabel,
    TransparentToolButton,
)

from core.task_types import TASK_REGISTRY
from gui import i18n
from gui.theme import T


_RECORDS_SPECS: list[tuple[str, FIF, str]] = [
    ("history", FIF.HISTORY, "tools.history"),
]

_PRIMARY_FORMAT_SPECS: list[tuple[str, FIF, str]] = [
    ("migrate_format", FIF.SYNC, "delivery.migrate.cta"),
]

class _ClassRow(QFrame):
    """One row in the 类别管理 list — name + count + action menu."""

    rename_requested = pyqtSignal(str)
    merge_requested = pyqtSignal(str)
    split_requested = pyqtSignal(str)

    def __init__(self, name: str, count: int,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._name = name
        self.setObjectName("manageClassRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(36)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(T.PAD_LG, 0, T.GAP, 0)
        lay.setSpacing(T.GAP)

        name_lbl = BodyLabel(name)
        name_lbl.setObjectName("manageClassRowName")
        lay.addWidget(name_lbl, 1)

        count_lbl = CaptionLabel(
            i18n.t("manage.classes.count_suffix", n=count))
        count_lbl.setObjectName("manageClassRowCount")
        lay.addWidget(count_lbl)

        self._menu_btn = TransparentToolButton(FIF.MORE)
        self._menu_btn.setToolTip(i18n.t("manage.classes.menu"))
        self._menu_btn.clicked.connect(self._show_menu)
        lay.addWidget(self._menu_btn)

    def setEnabled(self, enabled: bool) -> None:  # type: ignore[override]
        super().setEnabled(enabled)
        self._menu_btn.setEnabled(enabled)

    def _show_menu(self) -> None:
        menu = RoundMenu(parent=self)
        menu.addAction(Action(
            FIF.EDIT, i18n.t("manage.classes.rename"),
            triggered=lambda: self.rename_requested.emit(self._name)))
        menu.addAction(Action(
            FIF.LINK, i18n.t("manage.classes.merge"),
            triggered=lambda: self.merge_requested.emit(self._name)))
        menu.addAction(Action(
            FIF.IOT, i18n.t("manage.classes.split"),
            triggered=lambda: self.split_requested.emit(self._name)))
        # Anchor the menu just below the menu button.
        pos = self._menu_btn.mapToGlobal(
            self._menu_btn.rect().bottomRight())
        menu.exec(pos)


class ProjectManageHub(QFrame):
    """项目设置 stage body — config plus project-mutating operations."""

    # -- History --
    history_requested = pyqtSignal()
    # -- Project format operation --
    migrate_format_requested = pyqtSignal()
    # -- Preset --
    change_preset_requested = pyqtSignal()
    # -- Class management — payload is the source category name --
    rename_category_requested = pyqtSignal(str)
    merge_category_requested = pyqtSignal(str)
    split_category_requested = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("projectManageHub")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root.addWidget(self._scroll)
        scroll = self._scroll  # local alias for the rest of __init__

        inner = QWidget()
        inner_lay = QVBoxLayout(inner)
        inner_lay.setContentsMargins(
            T.PAD_2XL, T.PAD_XL, T.PAD_2XL, T.PAD_XL)
        inner_lay.setSpacing(T.GAP_LG)

        # Tracked for retranslate without rebuilding the tree.
        self._section_titles: list[tuple[StrongBodyLabel, str]] = []
        # kind → (button, label_key) for project/action buttons.
        self._buttons: dict[str, tuple[PushButton, str]] = {}
        # Class rows live in a child VBox we rebuild on every dataset
        # change; keep the layout reference around for tear-down.
        self._classes_lay: QVBoxLayout | None = None
        self._classes_count_label: CaptionLabel | None = None
        self._classes_empty_label: CaptionLabel | None = None
        # Whether the action surface is currently enabled — kept around
        # so class rows added on a late dataset_changed signal can pick
        # up the right initial state.
        self._actions_enabled: bool = False

        # -- 项目元信息 --
        # Static value labels — populated by set_project.
        self._meta_name = BodyLabel("—")
        self._meta_task = BodyLabel("—")
        self._meta_format = BodyLabel("—")
        self._meta_classes = BodyLabel("—")
        self._meta_keys: list[tuple[CaptionLabel, str]] = []

        primary_format_signals = {
            "migrate_format": self.migrate_format_requested,
        }
        record_signals = {"history": self.history_requested}

        inner_lay.addWidget(self._build_meta_section())
        inner_lay.addWidget(self._build_classes_section())
        inner_lay.addWidget(self._build_preset_section())
        inner_lay.addWidget(
            self._build_button_section(
                "hub.section.primary_format",
                _PRIMARY_FORMAT_SPECS,
                primary_format_signals))
        inner_lay.addWidget(
            self._build_button_section(
                "hub.section.records", _RECORDS_SPECS, record_signals))
        inner_lay.addStretch(1)
        scroll.setWidget(inner)

        i18n.bus.language_changed.connect(self._retranslate)

    # ════════════════════════════════════════════════════════════════
    # Public API
    # ════════════════════════════════════════════════════════════════

    def set_actions_enabled(self, enabled: bool) -> None:
        """Gate the history button + every class-row action menu."""
        self._actions_enabled = enabled
        for _kind, (btn, _key) in self._buttons.items():
            btn.setEnabled(enabled)
        if self._classes_lay is not None:
            for i in range(self._classes_lay.count()):
                w = self._classes_lay.itemAt(i).widget()
                if isinstance(w, _ClassRow):
                    w.setEnabled(enabled)

    def set_project(self, project) -> None:
        """Populate meta strip + preset display."""
        # -- Meta strip --
        if project is None:
            empty = i18n.t("hub.meta.empty")
            self._meta_name.setText(empty)
            self._meta_task.setText("—")
            self._meta_format.setText("—")
            self._meta_classes.setText("—")
        else:
            name = getattr(project, "name", "") or "—"
            task_type = getattr(project, "task_type", None)
            if task_type is not None and task_type in TASK_REGISTRY:
                task_label = TASK_REGISTRY[task_type].display_name
            else:
                task_label = str(task_type or "—")
            fmt = getattr(project, "annotation_format", "") or "—"
            classes = getattr(project, "class_names", []) or []
            self._meta_name.setText(name)
            self._meta_task.setText(task_label)
            self._meta_format.setText(
                fmt.upper() if fmt and fmt != "—" else "—")
            self._meta_classes.setText(str(len(classes)))

        # -- Preset display + caps gate --
        self._refresh_preset_display(project)

    def _refresh_preset_display(self, project) -> None:
        """Push the project's preset name + description into the preset card."""
        from core.annotation_preset import preset_by_id

        if not hasattr(self, "_preset_name_label"):
            return
        if project is None:
            self._preset_name_label.setText("—")
            self._preset_desc_label.setText("")
            self._preset_change_btn.setEnabled(False)
            return
        pid = getattr(project, "preset_id", "")
        preset = preset_by_id(pid)
        if preset is not None:
            self._preset_name_label.setText(preset.display_name)
            self._preset_desc_label.setText(preset.description)
        else:
            self._preset_name_label.setText("自定义")
            self._preset_desc_label.setText(
                "自定义任务预设；大模型标注字段在标注页始终可用")
        self._preset_change_btn.setEnabled(True)

    def set_dataset(self, dataset) -> None:
        """Rebuild the class-management list from the active dataset."""
        if self._classes_lay is None:
            return

        # Tear down prior rows.
        while self._classes_lay.count():
            item = self._classes_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        cats = list(getattr(dataset, "categories", []) or []) \
            if dataset is not None else []
        # Sort by image count (matches CatalogPanel default).
        cats = sorted(cats, key=lambda c: c.image_count, reverse=True)

        if not cats:
            empty = CaptionLabel(i18n.t("manage.classes.empty"))
            empty.setObjectName("manageClassesEmpty")
            empty.setWordWrap(True)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._classes_lay.addWidget(empty)
            self._classes_empty_label = empty
        else:
            self._classes_empty_label = None
            for cat in cats:
                row = _ClassRow(cat.name, cat.image_count)
                row.setEnabled(self._actions_enabled)
                row.rename_requested.connect(
                    self.rename_category_requested.emit)
                row.merge_requested.connect(
                    self.merge_category_requested.emit)
                row.split_requested.connect(
                    self.split_category_requested.emit)
                self._classes_lay.addWidget(row)

        if self._classes_count_label is not None:
            self._classes_count_label.setText(
                i18n.t("manage.classes.count_suffix", n=len(cats))
                if cats else ""
            )

    # ════════════════════════════════════════════════════════════════
    # Section builders
    # ════════════════════════════════════════════════════════════════

    def _build_meta_section(self) -> QFrame:
        card = QFrame()
        card.setObjectName("chartFrame")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(T.PAD_XL, T.PAD_LG, T.PAD_XL, T.PAD_LG)
        lay.setSpacing(T.GAP_LG)

        title = StrongBodyLabel(i18n.t("hub.section.meta"))
        title.setObjectName("hubSectionTitle")
        lay.addWidget(title)
        self._section_titles.append((title, "hub.section.meta"))

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(T.PAD_XL)
        grid.setVerticalSpacing(T.GAP)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)

        rows = [
            ("hub.meta.name",    self._meta_name),
            ("hub.meta.task",    self._meta_task),
            ("hub.meta.format",  self._meta_format),
            ("hub.meta.classes", self._meta_classes),
        ]
        for r, (key, value_lbl) in enumerate(rows):
            key_lbl = CaptionLabel(i18n.t(key))
            key_lbl.setObjectName("hubMetaKey")
            grid.addWidget(key_lbl, r, 0, Qt.AlignmentFlag.AlignLeft)
            value_lbl.setObjectName("hubMetaValue")
            grid.addWidget(value_lbl, r, 1, Qt.AlignmentFlag.AlignLeft)
            self._meta_keys.append((key_lbl, key))

        lay.addLayout(grid)
        return card

    def _build_classes_section(self) -> QFrame:
        card = QFrame()
        card.setObjectName("chartFrame")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(T.PAD_XL, T.PAD_LG, T.PAD_XL, T.PAD_LG)
        lay.setSpacing(T.GAP)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(T.GAP)
        title = StrongBodyLabel(i18n.t("hub.section.classes"))
        title.setObjectName("hubSectionTitle")
        head.addWidget(title)
        head.addStretch(1)
        # Row count badge — set lazily on dataset binding.
        count = CaptionLabel("")
        count.setObjectName("manageClassesCount")
        head.addWidget(count)
        lay.addLayout(head)
        self._section_titles.append((title, "hub.section.classes"))
        self._classes_count_label = count

        # Cap the list at ~280px and let it scroll internally so very
        # tall projects don't push the rest of the page off-screen.
        list_host = QWidget()
        list_lay = QVBoxLayout(list_host)
        list_lay.setContentsMargins(0, 0, 0, 0)
        list_lay.setSpacing(T.GAP_XS)
        self._classes_lay = list_lay

        scroll = QScrollArea()
        scroll.setObjectName("manageClassesScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMinimumHeight(120)
        scroll.setMaximumHeight(280)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(list_host)
        lay.addWidget(scroll)

        # Seed an empty placeholder so the section reads as built-but-
        # waiting before the first dataset_changed fires.
        empty = CaptionLabel(i18n.t("manage.classes.empty"))
        empty.setObjectName("manageClassesEmpty")
        empty.setWordWrap(True)
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        list_lay.addWidget(empty)
        self._classes_empty_label = empty

        return card

    def _build_preset_section(self) -> QFrame:
        """Primary preset display — name + description + 更改预设 button."""
        card = QFrame()
        card.setObjectName("chartFrame")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._capabilities_card = card

        lay = QVBoxLayout(card)
        lay.setContentsMargins(T.PAD_XL, T.PAD_LG, T.PAD_XL, T.PAD_LG)
        lay.setSpacing(T.GAP)

        title = StrongBodyLabel(i18n.t("hub.section.preset"))
        title.setObjectName("hubSectionTitle")
        lay.addWidget(title)
        self._section_titles.append((title, "hub.section.preset"))

        # Name + description — populated by _refresh_preset_display.
        name_row = QHBoxLayout()
        name_row.setContentsMargins(0, 0, 0, 0)
        name_row.setSpacing(T.GAP)
        self._preset_name_label = StrongBodyLabel("—")
        self._preset_name_label.setObjectName("hubMetaValue")
        name_row.addWidget(self._preset_name_label)
        name_row.addStretch(1)
        self._preset_change_btn = PushButton(i18n.t("manage.preset.change"))
        self._preset_change_btn.setIcon(FIF.SYNC)
        self._preset_change_btn.setFixedHeight(T.CONTROL_HEIGHT)
        self._preset_change_btn.setEnabled(False)
        self._preset_change_btn.clicked.connect(
            self.change_preset_requested.emit)
        name_row.addWidget(self._preset_change_btn)
        lay.addLayout(name_row)

        self._preset_desc_label = CaptionLabel("")
        self._preset_desc_label.setObjectName("manageCapsHint")
        self._preset_desc_label.setWordWrap(True)
        lay.addWidget(self._preset_desc_label)

        return card

    def _build_button_section(
        self,
        title_key: str,
        button_specs: list[tuple[str, FIF, str]],
        kind_to_signal: dict,
    ) -> QFrame:
        card = QFrame()
        card.setObjectName("chartFrame")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(T.PAD_XL, T.PAD_LG, T.PAD_XL, T.PAD_LG)
        lay.setSpacing(T.GAP)

        title = StrongBodyLabel(i18n.t(title_key))
        title.setObjectName("hubSectionTitle")
        lay.addWidget(title)
        self._section_titles.append((title, title_key))

        for kind, icon, label_key in button_specs:
            btn = PushButton(i18n.t(label_key))
            btn.setIcon(icon)
            btn.setFixedHeight(T.CONTROL_HEIGHT)
            btn.setEnabled(False)
            signal = kind_to_signal[kind]
            btn.clicked.connect(signal.emit)
            lay.addWidget(btn)
            self._buttons[kind] = (btn, label_key)

        return card

    # ════════════════════════════════════════════════════════════════
    # Internals
    # ════════════════════════════════════════════════════════════════

    def _retranslate(self, _lang: str) -> None:
        for lbl, key in self._section_titles:
            lbl.setText(i18n.t(key))
        for lbl, key in self._meta_keys:
            lbl.setText(i18n.t(key))
        for _kind, (btn, key) in self._buttons.items():
            btn.setText(i18n.t(key))
        if hasattr(self, "_preset_change_btn"):
            self._preset_change_btn.setText(i18n.t("manage.preset.change"))
        if self._classes_empty_label is not None:
            self._classes_empty_label.setText(i18n.t("manage.classes.empty"))
