"""大模型标注 pane — caption editor + multi-turn conversation editor.

Large-model annotation is a mode, not a project capability switch.  The
pane always shows the caption and conversation editors; grounding lives
in AnnotationPane as per-region text for shape-based tasks.

Save actions surface as payload-carrying signals; the shell
(DetailView) persists to ``Sample`` + emits the public
``caption_saved`` / ``conversations_saved`` signals that the outer
view wires to the disk writers.

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
    CaptionLabel,
    FluentIcon as FIF,
    PlainTextEdit,
    PushButton,
    ToolButton,
)

from gui import i18n
from gui.theme import T


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
    """大模型标注 segment body — caption / conversations / empty-state."""

    # Payload: caption text (already stripped).
    save_caption_requested = pyqtSignal(str)
    # Payload: list[dict[from, value]] of turns with non-empty value.
    save_conversations_requested = pyqtSignal(object)
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
        # Grounding lives in AnnotationPane (per-region text), not in
        # VlmPane.
        self._has_grounding = has_grounding
        self._conv_turns: list[_ConvTurnWidget] = []
        # Editor refs default to None so the empty-state branch (early
        # return) leaves :meth:`set_caption` / :meth:`set_conversations`
        # safe to call from the shell — they each guard on None.
        self._caption_edit: PlainTextEdit | None = None
        self._conv_layout: QVBoxLayout | None = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(T.GAP_LG)

        if has_caption:
            lay.addWidget(self._section_label(i18n.t("vlm.caption")))
            self._caption_edit = PlainTextEdit()
            self._caption_edit.setObjectName("captionEdit")
            self._caption_edit.setPlaceholderText(
                i18n.t("vlm.caption.placeholder"))
            self._caption_edit.setFixedHeight(80)
            lay.addWidget(self._caption_edit)

            cap_save = PushButton(i18n.t("vlm.caption.save"))
            cap_save.setFixedHeight(28)
            cap_save.clicked.connect(self._on_save_caption)
            lay.addWidget(cap_save)

        if has_conversations:
            lay.addWidget(self._section_label(i18n.t("vlm.conv")))

            conv_scroll = QScrollArea()
            conv_scroll.setObjectName("convScroll")
            conv_scroll.setWidgetResizable(True)
            conv_scroll.setMaximumHeight(220)
            conv_scroll.setMinimumHeight(0)
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

        lay.addStretch(1)

    # ---------- public API ----------

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

    # ---------- internal ----------

    def _section_label(self, text: str) -> CaptionLabel:
        lbl = CaptionLabel(text.upper())
        lbl.setObjectName("sectionHeader")
        return lbl

    def _add_turn_widget(
        self, role: str = "human", text: str = "",
    ) -> _ConvTurnWidget:
        assert self._conv_layout is not None  # gated by has_conversations
        tw = _ConvTurnWidget(role, text)
        tw.removed.connect(self._on_conv_turn_removed)
        insert_idx = self._conv_layout.count() - 1  # before the stretch
        self._conv_layout.insertWidget(insert_idx, tw)
        self._conv_turns.append(tw)
        return tw

    def _on_conv_add_turn(self) -> None:
        # Alternate role from the last turn, or start with human.
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
        # Drop empty turns so blank placeholder rows don't persist to disk.
        convos = [tw.to_dict() for tw in self._conv_turns
                  if tw.to_dict()["value"]]
        self.save_conversations_requested.emit(convos)
