"""Delivery hub — target-format-first delivery surface.

The delivery page is intentionally downstream of annotation and dataset
versioning. Once a project has a target format, this page should not ask the
user to choose from every export format again. It highlights the current
target format, shows matching frozen versions, and keeps conversion as a
secondary utility.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    FluentIcon as FIF,
    PrimaryPushButton,
    PushButton,
    StrongBodyLabel,
)

from gui import i18n
from gui.theme import T
from gui.widgets.scope_badge import Scope, ScopeBadge


def _schema_display_name(target_format: str) -> str:
    """Return a user-facing target-format name."""
    if not target_format:
        return "—"
    try:
        from core.target_readiness import schema_key_for_target_format
        from core.schema import get
        schema = get(schema_key_for_target_format(target_format))
        if schema is not None:
            return schema.display_name
    except Exception:
        pass
    return target_format


def _version_meta(version) -> str:
    fmt = str(getattr(version, "fmt", "") or "—").upper()
    created = str(getattr(version, "created_at", "") or "—").replace("T", " ")
    return i18n.t(
        "tv.history.meta",
        fmt=fmt,
        samples=f"{int(getattr(version, 'sample_count', 0)):,}",
        train=int(getattr(version, "train_count", 0)),
        val=int(getattr(version, "val_count", 0)),
        test=int(getattr(version, "test_count", 0)),
        created=created,
    )


class _TaskCard(QFrame):
    """Secondary utility card."""

    def __init__(
        self,
        title_key: str,
        scope_key: str,
        input_key: str,
        output_key: str,
        cta_key: str,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("taskCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        root = QVBoxLayout(self)
        root.setContentsMargins(T.PAD_XL, T.PAD_LG, T.PAD_XL, T.PAD_LG)
        root.setSpacing(T.GAP)

        self._i18n_refs: list[tuple[QWidget, str]] = []

        head = QHBoxLayout()
        title = StrongBodyLabel(i18n.t(title_key))
        title.setObjectName("taskCardTitle")
        head.addWidget(title)
        self._i18n_refs.append((title, title_key))
        head.addStretch(1)
        badge = ScopeBadge(i18n.t("scope.readonly"), Scope.READONLY)
        head.addWidget(badge)
        self._i18n_refs.append((badge, "scope.readonly"))
        root.addLayout(head)

        for key_i18n, val_i18n in (
            ("task.scope", scope_key),
            ("task.input", input_key),
            ("task.output", output_key),
        ):
            row = QHBoxLayout()
            row.setSpacing(T.GAP)
            key = CaptionLabel(i18n.t(key_i18n))
            key.setObjectName("taskCardKey")
            key.setFixedWidth(72)
            row.addWidget(key, 0, Qt.AlignmentFlag.AlignTop)
            value = CaptionLabel(i18n.t(val_i18n))
            value.setObjectName("taskCardValue")
            value.setWordWrap(True)
            row.addWidget(value, 1)
            self._i18n_refs.append((key, key_i18n))
            self._i18n_refs.append((value, val_i18n))
            root.addLayout(row)

        cta_row = QHBoxLayout()
        cta_row.addStretch(1)
        self._cta = PushButton(i18n.t(cta_key))
        self._cta.setFixedHeight(32)
        self._cta.setEnabled(False)
        cta_row.addWidget(self._cta)
        self._i18n_refs.append((self._cta, cta_key))
        root.addLayout(cta_row)

    @property
    def cta(self) -> PushButton:
        return self._cta

    def retranslate(self) -> None:
        for widget, key in self._i18n_refs:
            widget.setText(i18n.t(key))


class _DeliveryVersionRow(QFrame):
    """One legacy generated version — open to inspect, delete to reclaim space."""

    open_requested = pyqtSignal(str)
    delete_requested = pyqtSignal(str)

    def __init__(self, version, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("tvVersionRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._version = version
        self._path = str(getattr(version, "path", ""))

        root = QHBoxLayout(self)
        root.setContentsMargins(T.PAD_LG, T.PAD, T.PAD_LG, T.PAD)
        root.setSpacing(T.GAP)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(T.GAP_XS)
        self._name = StrongBodyLabel(str(getattr(version, "name", "")))
        self._name.setObjectName("tvVersionName")
        self._meta = CaptionLabel("")
        self._meta.setObjectName("tvVersionMeta")
        text_col.addWidget(self._name)
        text_col.addWidget(self._meta)
        root.addLayout(text_col, 1)

        self._open_btn = PushButton()
        self._open_btn.setIcon(FIF.FOLDER)
        self._open_btn.setFixedHeight(T.CONTROL_HEIGHT)
        self._open_btn.clicked.connect(
            lambda: self.open_requested.emit(self._path))
        root.addWidget(self._open_btn)

        self._delete_btn = PushButton()
        self._delete_btn.setIcon(FIF.DELETE)
        self._delete_btn.setFixedHeight(T.CONTROL_HEIGHT)
        self._delete_btn.clicked.connect(
            lambda: self.delete_requested.emit(self._path))
        root.addWidget(self._delete_btn)

        self.retranslate()

    def set_actions_enabled(self, enabled: bool) -> None:
        self._open_btn.setEnabled(enabled)
        self._delete_btn.setEnabled(enabled)

    def retranslate(self) -> None:
        self._meta.setText(_version_meta(self._version))
        self._open_btn.setText(i18n.t("delivery.version.open"))
        self._delete_btn.setText(i18n.t("delivery.version.delete"))


class _TargetDeliveryCard(QFrame):
    """Primary card: export the current project's target format directly."""

    export_requested = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("taskCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._actions_enabled = False
        self._target_format = ""
        self._task_type = None
        self._sample_set = None

        root = QVBoxLayout(self)
        root.setContentsMargins(T.PAD_XL, T.PAD_LG, T.PAD_XL, T.PAD_LG)
        root.setSpacing(T.GAP)

        head = QHBoxLayout()
        self._title = StrongBodyLabel(i18n.t("delivery.target.title"))
        self._title.setObjectName("taskCardTitle")
        head.addWidget(self._title)
        head.addStretch(1)
        self._badge = ScopeBadge(i18n.t("scope.readonly"), Scope.READONLY)
        head.addWidget(self._badge)
        root.addLayout(head)

        self._target = BodyLabel("")
        self._target.setObjectName("tvSplitSummary")
        root.addWidget(self._target)

        self._status = CaptionLabel("")
        self._status.setObjectName("taskCardValue")
        self._status.setWordWrap(True)
        root.addWidget(self._status)

        self._meta = CaptionLabel("")
        self._meta.setObjectName("tvVersionMeta")
        self._meta.setWordWrap(True)
        root.addWidget(self._meta)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(T.GAP)
        btn_row.addStretch(1)

        self._export_btn = PrimaryPushButton(i18n.t("delivery.target.export_now"))
        self._export_btn.setIcon(FIF.SEND)
        self._export_btn.setFixedHeight(T.CONTROL_HEIGHT)
        self._export_btn.setMinimumWidth(120)
        self._export_btn.clicked.connect(
            lambda: self.export_requested.emit(self._target_format))
        btn_row.addWidget(self._export_btn)

        root.addLayout(btn_row)
        self._refresh()

    def set_actions_enabled(self, enabled: bool) -> None:
        self._actions_enabled = enabled
        self._refresh()

    def set_project(self, project) -> None:
        self._target_format = getattr(project, "target_format", "") if project else ""
        self._task_type = getattr(project, "task_type", None) if project else None
        self._refresh()

    def set_sample_set(self, sample_set) -> None:
        self._sample_set = sample_set
        self._refresh()

    def retranslate(self) -> None:
        self._title.setText(i18n.t("delivery.target.title"))
        self._badge.setText(i18n.t("scope.readonly"))
        self._export_btn.setText(i18n.t("delivery.target.export_now"))
        self._refresh()

    def _refresh(self) -> None:
        target_name = _schema_display_name(self._target_format)
        self._target.setText(i18n.t("delivery.target.current", fmt=target_name))
        has_target = bool(self._target_format)

        if not has_target:
            self._status.setText(i18n.t("delivery.target.no_target"))
            self._meta.setText(i18n.t("delivery.target.no_target_hint"))
        else:
            self._status.setText(i18n.t("delivery.target.export_hint"))
            self._meta.setText(self._completion_text())

        self._export_btn.setEnabled(self._actions_enabled and has_target)

    def _completion_text(self) -> str:
        ss = self._sample_set
        if ss is None or not self._target_format:
            return ""
        total = len(ss.samples)
        if total <= 0:
            return ""
        try:
            from core.target_readiness import completed_paths_for_target
            done = len(completed_paths_for_target(
                ss.samples, self._target_format, self._task_type))
        except Exception:
            done = sum(1 for sample in ss.samples if sample.has_label)
        return i18n.t("delivery.target.completion", done=done, total=total)


class _VersionDeliveryCard(QFrame):
    """Read-only cleanup list for legacy generated versions.

    New workflows no longer generate versions; this card only surfaces
    snapshots already sitting under ``<project>/versions`` so the user
    can open or delete them to reclaim disk space.  Hidden entirely
    when no such versions exist.
    """

    open_requested = pyqtSignal(str)
    delete_requested = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("taskCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._rows: list[_DeliveryVersionRow] = []
        self._actions_enabled = False
        self._versions: list = []

        root = QVBoxLayout(self)
        root.setContentsMargins(T.PAD_XL, T.PAD_LG, T.PAD_XL, T.PAD_LG)
        root.setSpacing(T.GAP)

        head = QHBoxLayout()
        self._title = StrongBodyLabel(i18n.t("delivery.version.target_title"))
        self._title.setObjectName("taskCardTitle")
        head.addWidget(self._title)
        head.addStretch(1)
        self._badge = ScopeBadge(i18n.t("scope.readonly"), Scope.READONLY)
        head.addWidget(self._badge)
        root.addLayout(head)

        self._body = CaptionLabel(i18n.t("delivery.version.target_body"))
        self._body.setObjectName("taskCardValue")
        self._body.setWordWrap(True)
        root.addWidget(self._body)

        self._empty = CaptionLabel(i18n.t("delivery.version.target_empty"))
        self._empty.setObjectName("taskCardValue")
        self._empty.setWordWrap(True)
        root.addWidget(self._empty)

        self._rows_lay = QVBoxLayout()
        self._rows_lay.setContentsMargins(0, 0, 0, 0)
        self._rows_lay.setSpacing(T.GAP)
        root.addLayout(self._rows_lay)

    def set_actions_enabled(self, enabled: bool) -> None:
        self._actions_enabled = enabled
        for row in self._rows:
            row.set_actions_enabled(enabled)

    def has_versions(self) -> bool:
        return bool(self._versions)

    def set_versions(self, versions) -> None:
        self._versions = list(versions or [])
        self._rebuild()

    def retranslate(self) -> None:
        self._title.setText(i18n.t("delivery.version.target_title"))
        self._badge.setText(i18n.t("scope.readonly"))
        self._body.setText(i18n.t("delivery.version.target_body"))
        self._empty.setText(i18n.t("delivery.version.target_empty"))
        for row in self._rows:
            row.retranslate()

    def _rebuild(self) -> None:
        while self._rows_lay.count():
            item = self._rows_lay.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._rows = []

        self._empty.setVisible(not self._versions)
        for version in self._versions:
            row = _DeliveryVersionRow(version)
            row.set_actions_enabled(self._actions_enabled)
            row.open_requested.connect(self.open_requested.emit)
            row.delete_requested.connect(self.delete_requested.emit)
            self._rows_lay.addWidget(row)
            self._rows.append(row)


class DeliveryHub(QFrame):
    """Delivery stage body."""

    convert_annot_requested = pyqtSignal()
    open_version_requested = pyqtSignal(str)
    delete_version_requested = pyqtSignal(str)
    export_requested = pyqtSignal(str)
    start_vlm_workflow_requested = pyqtSignal()
    bulk_fill_region_text_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("deliveryHub")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root.addWidget(scroll)

        inner = QWidget()
        inner_lay = QVBoxLayout(inner)
        inner_lay.setContentsMargins(
            T.PAD_2XL, T.PAD_XL, T.PAD_2XL, T.PAD_XL)
        inner_lay.setSpacing(T.GAP_LG)

        self._cards: list[_TaskCard] = []
        self._action_buttons: list[PushButton | PrimaryPushButton] = []

        self._target_card = _TargetDeliveryCard()
        self._target_card.export_requested.connect(self.export_requested.emit)
        inner_lay.addWidget(self._target_card)

        self._version_card = _VersionDeliveryCard()
        self._version_card.open_requested.connect(
            self.open_version_requested.emit)
        self._version_card.delete_requested.connect(
            self.delete_version_requested.emit)
        self._version_card.setVisible(False)
        inner_lay.addWidget(self._version_card)

        self._secondary_title = StrongBodyLabel(
            i18n.t("delivery.secondary.title"))
        self._secondary_title.setObjectName("taskCardTitle")
        inner_lay.addWidget(self._secondary_title)

        convert_card = _TaskCard(
            "delivery.convert.title",
            "delivery.convert.scope",
            "delivery.convert.input",
            "delivery.convert.output",
            "delivery.convert.cta",
        )
        convert_card.cta.clicked.connect(self.convert_annot_requested.emit)
        self._add_card(convert_card, inner_lay)

        inner_lay.addStretch(1)
        scroll.setWidget(inner)

        i18n.bus.language_changed.connect(self._retranslate)

    def set_actions_enabled(self, enabled: bool) -> None:
        for button in self._action_buttons:
            button.setEnabled(enabled)
        self._target_card.set_actions_enabled(enabled)
        self._version_card.set_actions_enabled(enabled)

    def set_project(self, project) -> None:
        self._target_card.set_project(project)

    def set_sample_set(self, _sample_set) -> None:
        self._target_card.set_sample_set(_sample_set)

    def set_versions(self, versions) -> None:
        self._version_card.set_versions(versions)
        self._version_card.setVisible(self._version_card.has_versions())

    def _add_card(self, card: _TaskCard, container: QVBoxLayout) -> None:
        container.addWidget(card)
        self._cards.append(card)
        self._action_buttons.append(card.cta)

    def _retranslate(self, _lang: str) -> None:
        self._target_card.retranslate()
        self._version_card.retranslate()
        self._secondary_title.setText(i18n.t("delivery.secondary.title"))
        for card in self._cards:
            card.retranslate()
