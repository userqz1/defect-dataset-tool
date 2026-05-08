"""数据处理 hub — project-mutating data operations.

This stage owns operations that change images, annotations, or generated
labels. It is intentionally separate from Project Settings (configuration)
and Export (read-only/copy deliverables).
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget,
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

from gui import i18n
from gui.theme import T
from gui.widgets.scope_badge import Scope, ScopeBadge


_PROCESS_SPECS: list[tuple[str, FIF, str]] = [
    ("resize",  FIF.ZOOM,   "delivery.process.resize"),
    ("crop",    FIF.CUT,    "delivery.process.crop"),
    ("rotate",  FIF.ROTATE, "delivery.process.rotate"),
    ("flip",    FIF.IOT,    "delivery.process.flip"),
    ("convert", FIF.PHOTO,  "delivery.process.convert"),
    ("augment", FIF.ADD,    "delivery.process.augment"),
    ("predict", FIF.ROBOT,  "delivery.process.predict"),
]

_CLASS_LIST_MAX_HEIGHT = 280


class _ProcessCard(QFrame):
    """One process section with a title, scope badge and button list."""

    def __init__(
        self,
        title_key: str,
        badge_key: str,
        badge_scope: Scope,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("chartFrame")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        root = QVBoxLayout(self)
        root.setContentsMargins(T.PAD_XL, T.PAD_LG, T.PAD_XL, T.PAD_LG)
        root.setSpacing(T.GAP)

        head = QHBoxLayout()
        title = StrongBodyLabel(i18n.t(title_key))
        title.setObjectName("hubSectionTitle")
        head.addWidget(title)
        head.addStretch(1)
        badge = ScopeBadge(i18n.t(badge_key), badge_scope)
        head.addWidget(badge)
        root.addLayout(head)

        self._title = title
        self._title_key = title_key
        self._badge = badge
        self._badge_key = badge_key
        self._buttons: list[tuple[PushButton, str]] = []

        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(T.GAP_XS)
        root.addLayout(self.body)

    def add_button(self, icon: FIF, label_key: str, signal) -> PushButton:
        btn = PushButton(i18n.t(label_key))
        btn.setIcon(icon)
        btn.setFixedHeight(T.CONTROL_HEIGHT)
        btn.setEnabled(False)
        btn.clicked.connect(signal.emit)
        self.body.addWidget(btn)
        self._buttons.append((btn, label_key))
        return btn

    def add_button_grid(
        self,
        specs: list[tuple[FIF, str, object]],
        cols: int = 2,
    ) -> None:
        container = QWidget()
        grid = QGridLayout(container)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(T.GAP)
        for idx, (icon, label_key, sig) in enumerate(specs):
            btn = PushButton(i18n.t(label_key))
            btn.setIcon(icon)
            btn.setFixedHeight(T.CONTROL_HEIGHT)
            btn.setEnabled(False)
            btn.clicked.connect(sig.emit)
            self._buttons.append((btn, label_key))
            grid.addWidget(btn, idx // cols, idx % cols)
        self.body.addWidget(container)

    def set_actions_enabled(self, enabled: bool) -> None:
        for btn, _key in self._buttons:
            btn.setEnabled(enabled)

    def retranslate(self) -> None:
        self._title.setText(i18n.t(self._title_key))
        self._badge.setText(i18n.t(self._badge_key))
        for btn, key in self._buttons:
            btn.setText(i18n.t(key))


class _ClassRow(QFrame):
    """One category row with a small action menu."""

    rename_requested = pyqtSignal(str)
    merge_requested = pyqtSignal(str)
    split_requested = pyqtSignal(str)

    def __init__(self, name: str, count: int,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._name = name
        self.setObjectName("manageClassRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(T.CONTROL_HEIGHT)

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
        pos = self._menu_btn.mapToGlobal(
            self._menu_btn.rect().bottomRight())
        menu.exec(pos)


class _ClassCard(QFrame):
    """Category-management section for data-processing operations."""

    rename_requested = pyqtSignal(str)
    merge_requested = pyqtSignal(str)
    split_requested = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chartFrame")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._actions_enabled = False

        root = QVBoxLayout(self)
        root.setContentsMargins(T.PAD_XL, T.PAD_LG, T.PAD_XL, T.PAD_LG)
        root.setSpacing(T.GAP)

        head = QHBoxLayout()
        self._title = StrongBodyLabel(i18n.t("hub.section.classes"))
        self._title.setObjectName("hubSectionTitle")
        head.addWidget(self._title)
        head.addStretch(1)
        self._count = CaptionLabel("")
        self._count.setObjectName("manageClassesCount")
        head.addWidget(self._count)
        root.addLayout(head)

        self._hint = CaptionLabel(i18n.t("process.classes.note"))
        self._hint.setObjectName("taskCardKey")
        self._hint.setWordWrap(True)
        root.addWidget(self._hint)

        scroller = QScrollArea()
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QFrame.Shape.NoFrame)
        scroller.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroller.setMaximumHeight(_CLASS_LIST_MAX_HEIGHT)
        root.addWidget(scroller)

        inner = QWidget()
        self._rows_lay = QVBoxLayout(inner)
        self._rows_lay.setContentsMargins(0, 0, 0, 0)
        self._rows_lay.setSpacing(T.GAP_XS)
        scroller.setWidget(inner)

    def set_actions_enabled(self, enabled: bool) -> None:
        self._actions_enabled = enabled
        for i in range(self._rows_lay.count()):
            w = self._rows_lay.itemAt(i).widget()
            if isinstance(w, _ClassRow):
                w.setEnabled(enabled)

    def set_dataset(self, dataset) -> None:
        while self._rows_lay.count():
            item = self._rows_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        cats = list(getattr(dataset, "categories", []) or []) \
            if dataset is not None else []
        cats = sorted(cats, key=lambda c: c.image_count, reverse=True)
        self._count.setText(
            i18n.t("manage.classes.count_suffix", n=len(cats))
            if cats else ""
        )

        if not cats:
            empty = CaptionLabel(i18n.t("manage.classes.empty"))
            empty.setObjectName("manageClassesEmpty")
            empty.setWordWrap(True)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._rows_lay.addWidget(empty)
            return

        for cat in cats:
            row = _ClassRow(cat.name, cat.image_count)
            row.setEnabled(self._actions_enabled)
            row.rename_requested.connect(self.rename_requested.emit)
            row.merge_requested.connect(self.merge_requested.emit)
            row.split_requested.connect(self.split_requested.emit)
            self._rows_lay.addWidget(row)
        self._rows_lay.addStretch(1)

    def retranslate(self) -> None:
        self._title.setText(i18n.t("hub.section.classes"))
        self._hint.setText(i18n.t("process.classes.note"))


class DataProcessHub(QFrame):
    """数据处理 stage body — import labels + batch data operations."""

    import_annot_requested = pyqtSignal()
    migrate_format_requested = pyqtSignal()
    rename_category_requested = pyqtSignal(str)
    merge_category_requested = pyqtSignal(str)
    split_category_requested = pyqtSignal(str)
    resize_requested = pyqtSignal()
    crop_requested = pyqtSignal()
    rotate_requested = pyqtSignal()
    flip_requested = pyqtSignal()
    convert_requested = pyqtSignal()
    augment_requested = pyqtSignal()
    predict_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("dataProcessHub")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root.addWidget(scroll)

        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(T.PAD_2XL, T.PAD_XL, T.PAD_2XL, T.PAD_XL)
        lay.setSpacing(T.GAP_LG)

        self._cards: list[_ProcessCard] = []

        annot_card = _ProcessCard(
            "process.section.annot",
            "scope.writes_labels",
            Scope.WRITES,
        )
        annot_card.add_button_grid([
            (FIF.FOLDER, "delivery.import.cta", self.import_annot_requested),
            (FIF.SYNC, "delivery.migrate.cta", self.migrate_format_requested),
        ])
        lay.addWidget(annot_card)
        self._cards.append(annot_card)

        self._class_card = _ClassCard()
        self._class_card.rename_requested.connect(
            self.rename_category_requested.emit)
        self._class_card.merge_requested.connect(
            self.merge_category_requested.emit)
        self._class_card.split_requested.connect(
            self.split_category_requested.emit)
        lay.addWidget(self._class_card)

        batch_card = _ProcessCard(
            "process.section.batch",
            "scope.writes_images",
            Scope.WRITES,
        )
        kind_to_signal = {
            "resize":  self.resize_requested,
            "crop":    self.crop_requested,
            "rotate":  self.rotate_requested,
            "flip":    self.flip_requested,
            "convert": self.convert_requested,
            "augment": self.augment_requested,
            "predict": self.predict_requested,
        }
        batch_card.add_button_grid([
            (icon, key, kind_to_signal[kind])
            for kind, icon, key in _PROCESS_SPECS
        ])
        lay.addWidget(batch_card)
        self._cards.append(batch_card)

        note = CaptionLabel(i18n.t("process.note"))
        note.setObjectName("taskCardKey")
        note.setWordWrap(True)
        lay.addWidget(note)
        self._note = note

        lay.addStretch(1)
        scroll.setWidget(inner)

        i18n.bus.language_changed.connect(self._retranslate)

    def set_actions_enabled(self, enabled: bool) -> None:
        for card in self._cards:
            card.set_actions_enabled(enabled)
        self._class_card.set_actions_enabled(enabled)

    def set_dataset(self, dataset) -> None:
        self._class_card.set_dataset(dataset)

    def _retranslate(self, _lang: str) -> None:
        for card in self._cards:
            card.retranslate()
        self._class_card.retranslate()
        self._note.setText(i18n.t("process.note"))
