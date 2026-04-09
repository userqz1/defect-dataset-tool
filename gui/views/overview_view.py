"""Overview page: stat cards + category distribution chart + extended stats."""
from __future__ import annotations

import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    IndeterminateProgressBar,
    InfoBar,
    InfoBarPosition,
    LargeTitleLabel,
    PrimaryPushButton,
    SubtitleLabel,
)

from core.models import Dataset
from core.stats import DatasetStats, ExtendedStats, compute_stats
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
        self._dataset: Dataset | None = None
        self._ext_worker = None

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(32, 28, 32, 24)
        root_layout.setSpacing(T.GAP_XL)

        # 标题 + 导出按钮
        header = QHBoxLayout()
        header.setSpacing(T.GAP_LG)
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        self.title_label = SubtitleLabel("概览")
        self.subtitle_label = CaptionLabel("尚未加载数据")
        title_col.addWidget(self.title_label)
        title_col.addWidget(self.subtitle_label)
        header.addLayout(title_col, 1)
        self.export_btn = PrimaryPushButton("导出报告")
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self._on_export_report)
        header.addWidget(self.export_btn, 0, Qt.AlignmentFlag.AlignBottom)
        root_layout.addLayout(header)

        # 分析进度条（扩展统计计算时显示）
        self._analysis_bar = IndeterminateProgressBar(self, start=False)
        self._analysis_label = CaptionLabel("")
        root_layout.addWidget(self._analysis_bar)
        root_layout.addWidget(self._analysis_label)
        self._analysis_bar.hide()
        self._analysis_label.hide()

        # 基本统计卡（第一行）
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

        # 扩展统计卡（第二行，加载后显示）
        ext_grid = QGridLayout()
        ext_grid.setSpacing(T.GAP_LG)
        self.card_imbalance = StatCard("类别平衡", "—")
        self.card_obj_per_img = StatCard("目标/图", "—")
        self.card_size = StatCard("图像尺寸", "—")
        self.card_ready = StatCard("训练就绪", "—")
        ext_grid.addWidget(self.card_imbalance, 0, 0)
        ext_grid.addWidget(self.card_obj_per_img, 0, 1)
        ext_grid.addWidget(self.card_size, 0, 2)
        ext_grid.addWidget(self.card_ready, 0, 3)
        root_layout.addLayout(ext_grid)

        # 警告区
        self.warnings_frame = QFrame()
        self.warnings_frame.setObjectName("warningsFrame")
        self.warnings_layout = QVBoxLayout(self.warnings_frame)
        self.warnings_layout.setContentsMargins(T.PAD_XL, T.PAD_LG, T.PAD_XL, T.PAD_LG)
        self.warnings_layout.setSpacing(T.GAP_XS)
        self.warnings_frame.hide()
        root_layout.addWidget(self.warnings_frame)

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
        self.plot.setMinimumHeight(260)
        plot_item = self.plot.getPlotItem()
        plot_item.hideAxis("top")
        plot_item.hideAxis("right")
        plot_item.getAxis("left").setPen(T.BORDER)
        plot_item.getAxis("bottom").setPen(T.BORDER)
        plot_item.getAxis("left").setTextPen(T.TEXT_2)
        plot_item.getAxis("bottom").setTextPen(T.TEXT_2)
        plot_item.getAxis("left").setWidth(56)
        plot_item.getAxis("bottom").setHeight(40)
        plot_item.layout.setContentsMargins(8, 12, 16, 8)
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot.setMenuEnabled(False)
        chart_layout.addWidget(self.plot)

        root_layout.addWidget(chart_frame, 1)

    def set_dataset(self, dataset: Dataset) -> None:
        self._dataset = dataset
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
        self.export_btn.setEnabled(stats.total_images > 0)

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
                f"{pct:.1f}% 待处理",
                hint_warn=True,
            )
        else:
            self.card_unlabeled.update_value("0", "全部已标注")

        self._draw_distribution(stats)

    def _start_extended_stats(self, dataset: Dataset) -> None:
        from core.stats import compute_extended_stats
        from gui.workers.batch_worker import BatchWorker

        # Show analysis progress
        self._analysis_bar.show()
        self._analysis_bar.start()
        self._analysis_label.setText("正在分析标注数据…")
        self._analysis_label.show()

        def task(cb):
            return compute_extended_stats(dataset, progress_cb=cb)

        self._ext_worker = BatchWorker(task)
        self._ext_worker.finished_ok.connect(self._on_extended_stats)
        self._ext_worker.failed.connect(self._on_extended_stats_failed)
        self._ext_worker.start()

    def _hide_analysis_bar(self) -> None:
        self._analysis_bar.stop()
        self._analysis_bar.hide()
        self._analysis_label.hide()

    def _on_extended_stats_failed(self, msg: str) -> None:
        self._hide_analysis_bar()
        self._analysis_label.setText(f"分析失败: {msg}")
        self._analysis_label.show()

    def _on_extended_stats(self, ext: ExtendedStats) -> None:
        self._hide_analysis_bar()
        # Imbalance card
        if ext.imbalance_ratio > 5:
            self.card_imbalance.update_value(
                f"{ext.imbalance_ratio:.1f}:1", "严重不平衡", hint_warn=True
            )
        elif ext.imbalance_ratio > 2:
            self.card_imbalance.update_value(
                f"{ext.imbalance_ratio:.1f}:1", "轻度不平衡", hint_warn=True
            )
        else:
            self.card_imbalance.update_value(f"{ext.imbalance_ratio:.1f}:1", "平衡")

        # Objects per image
        self.card_obj_per_img.update_value(
            f"{ext.objects_per_image_median:.0f}",
            f"范围 {ext.objects_per_image_min}~{ext.objects_per_image_max}",
        )

        # Image size
        if ext.image_sizes:
            sz = ext.image_sizes
            self.card_size.update_value(
                f"{sz.median_w}x{sz.median_h}",
                f"{sz.min_w}x{sz.min_h} ~ {sz.max_w}x{sz.max_h}",
            )
        else:
            self.card_size.update_value("—", "无尺寸信息")

        # Training readiness
        warn_count = len(ext.warnings)
        if warn_count == 0:
            self.card_ready.update_value("就绪", "所有检查通过")
        else:
            self.card_ready.update_value(
                f"{warn_count} 项警告", "请查看下方详情", hint_warn=True
            )

        # Warnings list
        # Clear old
        while self.warnings_layout.count():
            item = self.warnings_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if ext.warnings:
            title = CaptionLabel("训练就绪检查")
            title.setObjectName("warningsTitle")
            self.warnings_layout.addWidget(title)
            for msg in ext.warnings:
                lbl = BodyLabel(f"  {msg}")
                lbl.setObjectName("hintWarn")
                self.warnings_layout.addWidget(lbl)
            self.warnings_frame.show()
        else:
            self.warnings_frame.hide()

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

    def _on_export_report(self) -> None:
        if self._dataset is None:
            return
        directory = QFileDialog.getExistingDirectory(
            self, "选择报告输出目录"
        )
        if not directory:
            return
        from pathlib import Path
        from core.exporter.report import export_csv, export_json

        out = Path(directory)
        try:
            csv_files = export_csv(self._dataset, out)
            json_file = export_json(self._dataset, out)
            names = ", ".join(f.name for f in csv_files) + ", " + json_file.name
            InfoBar.success(
                title="报告已导出",
                content=names,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=4000,
                parent=self.window(),
            )
        except Exception as e:  # noqa: BLE001
            InfoBar.error(
                title="导出失败",
                content=str(e),
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=5000,
                parent=self.window(),
            )
