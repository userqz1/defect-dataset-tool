"""Application entry point."""
from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from gui.main_window import MainWindow

_ICON = Path(__file__).parent / "assets" / "icon.ico"

APP_NAME = "数据坊"  # DataForge


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    if _ICON.exists():
        app.setWindowIcon(QIcon(str(_ICON)))
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
