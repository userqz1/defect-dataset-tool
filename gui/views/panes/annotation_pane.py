"""传统标注 pane — shape list only.

Only instantiated when ``TaskWorkbenchSpec.has_annotation`` is True and
``image_label_kind`` is NONE (shape-based tasks like detection /
segmentation).

Grounding (per-shape region text) now lives in VlmPane so that all
large-model features are grouped under the 大模型标注 tab.

Shape drawing tools (the shape-type dropdown, 类别 combo, save button)
live in the DetailView **topbar** — they drive the canvas while you draw.
The **delete** button lives HERE next to the shape list instead, because
deleting operates on a selected list entry; keeping it off the topbar also
frees ribbon space (the topbar was overcrowded).
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
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
    ToolButton,
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
    # Double-click a row (or right-click "重命名") → rename that shape's
    # label in place. Payload is (row, new_label); DetailView normalizes
    # the label, updates the shape, and refreshes the canvas + list.
    rename_shape_requested = pyqtSignal(int, str)

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
        # Raw label / shape_type per row — lets us reformat a row after an
        # inline rename without re-reading the annotation. _editing_row marks
        # the row whose inline editor is open.
        self._labels: list[str] = []
        self._types: list[str] = []
        self._editing_row: int = -1

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(T.GAP_LG)

        if mode_title:
            lay.addWidget(self._build_mode_card(mode_title, tool_labels or []))

        lay.addWidget(self._section_label("标注列表"))
        # "对象位置与类别" 提示 + 删除按钮同排 —— 删除本就是对标注的操作，放在
        # 列表旁比塞在顶栏更顺手，也给顶栏腾了地方。按钮删当前选中项，未选中时禁用。
        hint_row = QHBoxLayout()
        hint_row.setContentsMargins(0, 0, 0, 0)
        hint_row.setSpacing(T.GAP_XS)
        hint = CaptionLabel(i18n.t("annotation.traditional.hint"))
        hint.setObjectName("annotationModeHint")
        hint.setWordWrap(True)
        hint_row.addWidget(hint, 1)
        self.delete_btn = ToolButton(FIF.DELETE)
        self.delete_btn.setToolTip("删除选中标注 (Del)")
        self.delete_btn.setEnabled(False)
        self.delete_btn.clicked.connect(self._on_delete_clicked)
        hint_row.addWidget(self.delete_btn)
        lay.addLayout(hint_row)

        self.shape_list = QListWidget()
        self.shape_list.setObjectName("shapeList")
        # List → canvas: bridge currentRowChanged into the shape_selected
        # signal so DetailView can mirror the selection on the viewer.
        # ``select_shape`` (the canvas → list mirror) blocks signals
        # around its setCurrentRow call so we won't loop back.
        self.shape_list.currentRowChanged.connect(
            self._on_current_row_changed)
        # Inline rename: double-click a row edits just the label. We drive
        # editing manually (NoEditTriggers) so the editor shows the raw
        # label, not the "● label (type)" display string.
        self.shape_list.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.shape_list.itemDoubleClicked.connect(self._begin_rename)
        self.shape_list.itemDelegate().closeEditor.connect(self._end_rename)
        # Right-click on a row → "重命名" / "删除此标注" context menu.
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
        self._labels = [s.label for s in shapes]
        self._types = [s.shape_type for s in shapes]
        self._editing_row = -1
        if shapes:
            for i in range(len(shapes)):
                item = QListWidgetItem(self._format_row(i))
                item.setForeground(color_for_label(self._labels[i]))
                self.shape_list.addItem(item)
        else:
            placeholder = QListWidgetItem("（无标注）")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.shape_list.addItem(placeholder)
        self.shape_list.blockSignals(False)
        # A rebuild clears the selection → nothing to delete yet.
        self.delete_btn.setEnabled(False)

    def select_shape(self, idx: int) -> None:
        """Mirror an external (viewer-driven) selection into the list."""
        self.shape_list.blockSignals(True)
        if 0 <= idx < self.shape_list.count():
            self.shape_list.setCurrentRow(idx)
        else:
            self.shape_list.clearSelection()
        self.shape_list.blockSignals(False)
        self.delete_btn.setEnabled(0 <= idx < self._shape_count)

    # ---------- internal ----------

    def _on_current_row_changed(self, row: int) -> None:
        valid = 0 <= row < self._shape_count
        self.delete_btn.setEnabled(valid)
        if self._shape_count == 0:
            return
        if not valid:
            self.shape_selected.emit(-1)
            return
        self.shape_selected.emit(row)

    def _on_delete_clicked(self) -> None:
        """Delete the currently selected shape (same path as right-click)."""
        row = self.shape_list.currentRow()
        if 0 <= row < self._shape_count:
            self.delete_shape_requested.emit(row)

    def _format_row(self, i: int) -> str:
        return f"●  {self._labels[i]}   ({self._types[i]})"

    def _begin_rename(self, item: QListWidgetItem) -> None:
        """Double-click / "重命名" → edit just the raw label in place."""
        row = self.shape_list.row(item)
        if not (0 <= row < self._shape_count):
            return
        self._editing_row = row
        # Show the raw label (not "● label (type)") in the editor.
        self.shape_list.blockSignals(True)
        item.setText(self._labels[row])
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        self.shape_list.blockSignals(False)
        self.shape_list.editItem(item)

    def _end_rename(self, *_args) -> None:
        """Editor closed (commit or cancel) → reformat the row; emit if changed.

        On cancel the model text is untouched (still the raw label we set),
        so ``new_label == orig`` and nothing is emitted.  The actual rename is
        deferred one tick so the editor fully tears down before DetailView
        rebuilds the list in response.
        """
        row = self._editing_row
        self._editing_row = -1
        if not (0 <= row < self._shape_count):
            return
        item = self.shape_list.item(row)
        if item is None:
            return
        new_label = item.text().strip()
        orig = self._labels[row]
        self.shape_list.blockSignals(True)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        item.setText(self._format_row(row))  # restore "● label (type)"
        self.shape_list.blockSignals(False)
        if new_label and new_label != orig:
            QTimer.singleShot(
                0, lambda: self.rename_shape_requested.emit(row, new_label))

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
            FIF.EDIT, "重命名",
            triggered=lambda: self._begin_rename(item)))
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
