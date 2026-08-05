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
    ComboBox,
    FluentIcon as FIF,
    RoundMenu,
    ToolButton,
)

from core.models import Annotation
from gui import i18n
from gui.theme import T
from gui.widgets.image_viewer import color_for_label

# Sentinel entry at the bottom of every row's class dropdown. The combo is
# non-editable (see _build_row_widget), so this is where a class name the
# project has never seen gets typed.
NEW_CLASS_ENTRY = "＋ 新建类别…"

# Vertical padding QSS puts inside every shapeList item
# (``QListWidget#shapeList::item { padding: 6px 10px }``). It is carved
# out of the area the row widget gets, but setSizeHint is measured in
# whole-item pixels — so the widget's own height has to be reported PLUS
# this, or the row is handed less than it asked for and the class name
# gets clipped mid-glyph.
_ITEM_V_PADDING = 12


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
    # A row's class dropdown was used → reclassify that shape. Payload is
    # (row, new_label); DetailView normalizes the label, updates the shape,
    # and refreshes the canvas + list. Same signal the 1-9 shortcuts hit.
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
        # Raw label / shape_type per row, so a row can be refreshed in
        # place without re-reading the annotation.
        self._labels: list[str] = []
        self._types: list[str] = []
        # Project classes offered by each row's class dropdown. Retyping a
        # class name to reclassify a box is the slow path; picking an
        # existing one should not require typing at all.
        self._class_names: list[str] = []
        # True while the rows are being populated, so a programmatic
        # setCurrentText is not mistaken for the user picking a class.
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
        # Rows host their own class dropdown, so the list itself never
        # edits: an item editor would render underneath the row widget.
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
        """Sync the shape list to *annotation*.

        Rows are REUSED whenever the row count is unchanged — only their
        contents are updated. This is not just an optimisation: this
        method runs on every shape edit, and destroying + recreating the
        per-row widgets each time is what destabilised the app. Keeping
        the widgets alive removes that churn entirely.
        """
        shapes = annotation.shapes if annotation else []
        self._syncing_rows = True
        try:
            self.shape_list.blockSignals(True)
            reuse = (bool(shapes)
                     and self.shape_list.count() == len(shapes)
                     and self._shape_count == len(shapes))
            self._shape_count = len(shapes)
            self._labels = [s.label for s in shapes]
            self._types = [s.shape_type for s in shapes]
            if reuse:
                for i in range(len(shapes)):
                    self._update_row_widget(i)
            elif shapes:
                self.shape_list.clear()
                for i in range(len(shapes)):
                    item = QListWidgetItem()
                    widget = self._build_row_widget(i)
                    hint = widget.sizeHint()
                    hint.setHeight(hint.height() + _ITEM_V_PADDING)
                    item.setSizeHint(hint)
                    self.shape_list.addItem(item)
                    self.shape_list.setItemWidget(item, widget)
            else:
                self.shape_list.clear()
                placeholder = QListWidgetItem("（无标注）")
                placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
                self.shape_list.addItem(placeholder)
            self.shape_list.blockSignals(False)
        finally:
            self._syncing_rows = False
        if not reuse:
            # Only a real rebuild drops the selection.
            self.delete_btn.setEnabled(False)

    def _row_parts(self, row: int):
        """(dot, combo, type-label) of an existing row, or (None,)*3."""
        item = self.shape_list.item(row)
        if item is None:
            return None, None, None
        widget = self.shape_list.itemWidget(item)
        if widget is None:
            return None, None, None
        return (widget.findChild(BodyLabel),
                widget.findChild(ComboBox),
                widget.findChild(CaptionLabel))

    def _class_options(self, label: str) -> list[str]:
        """Dropdown entries for a shape currently labelled *label*.

        The shape's own class leads when the project doesn't know it —
        imported data carries names like "TODO" — so merely opening the
        dropdown can never silently retarget it.
        """
        options = list(self._class_names)
        if label and label not in options:
            options.insert(0, label)
        return options + [NEW_CLASS_ENTRY]

    def _update_row_widget(self, i: int) -> None:
        """Refresh an existing row in place — no widget is destroyed."""
        dot, combo, kind = self._row_parts(i)
        if combo is None:
            return
        label = self._labels[i]
        options = self._class_options(label)
        if [combo.itemText(n) for n in range(combo.count())] != options:
            combo.clear()
            combo.addItems(options)
        combo.setCurrentText(label)
        if dot is not None:
            dot.setStyleSheet(f"color: {color_for_label(label).name()}")
        if kind is not None:
            kind.setText(f"({self._types[i]})")

    def _build_row_widget(self, i: int) -> QWidget:
        """One list row: colour dot + class dropdown + shape type.

        The dropdown is a plain (non-editable) ComboBox on purpose. An
        EditableComboBox subclasses QLineEdit and carries a
        LineEditButton child; churning those inside the list produced a
        flood of "disconnect from destroyed signal" warnings and then a
        native crash. Measured: 300 rebuild rounds gave 1801 Qt warnings
        with EditableComboBox and 1 with ComboBox. New class names go
        through the "＋ 新建类别…" entry instead.
        """
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(T.GAP_XS, 2, T.GAP_XS, 2)
        lay.setSpacing(T.GAP_XS)

        dot = BodyLabel("●")
        dot.setObjectName("shapeRowDot")
        # Inline colour, deliberately: this is a *category-identity*
        # colour — the same hash-derived one the canvas paints the box
        # with — which CLAUDE.md carves out of the token rule precisely
        # because it must stay put across light/dark. It is per-instance
        # and computed, so QSS cannot express it. Value still comes from
        # color_for_label, never a literal.
        dot.setStyleSheet(f"color: {color_for_label(self._labels[i]).name()}")
        lay.addWidget(dot)

        combo = ComboBox()
        combo.setObjectName("shapeRowClass")
        # No setFixedWidth — CLAUDE.md gotcha: class names are arbitrary
        # length and a fixed width clips them. A minimum *height* is fine
        # and necessary: CJK and latin share a line height, and without a
        # floor the row layout compresses the combo below its text.
        combo.setMinimumWidth(150)
        combo.setMinimumHeight(combo.sizeHint().height())
        combo.addItems(self._class_options(self._labels[i]))
        combo.setCurrentText(self._labels[i])
        combo.setToolTip("改为其他类别（也可用 1-9 快捷键）")
        combo.activated.connect(
            lambda _n, r=i, c=combo: self._on_row_class_picked(r, c))
        lay.addWidget(combo, 1)

        kind = CaptionLabel(f"({self._types[i]})")
        kind.setObjectName("shapeRowType")
        lay.addWidget(kind)
        return row

    def _on_row_class_picked(self, row: int, combo) -> None:
        """A row's dropdown was used. Ignored while we are populating."""
        if self._syncing_rows:
            return
        if not (0 <= row < len(self._labels)):
            return
        picked = combo.currentText()
        current = self._labels[row]
        if picked == NEW_CLASS_ENTRY:
            from gui.dialogs.op_dialogs import NewClassNameDialog
            dlg = NewClassNameDialog(current, self.window())
            picked = dlg.name() if dlg.exec() else ""
            if not picked:
                # Cancelled — put the sentinel back to the real class so
                # the row never displays "＋ 新建类别…" as its label.
                self._syncing_rows = True
                combo.setCurrentText(current)
                self._syncing_rows = False
                return
        if not picked or picked == current:
            return
        # Select the row first so the canvas highlights the shape about to
        # change — a mis-click must not retarget a box the user can't see.
        self.shape_list.setCurrentRow(row)
        self.rename_shape_requested.emit(row, picked)

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

        # No "改为类别" / "重命名" entries: the row's own dropdown does both,
        # right where the label is. The inline item editor cannot work
        # here anyway — it renders underneath the row widget.
        menu = RoundMenu(parent=self.shape_list)
        menu.addAction(Action(
            FIF.DELETE, i18n.t("annotation.delete_this"),
            triggered=lambda: self.delete_shape_requested.emit(row)))
        menu.exec(self.shape_list.viewport().mapToGlobal(pos))

    def set_class_names(self, names: list[str]) -> None:
        """Project classes offered by each row's class dropdown."""
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
