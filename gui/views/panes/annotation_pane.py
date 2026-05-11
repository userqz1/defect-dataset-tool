"""传统标注 pane — shape list only.

Only instantiated when ``TaskWorkbenchSpec.has_annotation`` is True and
``image_label_kind`` is NONE (shape-based tasks like detection /
segmentation).

Grounding (per-shape region text) now lives in VlmPane so that all
large-model features are grouped under the 大模型标注 tab.

Shape drawing tools (rect / polygon buttons, label combo, save-shape
button) live in the DetailView **topbar** rather than the pane body,
because they've always been part of the toolbar ribbon and moving
them would break the keyboard-shortcut + edit-mode wiring.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    Action,
    BodyLabel,
    CaptionLabel,
    FluentIcon as FIF,
    RoundMenu,
)

from core.models import Annotation
from gui import i18n
from gui.theme import T
from gui.widgets.image_viewer import color_for_label


class AnnotationPane(QWidget):
    """传统标注 segment body — shape list."""

    # User picked a row in the shape list — DetailView mirrors this
    # back into the ImageViewer so the matching shape highlights on
    # the canvas. Bidirectional with viewer.selection_changed; both
    # sides use blockSignals around their cross-mirrors to avoid loops.
    shape_selected = pyqtSignal(int)
    # Right-click → "删除此标注" on a single list row. Payload is the
    # row index; DetailView maps it to the underlying shape and runs
    # the delete through the viewer (so shapes_changed fires + the
    # canvas repaints in one path).
    delete_shape_requested = pyqtSignal(int)

    def __init__(
        self,
        mode_title: str = "",
        tool_labels: list[str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        # Track the live count of real shapes so currentRowChanged can
        # filter out the "（无标注）" placeholder row from emit-back.
        self._shape_count: int = 0

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(T.GAP_LG)

        if mode_title:
            lay.addWidget(self._build_mode_card(mode_title, tool_labels or []))

        lay.addWidget(self._section_label("标注列表"))
        hint = CaptionLabel(i18n.t("annotation.traditional.hint"))
        hint.setObjectName("annotationModeHint")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        self.shape_list = QListWidget()
        self.shape_list.setObjectName("shapeList")
        # List → canvas: bridge currentRowChanged into the shape_selected
        # signal so DetailView can mirror the selection on the viewer.
        # ``select_shape`` (the canvas → list mirror) blocks signals
        # around its setCurrentRow call so we won't loop back.
        self.shape_list.currentRowChanged.connect(
            self._on_current_row_changed)
        # Right-click on a row → "删除此标注" context menu.
        self.shape_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.shape_list.customContextMenuRequested.connect(
            self._on_list_context_menu)
        lay.addWidget(self.shape_list, 1)

    # ---------- public API (shell drives these) ----------

    def refresh_shape_list(self, annotation: Annotation | None) -> None:
        """Rebuild the shape list from the current annotation."""
        self.shape_list.blockSignals(True)
        self.shape_list.clear()
        shapes = annotation.shapes if annotation else []
        self._shape_count = len(shapes)
        if shapes:
            for shape in shapes:
                item = QListWidgetItem(
                    f"●  {shape.label}   ({shape.shape_type})")
                item.setForeground(color_for_label(shape.label))
                self.shape_list.addItem(item)
        else:
            placeholder = QListWidgetItem("（无标注）")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.shape_list.addItem(placeholder)
        self.shape_list.blockSignals(False)

    def select_shape(self, idx: int) -> None:
        """Mirror an external (viewer-driven) selection into the list."""
        self.shape_list.blockSignals(True)
        if 0 <= idx < self.shape_list.count():
            self.shape_list.setCurrentRow(idx)
        else:
            self.shape_list.clearSelection()
        self.shape_list.blockSignals(False)

    # ---------- internal ----------

    def _on_current_row_changed(self, row: int) -> None:
        if self._shape_count == 0:
            return
        if not (0 <= row < self._shape_count):
            self.shape_selected.emit(-1)
            return
        self.shape_selected.emit(row)

    def _on_list_context_menu(self, pos) -> None:
        """Right-click on a list row → "删除此标注"."""
        if self._shape_count == 0:
            return
        item = self.shape_list.itemAt(pos)
        if item is None:
            return
        row = self.shape_list.row(item)
        if not (0 <= row < self._shape_count):
            return
        self.shape_list.setCurrentRow(row)

        menu = RoundMenu(parent=self.shape_list)
        menu.addAction(Action(
            FIF.DELETE, i18n.t("annotation.delete_this"),
            triggered=lambda: self.delete_shape_requested.emit(row)))
        menu.exec(self.shape_list.viewport().mapToGlobal(pos))

    def _section_label(self, text: str) -> CaptionLabel:
        lbl = CaptionLabel(text.upper())
        lbl.setObjectName("sectionHeader")
        return lbl

    def _build_mode_card(self, title: str, tool_labels: list[str]) -> QFrame:
        card = QFrame()
        card.setObjectName("annotationModeCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        root = QVBoxLayout(card)
        root.setContentsMargins(T.PAD, T.PAD, T.PAD, T.PAD)
        root.setSpacing(T.GAP_XS)

        title_lbl = BodyLabel(title)
        title_lbl.setObjectName("annotationModeTitle")
        root.addWidget(title_lbl)

        if tool_labels:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(T.GAP_XS)
            for label in tool_labels:
                chip = CaptionLabel(label)
                chip.setObjectName("annotationModeChip")
                row.addWidget(chip)
            row.addStretch(1)
            root.addLayout(row)
        return card
