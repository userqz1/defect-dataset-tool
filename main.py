"""Application entry point."""
from __future__ import annotations

import faulthandler
import logging
import logging.handlers
import sys
import threading
import traceback
from pathlib import Path

from PyQt6.QtCore import QtMsgType, qInstallMessageHandler
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from gui.main_window import MainWindow

_ICON = Path(__file__).parent / "assets" / "icon.ico"
_APP_DATA = Path.home() / ".dataforge"
_LOG_DIR = _APP_DATA / "logs"
_WINDOWS_APP_ID = "DataForge.DatasetWorkbench"

APP_NAME = "数据工坊"  # DataForge

# Module-level ref to keep the fault-handler file alive for process
# lifetime. If this gets garbage-collected, faulthandler's fd becomes
# invalid and a future segfault would land nowhere.
_fault_file = None


def _setup_logging() -> None:
    """Configure root logger + route uncaught errors into the same log.

    Paths:
        ~/.dataforge/logs/app.log   — Python-level (rotates 1 MB × 5)
        ~/.dataforge/logs/fault.log — C-level tracebacks (segfault / SEH)

    Captured:
        1. All ``logger.*`` calls from any module (inherited config).
        2. Uncaught Python exceptions on the main thread (sys.excepthook).
        3. Uncaught exceptions from QThread / threading.Thread workers
           (threading.excepthook).
        4. Qt C++ warnings / critical / fatal messages (Qt message handler).
        5. Native crashes — segfault, SEH, access violation — dumped to
           fault.log via faulthandler before the process exits.
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

    _install_excepthooks()
    _install_qt_message_handler()
    _install_faulthandler()


def _install_excepthooks() -> None:
    """Route uncaught Python exceptions (main + worker threads) to logger."""
    log = logging.getLogger("uncaught")

    def _hook(exc_type, exc_value, tb):
        # Let KeyboardInterrupt propagate so Ctrl+C still exits cleanly.
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, tb)
            return
        log.error("uncaught exception",
                  exc_info=(exc_type, exc_value, tb))

    sys.excepthook = _hook

    def _thread_hook(args: threading.ExceptHookArgs):
        if issubclass(args.exc_type, SystemExit):
            return
        log.error("uncaught thread exception in %s",
                  args.thread.name if args.thread else "?",
                  exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    threading.excepthook = _thread_hook


def _install_qt_message_handler() -> None:
    """Forward Qt's own C++ qWarning/qCritical/qFatal to logging."""
    log = logging.getLogger("qt")
    level_map = {
        QtMsgType.QtDebugMsg: logging.DEBUG,
        QtMsgType.QtInfoMsg: logging.INFO,
        QtMsgType.QtWarningMsg: logging.WARNING,
        QtMsgType.QtCriticalMsg: logging.ERROR,
        QtMsgType.QtFatalMsg: logging.CRITICAL,
    }

    def _handler(msg_type, context, msg):
        level = level_map.get(msg_type, logging.INFO)
        # Some Qt messages bring file+line via context; include when present.
        where = ""
        if context and context.file:
            where = f" ({context.file}:{context.line})"
        log.log(level, "%s%s", msg, where)

    qInstallMessageHandler(_handler)


def _install_faulthandler() -> None:
    """Dump the C-level traceback of any native crash to fault.log.

    Opened with ``buffering=1`` (line-buffered) and a module-level
    reference so the fd stays valid for the whole process. faulthandler
    writes via raw fd on crash, so Python-side buffering isn't a concern.
    """
    global _fault_file
    fault_path = _LOG_DIR / "fault.log"
    # Line-mark run boundaries so multiple crashes across sessions stay
    # distinguishable in the appended file.
    _fault_file = open(fault_path, "a", buffering=1, encoding="utf-8")
    try:
        import datetime as _dt
        _fault_file.write(
            f"\n===== run started {_dt.datetime.now().isoformat()} =====\n"
        )
        _fault_file.flush()
    except Exception:
        pass
    faulthandler.enable(file=_fault_file, all_threads=True)


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


def _install_windows_app_id() -> None:
    """Register a stable Windows taskbar identity before Qt starts."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            _WINDOWS_APP_ID
        )
    except Exception:
        logging.getLogger(__name__).warning(
            "failed to set Windows AppUserModelID", exc_info=True
        )


def _load_app_icon() -> QIcon | None:
    if not _ICON.exists():
        logging.getLogger(__name__).warning("app icon not found: %s", _ICON)
        return None
    icon = QIcon(str(_ICON))
    if icon.isNull():
        logging.getLogger(__name__).warning("app icon failed to load: %s", _ICON)
        return None
    return icon


def main() -> int:
    _setup_logging()
    log = logging.getLogger(__name__)
    log.info("DataForge starting")
    _migrate_cache_dir()
    _install_windows_app_id()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName("DataForge")
    icon = _load_app_icon()
    if icon is not None:
        app.setWindowIcon(icon)

    # Root-cause fix for the "自动闪退": Qt's quitOnLastWindowClosed would
    # auto-quit the whole app when some transient top-level (an async popup /
    # tooltip / flyout) closed while it happened to be the last visible
    # window.  Turn that auto-quit OFF; the app now exits only when the main
    # window's closeEvent explicitly quits (see MainWindow.closeEvent).
    app.setQuitOnLastWindowClosed(False)

    window = MainWindow()
    if icon is not None:
        window.setWindowIcon(icon)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
