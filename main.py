"""Application entry point."""
from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from gui.main_window import MainWindow

_ICON = Path(__file__).parent / "assets" / "icon.ico"

APP_NAME = "数据工坊"  # DataForge


def _migrate_cache_dir() -> None:
    """One-time migration: rename ~/.defect_dataset_tool → ~/.dataforge."""
    old = Path.home() / ".defect_dataset_tool"
    new = Path.home() / ".dataforge"
    if old.is_dir() and not new.exists():
        old.rename(new)


def main() -> int:
    _migrate_cache_dir()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    if _ICON.exists():
        app.setWindowIcon(QIcon(str(_ICON)))
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
