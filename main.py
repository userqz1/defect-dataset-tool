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
    """One-time migration: copy ~/.defect_dataset_tool → ~/.dataforge.

    Uses shutil.copytree (not rename) so the old dir survives if
    the user downgrades. Writes a marker so it only runs once.
    """
    old = Path.home() / ".defect_dataset_tool"
    new = Path.home() / ".dataforge"
    marker = new / ".migrated"
    if old.is_dir() and not new.exists():
        import shutil
        shutil.copytree(old, new, dirs_exist_ok=True)
        marker.touch()
    elif new.is_dir() and not marker.exists():
        marker.touch()  # mark existing installs as migrated


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
