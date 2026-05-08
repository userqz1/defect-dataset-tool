"""标注 pane — image-level label workbench (classification / multi-label / anomaly).

Displaces :class:`AnnotationPane` whenever the workbench spec carries
``image_label_kind != NONE``: tasks that label the image as a whole
rather than drawing shapes on it.

Three modes:

- ``SINGLE``  — single-label classification. One chip per known class;
  click promotes the image to that class. Persisted by *moving* the
  image into ``<root>/<class>/images/``  (re-uses the existing
  change-category fileops path).
- ``MULTI``   — multi-label. Same chip set, multi-select. Click toggles
  membership in ``image_labels``. Persistence: the directory still
  carries the dominant category, the multi-label set is written through
  the LabelMe sidecar's ``flags`` map (see core.annotation_writer).
- ``ANOMALY`` — primary OK / NG toggle. NG drills into the anomaly type
  (= every non-"normal"/non-"good" category). Persistence: same as
  classification (move into the matching folder).

Pane intent is exposed through three signals; the shell decides how to
persist (file move vs. label-write) and emits its own outward signals
(`change_category_requested`, `image_labels_changed`).
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
)

from gui import i18n
from gui.theme import T
from gui.views.detail_specs import ImageLabelKind
from gui.widgets.chips import FilterChip


# Anomaly-task convention: any category whose lowercased name matches
# one of these is treated as "normal". Everything else is an anomaly type.
_NORMAL_NAMES = {"normal", "good", "ok", "正常", "良品", "合格"}


class ImageLabelPane(QWidget):
    """Image-level label workbench for classification / multi-label / anomaly."""

    # SINGLE / ANOMALY: user picked a class chip — emit the target category.
    # The shell turns this into a category move.
    class_picked = pyqtSignal(str)

    # MULTI: user toggled the chip set — emit the full new label list.
    # The shell persists via LabelMe flags.
    labels_changed = pyqtSignal(object)

    def __init__(
        self,
        kind: ImageLabelKind,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._kind = kind
        # Last-known dataset categories (sorted, deduped). Refreshed by
        # the shell on every image load.
        self._classes: list[str] = []
        # Unfiltered class list — same as _classes for SINGLE/MULTI; for
        # ANOMALY this still includes "normal"/"good" entries so the OK
        # button can target an existing folder when present.
        self._all_classes: list[str] = []
        # Currently selected / active labels for the loaded image.
        # SINGLE/ANOMALY: 0-or-1 element. MULTI: 0+ elements.
        self._active: set[str] = set()
        # Chip widgets keyed by class name — re-used across image loads
        # so we don't churn widgets per A/D press.
        self._chips: dict[str, FilterChip] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(T.GAP_LG)

        # Section header — kind-specific copy.
        if kind is ImageLabelKind.ANOMALY:
            header_text = i18n.t("imglabel.section.anomaly")
        elif kind is ImageLabelKind.MULTI:
            header_text = i18n.t("imglabel.section.multi")
        else:
            header_text = i18n.t("imglabel.section.single")
        root.addWidget(self._section_label(header_text))

        # Current value chip (SINGLE / ANOMALY only — MULTI shows the
        # toggle set directly).
        self._current_value = BodyLabel("—")
        self._current_value.setObjectName("imgLabelCurrent")
        if kind is ImageLabelKind.MULTI:
            self._current_value.hide()
        else:
            root.addWidget(self._current_value)

        # Anomaly OK/NG primary toggle. The class-type strip below it is
        # only shown when NG is selected.
        self._ok_btn: FilterChip | None = None
        self._ng_btn: FilterChip | None = None
        self._anomaly_type_zone: QFrame | None = None
        if kind is ImageLabelKind.ANOMALY:
            ok_row = QFrame()
            ok_lay = QHBoxLayout(ok_row)
            ok_lay.setContentsMargins(0, 0, 0, 0)
            ok_lay.setSpacing(T.GAP)
            self._ok_btn = FilterChip(i18n.t("imglabel.anomaly.ok"))
            self._ng_btn = FilterChip(i18n.t("imglabel.anomaly.ng"))
            grp = QButtonGroup(self)
            grp.setExclusive(True)
            grp.addButton(self._ok_btn)
            grp.addButton(self._ng_btn)
            self._ok_btn.clicked.connect(self._on_ok_clicked)
            self._ng_btn.clicked.connect(self._on_ng_clicked)
            ok_lay.addWidget(self._ok_btn)
            ok_lay.addWidget(self._ng_btn)
            ok_lay.addStretch(1)
            root.addWidget(ok_row)

        # Chip strip — flow-laid via a flow layout substitute (HBox + wrap
        # via QLabel-per-row would be over-engineering for v1.0; a single
        # row with horizontal scroll is fine for the typical 4-12 classes
        # found in practice).
        if kind is ImageLabelKind.ANOMALY:
            self._anomaly_type_zone = QFrame()
            type_root = QVBoxLayout(self._anomaly_type_zone)
            type_root.setContentsMargins(0, 0, 0, 0)
            type_root.setSpacing(T.GAP)
            type_root.addWidget(self._section_label(
                i18n.t("imglabel.anomaly.types")))
            self._chips_row = QFrame()
            self._chips_row.setObjectName("filterChipGroup")
            self._chips_lay = QHBoxLayout(self._chips_row)
            self._chips_lay.setContentsMargins(T.PAD, T.GAP, T.PAD, T.GAP)
            self._chips_lay.setSpacing(T.GAP)
            type_root.addWidget(self._chips_row)
            self._anomaly_type_zone.hide()
            root.addWidget(self._anomaly_type_zone)
        else:
            # SINGLE / MULTI — chip strip directly under the section.
            self._chips_row = QFrame()
            self._chips_row.setObjectName("filterChipGroup")
            self._chips_lay = QHBoxLayout(self._chips_row)
            self._chips_lay.setContentsMargins(T.PAD, T.GAP, T.PAD, T.GAP)
            self._chips_lay.setSpacing(T.GAP)
            root.addWidget(self._chips_row)

        # Empty hint — shown when the dataset has no categories yet.
        self._empty_hint = CaptionLabel(i18n.t("imglabel.no_classes"))
        self._empty_hint.setObjectName("imgLabelEmpty")
        self._empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_hint.hide()
        root.addWidget(self._empty_hint)

        root.addStretch(1)

    # ---------- public API (shell drives these) ----------

    def set_classes(self, classes: list[str]) -> None:
        """Refresh the chip strip from the dataset's known categories.

        For ANOMALY mode the chips strip lists *anomaly* categories only
        (drops "normal"/"good"). The OK button is mutually exclusive with
        every chip in the strip.
        """
        # Keep the full original list for OK→target resolution; chips
        # only show anomaly types in ANOMALY mode.
        self._all_classes = sorted(c for c in classes if c)
        if self._kind is ImageLabelKind.ANOMALY:
            anomaly_classes = [
                c for c in self._all_classes
                if c.lower() not in _NORMAL_NAMES
            ]
            self._classes = anomaly_classes
        else:
            self._classes = list(self._all_classes)
        self._rebuild_chips()
        self._empty_hint.setVisible(len(self._classes) == 0
                                    and self._kind is not ImageLabelKind.ANOMALY)

    def bind_image(
        self,
        category: str,
        image_labels: list[str] | None = None,
    ) -> None:
        """Repaint state for the currently-loaded image.

        ``category`` is the directory-derived class (always present).
        ``image_labels`` is the multi-label set (MULTI mode only). When
        omitted, the bound state for SINGLE/ANOMALY uses ``category``.
        """
        if self._kind is ImageLabelKind.MULTI:
            self._active = set(image_labels or [])
            if not self._active and category:
                # MULTI fallback: a freshly-imported image with no sidecar
                # uses its directory category as the single active label.
                self._active = {category}
            self._sync_chip_state()
            return

        # SINGLE or ANOMALY — single value semantics.
        self._active = {category} if category else set()
        if self._kind is ImageLabelKind.ANOMALY:
            self._bind_anomaly(category)
        else:
            self._current_value.setText(category or "—")
        self._sync_chip_state()

    # ---------- internal: chip lifecycle ----------

    def _rebuild_chips(self) -> None:
        """Replace chip widgets when the class list changes."""
        # Tear down old chips.
        for chip in self._chips.values():
            self._chips_lay.removeWidget(chip)
            chip.deleteLater()
        self._chips.clear()

        for cls in self._classes:
            chip = FilterChip(cls)
            chip.setCheckable(self._kind is ImageLabelKind.MULTI)
            chip.clicked.connect(
                lambda _checked=False, name=cls: self._on_chip_clicked(name)
            )
            self._chips[cls] = chip
            self._chips_lay.addWidget(chip)
        self._chips_lay.addStretch(1)
        self._sync_chip_state()

    def _sync_chip_state(self) -> None:
        for cls, chip in self._chips.items():
            if self._kind is ImageLabelKind.MULTI:
                chip.blockSignals(True)
                chip.setChecked(cls in self._active)
                chip.blockSignals(False)
            else:
                chip.blockSignals(True)
                chip.setChecked(cls in self._active)
                chip.blockSignals(False)

    # ---------- internal: anomaly mode ----------

    def _bind_anomaly(self, category: str) -> None:
        """Map the loaded category onto OK/NG + (when NG) anomaly type."""
        is_normal = (
            not category
            or category.lower() in _NORMAL_NAMES
            or category == "normal"
        )
        if self._ok_btn is None or self._ng_btn is None \
                or self._anomaly_type_zone is None:
            return
        self._ok_btn.blockSignals(True)
        self._ng_btn.blockSignals(True)
        self._ok_btn.setChecked(is_normal)
        self._ng_btn.setChecked(not is_normal)
        self._ok_btn.blockSignals(False)
        self._ng_btn.blockSignals(False)
        self._anomaly_type_zone.setVisible(not is_normal)
        self._current_value.setText(
            i18n.t("imglabel.anomaly.ok_value") if is_normal
            else f"NG · {category}"
        )

    # ---------- internal: signal routing ----------

    def _on_chip_clicked(self, name: str) -> None:
        if self._kind is ImageLabelKind.MULTI:
            if name in self._active:
                self._active.remove(name)
            else:
                self._active.add(name)
            self._sync_chip_state()
            self.labels_changed.emit(sorted(self._active))
            return

        # SINGLE / ANOMALY — emit category pick. Don't pre-mutate
        # self._active; the shell will trigger a rescan + bind_image
        # which repaints the correct state.
        self.class_picked.emit(name)

    def _on_ok_clicked(self) -> None:
        # Map OK → an existing normal-named folder when the dataset
        # already has one; fall back to "normal" so fileops creates the
        # canonical folder for fresh datasets.
        target = "normal"
        for cls in self._all_classes:
            if cls.lower() in _NORMAL_NAMES:
                target = cls
                break
        self.class_picked.emit(target)

    def _on_ng_clicked(self) -> None:
        # NG flips the OK button off; the user still has to pick the
        # anomaly type from the chip strip below — emit nothing yet.
        if self._anomaly_type_zone is not None:
            self._anomaly_type_zone.show()
        if self._current_value is not None:
            self._current_value.setText(i18n.t("imglabel.anomaly.pick_type"))

    # ---------- internal: UI helpers ----------

    def _section_label(self, text: str) -> CaptionLabel:
        lbl = CaptionLabel(text.upper())
        lbl.setObjectName("sectionHeader")
        return lbl
