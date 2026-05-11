"""大模型标注 pane — caption + conversations + grounding.

All large-model annotation features live here: image-level caption,
multi-turn conversations, and per-shape grounding (region text).

Grounding reuses the shapes created on the canvas.  The pane shows a
read-only shape list (same visual style) plus a region-text editor for
the selected shape.  Shape creation/deletion is driven by DetailView's
topbar tools; this pane edits the ``text`` attribute.

Save actions surface as payload-carrying signals; the shell
(DetailView) persists to ``Sample`` + emits the public
``caption_saved`` / ``conversations_saved`` / ``grounding_saved``
signals that the outer view wires to the disk writers.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CaptionLabel,
    FluentIcon as FIF,
    PlainTextEdit,
    PushButton,
    SegmentedWidget,
    ToolButton,
)

from core.models import Annotation
from gui import i18n
from gui.theme import T
from gui.widgets.image_viewer import color_for_label


class _ConvTurnWidget(QFrame):
    """Single conversation turn — role badge + text editor + delete."""

    removed = pyqtSignal(object)

    def __init__(self, role: str = "human", text: str = "",
                 parent: QWidget | None = None) -> None:
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


class VlmPane(QWidget):
    """大模型标注 segment body — caption / conversations / grounding."""

    # Payload: caption text (already stripped).
    save_caption_requested = pyqtSignal(str)
    # Payload: list[dict[from, value]] of turns with non-empty value.
    save_conversations_requested = pyqtSignal(object)
    # Grounding save — zero-arg because the payload (pulled from shapes
    # with text) lives in the shell.
    save_grounding_requested = pyqtSignal()
    # User clicked a row in the grounding shape list — DetailView
    # mirrors this back to the ImageViewer canvas + AnnotationPane.
    shape_selected = pyqtSignal(int)

    def __init__(
        self,
        has_caption: bool = True,
        has_conversations: bool = True,
        has_grounding: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._has_caption = has_caption
        self._has_conversations = has_conversations
        self._has_grounding = has_grounding
        self._conv_turns: list[_ConvTurnWidget] = []
        self._caption_edit: PlainTextEdit | None = None
        self._conv_layout: QVBoxLayout | None = None

        # Grounding state
        self._shape_count: int = 0
        self._bound_idx: int = -1
        self._grounding_list: QListWidget | None = None
        self._region_text_edit: PlainTextEdit | None = None
        self._region_text_hint: CaptionLabel | None = None

        self._format_tabs = SegmentedWidget()
        self._format_tabs.setObjectName("vlmFormatTabs")
        self._format_stack = QStackedWidget()
        self._format_stack.setObjectName("vlmFormatStack")
        self._format_keys: list[str] = []

        # The pane is split by output format. This mirrors commercial
        # annotation tools: one focused editor at a time, with the mode
        # switch visible and stable instead of stacking every VLM field
        # into one long form.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setObjectName("vlmScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(T.GAP)

        lay.addWidget(self._build_overview())

        if has_caption:
            self._add_format_page(
                "caption", i18n.t("vlm.format.caption"),
                self._build_caption_page(),
            )
        if has_conversations:
            self._add_format_page(
                "conversation", i18n.t("vlm.format.conv"),
                self._build_conversation_page(),
            )
        if has_grounding:
            self._add_format_page(
                "grounding", i18n.t("vlm.format.grounding"),
                self._build_grounding_page(),
            )

        self._format_tabs.setVisible(len(self._format_keys) > 1)
        if self._format_keys:
            first_key = (
                "grounding" if has_grounding and "grounding" in self._format_keys
                else self._format_keys[0]
            )
            self._format_stack.setCurrentIndex(
                self._format_keys.index(first_key))
            QTimer.singleShot(0, lambda: self._format_tabs.setCurrentItem(
                first_key))

        lay.addWidget(self._format_tabs)
        lay.addWidget(self._format_stack, 1)

        lay.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll)

    def _add_format_page(self, key: str, text: str, page: QWidget) -> None:
        self._format_stack.addWidget(page)
        self._format_keys.append(key)
        self._format_tabs.addItem(
            routeKey=key,
            text=text,
            onClick=lambda *_, p=page: self._format_stack.setCurrentWidget(p),
        )

    def _build_caption_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(T.GAP)

        lay.addWidget(self._section_label(i18n.t("vlm.caption")))
        self._caption_edit = PlainTextEdit()
        self._caption_edit.setObjectName("captionEdit")
        self._caption_edit.setPlaceholderText(
            i18n.t("vlm.caption.placeholder"))
        self._caption_edit.setFixedHeight(120)
        lay.addWidget(self._caption_edit)

        cap_save = PushButton(i18n.t("vlm.caption.save"))
        cap_save.setFixedHeight(28)
        cap_save.clicked.connect(self._on_save_caption)
        lay.addWidget(cap_save)
        lay.addStretch(1)
        return page

    def _build_conversation_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(T.GAP)

        lay.addWidget(self._section_label(i18n.t("vlm.conv")))

        conv_scroll = QScrollArea()
        conv_scroll.setObjectName("convScroll")
        conv_scroll.setWidgetResizable(True)
        conv_scroll.setMinimumHeight(180)
        conv_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        conv_container = QWidget()
        self._conv_layout = QVBoxLayout(conv_container)
        self._conv_layout.setContentsMargins(0, 0, 0, 0)
        self._conv_layout.setSpacing(T.GAP_XS)
        self._conv_layout.addStretch()

        conv_scroll.setWidget(conv_container)
        lay.addWidget(conv_scroll)

        conv_btns = QHBoxLayout()
        conv_btns.setSpacing(T.GAP_XS)
        conv_add = ToolButton(FIF.ADD)
        conv_add.setToolTip(i18n.t("vlm.conv.add"))
        conv_add.setFixedHeight(28)
        conv_add.clicked.connect(self._on_conv_add_turn)
        conv_btns.addWidget(conv_add)

        conv_save = PushButton(i18n.t("vlm.conv.save"))
        conv_save.setFixedHeight(28)
        conv_save.clicked.connect(self._on_save_conversations)
        conv_btns.addWidget(conv_save)
        lay.addLayout(conv_btns)
        return page

    def _build_grounding_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(T.GAP)

        lay.addWidget(self._section_label(i18n.t("vlm.grounding")))

        self._region_text_hint = CaptionLabel(i18n.t("vlm.grounding.empty"))
        self._region_text_hint.setObjectName("regionTextHint")
        self._region_text_hint.setWordWrap(True)
        self._region_text_hint.hide()
        lay.addWidget(self._region_text_hint)

        self._grounding_list = QListWidget()
        self._grounding_list.setObjectName("shapeList")
        self._grounding_list.setMaximumHeight(150)
        self._grounding_list.currentRowChanged.connect(
            self._on_grounding_row_changed)
        lay.addWidget(self._grounding_list)

        self._region_text_edit = PlainTextEdit()
        self._region_text_edit.setObjectName("regionTextEdit")
        self._region_text_edit.setFixedHeight(90)
        self._region_text_edit.setEnabled(False)
        lay.addWidget(self._region_text_edit)

        gnd_save = PushButton(i18n.t("vlm.grounding.save"))
        gnd_save.setFixedHeight(28)
        gnd_save.clicked.connect(self.save_grounding_requested.emit)
        lay.addWidget(gnd_save)
        lay.addStretch(1)
        return page

    def _build_overview(self) -> QFrame:
        """Top explanation card showing only the enabled VLM capabilities.

        Compact: title + inline chips — only chips for capabilities this
        project/task actually uses are shown.
        """
        card = QFrame()
        card.setObjectName("vlmOverviewCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(T.GAP, T.GAP, T.GAP, T.GAP)
        lay.setSpacing(T.GAP_XS)

        title = CaptionLabel(i18n.t("vlm.overview.title"))
        title.setObjectName("vlmOverviewTitle")
        lay.addWidget(title)

        # Only show chips for capabilities that are actually enabled.
        chips: list[str] = []
        if self._has_caption:
            chips.append("vlm.overview.caption")
        if self._has_conversations:
            chips.append("vlm.overview.conv")
        if self._has_grounding:
            chips.append("vlm.overview.grounding")

        if chips:
            row = QHBoxLayout()
            row.setSpacing(T.GAP_XS)
            for key in chips:
                chip = CaptionLabel(i18n.t(key))
                chip.setObjectName("vlmOverviewChip")
                row.addWidget(chip)
            row.addStretch(1)
            lay.addLayout(row)
        return card

    # ══════════════════════════════════════════════════════════════
    # Public API — caption / conversations
    # ══════════════════════════════════════════════════════════════

    def set_caption(self, text: str) -> None:
        if self._caption_edit is not None:
            self._caption_edit.setPlainText(text)

    def set_conversations(self, convos: list[dict[str, str]]) -> None:
        """Clear and rebuild the turn widgets from ``convos``."""
        if self._conv_layout is None:
            return
        for w in list(self._conv_turns):
            self._conv_layout.removeWidget(w)
            w.deleteLater()
        self._conv_turns.clear()
        for turn in convos:
            role = turn.get("from", "human")
            text = turn.get("value", "")
            self._add_turn_widget(role, text)

    # ══════════════════════════════════════════════════════════════
    # Public API — grounding (shape list + region text)
    # ══════════════════════════════════════════════════════════════

    @property
    def has_grounding(self) -> bool:
        return self._has_grounding

    def refresh_shape_list(self, annotation: Annotation | None) -> None:
        """Rebuild the grounding shape list from the current annotation.

        No-op when the pane was built without grounding support.
        """
        if self._grounding_list is None:
            return
        self._grounding_list.blockSignals(True)
        self._grounding_list.clear()
        shapes = annotation.shapes if annotation else []
        self._shape_count = len(shapes)
        if shapes:
            for shape in shapes:
                label_text = f"●  {shape.label}   ({shape.shape_type})"
                item = QListWidgetItem(label_text)
                item.setForeground(color_for_label(shape.label))
                self._grounding_list.addItem(item)
        else:
            placeholder = QListWidgetItem("（无标注）")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self._grounding_list.addItem(placeholder)
        self._grounding_list.blockSignals(False)
        if self._region_text_hint is not None:
            self._region_text_hint.setVisible(not shapes)

    def select_shape(self, idx: int) -> None:
        """Mirror an external selection into the grounding list."""
        if self._grounding_list is None:
            return
        self._grounding_list.blockSignals(True)
        if 0 <= idx < self._grounding_list.count():
            self._grounding_list.setCurrentRow(idx)
        else:
            self._grounding_list.clearSelection()
        self._grounding_list.blockSignals(False)

    def bind_region_text(self, idx: int, text: str) -> None:
        """Load ``text`` into the region-text editor for shape ``idx``."""
        if self._region_text_edit is None:
            return
        if idx < 0:
            self._bound_idx = -1
            self._region_text_edit.setPlainText("")
            self._region_text_edit.setEnabled(False)
            return
        self._bound_idx = idx
        self._region_text_edit.setPlainText(text)
        self._region_text_edit.setEnabled(True)

    def current_region_text(self) -> tuple[int, str]:
        """Return (bound shape index, editor text). (-1, '') when inactive."""
        if self._region_text_edit is None:
            return (-1, "")
        return (self._bound_idx,
                self._region_text_edit.toPlainText().strip())

    def clear_region_binding(self) -> None:
        """Reset the region-text binding (call after shapes_changed)."""
        if self._region_text_edit is None:
            return
        self._bound_idx = -1
        self._region_text_edit.setPlainText("")
        self._region_text_edit.setEnabled(False)

    # ══════════════════════════════════════════════════════════════
    # Internal
    # ══════════════════════════════════════════════════════════════

    def _section_label(self, text: str) -> CaptionLabel:
        lbl = CaptionLabel(text.upper())
        lbl.setObjectName("sectionHeader")
        return lbl

    def _add_turn_widget(
        self, role: str = "human", text: str = "",
    ) -> _ConvTurnWidget:
        assert self._conv_layout is not None
        tw = _ConvTurnWidget(role, text)
        tw.removed.connect(self._on_conv_turn_removed)
        insert_idx = self._conv_layout.count() - 1  # before the stretch
        self._conv_layout.insertWidget(insert_idx, tw)
        self._conv_turns.append(tw)
        return tw

    def _on_conv_add_turn(self) -> None:
        if self._conv_turns:
            last_role = self._conv_turns[-1].to_dict()["from"]
            role = "gpt" if last_role == "human" else "human"
        else:
            role = "human"
        self._add_turn_widget(role, "")

    def _on_conv_turn_removed(self, widget: _ConvTurnWidget) -> None:
        if widget in self._conv_turns:
            self._conv_turns.remove(widget)
        if self._conv_layout is not None:
            self._conv_layout.removeWidget(widget)
        widget.deleteLater()

    def _on_save_caption(self) -> None:
        if self._caption_edit is None:
            return
        self.save_caption_requested.emit(
            self._caption_edit.toPlainText().strip())

    def _on_save_conversations(self) -> None:
        convos = [tw.to_dict() for tw in self._conv_turns
                  if tw.to_dict()["value"]]
        self.save_conversations_requested.emit(convos)

    def _on_grounding_row_changed(self, row: int) -> None:
        """Bridge grounding list selection → shape_selected signal."""
        if self._shape_count == 0:
            return
        if not (0 <= row < self._shape_count):
            self.shape_selected.emit(-1)
            return
        self.shape_selected.emit(row)
