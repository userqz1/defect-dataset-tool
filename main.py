"""Application entry point."""
from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from gui.main_window import MainWindow

_ICON = Path(__file__).parent / "assets" / "icon.ico"
_APP_DATA = Path.home() / ".dataforge"
_LOG_DIR = _APP_DATA / "logs"

APP_NAME = "数据工坊"  # DataForge


def _setup_logging() -> None:
    """Configure root logger with rotating file + stderr handlers.

    Log file lives at ``~/.dataforge/logs/app.log`` (rotates at 1 MB,
    keeps 5 backups). All modules do ``logger = logging.getLogger(__name__)``
    and inherit this config.
    """
    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # Prevent duplicate handlers on hot-reload (dev)
    root.handlers.clear()

    file_h = logging.handlers.RotatingFileHandler(
        _LOG_DIR / "app.log",
        maxBytes=1_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_h.setFormatter(fmt)
    file_h.setLevel(logging.DEBUG)
    root.addHandler(file_h)

    stderr_h = logging.StreamHandler(sys.stderr)
    stderr_h.setFormatter(fmt)
    stderr_h.setLevel(logging.WARNING)
    root.addHandler(stderr_h)


def _migrate_cache_dir() -> None:
    """One-time migration: copy ~/.defect_dataset_tool → ~/.dataforge.

    Uses shutil.copytree (not rename) so the old dir survives if the user
    downgrades. Writes a marker so it only runs once. Review point #13:
    handle copy failures (disk full / perms / stale handles) without
    crashing the app, and log what was migrated.
    """
    log = logging.getLogger(__name__)
    old = Path.home() / ".defect_dataset_tool"
    new = Path.home() / ".dataforge"
    marker = new / ".migrated"

    if not old.is_dir():
        # Nothing to migrate; mark existing installs as done so we don't
        # re-check every boot.
        if new.is_dir() and not marker.exists():
            try:
                marker.touch()
            except OSError:
                log.warning("could not create .migrated marker", exc_info=True)
        return

    if new.exists() and marker.exists():
        return  # already migrated

    import shutil
    try:
        entry_count = sum(1 for _ in old.rglob("*"))
        log.info("migrating legacy cache %s → %s (%d entries)",
                 old, new, entry_count)
        shutil.copytree(old, new, dirs_exist_ok=True)
        marker.touch()
        log.info("cache migration complete; legacy dir left at %s "
                 "(safe to delete after verifying the app works)", old)
    except (OSError, shutil.Error) as e:
        # Don't block startup — user still has the legacy dir, just
        # without .dataforge-aware features. Surface clearly in log.
        log.error("cache migration FAILED (%s); legacy dir at %s "
                  "left untouched, new dir at %s may be partial",
                  e, old, new, exc_info=True)


def main() -> int:
    _setup_logging()
    logging.getLogger(__name__).info("DataForge starting")
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
