"""Overview page: stat cards + category distribution chart."""
from __future__ import annotations

import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.models import Dataset
from core.stats import DatasetStats, compute_stats

# 调色板
TEXT = "#2d2a26"
TEXT_2 = "#6b6760"
TEXT_3 = "#9a958a"
BORDER = "#e8e5dc"
CARD_BG = "#ffffff"
ACCENT = "#c96442"
WARNING = "#b8842b"


class StatCard(QFrame):
    def __init__(self, label: str, value: str, hint: str = "", hint_warn: bool = False) -> None:
        super().__init__()
        self.setObjectName("statCard")
        self.setStyleSheet(
            f"""
            QFrame#statCard {{
                background-color: {CARD_BG};
                border: 1px solid {BORDER};
                border-radius: 8px;
            }}
            """
        )
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(8)

        label_widget = QLabel(label.upper())
        label_widget.setStyleSheet(
            f"color: {TEXT_2}; font-size: 11px; letter-spacing: 0.6px; font-weight: 600;"
        )

        self.value_label = QLabel(value)
        value_font = QFont()
        value_font.setPointSize(22)
        value_font.setWeight(QFont.Weight.DemiBold)
        self.value_label.setFont(value_font)
        self.value_label.setStyleSheet(f"color: {TEXT};")

        self.hint_label = QLabel(hint)
        hint_color = WARNING if hint_warn else TEXT_2
        self.hint_label.setStyleSheet(f"color: {hint_color}; font-size: 11px;")

        layout.addWidget(label_widget)
        layout.addWidget(self.value_label)
        layout.addWidget(self.hint_label)

    def update_value(self, value: str, hint: str = "", hint_warn: bool = False) -> None:
        self.value_label.setText(value)
        self.hint_label.setText(hint)
        self.hint_label.setStyleSheet(
            f"color: {WARNING if hint_warn else TEXT_2}; font-size: 11px;"
        )


class OverviewView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("overviewView")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("QWidget#overviewView { background-color: #ffffff; }")

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(32, 28, 32, 24)
        root_layout.setSpacing(16)

        # 标题
        self.title_label = QLabel("概览")
        title_font = QFont()
        title_font.setPointSize(20)
        title_font.setWeight(QFont.Weight.DemiBold)
        self.title_label.setFont(title_font)
        self.title_label.setStyleSheet(f"color: {TEXT};")

        self.subtitle_label = QLabel("尚未打开数据集")
        self.subtitle_label.setStyleSheet(f"color: {TEXT_2}; font-size: 12px;")

        header = QVBoxLayout()
        header.setSpacing(2)
        header.addWidget(self.title_label)
        header.addWidget(self.subtitle_label)
        root_layout.addLayout(header)

        # 4 张统计卡
        cards_grid = QGridLayout()
        cards_grid.setSpacing(12)
        self.card_total = StatCard("总图片数", "—")
        self.card_anno = StatCard("总标注数", "—")
        self.card_cats = StatCard("类别数", "—")
        self.card_unlabeled = StatCard("未标注", "—")
        cards_grid.addWidget(self.card_total, 0, 0)
        cards_grid.addWidget(self.card_anno, 0, 1)
        cards_grid.addWidget(self.card_cats, 0, 2)
        cards_grid.addWidget(self.card_unlabeled, 0, 3)
        root_layout.addLayout(cards_grid)

        # 类别分布图
        chart_frame = QFrame()
        chart_frame.setObjectName("chartFrame")
        chart_frame.setStyleSheet(
            f"QFrame#chartFrame {{ background-color: {CARD_BG}; "
            f"border: 1px solid {BORDER}; border-radius: 8px; }}"
        )
        chart_layout = QVBoxLayout(chart_frame)
        chart_layout.setContentsMargins(20, 16, 20, 16)
        chart_layout.setSpacing(10)

        chart_title = QLabel("类别分布")
        chart_title.setStyleSheet(
            f"color: {TEXT_2}; font-size: 11px; letter-spacing: 0.6px; font-weight: 600;"
        )
        chart_layout.addWidget(chart_title)

        pg.setConfigOption("background", CARD_BG)
        pg.setConfigOption("foreground", TEXT)
        self.plot = pg.PlotWidget()
        self.plot.setMinimumHeight(260)
        self.plot.getPlotItem().hideAxis("top")
        self.plot.getPlotItem().hideAxis("right")
        self.plot.getPlotItem().getAxis("left").setPen(BORDER)
        self.plot.getPlotItem().getAxis("bottom").setPen(BORDER)
        self.plot.getPlotItem().getAxis("left").setTextPen(TEXT_2)
        self.plot.getPlotItem().getAxis("bottom").setTextPen(TEXT_2)
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
            x=x, height=counts, width=0.6, brush=QColor(ACCENT), pen=QColor(ACCENT)
        )
        self.plot.addItem(bar)

        axis = self.plot.getPlotItem().getAxis("bottom")
        axis.setTicks([list(zip(x, names))])
        self.plot.setXRange(-0.5, len(names) - 0.5, padding=0.05)
        self.plot.setYRange(0, max(counts) * 1.15, padding=0)
