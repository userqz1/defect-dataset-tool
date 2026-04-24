"""Migrate project annotation format dialog.

Lets the user switch the project's primary annotation format. Shows
conversion hints, then runs in-place migration + optional round-trip
validation. Updates Project.annotation_format on success.
"""
from __future__ import annotations

from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CheckBox,
    ComboBox,
    MessageBoxBase,
    StrongBodyLabel,
    SubtitleLabel,
)

from core.format_convert import (
    FORMATS,
    conversion_hints,
    writeback_formats,
)


_MIGRATE_TARGETS = [
    (k, FORMATS[k].display_name)
    for k in writeback_formats()
]


class MigrateFormatDialog(MessageBoxBase):
    """Confirm project format migration: current → target."""

    def __init__(self, current_format: str, n_labeled: int,
                 parent=None) -> None:
        super().__init__(parent=parent)
        self.widget.setMinimumWidth(480)
        self.yesButton.setText("迁移")
        self.cancelButton.setText("取消")

        self._current = current_format

        self.titleLabel = SubtitleLabel("切换主标注格式", self)
        self.viewLayout.addWidget(self.titleLabel)

        # Current format display
        cur_name = FORMATS.get(current_format)
        cur_disp = cur_name.display_name if cur_name else current_format
        self.viewLayout.addWidget(
            BodyLabel(f"当前格式: {cur_disp}", self))

        # Target format
        self.viewLayout.addWidget(BodyLabel("目标格式", self))
        self._target_combo = ComboBox(self)
        for key, name in _MIGRATE_TARGETS:
            self._target_combo.addItem(name)
        # Pre-select next format (skip current)
        for i, (key, _) in enumerate(_MIGRATE_TARGETS):
            if key != current_format:
                self._target_combo.setCurrentIndex(i)
                break
        self.viewLayout.addWidget(self._target_combo)

        # Scope info
        self.viewLayout.addWidget(
            CaptionLabel(f"{n_labeled:,} 个已标注文件将被��换", self))

        # Round-trip validation option
        self._validate_chk = CheckBox("迁移后 round-trip 验证", self)
        self.viewLayout.addWidget(self._validate_chk)

        # Hints
        self._hints_label = StrongBodyLabel("", self)
        self.viewLayout.addWidget(self._hints_label)
        self._hints_body = CaptionLabel("", self)
        self._hints_body.setWordWrap(True)
        self.viewLayout.addWidget(self._hints_body)

        self._target_combo.currentIndexChanged.connect(self._refresh)
        self._refresh()

    def _target_key(self) -> str:
        idx = self._target_combo.currentIndex()
        return _MIGRATE_TARGETS[idx][0] if 0 <= idx < len(_MIGRATE_TARGETS) else ""

    def _refresh(self) -> None:
        target = self._target_key()
        same = (target == self._current)
        self.yesButton.setEnabled(not same)

        if same or not target:
            self._hints_label.setText("")
            self._hints_body.setText("")
            return

        hint = conversion_hints(self._current, target)
        lines: list[str] = []
        if hint.preserved:
            lines.append(f"[preserved] {', '.join(hint.preserved)}")
        if hint.degraded:
            lines.append(f"[degraded] {', '.join(hint.degraded)}")
        if hint.lost:
            lines.append(f"[lost] {', '.join(hint.lost)}")
        for n in hint.notes:
            lines.append(f"  {n}")

        src_info = FORMATS.get(self._current)
        dst_info = FORMATS.get(target)
        src_name = src_info.display_name if src_info else self._current
        dst_name = dst_info.display_name if dst_info else target
        self._hints_label.setText(f"{src_name} -> {dst_name}")
        self._hints_body.setText("\n".join(lines) if lines else "")

    def migrate_options(self) -> dict:
        return {
            "target_format": self._target_key(),
            "validate": self._validate_chk.isChecked(),
        }
