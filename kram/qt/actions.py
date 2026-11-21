"""The main window's QActions and menus, built from kram.app.actions and kram.app.preferences. What the actions do,
the window connects."""
import html

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup, QIcon, QKeySequence
from PySide6.QtWidgets import QMenu, QMenuBar, QWidget

from ..app import preferences
from ..app.actions import (
    MARK_ACTIONS,
    TABLE_SHORTCUT_ACTIONS,
    ActionDef,
    ActionState,
    DynamicItem,
    Menu,
    MenuItem,
    action_defs,
    downgrade_submenu,
    mark_id,
    mark_upgrades_id,
    mark_upgrades_menu,
    menu_bar,
    package_menu_items,
)
from ..app.preferences import Pref
from ..core.filters import UPGRADES_FIXES, UPGRADES_SECURITY, UPGRADES_SECURITY_HIGH
from .icons import icon as painted_icon

TOOLKIT = "qt"
# the platform's own keys for these (the data says Ctrl+F, Ctrl+Q): what the desktop's other apps use
STANDARD_KEYS = {"find": QKeySequence.StandardKey.Find, "quit": QKeySequence.StandardKey.Quit}
WRAP_TIP = 100  # Qt does not wrap a plain-text tooltip: a longer one goes in as rich text, which it wraps


def qicon(name) -> QIcon:
    """A theme icon by name, or a painted one by kram.app.icons.IconRef."""
    if name is None:
        return QIcon()
    return painted_icon(name) if isinstance(name, tuple) else QIcon.fromTheme(name)


def fill_dynamic(menu: QMenu, items: list[DynamicItem]) -> None:
    for item in items:
        act = menu.addAction(qicon(item.icon), item.label)
        if item.run is not None:
            act.triggered.connect(lambda _on=False, run=item.run: run())
        act.setEnabled(item.enabled)
        if item.tip:
            act.setToolTip(item.tip)


class WindowActions:
    def __init__(self, window: QWidget):
        self._window = window
        self.by_id: dict[str, QAction] = {d.id: self._action(d) for d in action_defs()}
        for name in ("reload", "reload_cache", "mark_upgrades", "mark_unneeded", "apply", "unmark_all", "properties",
                     "repos", "filters", "new_filter", "copr", "cache", "notifications", "find", "back",
                     "save_marks", "read_marks", "export_csv", "history", "open_file", "quit", "about", "copy_name",
                     "copy_nevra", "lock", "unlock", "show_in_history", "why_blocked", "unmark"):
            setattr(self, name, self.by_id[name])
        self.mark_upgrades_of_kind = {kind: self.by_id[mark_upgrades_id(kind)]
                                      for kind in (UPGRADES_SECURITY, UPGRADES_SECURITY_HIGH, UPGRADES_FIXES)}
        self.mark: dict = {action: self.by_id[mark_id(action)] for action in MARK_ACTIONS}
        self.mark_upgrades_menu = self._build_menu(mark_upgrades_menu())
        submenu = downgrade_submenu()
        self.downgrade_menu = QMenu(submenu.title, window)
        self.downgrade_menu.setIcon(qicon(submenu.icon))
        # Breeze's monochrome update glyphs match the other toolbar icons; system-software-update is a colour app
        # icon there, kept as the fallback. With upgrades to mark the button shows update-medium; update-none says
        # "nothing to update" and its dim grey is exactly right for the disabled button, but would make an enabled
        # one look disabled
        fallback = QIcon.fromTheme("system-software-update")
        self._upgrade_icons = {True: QIcon.fromTheme("update-medium", fallback),
                               False: QIcon.fromTheme("update-none", fallback)}
        # the settings of kram.app.preferences: a checkable action per bool, a group of them per choice
        self.prefs: dict[str, QAction] = {}
        self.pref_groups: dict[str, QActionGroup] = {}
        for pref in preferences.prefs_for(TOOLKIT):
            if pref.kind == "bool":
                self.prefs[pref.key] = self._bool_pref(pref)
            elif pref.kind == "choice":
                self.pref_groups[pref.key] = self._choice_pref(pref)
        self.status_click = self.prefs[preferences.STATUS_CLICK]
        self.watch_releases = self.prefs[preferences.WATCH_RELEASES]
        self.toolbar_styles = self.pref_groups[preferences.TOOLBAR_STYLE]
        self.set_upgrades_available(False)

    def _action(self, d: ActionDef) -> QAction:
        a = QAction(qicon(d.icon), d.label, self._window)
        if d.id in STANDARD_KEYS:
            a.setShortcut(QKeySequence(STANDARD_KEYS[d.id]))
        elif d.shortcuts:
            a.setShortcuts([QKeySequence(s) for s in d.shortcuts])
        a.setEnabled(d.enabled)
        a.setVisible(d.visible)
        if d.tip:
            a.setToolTip(d.tip)
            a.setStatusTip(d.tip)
        if d.scope == "table":
            a.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        else:
            self._window.addAction(a)  # shortcuts work even when the action is only in a menu
        return a

    def _bool_pref(self, pref: Pref) -> QAction:
        a = QAction(pref.label, self._window, checkable=True)
        if pref.tip:
            a.setToolTip(f"<p>{html.escape(pref.tip)}</p>" if len(pref.tip) > WRAP_TIP else pref.tip)
            a.setStatusTip(pref.tip)
        a.setVisible(pref.visible())
        a.setChecked(preferences.value(pref))
        a.toggled.connect(lambda on: preferences.set_value(pref, on))
        return a

    def _choice_pref(self, pref: Pref) -> QActionGroup:
        group = QActionGroup(self._window)
        current = preferences.value(pref)
        for choice, label in pref.choices:
            a = group.addAction(label)
            a.setCheckable(True)
            a.setData(choice)
            a.setChecked(choice == current)
        group.triggered.connect(lambda a: preferences.set_value(pref, a.data()))
        return group

    def table_actions(self) -> list[QAction]:
        """For the package table to add: their shortcuts work only there."""
        return [self.by_id[i] for i in TABLE_SHORTCUT_ACTIONS]

    def set_upgrades_available(self, available: bool) -> None:
        self.mark_upgrades.setEnabled(available)
        self.mark_upgrades_menu.setEnabled(available)
        self.mark_upgrades.setIcon(self._upgrade_icons[available])

    def apply_state(self, state: ActionState, extra: dict[str, QAction] | None = None) -> None:
        """Enable and show the actions as kram.app.actions.action_state says. `extra`: actions of other parts
        (the new-release button) by id."""
        extra = extra or {}
        for action_id, on in state.enabled.items():
            if action_id == "downgrade":
                self.downgrade_menu.setEnabled(on)
            elif action_id == "mark_upgrades_menu":
                self.set_upgrades_available(on)
            elif action_id in self.by_id:
                if action_id != "mark_upgrades":  # with its menu above
                    self.by_id[action_id].setEnabled(on)
            elif action_id in extra:
                extra[action_id].setEnabled(on)
        for action_id, on in state.visible.items():
            self.by_id[action_id].setVisible(on)

    # ---------------------------------------------------------------- menus

    def _build_menu(self, menu: Menu) -> QMenu:
        if menu.id == "mark_upgrades" and hasattr(self, "mark_upgrades_menu"):
            return self.mark_upgrades_menu  # one menu: the toolbar button's and the Edit menu's
        if menu.id == "downgrade":
            return self.downgrade_menu
        m = QMenu(menu.title, self._window)
        if menu.icon:
            m.setIcon(qicon(menu.icon))
        self.fill(m, menu.items)
        return m

    def fill(self, menu: QMenu, items: tuple[MenuItem, ...]) -> None:
        for item in items:
            if item.separator:
                menu.addSeparator()
            elif item.action is not None:
                menu.addAction(self.by_id[item.action])
            elif item.submenu is not None:
                menu.addMenu(self._build_menu(item.submenu))
            elif item.prefs is not None:
                menu.setToolTipsVisible(True)
                for pref in preferences.prefs_for(TOOLKIT, item.prefs):
                    if pref.kind == "bool":
                        menu.addAction(self.prefs[pref.key])
                    elif pref.kind == "choice":
                        menu.addMenu(pref.label).addActions(self.pref_groups[pref.key].actions())

    def fill_package_menu(self, menu: QMenu) -> None:
        """The Package menu, the table's context menu and the status icon's menu."""
        self.fill(menu, package_menu_items())

    def fill_menu_bar(self, mb: QMenuBar) -> None:
        for menu in menu_bar():
            self.fill(mb.addMenu(menu.title), menu.items)
