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

from PyQt6.QtCore import Qt, pyqtSignal
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
    EditableComboBox,
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
    # A row's class dropdown was picked or typed into → reclassify that
    # shape. Payload is (row, new_label); DetailView normalizes the
    # label, updates the shape, and refreshes the canvas + list. Same
    # signal the 1-9 shortcuts land on.
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
        # Raw label / shape_type per row, so a row can be rebuilt without
        # re-reading the annotation.
        self._labels: list[str] = []
        self._types: list[str] = []
        # Project classes offered by each row's class dropdown. Retyping a
        # class name to reclassify a box is the slow path; picking an
        # existing one should not require typing at all.
        self._class_names: list[str] = []
        # True while refresh_shape_list is populating the row combos, so
        # their setCurrentIndex isn't mistaken for a user pick.
        self._syncing_rows: bool = False

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
        # Each row hosts its own editable class dropdown, so the list
        # itself never edits: an item editor would render underneath the
        # row widget and be invisible.
        self.shape_list.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
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
        self._labels = [s.label for s in shapes]
        self._types = [s.shape_type for s in shapes]
        if shapes:
            # Row widgets are built with their combos pre-set; without this
            # gate each setCurrentIndex would look like a user pick and fire
            # a rename back at the shape we are merely displaying.
            self._syncing_rows = True
            try:
                for i in range(len(shapes)):
                    item = QListWidgetItem()
                    widget = self._build_row_widget(i)
                    item.setSizeHint(widget.sizeHint())
                    self.shape_list.addItem(item)
                    self.shape_list.setItemWidget(item, widget)
            finally:
                self._syncing_rows = False
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


    def _build_row_widget(self, i: int) -> QWidget:
        """One list row: colour dot + class dropdown + shape type.

        The dropdown is the point — reclassifying used to mean retyping
        the class name. Deliberately NOT editable: an editable combo
        emits on every keystroke, which would fire a rename per
        character. Brand-new class names still go through the
        right-click 重命名, which is the rare case.
        """
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(T.GAP_XS, 2, T.GAP_XS, 2)
        lay.setSpacing(T.GAP_XS)

        dot = BodyLabel("●")
        dot.setObjectName("shapeRowDot")
        # Inline colour, deliberately. This is a *category-identity*
        # colour — the same hash-derived one the canvas paints the box
        # with, so row and box agree at a glance — not a theme colour, and
        # CLAUDE.md carves those out from the tokens rule precisely
        # because they must stay put across light/dark. It is per-instance
        # and computed, so QSS placeholders cannot express it, and a
        # QPalette would lose to the global stylesheet. The value still
        # comes from color_for_label, never a literal.
        dot.setStyleSheet(f"color: {color_for_label(self._labels[i]).name()}")
        lay.addWidget(dot)

        combo = EditableComboBox()
        combo.setObjectName("shapeRowClass")
        # No setFixedWidth — CLAUDE.md gotcha: class names are CJK-ish and
        # arbitrary length; a fixed width clips them.
        combo.setMinimumWidth(150)
        options = list(self._class_names)
        if self._labels[i] not in options:
            # The shape's own class may not be in the project list yet
            # (imported data, a name typed once). Never let opening the
            # dropdown silently retarget the shape.
            options.insert(0, self._labels[i])
        combo.addItems(options)
        combo.setCurrentText(self._labels[i])
        combo.setToolTip("选择已有类别，或直接输入新类别名")
        # Commit on pick and on finished-typing only. currentTextChanged
        # would fire once per keystroke, renaming the shape to every
        # prefix of what is being typed.
        # qfluentwidgets' EditableComboBox subclasses QLineEdit directly,
        # so editingFinished lives on the widget — there is no lineEdit().
        combo.activated.connect(
            lambda _n, r=i, c=combo: self._on_row_class_committed(r, c))
        combo.editingFinished.connect(
            lambda r=i, c=combo: self._on_row_class_committed(r, c))
        lay.addWidget(combo, 1)

        kind = CaptionLabel(f"({self._types[i]})")
        kind.setObjectName("shapeRowType")
        lay.addWidget(kind)
        return row

    def _on_row_class_committed(self, row: int, combo) -> None:
        """A row's class was picked or typed. Ignored while rebuilding."""
        if self._syncing_rows:
            return
        if not (0 <= row < len(self._labels)):
            return
        new_label = combo.currentText().strip()
        if not new_label or new_label == self._labels[row]:
            return
        # Selecting the row first means the canvas highlights the shape the
        # user is about to change — otherwise a mis-click retargets a box
        # they cannot see.
        self.shape_list.setCurrentRow(row)
        self.rename_shape_requested.emit(row, new_label)

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

        # No "改为类别" / "重命名" entries: each row now carries an editable
        # class dropdown that does both, right where the label is. A menu
        # duplicating it would be a third way to do one thing — and the
        # inline rename editor cannot work here anyway, since it renders
        # underneath the row widget.
        menu = RoundMenu(parent=self.shape_list)
        menu.addAction(Action(
            FIF.DELETE, i18n.t("annotation.delete_this"),
            triggered=lambda: self.delete_shape_requested.emit(row)))
        menu.exec(self.shape_list.viewport().mapToGlobal(pos))

    def set_class_names(self, names: list[str]) -> None:
        """Project classes offered by the right-click "改为类别" list."""
        self._class_names = [n for n in names if n]

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
