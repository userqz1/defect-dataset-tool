"""Abstract base class for node workspace views.

Every pipeline node that has a dedicated workspace (double-click to open)
inherits from this class. The contract:

- ``bind_node(node_item)``: Set the NodeItem reference + load params into UI.
- ``_push_params()``: Write current UI state back to NodeItem (called on every
  control change via signals wired in __init__).
- ``set_dataset(dataset)``: Receive the current dataset for display / config.

Result display is NOT a workspace responsibility — it lives in the
``NodePreviewPanel`` on the right side of the canvas.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget

from core.models import Dataset


class NodeWorkspace(QWidget):
    """Base class for node workspace views bound to pipeline nodes."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._dataset: Dataset | None = None
        self._node_item = None  # NodeItem — single source of truth for params

    def bind_node(self, node_item) -> None:
        """Bind to a NodeItem: store reference + load params into UI controls.

        Subclasses MUST override this. Use ``blockSignals(True)`` on each
        control before setting values to avoid feedback loops.
        """
        self._node_item = node_item

    def _push_params(self) -> None:
        """Write current UI control values back to NodeItem.

        Called automatically on every control change (connected in __init__).
        Subclasses MUST override this.
        """

    def set_dataset(self, dataset: Dataset | None) -> None:
        """Receive the current dataset. Subclasses override for UI updates."""
        self._dataset = dataset
