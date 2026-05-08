"""Main window — dataset-browser-first layout.

Navigation (IA v2):
  TOP    — 首页 (DatasetWelcome)  |  浏览器 (DatasetBrowserView)
  BOTTOM — 设置 (SettingsView popup)

OrganizeView is registered on the stack but NOT on the nav rail; it's
reached from inside Browser's 收件箱 stage.

AppState owns the shared Dataset/Project. All views react to its signals.
"""
from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QColor
from qfluentwidgets import (
    FluentIcon as FIF,
    FluentWindow,
    InfoBar,
    InfoBarPosition,
    NavigationItemPosition,
    setTheme,
    setThemeColor,
    Theme,
)

from gui.app_state import AppState
from gui.theme import T, load_qss, set_theme as set_app_theme
from gui.views.settings_view import SettingsView

logger = logging.getLogger(__name__)


def _install_nav_expand_patch() -> None:
    """Monkey-patch qfluentwidgets.NavigationPanel so clicks in collapsed mode
    expand the sidebar before (or instead of) switching interfaces.

    Why this exists (review #8): default NavigationPanel behavior in
    narrow/COMPACT mode is to switch interface silently on click — users hit
    a nav icon, the page switches, but they don't see labels to know what
    they picked. The patched version expands the panel first on a collapsed
    click so labels become visible, preserving click-to-switch on already-
    expanded panels.

    Tested against: qfluentwidgets 1.11 (see requirements.txt pin). The
    patched symbol ``_onWidgetClicked`` is a private attribute; upstream
    rename / signature change will break the patch, so we wrap everything
    in try/except and fall through cleanly — the app still works, just
    without the expand-before-switch behavior.
    """
    try:
        from qfluentwidgets.components.navigation.navigation_panel import (
            NavigationDisplayMode, NavigationPanel,
        )
        if getattr(NavigationPanel, "_dataforge_patched", False):
            return
        original = NavigationPanel._onWidgetClicked

        def patched(self):
            widget = self.sender()
            if widget is None:
                return
            is_narrow = (self.isCollapsed()
                         or self.displayMode == NavigationDisplayMode.COMPACT)
            if not widget.isSelectable:
                if is_narrow:
                    self.expand(useAni=True)
                    return
                return original(self)
            if is_narrow:
                self.expand(useAni=True)
            return original(self)

        NavigationPanel._onWidgetClicked = patched
        NavigationPanel._dataforge_patched = True
    except Exception:
        # qfluentwidgets upstream changed — log once so a maintainer notices
        # the nav UX regressed, but don't crash the app on startup.
        logger.warning(
            "nav expand patch failed — qfluentwidgets API may have changed; "
            "collapsed nav clicks will switch without auto-expanding",
            exc_info=True,
        )


class MainWindow(FluentWindow):

    def __init__(self) -> None:
        _install_nav_expand_patch()
        super().__init__()

        # Install brand title bar BEFORE theme/qss so stylesheet applies
        # to it on first paint. Design §1: brand D chip + serif name +
        # breadcrumb path.
        from gui.widgets.brand_title_bar import BrandTitleBar
        self._brand_bar = BrandTitleBar(self)
        self.setTitleBar(self._brand_bar)

        from core.user_settings import load_settings
        s = load_settings()
        if s.theme == "dark":
            set_app_theme("dark")
            setTheme(Theme.DARK)
        else:
            setTheme(Theme.LIGHT)
        setThemeColor(QColor(T.ACCENT))
        self.setStyleSheet(load_qss())

        self.setWindowTitle("数据工坊")
        # Geometry is finalized AFTER the first show so we know which
        # screen the window actually landed on (primary vs. extended
        # desktop) — sizing eagerly here would always pick primary and
        # mis-place on multi-monitor setups.  Minimum width is set now
        # so the layout solver has a floor to work against during
        # construction.
        self.setMinimumSize(1080, 680)

        # Shared state
        self._state = AppState(parent=self)
        # Title-bar breadcrumbs follow the active dataset.
        self._state.dataset_changed.connect(
            lambda ds: self._brand_bar.set_path(ds.root_path if ds else None)
        )
        # Click brand → return to launchpad. Discoverable single-click
        # exit from any project, no matter how deep the user is.
        self._brand_bar.home_clicked.connect(
            lambda: self.switchTo(self.home)
        )

        try:
            self.navigationInterface.panel.returnButton.hide()
        except Exception:
            # qfluentwidgets internal layout — best-effort tweak.
            logger.debug("hide returnButton failed", exc_info=True)

        self._build_views()
        # Nav-rail clicks set the stackedWidget directly, bypassing
        # our overridden switchTo. Hooking currentChanged catches both
        # paths so the home launchpad refreshes on re-entry whenever
        # the user has mutated a dataset elsewhere.
        self.stackedWidget.currentChanged.connect(self._on_stack_changed)
        self.switchTo(self.home)

        # Design §NavRail is a 60px icon-only rail — *never* auto-expand.
        # qfluentwidgets otherwise re-expands on menu-button click, nav-item
        # click (selectable), or hover. We lock it in three ways:
        #   1. Collapse now, so the first paint is narrow.
        #   2. Hide the ☰ menu button so users can't toggle it manually.
        #   3. Monkey-patch panel.expand() to a no-op so nothing else can
        #      sneak an expand past us (e.g. internal item-click handler).
        try:
            panel = self.navigationInterface.panel
            panel.collapse()
            panel.menuButton.hide()
            panel.expand = lambda *a, **kw: None  # type: ignore[assignment]
        except Exception:
            logger.debug("nav rail lockdown failed", exc_info=True)

        # Geometry: set on the first show so the chosen screen reflects
        # where the window actually landed (multi-monitor setups would
        # otherwise always pick primary).  Guarded against re-firing
        # via _geometry_set.
        self._geometry_set: bool = False

    # ---------- Geometry ----------

    def showEvent(self, event):  # type: ignore[override]
        super().showEvent(event)
        if not self._geometry_set:
            self._geometry_set = True
            # Defer one event-loop tick so QWindow.screen() reports the
            # final landing screen rather than primary.
            QTimer.singleShot(0, self._fit_and_center)

    def _fit_and_center(self) -> None:
        """Pick a sensible default size and center on the active screen.

        Targets 82% × 82% of available screen, capped at 1500×920 so
        ultra-wide displays don't render an unwieldy window.  Prefers
        the screen the window currently lives on (multi-monitor); falls
        back to primary.
        """
        from PyQt6.QtGui import QGuiApplication

        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return
        geom = screen.availableGeometry()
        w = min(int(geom.width() * 0.82), 1500)
        h = min(int(geom.height() * 0.82), 920)
        # Floor at the minimum size so tiny screens still get a usable
        # window — setMinimumSize already enforces this on resize but
        # we want the post-center math to read the same numbers.
        w = max(w, self.minimumWidth())
        h = max(h, self.minimumHeight())
        self.resize(w, h)
        self.move(
            geom.x() + (geom.width() - w) // 2,
            geom.y() + (geom.height() - h) // 2,
        )

    # ---------- Build ----------

    def _build_views(self) -> None:
        from gui.views.dataset_browser_view import DatasetBrowserView
        from gui.views.dataset_welcome import DatasetWelcome
        from gui.views.organize_view import OrganizeView

        # Home — dataset list
        self.home = DatasetWelcome()
        self.home.open_dataset.connect(self._open_dataset)
        self.home.create_project.connect(self._create_project)

        # Organize — batch import → classify → land (v1.2 §9.3).
        # IA v2: OrganizeView is internal-only — registered on the stack so
        # `switchTo(self.organize)` still works for Inbox→import jumps, but
        # NOT added as a nav rail item. The user-visible import entry point
        # is the Browser's "收件箱" stage.
        from gui.controllers.workflow_controller import WorkflowController
        self._wf_ctrl = WorkflowController(self._state)
        self.organize = OrganizeView()
        self.organize.set_state(self._state, self._wf_ctrl)
        self.organize.import_done.connect(self._open_dataset)
        self.stackedWidget.addWidget(self.organize)

        # Browser — top-level dataset browser
        self.browser = DatasetBrowserView(self._state)
        # Inbox stage's "导入新批次" button jumps to OrganizeView; when a
        # project is active, OrganizeView auto-targets project/_inbox/ so
        # the import lands in the current project's inbox. OrganizeView's
        # own import_done signal already bounces back into _open_dataset,
        # which re-enters the browser on completion.
        self.browser.request_organize_view.connect(
            lambda: self.switchTo(self.organize))

        # Settings lives as a floating popup (design handoff §Tweaks) —
        # NOT a routable subInterface. It's parented to MainWindow so popup
        # geometry + Qt.Popup click-outside handling work. Settings only
        # holds global preferences (theme / language / catalog / cache);
        # project-scoped actions (format migration, capabilities, etc.)
        # live in the Browser's 项目中心 stage.
        self.settings_view = SettingsView(self)
        self.settings_view.theme_changed.connect(self._on_theme_changed)
        # The catalog toggle from the popup drives the DatasetBrowserView's
        # own catalog-visibility signal — DatasetBrowserView already handles
        # the in-window visibility state.
        self.settings_view.catalog_toggled.connect(
            lambda on: self.browser._set_catalog_open(on)
        )

        # Nav — TOP (labels via gui.i18n.t — live-updated on language switch).
        # IA v2: only Home and Browser. Organize is reached from inside the
        # Browser's 收件箱 stage; Settings is the bottom gear popup.
        from gui import i18n
        self.addSubInterface(self.home, FIF.HOME_FILL, i18n.t("nav.home"),
                             position=NavigationItemPosition.TOP)
        self.addSubInterface(self.browser, FIF.PHOTO, i18n.t("nav.browser"),
                             position=NavigationItemPosition.TOP)

        # Nav — BOTTOM: gear button opens the floating Tweaks panel.
        # selectable=False keeps it an action (no route highlight on click).
        self.navigationInterface.addItem(
            routeKey="settings-trigger",
            icon=FIF.SETTING,
            text=i18n.t("nav.settings"),
            onClick=self._open_settings_popup,
            selectable=False,
            position=NavigationItemPosition.BOTTOM,
        )
        # Re-label nav items when the language flips. qfluentwidgets stores
        # the display text inside each NavigationTreeWidget item; reach into
        # the widget map to update in place.
        i18n.bus.language_changed.connect(self._relabel_nav)

    # ---------- Dataset operations ----------

    def _open_dataset(self, path_str: str, intent: str = "") -> None:
        """Open a dataset directory — show task type dialog if new.

        ``intent`` (P1.8): one of ``"inbox" / "annotate" / "review" /
        "delivery" / "manage"`` — routes the post-open landing to the
        matching workbench stage.  Empty string defaults to 标注工作台
        (the conventional starting surface).
        """
        root = Path(path_str)
        if not root.is_dir():
            InfoBar.warning("", "目录不存在", parent=self,
                            duration=2000, position=InfoBarPosition.TOP)
            return

        from core.project import load_project

        project = load_project(root)
        if project:
            task_type = project.task_type
        else:
            from gui.dialogs.task_type_dialog import TaskTypeDialog
            dlg = TaskTypeDialog(self)
            if not dlg.exec():
                return
            task_type = dlg.selected_task_type()
            if task_type is None:
                return

        self._state.open_dataset(root, task_type)
        self.browser.open_directory(root)
        self.switchTo(self.browser)
        self._apply_intent(intent)

    def _create_project(self, path_str: str, name: str,
                        preset_id: str, task_type: object) -> None:
        """Create an empty project and switch to browser.

        New projects always land on 新数据 — there's no data yet, so
        the conventional default (标注工作台) would show an empty grid
        and confuse the user.  Inbox is where they need to be.
        """
        root = Path(path_str)
        self._state.open_project(  # type: ignore[arg-type]
            root, name, task_type, preset_id=preset_id)
        self.browser.open_directory(root)
        self.switchTo(self.browser)
        self._apply_intent("inbox")
        self.home.refresh()

    def _apply_intent(self, intent: str) -> None:
        """Map a welcome-page intent string → workbench stage swap.

        Empty intent / unknown intent → keep the workbench's own default
        landing (which since IA v2 phase 1 is the OVERVIEW stage).
        """
        if not intent:
            return
        from gui.widgets.workspace_sidebar import StageIndex
        intent_to_stage = {
            "overview": StageIndex.OVERVIEW,
            "inbox":    StageIndex.INBOX,
            "process":  StageIndex.PROCESS,
            "annotate": StageIndex.ANNOTATE,
            "review":   StageIndex.REVIEW,
            "delivery": StageIndex.DELIVERY,
        }
        stage = intent_to_stage.get(intent)
        if stage is not None:
            self.browser.set_active_stage(stage)

    # ---------- i18n ----------

    def _relabel_nav(self, _lang: str) -> None:
        """Re-apply translated labels on the nav panel.

        qfluentwidgets' NavigationPanel stores ``{routeKey: NavigationItem}``
        in ``panel.items``; each NavigationItem wraps the actual button
        widget under ``.widget``. The button has a ``setText`` method.
        """
        from gui import i18n
        panel = self.navigationInterface.panel
        mapping = {
            self.home.objectName(): i18n.t("nav.home"),
            self.browser.objectName(): i18n.t("nav.browser"),
            "settings-trigger": i18n.t("nav.settings"),
        }
        for key, label in mapping.items():
            item = panel.items.get(key)
            w = getattr(item, "widget", None) if item else None
            if w is not None and hasattr(w, "setText"):
                try:
                    w.setText(label)
                except Exception:
                    logger.debug("relabel failed for %s", key, exc_info=True)

    # ---------- Settings popup ----------

    def _open_settings_popup(self) -> None:
        """Show the settings popup at window-bottom-left, right of the rail.

        Design §Tweaks positions the panel at ``left: 68px; bottom: 16px``
        of the viewport. We follow that literally using the main window's
        own geometry so it doesn't matter whether the nav panel is using
        its icon-only or (long-deprecated) expanded width.
        """
        self.settings_view.adjustSize()
        mw_tl_global = self.mapToGlobal(self.rect().topLeft())
        x = mw_tl_global.x() + 68
        y = mw_tl_global.y() + self.height() - self.settings_view.height() - 16
        self.settings_view.move(x, y)
        self.settings_view.show()
        self.settings_view.raise_()

    # ---------- Navigation ----------

    def switchTo(self, interface):
        # Refresh logic lives on the stackedWidget hook below so nav-rail
        # clicks (which bypass this override) get the same treatment.
        super().switchTo(interface)

    def _on_stack_changed(self, index: int) -> None:
        """Refresh the home page whenever it becomes the visible interface.

        The nav rail's "首页" click routes through ``stackedWidget``
        directly, bypassing our overridden :meth:`switchTo`. Hooking
        ``currentChanged`` catches every path — programmatic
        ``switchTo`` plus user clicks on the rail — so deletions /
        adds in the workbench show up the next time the user lands
        on the home launchpad without any manual refresh.

        Refresh is cheap: reads ``recent.json`` + each project's
        ``.dataforge/*.json``; firing it on every interface swap is
        fine.
        """
        try:
            if self.stackedWidget.widget(index) is self.home:
                self.home.refresh()
        except Exception:
            logger.debug("home refresh on stack-change failed",
                          exc_info=True)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # Force collapse on every resize — qfluentwidgets' internal logic
        # otherwise re-expands the panel at wider widths. Design §NavRail
        # mandates a constant 60px icon-only rail.
        try:
            panel = self.navigationInterface.panel
            if not panel.isCollapsed():
                panel.collapse()
        except Exception:
            logger.debug("nav resize collapse failed", exc_info=True)

    def _on_theme_changed(self, name: str) -> None:
        set_app_theme(name, window=self)
        setTheme(Theme.DARK if name == "dark" else Theme.LIGHT)
        setThemeColor(QColor(T.ACCENT))
        from core.user_settings import save_settings, UserSettings
        save_settings(UserSettings(theme=name))

    def closeEvent(self, e):
        self._state.close_dataset()
        self.browser.cleanup()
        super().closeEvent(e)
