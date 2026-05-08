"""标注 pane — shape list + per-shape region-text editor (grounding).

Only instantiated when ``TaskWorkbenchSpec.has_annotation`` is True.
If ``show_region_text`` is False (classification / keypoint / anomaly),
the region-text editor and its save button are not created — the pane
is just the shape list.

Shape drawing tools (rect / polygon buttons, label combo, save-shape
button) live in the DetailView **topbar** rather than the pane body,
because they've always been part of the toolbar ribbon and moving
them would break the keyboard-shortcut + edit-mode wiring.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    Action,
    CaptionLabel,
    FluentIcon as FIF,
    PlainTextEdit,
    PushButton,
    RoundMenu,
)

from core.models import Annotation
from gui import i18n
from gui.theme import T
from gui.widgets.image_viewer import color_for_label


class AnnotationPane(QWidget):
    """标注 segment body — shape list + optional grounding editor."""

    # User clicked "save grounding". DetailView commits the pending
    # region-text edit, then writes through to Sample.regions + emits
    # grounding_saved on the shell. Zero-arg because the payload
    # (pulled from shapes with text) lives in the shell.
    save_grounding_requested = pyqtSignal()
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
        show_region_text: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._show_region_text = show_region_text
        # Shape index currently bound to the region-text editor. -1 when
        # nothing is selected (empty list) or selection is out of range
        # after a shapes_changed rebuild.
        self._bound_idx: int = -1

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(T.GAP_LG)

        lay.addWidget(self._section_label("标注列表"))
        self.shape_list = QListWidget()
        self.shape_list.setObjectName("shapeList")
        # Track the live count of real shapes so currentRowChanged can
        # filter out the "（无标注）" placeholder row from emit-back.
        self._shape_count: int = 0
        # List → canvas: bridge currentRowChanged into the shape_selected
        # signal so DetailView can mirror the selection on the viewer.
        # ``select_shape`` (the canvas → list mirror) blocks signals
        # around its setCurrentRow call so we won't loop back.
        self.shape_list.currentRowChanged.connect(
            self._on_current_row_changed)
        # Right-click on a row → "删除此标注" context menu.  Per-row
        # delete sat behind a global Delete-key + a topbar button
        # before; this brings the action to where the user is looking.
        self.shape_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.shape_list.customContextMenuRequested.connect(
            self._on_list_context_menu)
        lay.addWidget(self.shape_list, 1)

        # Region-text (grounding) — off for classification/keypoint/anomaly.
        self._region_text_header: CaptionLabel | None = None
        self._region_text_edit: PlainTextEdit | None = None
        self._region_text_save_btn: PushButton | None = None
        # Empty hint shown above the editor when no shapes exist yet —
        # tells users that grounding requires creating a shape first
        # rather than presenting a disabled editor with no explanation.
        self._region_text_hint: CaptionLabel | None = None
        if show_region_text:
            self._region_text_header = self._section_label(
                i18n.t("vlm.region_text"))
            lay.addWidget(self._region_text_header)

            self._region_text_hint = CaptionLabel(
                i18n.t("annotation.grounding.empty"))
            self._region_text_hint.setObjectName("regionTextHint")
            self._region_text_hint.setWordWrap(True)
            self._region_text_hint.hide()  # shown only when shape list empty
            lay.addWidget(self._region_text_hint)

            self._region_text_edit = PlainTextEdit()
            self._region_text_edit.setObjectName("regionTextEdit")
            self._region_text_edit.setFixedHeight(56)
            self._region_text_edit.setEnabled(False)
            lay.addWidget(self._region_text_edit)

            self._region_text_save_btn = PushButton(
                i18n.t("vlm.region_text.save"))
            self._region_text_save_btn.setFixedHeight(28)
            self._region_text_save_btn.clicked.connect(
                self.save_grounding_requested.emit)
            lay.addWidget(self._region_text_save_btn)

    # ---------- public API (shell drives these) ----------

    def refresh_shape_list(self, annotation: Annotation | None) -> None:
        """Rebuild the shape list from the current annotation."""
        # Block signals during rebuild so the implicit row reset doesn't
        # leak through currentRowChanged → shape_selected and clobber
        # the canvas selection.
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
            # The placeholder isn't a real selectable annotation — disable
            # interaction so currentRowChanged never fires for it.
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.shape_list.addItem(placeholder)
        self.shape_list.blockSignals(False)
        # When grounding is enabled, surface the "create a shape first"
        # hint instead of leaving the user staring at a disabled
        # region-text editor with no explanation.
        if self._region_text_hint is not None:
            self._region_text_hint.setVisible(not shapes)

    def select_shape(self, idx: int) -> None:
        """Mirror an external (viewer-driven) selection into the list."""
        self.shape_list.blockSignals(True)
        if 0 <= idx < self.shape_list.count():
            self.shape_list.setCurrentRow(idx)
        else:
            self.shape_list.clearSelection()
        self.shape_list.blockSignals(False)

    def bind_region_text(self, idx: int, text: str) -> None:
        """Load ``text`` into the region-text editor for shape ``idx``.

        No-op when the pane was built without a region-text editor.
        """
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

    @property
    def has_region_text(self) -> bool:
        return self._region_text_edit is not None

    # ---------- internal ----------

    def _on_current_row_changed(self, row: int) -> None:
        """Bridge list selection → canvas via the shape_selected signal.

        Filters out the "（无标注）" placeholder row (when shape count
        is 0) so the viewer doesn't get a bogus index 0 when the list
        is empty.
        """
        if self._shape_count == 0:
            return
        # Out-of-range rows from a stale rebuild also become -1 so the
        # viewer clears its highlight.
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
        # Make sure the right-clicked row is the one selected before we
        # surface the menu — keeps the canvas highlight aligned with
        # what's about to be deleted.
        self.shape_list.setCurrentRow(row)

        menu = RoundMenu(parent=self.shape_list)
        menu.addAction(Action(
            FIF.DELETE, i18n.t("annotation.delete_this"),
            triggered=lambda: self.delete_shape_requested.emit(row)))
        menu.exec(self.shape_list.viewport().mapToGlobal(pos))

    def _section_label(self, text: str) -> CaptionLabel:
        # Matches the DetailView helper one-for-one so section styling
        # is identical to the old monolithic layout.
        lbl = CaptionLabel(text.upper())
        lbl.setObjectName("sectionHeader")
        return lbl
