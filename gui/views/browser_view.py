"""Browser view: category tree + filter bar + thumbnail grid + pagination."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import FluentIcon as FIF, LineEdit, ToolButton

from core import fileops, index_cache, transform as tx
from core.convert import convert_batch
from core.dedup import find_duplicates
from core.exporter.subset import export_subset
from core.models import Dataset, ImageInfo
from gui.dialogs.op_dialogs import (
    ConvertDialog,
    CropDialog,
    FlipDialog,
    RenameDialog,
    ResizeDialog,
    RotateDialog,
)
from gui.widgets.category_tree import CategoryTree
from gui.widgets.thumbnail_grid import ThumbnailGrid
from gui.workers.batch_worker import BatchWorker

PAGE_SIZE = 60

BG = "#ffffff"
SIDEBAR = "#f5f4ef"
BORDER = "#e8e5dc"
TEXT = "#2d2a26"
TEXT_2 = "#6b6760"
TEXT_3 = "#9a958a"
ACCENT = "#c96442"
ACCENT_SOFT = "#f4e8e2"


class FilterChip(QPushButton):
    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            f"""
            QPushButton {{
                background-color: transparent;
                border: 1px solid {BORDER};
                border-radius: 6px;
                padding: 5px 14px;
                font-size: 12px;
                color: {TEXT_2};
            }}
            QPushButton:hover {{ background-color: #faf9f7; color: {TEXT}; }}
            QPushButton:checked {{
                background-color: {ACCENT_SOFT};
                border-color: {ACCENT};
                color: {ACCENT};
            }}
            """
        )


class BrowserView(QWidget):
    image_activated = pyqtSignal(object, list)  # (current ImageInfo, full list)
    thumb_request = pyqtSignal(object)          # Path

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("browserView")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"QWidget#browserView {{ background-color: {BG}; }}")

        self._dataset: Dataset | None = None
        self._current_category: str = ""
        self._filter_mode: str = "all"   # all / labeled / unlabeled
        self._search_text: str = ""
        self._page: int = 0
        self._filtered: list[ImageInfo] = []

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 左侧类别树
        left = QFrame()
        left.setFixedWidth(240)
        left.setStyleSheet(f"background-color: {SIDEBAR}; border-right: 1px solid {BORDER};")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        header = QLabel("  " + self.tr("类别"))
        header.setFixedHeight(44)
        header.setStyleSheet(
            f"color: {TEXT_2}; font-size: 11px; font-weight: 600; letter-spacing: 0.8px;"
            f"border-bottom: 1px solid {BORDER}; padding-left: 14px;"
        )
        left_layout.addWidget(header)

        self.tree = CategoryTree()
        self.tree.category_selected.connect(self._on_category_selected)
        left_layout.addWidget(self.tree)

        root.addWidget(left)

        # 右侧主区
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(20, 16, 20, 12)
        right_layout.setSpacing(10)

        # 筛选栏
        filter_bar = QHBoxLayout()
        filter_bar.setSpacing(8)

        self.search = LineEdit()
        self.search.setPlaceholderText(self.tr("搜索文件名…"))
        self.search.setFixedWidth(280)
        self.search.setFixedHeight(32)
        self.search.textChanged.connect(self._on_search_changed)
        filter_bar.addWidget(self.search)

        self.chip_group = QButtonGroup(self)
        self.chip_group.setExclusive(True)
        for key, label in [
            ("all", self.tr("全部")),
            ("labeled", self.tr("已标注")),
            ("unlabeled", self.tr("未标注")),
        ]:
            chip = FilterChip(label)
            chip.setProperty("filterKey", key)
            chip.clicked.connect(lambda _c=False, k=key: self._on_filter_changed(k))
            self.chip_group.addButton(chip)
            filter_bar.addWidget(chip)
            if key == "all":
                chip.setChecked(True)

        filter_bar.addStretch(1)

        self.dedup_btn = QPushButton(self.tr("查找重复"))
        self.dedup_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.dedup_btn.setStyleSheet(
            f"QPushButton {{ background:transparent; border:1px solid {BORDER};"
            f" border-radius:6px; padding:5px 14px; font-size:12px; color:{TEXT_2}; }}"
            f"QPushButton:hover {{ background:#faf9f7; color:{ACCENT}; border-color:{ACCENT}; }}"
        )
        self.dedup_btn.clicked.connect(self._do_find_duplicates)
        filter_bar.addWidget(self.dedup_btn)

        self.selection_label = QLabel("")
        self.selection_label.setStyleSheet(f"color: {TEXT_3}; font-size: 11px;")
        filter_bar.addWidget(self.selection_label)

        right_layout.addLayout(filter_bar)

        # 缩略图网格
        self.grid = ThumbnailGrid()
        self.grid.item_activated.connect(self._on_item_activated)
        self.grid.selection_changed.connect(self._on_selection_changed)
        self.grid.request_thumb.connect(lambda p: self.thumb_request.emit(p))
        self.grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self._on_context_menu)
        self._worker: BatchWorker | None = None
        self._progress: QProgressDialog | None = None
        right_layout.addWidget(self.grid, 1)

        # 分页栏
        pager = QHBoxLayout()
        pager.setSpacing(8)
        self.prev_btn = ToolButton(FIF.LEFT_ARROW)
        self.prev_btn.clicked.connect(self._prev_page)
        self.next_btn = ToolButton(FIF.RIGHT_ARROW)
        self.next_btn.clicked.connect(self._next_page)
        self.page_label = QLabel("—")
        self.page_label.setStyleSheet(f"color: {TEXT_2}; font-size: 12px;")
        pager.addStretch(1)
        pager.addWidget(self.prev_btn)
        pager.addWidget(self.page_label)
        pager.addWidget(self.next_btn)
        right_layout.addLayout(pager)

        root.addWidget(right, 1)

    # ---------- 外部接口 ----------

    def load_dataset(self, dataset: Dataset) -> None:
        self._dataset = dataset
        self._current_category = ""
        self._page = 0
        self.tree.load_dataset(dataset)
        self._apply_filter_and_show()

    def on_thumb_ready(self, path: str, jpeg_bytes: bytes, w: int, h: int) -> None:
        self.grid.on_thumb_ready(path, jpeg_bytes, w, h)

    # ---------- 内部 ----------

    def _all_images(self) -> list[ImageInfo]:
        if not self._dataset:
            return []
        if self._current_category:
            for cat in self._dataset.categories:
                if cat.name == self._current_category:
                    return list(cat.images)
            return []
        # 全部
        out: list[ImageInfo] = []
        for cat in self._dataset.categories:
            out.extend(cat.images)
        return out

    def _apply_filter_and_show(self) -> None:
        imgs = self._all_images()
        if self._filter_mode == "labeled":
            imgs = [i for i in imgs if i.has_label]
        elif self._filter_mode == "unlabeled":
            imgs = [i for i in imgs if not i.has_label]
        if self._search_text:
            q = self._search_text.lower()
            imgs = [i for i in imgs if q in i.path.name.lower()]
        self._filtered = imgs
        self._page = 0
        self._show_page()

    def _show_page(self) -> None:
        total = len(self._filtered)
        page_count = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        self._page = max(0, min(self._page, page_count - 1))
        start = self._page * PAGE_SIZE
        end = min(start + PAGE_SIZE, total)
        page_imgs = self._filtered[start:end]
        self.grid.set_images(page_imgs)
        if total == 0:
            self.page_label.setText(self.tr("没有匹配的图片"))
        else:
            self.page_label.setText(
                self.tr("第 {cur} / {total_pages} 页  ·  共 {n} 张").format(
                    cur=self._page + 1, total_pages=page_count, n=f"{total:,}"
                )
            )
        self.prev_btn.setEnabled(self._page > 0)
        self.next_btn.setEnabled(self._page < page_count - 1)

    def _on_category_selected(self, category: str) -> None:
        self._current_category = category
        self._apply_filter_and_show()

    def _on_filter_changed(self, mode: str) -> None:
        self._filter_mode = mode
        self._apply_filter_and_show()

    def _on_search_changed(self, text: str) -> None:
        self._search_text = text.strip()
        self._apply_filter_and_show()

    def _on_selection_changed(self, selected: list[ImageInfo]) -> None:
        n = len(selected)
        self.selection_label.setText(
            self.tr("已选 {n} 张").format(n=n) if n else ""
        )

    def _on_item_activated(self, img: ImageInfo) -> None:
        self.image_activated.emit(img, self._filtered)

    def _prev_page(self) -> None:
        self._page -= 1
        self._show_page()

    def _next_page(self) -> None:
        self._page += 1
        self._show_page()

    # ---------- 右键菜单 / 批量操作 ----------

    def _on_context_menu(self, pos) -> None:
        sel = self.grid.selected_images()
        if not sel:
            return
        menu = QMenu(self)
        menu.addAction(
            self.tr("已选 {n} 张").format(n=len(sel))
        ).setEnabled(False)
        menu.addSeparator()
        menu.addAction(self.tr("删除 (回收站)"), lambda: self._do_delete(sel))
        menu.addAction(self.tr("批量重命名…"), lambda: self._do_rename(sel))
        menu.addAction(self.tr("移动到类别…"), lambda: self._do_move(sel))
        menu.addSeparator()
        menu.addAction(self.tr("格式转换…"), lambda: self._do_convert(sel))
        menu.addAction(self.tr("缩放…"), lambda: self._do_transform(sel, tx.resize_one, ResizeDialog))
        menu.addAction(self.tr("裁剪…"), lambda: self._do_transform(sel, tx.crop_one, CropDialog))
        menu.addAction(self.tr("旋转…"), lambda: self._do_transform(sel, tx.rotate_one, RotateDialog))
        menu.addAction(self.tr("翻转…"), lambda: self._do_transform(sel, tx.flip_one, FlipDialog))
        menu.addSeparator()
        menu.addAction(self.tr("导出为子集数据集…"), lambda: self._do_export_subset(sel))
        menu.exec(self.grid.viewport().mapToGlobal(pos))

    # ---- 各操作 ----

    def _do_delete(self, sel: list[ImageInfo]) -> None:
        if QMessageBox.question(
            self, self.tr("确认删除"),
            self.tr("将 {n} 个图片+标注移至回收站，确认？").format(n=len(sel)),
        ) != QMessageBox.StandardButton.Yes:
            return
        self._run(
            lambda cb: fileops.delete_pairs(sel, to_trash=True),
            self.tr("正在删除…"),
        )

    def _do_rename(self, sel: list[ImageInfo]) -> None:
        dlg = RenameDialog(self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        pattern = dlg.pattern.text()
        start = dlg.start.value()
        self._run(
            lambda cb: fileops.batch_rename(sel, pattern=pattern, start=start),
            self.tr("正在重命名…"),
        )

    def _do_move(self, sel: list[ImageInfo]) -> None:
        if not self._dataset:
            return
        cats = [c.name for c in self._dataset.categories]
        from PyQt6.QtWidgets import QInputDialog
        target, ok = QInputDialog.getItem(
            self, self.tr("移动到类别"), self.tr("目标类别:"), cats, 0, True
        )
        if not ok or not target:
            return
        root = self._dataset.root_path
        self._run(
            lambda cb: fileops.move_to_category(sel, root, target),
            self.tr("正在移动到 {target}…").format(target=target),
        )

    def _do_convert(self, sel: list[ImageInfo]) -> None:
        dlg = ConvertDialog(self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        opts = dlg.options()
        paths = [i.path for i in sel]
        self._run(
            lambda cb: convert_batch(paths, opts, progress_cb=cb),
            self.tr("正在转换…"),
        )

    def _do_transform(self, sel: list[ImageInfo], op_fn, DlgCls) -> None:
        dlg = DlgCls(self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        opts = dlg.options()
        paths = [i.path for i in sel]
        self._run(
            lambda cb: tx.batch_apply(paths, op_fn, opts, progress_cb=cb),
            self.tr("处理中…"),
        )

    def _do_export_subset(self, sel: list[ImageInfo]) -> None:
        out = QFileDialog.getExistingDirectory(self, self.tr("选择导出目录"))
        if not out:
            return
        from pathlib import Path as _P
        out_path = _P(out)
        self._run(
            lambda cb: export_subset(sel, out_path, progress_cb=cb),
            self.tr("正在导出子集…"),
        )

    def _do_find_duplicates(self) -> None:
        if not self._filtered:
            QMessageBox.information(
                self, self.tr("查找重复"), self.tr("当前没有可扫描的图片")
            )
            return
        imgs = list(self._filtered)
        group_tpl = self.tr("{n} 张: {names}")

        def _run(cb):
            groups = find_duplicates(imgs, threshold=5, progress_cb=cb)
            res = fileops.OpResult()
            for g in groups:
                if len(g.images) < 2:
                    continue
                res.succeeded.append(g.images[0].path)
                names = ", ".join(i.path.name for i in g.images[:6])
                if len(g.images) > 6:
                    names += f"  (+{len(g.images) - 6})"
                res.failed.append(
                    (g.images[0].path, group_tpl.format(n=len(g.images), names=names))
                )
            return res

        self._run(_run, self.tr("正在计算 pHash…"))

    # ---- 通用 worker 驱动 ----

    def _run(self, fn, title: str) -> None:
        if self._worker is not None:
            QMessageBox.information(
                self, self.tr("请稍候"), self.tr("已有操作正在执行")
            )
            return
        self._progress = QProgressDialog(title, self.tr("取消"), 0, 0, self)
        self._progress.setWindowTitle(self.tr("批量操作"))
        self._progress.setMinimumDuration(0)
        self._progress.setAutoClose(False)
        self._progress.setCancelButton(None)
        self._progress.show()

        self._worker = BatchWorker(fn)
        self._worker.progress.connect(self._on_op_progress)
        self._worker.finished_ok.connect(self._on_op_done)
        self._worker.failed.connect(self._on_op_failed)
        self._worker.start()

    def _on_op_progress(self, done: int, total: int, name: str) -> None:
        if not self._progress:
            return
        if total:
            self._progress.setMaximum(total)
            self._progress.setValue(done)
        self._progress.setLabelText(f"{done}/{total}  {name}")

    def _on_op_done(self, result) -> None:
        self._cleanup_worker()
        # 清索引缓存，下次打开重新扫描
        if self._dataset:
            try:
                index_cache.clear(self._dataset.root_path)
            except Exception:
                pass
        if result.fail_count:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle(self.tr("完成（有失败）"))
            box.setText(
                self.tr("成功 {ok} 个，失败 {fail} 个").format(
                    ok=result.ok_count, fail=result.fail_count
                )
            )
            details = "\n".join(f"{p}\n  → {err}" for p, err in result.failed[:200])
            box.setDetailedText(details)
            box.exec()
        else:
            QMessageBox.information(
                self, self.tr("完成"),
                self.tr("成功 {ok} 个").format(ok=result.ok_count),
            )
        # 刷新当前视图
        self._apply_filter_and_show()

    def _on_op_failed(self, msg: str) -> None:
        self._cleanup_worker()
        QMessageBox.critical(self, self.tr("操作失败"), msg)

    def _cleanup_worker(self) -> None:
        if self._progress:
            self._progress.close()
            self._progress = None
        if self._worker:
            self._worker.deleteLater()
            self._worker = None
