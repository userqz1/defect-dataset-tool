"""Side-by-side before/after preview pane for transforms and augmentations."""
from __future__ import annotations

from io import BytesIO

from PIL import Image
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout
from qfluentwidgets import CaptionLabel

from gui.theme import T


class _ImageSlot(QFrame):
    def __init__(self, title: str) -> None:
        super().__init__()
        self.setObjectName("previewSlot")
        self.setMinimumSize(260, 220)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(T.GAP, T.GAP, T.GAP, T.GAP)
        layout.setSpacing(T.GAP_XS)
        self.title = CaptionLabel(title)
        layout.addWidget(self.title)
        # Dual-use: holds a pixmap (set by set_pil_image) OR a "(无)"
        # fallback text when no image is loaded. CaptionLabel styles the
        # fallback text consistently with the rest of the UI.
        self.image_label = CaptionLabel("(无)")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(240, 180)
        self.image_label.setScaledContents(False)
        layout.addWidget(self.image_label, 1)

    def set_pil_image(self, im: Image.Image | None) -> None:
        if im is None:
            self.image_label.setText("(无)")
            self.image_label.setPixmap(QPixmap())
            return
        # PIL → QPixmap via PNG bytes (cross-version safe)
        buf = BytesIO()
        im.convert("RGB").save(buf, format="PNG")
        pix = QPixmap()
        pix.loadFromData(buf.getvalue(), "PNG")
        target = self.image_label.size()
        if not target.isEmpty():
            pix = pix.scaled(
                target,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self.image_label.setPixmap(pix)


class PreviewPane(QFrame):
    """Two slots: original | result."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("previewPane")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(T.GAP_LG)
        self.before = _ImageSlot("原图")
        self.after = _ImageSlot("效果")
        layout.addWidget(self.before, 1)
        layout.addWidget(self.after, 1)

    def set_before_after(self, before: Image.Image | None, after: Image.Image | None) -> None:
        self.before.set_pil_image(before)
        self.after.set_pil_image(after)
