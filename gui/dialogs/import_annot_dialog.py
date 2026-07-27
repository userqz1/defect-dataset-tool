"""Annotation import dialog — import labels from external annotation files.

Lets the user point to annotation files in a specific format and merge
them into the current dataset. The dialog only collects parameters;
the caller drives execution.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFileDialog, QHBoxLayout
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CheckBox,
    ComboBox,
    MessageBoxBase,
    PushButton,
    SubtitleLabel,
)


_FORMAT_ITEMS = [
    ("labelme", "LabelMe JSON (.json)"),
    ("yolo", "YOLO TXT (.txt)"),
    ("yoloobb", "YOLO-OBB TXT (.txt)"),
    ("dota", "DOTA labelTxt (.txt)"),
    ("voc", "Pascal VOC XML (.xml)"),
    ("coco", "COCO JSON (.json)"),
    ("vlm_jsonl", "VLM JSONL — LLaVA / ShareGPT / Swift (.jsonl)"),
    ("caption_sidecar", "Caption sidecars (folder · *.txt)"),
    ("conversations_sidecar", "Conversations sidecars (folder · *.conversations.json)"),
    ("image_labels_sidecar", "Multi-label sidecars (folder · *.labels.json)"),
]


class ImportAnnotDialog(MessageBoxBase):
    """Collect annotation-import parameters: format + source path."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent=parent)
        self.widget.setMinimumWidth(480)
        self.yesButton.setText("导入")
        self.cancelButton.setText("取消")

        self.titleLabel = SubtitleLabel("导入标注", self)
        self.viewLayout.addWidget(self.titleLabel)

        # Format selector
        self.viewLayout.addWidget(BodyLabel("标注格式", self))
        self._fmt_combo = ComboBox(self)
        for _, display in _FORMAT_ITEMS:
            self._fmt_combo.addItem(display)
        self.viewLayout.addWidget(self._fmt_combo)

        # Source path
        self.viewLayout.addWidget(BodyLabel("标注文件 / 目录", self))
        path_row = QHBoxLayout()
        self._path_label = CaptionLabel("未选择", self)
        self._path_label.setWordWrap(True)
        path_row.addWidget(self._path_label, 1)
        # CLAUDE.md gotcha: no setFixedWidth on text-bearing buttons.
        pick_btn = PushButton("选择", self)
        pick_btn.clicked.connect(self._pick_source)
        path_row.addWidget(pick_btn)
        self.viewLayout.addLayout(path_row)

        # Options
        self._overwrite_chk = CheckBox("覆盖已有标注", self)
        self.viewLayout.addWidget(self._overwrite_chk)

        self._source_path: Path | None = None
        self._update_ok()

    def _pick_source(self) -> None:
        fmt_key = self._format_key()
        # File-based formats need the file picker; folder-based formats
        # (per-image sidecars) need the directory picker.
        single_file_fmts = {"coco", "vlm_jsonl"}
        if fmt_key in single_file_fmts:
            filters = {
                "coco": "COCO JSON (*.json)",
                "vlm_jsonl": "JSONL (*.jsonl);;JSON (*.json)",
            }
            path, _ = QFileDialog.getOpenFileName(
                self, "选择标注文件", str(Path.home()),
                filters.get(fmt_key, "All (*)"))
            if path:
                self._source_path = Path(path)
                self._path_label.setText(str(self._source_path))
        else:
            # Directory (per-image annotation files / sidecars)
            d = QFileDialog.getExistingDirectory(
                self, "选择标注目录", str(Path.home()))
            if d:
                self._source_path = Path(d)
                self._path_label.setText(str(self._source_path))
        self._update_ok()

    def _format_key(self) -> str:
        idx = self._fmt_combo.currentIndex()
        return _FORMAT_ITEMS[idx][0] if 0 <= idx < len(_FORMAT_ITEMS) else "labelme"

    def _update_ok(self) -> None:
        self.yesButton.setEnabled(self._source_path is not None)

    def import_options(self) -> dict:
        return {
            "format": self._format_key(),
            "source_path": self._source_path,
            "overwrite": self._overwrite_chk.isChecked(),
        }
