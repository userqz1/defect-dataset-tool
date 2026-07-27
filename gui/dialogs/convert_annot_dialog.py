"""Annotation conversion wizard — source format -> target format.

Shows field mapping, loss hints, and optional round-trip validation.
The dialog only collects parameters; the caller drives execution.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QFileDialog, QHBoxLayout
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CheckBox,
    ComboBox,
    MessageBoxBase,
    PushButton,
    StrongBodyLabel,
    SubtitleLabel,
)

from core.format_convert import (
    FORMATS,
    conversion_hints,
)


# Formats that have both readers and writers (round-trippable subset)
_CONVERT_FORMATS = [
    ("labelme", "LabelMe JSON"),
    ("yolo", "YOLO TXT"),
    ("voc", "Pascal VOC XML"),
    ("coco", "COCO JSON"),
    ("csv", "CSV"),
    ("jsonl", "JSONL"),
    ("llava", "LLaVA JSONL"),
    ("sharegpt", "ShareGPT JSON"),
    ("swift", "Swift JSONL"),
]


class ConvertAnnotDialog(MessageBoxBase):
    """Conversion wizard: pick source/target formats, show loss hints."""

    def __init__(self, current_format: str = "", parent=None) -> None:
        super().__init__(parent=parent)
        self.widget.setMinimumWidth(520)
        self.yesButton.setText("转换")
        self.cancelButton.setText("取消")

        self.titleLabel = SubtitleLabel("标注格式转换", self)
        self.viewLayout.addWidget(self.titleLabel)

        # Source format
        self.viewLayout.addWidget(BodyLabel("源格式", self))
        self._src_combo = ComboBox(self)
        for key, name in _CONVERT_FORMATS:
            self._src_combo.addItem(name)
        # Pre-select current format
        for i, (key, _) in enumerate(_CONVERT_FORMATS):
            if key == current_format:
                self._src_combo.setCurrentIndex(i)
                break
        self.viewLayout.addWidget(self._src_combo)

        # Target format
        self.viewLayout.addWidget(BodyLabel("目标格式", self))
        self._dst_combo = ComboBox(self)
        for key, name in _CONVERT_FORMATS:
            self._dst_combo.addItem(name)
        self.viewLayout.addWidget(self._dst_combo)

        # Output directory
        self.viewLayout.addWidget(BodyLabel("输出目录", self))
        path_row = QHBoxLayout()
        self._out_label = CaptionLabel("未选择", self)
        self._out_label.setWordWrap(True)
        path_row.addWidget(self._out_label, 1)
        # CLAUDE.md gotcha: no setFixedWidth on text-bearing buttons
        # — let the button shrink-wrap its label.
        pick_btn = PushButton("选择", self)
        pick_btn.clicked.connect(self._pick_output)
        path_row.addWidget(pick_btn)
        self.viewLayout.addLayout(path_row)

        # Options
        self._copy_images_chk = CheckBox("复制图片到输出目录", self)
        self._copy_images_chk.setChecked(True)
        self.viewLayout.addWidget(self._copy_images_chk)

        self._validate_chk = CheckBox("转换后 round-trip 验证", self)
        self.viewLayout.addWidget(self._validate_chk)

        # Hints panel
        self._hints_title = StrongBodyLabel("", self)
        self.viewLayout.addWidget(self._hints_title)
        self._hints_body = CaptionLabel("", self)
        self._hints_body.setWordWrap(True)
        self.viewLayout.addWidget(self._hints_body)

        self._out_dir: Path | None = None

        # Wire combo changes to update hints
        self._src_combo.currentIndexChanged.connect(self._refresh_hints)
        self._dst_combo.currentIndexChanged.connect(self._refresh_hints)
        self._refresh_hints()
        self._update_ok()

    def _pick_output(self) -> None:
        d = QFileDialog.getExistingDirectory(
            self, "选择输出目录", str(Path.home()))
        if d:
            self._out_dir = Path(d)
            self._out_label.setText(str(self._out_dir))
        self._update_ok()

    def _update_ok(self) -> None:
        src_key = self._format_key(self._src_combo)
        dst_key = self._format_key(self._dst_combo)
        self.yesButton.setEnabled(
            self._out_dir is not None and src_key != dst_key)

    def _format_key(self, combo: ComboBox) -> str:
        idx = combo.currentIndex()
        return _CONVERT_FORMATS[idx][0] if 0 <= idx < len(_CONVERT_FORMATS) else ""

    def _refresh_hints(self) -> None:
        src = self._format_key(self._src_combo)
        dst = self._format_key(self._dst_combo)
        if not src or not dst or src == dst:
            self._hints_title.setText("")
            self._hints_body.setText("")
            self._update_ok()
            return

        hint = conversion_hints(src, dst)
        lines: list[str] = []
        if hint.preserved:
            lines.append(f"[preserved] {', '.join(hint.preserved)}")
        if hint.degraded:
            lines.append(f"[degraded] {', '.join(hint.degraded)}")
        if hint.lost:
            lines.append(f"[lost] {', '.join(hint.lost)}")
        if hint.notes:
            for n in hint.notes:
                lines.append(f"  {n}")

        src_name = FORMATS.get(src, src)
        dst_name = FORMATS.get(dst, dst)
        if isinstance(src_name, str):
            src_disp = src_name
        else:
            src_disp = src_name.display_name
        if isinstance(dst_name, str):
            dst_disp = dst_name
        else:
            dst_disp = dst_name.display_name

        self._hints_title.setText(f"{src_disp} -> {dst_disp}")
        self._hints_body.setText("\n".join(lines) if lines else "")
        self._update_ok()

    def convert_options(self) -> dict:
        return {
            "src_format": self._format_key(self._src_combo),
            "dst_format": self._format_key(self._dst_combo),
            "out_dir": self._out_dir,
            "copy_images": self._copy_images_chk.isChecked(),
            "validate": self._validate_chk.isChecked(),
        }
