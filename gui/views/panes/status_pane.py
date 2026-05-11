"""状态 pane — workflow status + transition actions.

Only instantiated when ``TaskWorkbenchSpec.has_status`` is True. In
practice every real task has workflow state, so the flag exists only
so a future view-only spec could skip it.

Three buttons gate themselves by the current status:

    new / prelabeled / annotating / needs_fix → [标注完成]
    review_pending                             → [通过] [需修补]
    ready / exported                           → nothing
"""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CaptionLabel,
    PrimaryPushButton,
    PushButton,
)

from gui import i18n
from gui.theme import T


# Lives at module scope so shell code (_on_save) can reuse the same
# mapping for its InfoBar messages without importing the pane class.
WF_STATUS_LABELS: dict[str, str] = {
    "new":            "● 新建",
    "prelabeled":     "● 预标注",
    "annotating":     "● 标注中",
    "review_pending": "● 待审核",
    "needs_fix":      "● 需修补",
    "ready":          "✓ 就绪",
    "exported":       "✓ 已导出",
}


class StatusPane(QWidget):
    """状态 segment body — current status + transition buttons."""

    # Payload: new status key ("review_pending" / "ready" / "needs_fix").
    status_change_requested = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(T.GAP_LG)

        self._status_label = CaptionLabel("—")
        self._status_label.setObjectName("statValue")
        lay.addWidget(self._status_label)

        row = QHBoxLayout()
        row.setSpacing(T.GAP_XS)
        self._submit_btn = PrimaryPushButton(i18n.t("wf.submit_review"))
        self._submit_btn.setFixedHeight(28)
        self._submit_btn.clicked.connect(
            lambda: self.status_change_requested.emit("review_pending"))
        row.addWidget(self._submit_btn)

        self._approve_btn = PushButton(i18n.t("wf.approve"))
        self._approve_btn.setFixedHeight(28)
        self._approve_btn.clicked.connect(
            lambda: self.status_change_requested.emit("ready"))
        row.addWidget(self._approve_btn)

        self._reject_btn = PushButton(i18n.t("wf.reject"))
        self._reject_btn.setFixedHeight(28)
        self._reject_btn.clicked.connect(
            lambda: self.status_change_requested.emit("needs_fix"))
        row.addWidget(self._reject_btn)
        lay.addLayout(row)

        lay.addStretch(1)

        # Hide everything until the first image loads (set_status is what
        # flips visibility back on).  Matches the previous DetailView
        # behaviour where wf widgets were only visible for images with
        # actual workflow state.
        self._all_widgets = (self._status_label, self._submit_btn,
                             self._approve_btn, self._reject_btn)
        for w in self._all_widgets:
            w.setVisible(False)

    # ---------- public API ----------

    def set_status(self, status: str) -> None:
        """Update label + button visibility for ``status``.

        Empty ``status`` means 'no workflow for this image' → hide
        everything (matches the original per-image gating where images
        without a Sample.work_status showed no workflow row).
        """
        has_wf = bool(status)
        self._status_label.setVisible(has_wf)
        if not has_wf:
            for b in (self._submit_btn, self._approve_btn, self._reject_btn):
                b.setVisible(False)
            return
        self._status_label.setText(
            WF_STATUS_LABELS.get(status, status))
        self._submit_btn.setVisible(
            status in ("new", "prelabeled", "annotating", "needs_fix"))
        self._approve_btn.setVisible(status == "review_pending")
        self._reject_btn.setVisible(status == "review_pending")
