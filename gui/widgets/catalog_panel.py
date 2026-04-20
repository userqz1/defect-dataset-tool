"""Catalog panel — right-hand 340px column for class distribution + tree.

Follows the design handoff's 4-region layout:

- Header: serif "类别分布 · Class distribution" + uppercase sub "CATALOGUE · N · sum".
- Distribution card (reuse gui.widgets.distribution_chart.DistributionChart):
  40px bar chart + imbalance caption.
- Sort tabs (按数量 / 按名称) — 按数量 is the default, 按名称 is a no-op
  placeholder for now (sorting is done on CategoryTree.load_dataset).
- Class tree (reuse CategoryTree) — gets the existing rename / merge /
  split signals so all data-ops continue working.

Lives outside BrowserView so the design's 3-column body layout
(Tools | Viewer | Catalog) can be expressed naturally in
DatasetBrowserView.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CaptionLabel, FluentIcon as FIF, PushButton, ToolButton

from core.models import Dataset
from gui import i18n
from gui.theme import T
from gui.widgets.category_tree import CategoryTree
from gui.widgets.distribution_chart import DistributionChart


class CatalogPanel(QFrame):
    """Right-hand column — serif header, distribution card, tabs, class rows."""

    # Forwarded from CategoryTree — DatasetBrowserView wires these to
    # BrowserView handlers so the existing data-op plumbing stays intact.
    category_selected = pyqtSignal(str)
    rename_requested = pyqtSignal(str)
    merge_requested = pyqtSignal(str)
    split_requested = pyqtSignal(str)
    close_requested = pyqtSignal()   # user clicked the × in the panel header

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("catalogPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(340)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header (serif title + uppercase subtitle + close × on right)
        head = QFrame()
        head_lay = QHBoxLayout(head)
        head_lay.setContentsMargins(T.PAD_LG, T.PAD_LG, T.PAD_LG, T.GAP)
        head_lay.setSpacing(T.GAP)

        head_text = QVBoxLayout()
        head_text.setContentsMargins(0, 0, 0, 0)
        head_text.setSpacing(2)
        self._title = BodyLabel(i18n.t("catalog.title"))
        self._title.setObjectName("catalogTitle")
        self._subtitle = CaptionLabel(f"{i18n.t('catalog.subtitle')} · —")
        self._subtitle.setObjectName("catalogSubtitle")
        head_text.addWidget(self._title)
        head_text.addWidget(self._subtitle)
        head_lay.addLayout(head_text, 1)

        close_btn = ToolButton(FIF.CLOSE)
        close_btn.setFixedSize(22, 22)
        close_btn.setToolTip("关闭类别面板(DatasetBar 切换按钮可重新打开)")
        close_btn.clicked.connect(self.close_requested.emit)
        head_lay.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignTop)

        root.addWidget(head)

        # Distribution chart card
        self._distribution = DistributionChart()
        root.addWidget(self._distribution)

        # Sort tabs — 按数量 is the default; 按名称 re-sorts on click.
        tabs_row = QHBoxLayout()
        tabs_row.setContentsMargins(T.PAD_LG, 0, T.PAD_LG, T.GAP)
        tabs_row.setSpacing(T.GAP_XS)

        self._sort_group = QButtonGroup(self)
        self._sort_group.setExclusive(True)
        self._tab_count = PushButton(i18n.t("catalog.tab.count"))
        self._tab_count.setObjectName("catalogTab")
        self._tab_count.setCheckable(True)
        self._tab_count.setChecked(True)
        self._tab_name = PushButton(i18n.t("catalog.tab.name"))
        self._tab_name.setObjectName("catalogTab")
        self._tab_name.setCheckable(True)
        self._sort_group.addButton(self._tab_count)
        self._sort_group.addButton(self._tab_name)
        self._tab_count.clicked.connect(lambda: self._resort("count"))
        self._tab_name.clicked.connect(lambda: self._resort("name"))
        tabs_row.addWidget(self._tab_count)
        tabs_row.addWidget(self._tab_name)
        tabs_row.addStretch(1)
        root.addLayout(tabs_row)

        # Class tree — keep existing widget; CatalogPanel just re-homes it.
        self._tree = CategoryTree()
        self._tree.category_selected.connect(self.category_selected.emit)
        self._tree.rename_requested.connect(self.rename_requested.emit)
        self._tree.merge_requested.connect(self.merge_requested.emit)
        self._tree.split_requested.connect(self.split_requested.emit)
        root.addWidget(self._tree, 1)

        self._dataset: Dataset | None = None
        self._sort = "count"

        i18n.bus.language_changed.connect(self._retranslate)

    def _retranslate(self, _lang: str) -> None:
        self._title.setText(i18n.t("catalog.title"))
        self._tab_count.setText(i18n.t("catalog.tab.count"))
        self._tab_name.setText(i18n.t("catalog.tab.name"))
        # Subtitle and tree content depend on the current dataset
        if self._dataset is not None:
            self._refresh_subtitle(self._dataset)
            # CategoryTree rebuilds "All" row on load_dataset
            self._resort(self._sort)
        else:
            self._subtitle.setText(f"{i18n.t('catalog.subtitle')} · —")

    # ---------- public API ----------

    def set_dataset(self, ds: Dataset) -> None:
        self._dataset = ds
        self._distribution.set_dataset(ds)
        self._refresh_subtitle(ds)
        self._resort(self._sort)

    def clear(self) -> None:
        self._dataset = None
        self._distribution.clear()
        self._subtitle.setText(f"{i18n.t('catalog.subtitle')} · —")
        self._tree.clear()

    def get_category_names(self) -> list[str]:
        return self._tree.get_category_names()

    # Expose the tree for the outer view to call methods that aren't
    # covered by signals (e.g. selecting a specific category in code).
    @property
    def tree(self) -> CategoryTree:
        return self._tree

    # ---------- internals ----------

    def _refresh_subtitle(self, ds: Dataset) -> None:
        n_cls = len(ds.categories)
        total = sum(c.image_count for c in ds.categories)
        self._subtitle.setText(f"{i18n.t('catalog.subtitle')} · {n_cls} · {total:,}")

    def _resort(self, mode: str) -> None:
        self._sort = mode
        if self._dataset is None:
            return
        # Feed a Dataset whose .categories ordering matches the desired sort.
        # CategoryTree.load_dataset already sorts by count descending;
        # we re-order in-place for the "by name" case.
        cats = list(self._dataset.categories)
        if mode == "name":
            cats = sorted(cats, key=lambda c: c.name)
        else:
            cats = sorted(cats, key=lambda c: c.image_count, reverse=True)
        # Build a shallow-sorted copy (Dataset is dataclass w/ frozen=False).
        from dataclasses import replace
        sorted_ds = replace(self._dataset, categories=cats)
        self._tree.load_dataset(sorted_ds)
