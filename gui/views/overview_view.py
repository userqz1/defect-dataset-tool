"""Overview page: stat cards + category distribution chart."""
from __future__ import annotations

import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import CaptionLabel, LargeTitleLabel, SubtitleLabel

from core.models import Dataset
from core.stats import DatasetStats, compute_stats
from gui.theme import T


class StatCard(QFrame):
    """Label + big value + optional hint. Visual styling in app.qss."""

    def __init__(self, label: str, value: str, hint: str = "", hint_warn: bool = False) -> None:
        super().__init__()
        self.setObjectName("statCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(T.PAD_XL, T.PAD_LG, T.PAD_XL, T.PAD_LG)
        layout.setSpacing(T.GAP)

        layout.addWidget(CaptionLabel(label.upper()))
        self.value_label = LargeTitleLabel(value)
        layout.addWidget(self.value_label)
        self.hint_label = CaptionLabel(hint)
        layout.addWidget(self.hint_label)
        self._set_warn(hint_warn)

    def _set_warn(self, warn: bool) -> None:
        self.hint_label.setObjectName("hintWarn" if warn else "")
        self.hint_label.style().unpolish(self.hint_label)
        self.hint_label.style().polish(self.hint_label)

    def update_value(self, value: str, hint: str = "", hint_warn: bool = False) -> None:
        self.value_label.setText(value)
        self.hint_label.setText(hint)
        self._set_warn(hint_warn)


class OverviewView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("overviewView")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(32, 28, 32, 24)
        root_layout.setSpacing(T.GAP_XL)

        # 标题
        self.title_label = SubtitleLabel("概览")
        self.subtitle_label = CaptionLabel("尚未加载数据")

        header = QVBoxLayout()
        header.setSpacing(2)
        header.addWidget(self.title_label)
        header.addWidget(self.subtitle_label)
        root_layout.addLayout(header)

        # 4 张统计卡
        cards_grid = QGridLayout()
        cards_grid.setSpacing(T.GAP_LG)
        self.card_total = StatCard("总图片数", "")
        self.card_anno = StatCard("总标注数", "")
        self.card_cats = StatCard("类别数", "")
        self.card_unlabeled = StatCard("未标注", "")
        cards_grid.addWidget(self.card_total, 0, 0)
        cards_grid.addWidget(self.card_anno, 0, 1)
        cards_grid.addWidget(self.card_cats, 0, 2)
        cards_grid.addWidget(self.card_unlabeled, 0, 3)
        root_layout.addLayout(cards_grid)

        # 类别分布图
        chart_frame = QFrame()
        chart_frame.setObjectName("chartFrame")
        chart_layout = QVBoxLayout(chart_frame)
        chart_layout.setContentsMargins(T.PAD_XL, T.PAD_LG, T.PAD_XL, T.PAD_LG)
        chart_layout.setSpacing(T.GAP)

        chart_layout.addWidget(CaptionLabel("类别分布"))

        pg.setConfigOption("background", T.CONTENT)
        pg.setConfigOption("foreground", T.TEXT)
        self.plot = pg.PlotWidget()
        self.plot.setMinimumHeight(300)
        plot_item = self.plot.getPlotItem()
        plot_item.hideAxis("top")
        plot_item.hideAxis("right")
        plot_item.getAxis("left").setPen(T.BORDER)
        plot_item.getAxis("bottom").setPen(T.BORDER)
        plot_item.getAxis("left").setTextPen(T.TEXT_2)
        plot_item.getAxis("bottom").setTextPen(T.TEXT_2)
        # 给左/下轴留够空间，避免类别名 / 数值被裁剪或与标题重叠
        plot_item.getAxis("left").setWidth(56)
        plot_item.getAxis("bottom").setHeight(40)
        plot_item.layout.setContentsMargins(8, 12, 16, 8)
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot.setMenuEnabled(False)
        chart_layout.addWidget(self.plot)

        root_layout.addWidget(chart_frame, 1)

    def set_dataset(self, dataset: Dataset) -> None:
        stats = compute_stats(dataset)
        layout_label = {
            "standard": "标准布局",
            "flat": "扁平布局",
            "single": "单目录",
            "recursive": "递归扫描",
            "empty": "未发现图片",
        }.get(dataset.layout, dataset.layout)
        self.subtitle_label.setText(
            f"{dataset.name}  ·  {dataset.root_path}  ·  {layout_label}"
        )

        if stats.total_images == 0:
            self.card_total.update_value("0", "未在该目录下发现图片")
            self.card_anno.update_value("—")
            self.card_cats.update_value("—")
            self.card_unlabeled.update_value("—")
            self._draw_distribution(stats)
            return

        self.card_total.update_value(f"{stats.total_images:,}")
        self.card_anno.update_value(
            f"{stats.total_annotations:,}",
            f"平均 {stats.avg_annotations_per_image:.1f} / 图",
        )
        self.card_cats.update_value(str(stats.category_count))
        if stats.unlabeled_count > 0:
            pct = stats.unlabeled_count / stats.total_images * 100
            self.card_unlabeled.update_value(
                f"{stats.unlabeled_count:,}",
                f"⚠ {pct:.1f}% 待处理",
                hint_warn=True,
            )
        else:
            self.card_unlabeled.update_value("0", "全部已标注")

        self._draw_distribution(stats)

    def _draw_distribution(self, stats: DatasetStats) -> None:
        self.plot.clear()
        if not stats.category_distribution:
            return
        names = [n for n, _ in stats.category_distribution]
        counts = [c for _, c in stats.category_distribution]
        x = list(range(len(names)))

        bar = pg.BarGraphItem(
            x=x, height=counts, width=0.6, brush=QColor(T.ACCENT), pen=QColor(T.ACCENT)
        )
        self.plot.addItem(bar)

        axis = self.plot.getPlotItem().getAxis("bottom")
        axis.setTicks([list(zip(x, names))])
        self.plot.setXRange(-0.5, len(names) - 0.5, padding=0.05)
        self.plot.setYRange(0, max(counts) * 1.15, padding=0)
