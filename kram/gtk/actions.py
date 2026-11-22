"""The main window's actions and menus for GTK, built from kram.app.actions and kram.app.preferences: a
Gio.SimpleAction per ActionDef ("win.<name>"), a stateful one per bool setting, Gio.Menus from the menu structures.
What the actions do, the window connects.

Shortcuts: window-wide ones are the application's accelerators; the table-scoped ones (Ctrl+C, Ins, Del, Ctrl+Z…)
live in a Gtk.ShortcutController on the package list, so the search field keeps them (§6).
"""
from collections.abc import Callable

from gi.repository import Gio, GLib, Gtk

from ..app import preferences
from ..app.actions import (
    ActionDef,
    ActionState,
    DynamicItem,
    Menu,
    MenuItem,
    action_defs,
    mark_upgrades_menu,
    menu_bar,
    package_menu_items,
    table_menu,
)
from ..app.preferences import Pref

TOOLKIT = "gtk"
_KEYS = {"Ins": "Insert", "Del": "Delete", "Esc": "Escape", "PgUp": "Page_Up", "PgDown": "Page_Down"}
_MODIFIERS = {"Ctrl": "<Control>", "Shift": "<Shift>", "Alt": "<Alt>", "Meta": "<Meta>"}


def accel(shortcut: str) -> str:
    """kram.app.actions' neutral "Ctrl+Shift+Z" as GTK's "<Control><Shift>z"."""
    *mods, key = shortcut.split("+")
    key = _KEYS.get(key, key)
    if len(key) == 1:
        key = key.lower()
    return "".join(_MODIFIERS[m] for m in mods) + key


def action_name(action_id: str) -> str:
    """Gio action names allow letters, digits, "-" and "."."""
    return action_id.replace("_", "-")


def pref_action_name(pref: Pref) -> str:
    return "pref-" + pref.key.replace("/", "-").replace("_", "-")


def mnemonic(title: str) -> str:
    """Qt's "&File" as GTK's "_File"."""
    return title.replace("_", "__").replace("&", "_")


class WindowActions:
    def __init__(self, window: Gtk.ApplicationWindow, app: Gtk.Application):
        self._window, self._app = window, app
        self.defs: dict[str, ActionDef] = {d.id: d for d in action_defs()}
        self.by_id: dict[str, Gio.SimpleAction] = {}
        for d in self.defs.values():
            act = Gio.SimpleAction(name=action_name(d.id), enabled=d.enabled)
            window.add_action(act)
            self.by_id[d.id] = act
            if d.shortcuts and d.scope == "window":
                app.set_accels_for_action(f"win.{act.get_name()}", [accel(s) for s in d.shortcuts])
        self.visible: dict[str, bool] = {d.id: d.visible for d in self.defs.values()}
        self.prefs: dict[str, Gio.SimpleAction] = {}
        for pref in preferences.prefs_for(TOOLKIT):
            if pref.kind == "bool":
                act = Gio.SimpleAction.new_stateful(pref_action_name(pref), None,
                                                    GLib.Variant.new_boolean(bool(preferences.value(pref))))
                act.connect("change-state", self._pref_changed, pref)
                window.add_action(act)
                self.prefs[pref.key] = act
        self._dynamic: list[Gio.SimpleAction] = []
        self.downgrade_menu = Gio.Menu()
        self._downgrade_source: Callable[[], list[DynamicItem]] = lambda: []
        self._menus: dict[str, Gio.Menu] = {}
        self._sections: list[tuple[Gio.Menu, tuple[MenuItem, ...]]] = []  # rebuilt when visibility changes
        self._downgrade_enabled = False

    def connect(self, action_id: str, fn: Callable[[], None]) -> None:
        self.by_id[action_id].connect("activate", lambda _a, _p: fn())

    def _pref_changed(self, act: Gio.SimpleAction, value: GLib.Variant, pref: Pref) -> None:
        act.set_state(value)
        preferences.set_value(pref, value.get_boolean())

    def table_shortcuts(self) -> Gtk.ShortcutController:
        """The table-scoped shortcuts, for the package list to add: they work only while it has the focus."""
        controller = Gtk.ShortcutController()
        for d in self.defs.values():
            if d.scope == "table":
                for s in d.shortcuts:
                    controller.add_shortcut(Gtk.Shortcut(trigger=Gtk.ShortcutTrigger.parse_string(accel(s)),
                                                         action=Gtk.NamedAction.new(f"win.{action_name(d.id)}")))
        return controller

    # ---------------------------------------------------------------- state

    def apply_state(self, state: ActionState, extra: dict[str, Gio.SimpleAction] | None = None) -> None:
        extra = extra or {}
        for action_id, on in state.enabled.items():
            if action_id == "downgrade":
                self._downgrade_enabled = on
            elif action_id == "mark_upgrades_menu":
                continue  # the split button's arrow follows the button's action
            elif action_id in self.by_id:
                self.by_id[action_id].set_enabled(on)
            elif action_id in extra:
                extra[action_id].set_enabled(on)
        changed = any(self.visible.get(i) != on for i, on in state.visible.items())
        self.visible.update(state.visible)
        if changed:  # an item that comes and goes (Why It Cannot Be Upgraded): menus are models, rebuild them
            self._refill_sections()

    def set_downgrade_source(self, source: Callable[[], list[DynamicItem]]) -> None:
        self._downgrade_source = source

    def refresh_downgrade(self) -> None:
        """Fill the Downgrade submenu for the selection: GTK menus are models, built before they open."""
        self._fill_dynamic(self.downgrade_menu, self._downgrade_source(), "downgrade")

    # ---------------------------------------------------------------- menus

    def _dynamic_action(self, prefix: str, item: DynamicItem) -> str:
        name = f"dyn-{prefix}-{len(self._dynamic)}"
        act = Gio.SimpleAction(name=name, enabled=item.enabled and item.run is not None)
        if item.run is not None:
            act.connect("activate", lambda _a, _p, run=item.run: run())
        self._window.add_action(act)
        self._dynamic.append(act)
        return f"win.{name}"

    def _fill_dynamic(self, menu: Gio.Menu, items: list[DynamicItem], prefix: str) -> None:
        for act in [a for a in self._dynamic if a.get_name().startswith(f"dyn-{prefix}-")]:
            self._window.remove_action(act.get_name())
            self._dynamic.remove(act)
        menu.remove_all()
        for item in items:
            menu.append(item.label, self._dynamic_action(prefix, item))

    def dynamic_menu(self, items: list[DynamicItem | str | None], prefix: str) -> Gio.Menu:
        """A menu of dynamic items, action ids and separators (None), as Browser.sidebar_menu gives."""
        for act in [a for a in self._dynamic if a.get_name().startswith(f"dyn-{prefix}-")]:
            self._window.remove_action(act.get_name())
            self._dynamic.remove(act)
        menu, section = Gio.Menu(), Gio.Menu()
        for item in items:
            if item is None:
                if section.get_n_items():
                    menu.append_section(None, section)
                section = Gio.Menu()
            elif isinstance(item, str):
                section.append(self.defs[item].label, f"win.{action_name(item)}")
            else:
                section.append(item.label, self._dynamic_action(prefix, item))
        if section.get_n_items():
            menu.append_section(None, section)
        return menu

    def menu(self, menu: Menu) -> Gio.Menu:
        if menu.id == "downgrade":
            return self.downgrade_menu
        if menu.id and menu.id in self._menus:
            return self._menus[menu.id]
        model = Gio.Menu()
        self._fill(model, menu.items)
        if menu.id:
            self._menus[menu.id] = model
        return model

    def _fill(self, model: Gio.Menu, items: tuple[MenuItem, ...]) -> None:
        """Separators become sections, as GTK draws them."""
        part: list[MenuItem] = []
        for item in (*items, MenuItem(separator=True)):
            if not item.separator:
                part.append(item)
                continue
            if part:
                section = Gio.Menu()
                self._sections.append((section, tuple(part)))
                self._fill_section(section, tuple(part))
                model.append_section(None, section)
            part = []

    def _fill_section(self, section: Gio.Menu, items: tuple[MenuItem, ...]) -> None:
        section.remove_all()
        for item in items:
            if item.action is not None:
                if self.visible.get(item.action, True):
                    section.append(self.defs[item.action].label, f"win.{action_name(item.action)}")
            elif item.submenu is not None:
                section.append_submenu(mnemonic(item.submenu.title), self.menu(item.submenu))
            elif item.prefs is not None:
                for pref in preferences.prefs_for(TOOLKIT, item.prefs):
                    if pref.kind == "bool" and pref.visible():
                        section.append(pref.label, f"win.{pref_action_name(pref)}")

    def _refill_sections(self) -> None:
        for section, items in self._sections:
            self._fill_section(section, items)

    def package_menu(self) -> Gio.Menu:
        return self.menu(Menu("", package_menu_items()))

    def table_menu(self) -> Gio.Menu:
        return self.menu(table_menu())

    def mark_upgrades_menu(self) -> Gio.Menu:
        return self.menu(mark_upgrades_menu())

    def menu_bar(self) -> Gio.Menu:
        bar = Gio.Menu()
        for m in menu_bar():
            bar.append_submenu(mnemonic(m.title), self.menu(m))
        return bar

    def main_menu(self) -> Gio.Menu:
        """The header bar's menu: File, Edit, Package and Settings as submenus, Help's items as the last section."""
        main, top = Gio.Menu(), Gio.Menu()
        *menus, help_menu = menu_bar()
        for m in menus:
            top.append_submenu(mnemonic(m.title), self.menu(m))
        main.append_section(None, top)
        main.append_section(None, self.menu(Menu("", help_menu.items)))
        return main
