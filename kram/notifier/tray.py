"""The tray icon, alive only while upgrades exist (kram-tray.service, started and stopped by the check).

A bare StatusNotifierItem with a com.canonical.dbusmenu menu over Gio D-Bus, without Qt: about 30 MB instead
of about 80 MB for a QSystemTrayIcon. Plasma, and other desktops with a StatusNotifierWatcher (GNOME only with
the AppIndicator extension) show it. It reads the check's result file and follows its changes.
"""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from gi.repository import Gio, GLib

try:  # GLib 2.80 moved it; GLib.unix_signal_add warns since
    from gi.repository.GLibUnix import signal_add
except ImportError:
    signal_add = GLib.unix_signal_add

from .. import APP_ID
from ..i18n import _, ngettext
from . import read_state, stale_days, state_file

WATCHER = "org.kde.StatusNotifierWatcher"
ITEM_PATH = "/StatusNotifierItem"
KRAM_BUS_NAME = APP_ID  # kram.instance (not imported: it needs Qt)
UPGRADABLE = "upgradable"
MENU_PATH = "/MenuBar"
NO_WATCHER_GRACE = 60  # seconds without a tray host before the process gives up
# Kram's own icons (data/icons, installed into hicolor so every icon theme finds them; theme names like Breeze's
# update-high exist only in some themes) by kram.core.updates' severity, not imported: that would load libdnf5
# into this long-lived process
ICONS = {level: f"{APP_ID}-update-{level}" for level in ("low", "medium", "high")}
# the same icons once more, in a folder of our own that the panel searches too (IconThemePath). A panel that was
# running when Kram got installed has not seen the new hicolor icons (plasmashell caches its icon lookups until it
# restarts) and fell back to the nearest name it knew: Kram's own icon. The folder ends in "icons", which Plasma
# requires; Plasma adds it to its lookup (KIconLoader::addAppDir), GTK panels to their search path, so the user's
# icon theme still wins when it has an icon of the same name.
INSTALLED_ICON_DIR = "/usr/share/kram/icons"
SOURCE_ICON_DIR = Path(__file__).resolve().parents[2] / "data" / "icons"  # a source checkout


def icon_dir() -> str:
    return INSTALLED_ICON_DIR if os.path.isdir(INSTALLED_ICON_DIR) else str(SOURCE_ICON_DIR)

INTERFACES = Gio.DBusNodeInfo.new_for_xml("""<node>
<interface name="org.kde.StatusNotifierItem">
  <property name="Category" type="s" access="read"/>
  <property name="Id" type="s" access="read"/>
  <property name="Title" type="s" access="read"/>
  <property name="Status" type="s" access="read"/>
  <property name="IconName" type="s" access="read"/>
  <property name="IconThemePath" type="s" access="read"/>
  <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
  <property name="ItemIsMenu" type="b" access="read"/>
  <property name="Menu" type="o" access="read"/>
  <method name="Activate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
  <method name="ProvideXdgActivationToken"><arg type="s" direction="in"/></method>
  <method name="SecondaryActivate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
  <method name="ContextMenu"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
  <method name="Scroll"><arg type="i" direction="in"/><arg type="s" direction="in"/></method>
  <signal name="NewIcon"/><signal name="NewToolTip"/><signal name="NewStatus"><arg type="s"/></signal>
</interface>
<interface name="com.canonical.dbusmenu">
  <property name="Version" type="u" access="read"/>
  <property name="TextDirection" type="s" access="read"/>
  <property name="Status" type="s" access="read"/>
  <property name="IconThemePath" type="as" access="read"/>
  <method name="GetLayout">
    <arg type="i" direction="in"/><arg type="i" direction="in"/><arg type="as" direction="in"/>
    <arg type="u" direction="out"/><arg type="(ia{sv}av)" direction="out"/>
  </method>
  <method name="GetGroupProperties">
    <arg type="ai" direction="in"/><arg type="as" direction="in"/><arg type="a(ia{sv})" direction="out"/>
  </method>
  <method name="GetProperty">
    <arg type="i" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="out"/>
  </method>
  <method name="Event">
    <arg type="i" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="in"/>
    <arg type="u" direction="in"/>
  </method>
  <method name="EventGroup"><arg type="a(isvu)" direction="in"/><arg type="ai" direction="out"/></method>
  <method name="AboutToShow"><arg type="i" direction="in"/><arg type="b" direction="out"/></method>
  <method name="AboutToShowGroup">
    <arg type="ai" direction="in"/><arg type="ai" direction="out"/><arg type="ai" direction="out"/>
  </method>
  <signal name="LayoutUpdated"><arg type="u"/><arg type="i"/></signal>
  <signal name="ItemsPropertiesUpdated"><arg type="a(ia{sv}as)"/><arg type="a(ias)"/></signal>
</interface>
</node>""").interfaces


def open_kram(token: str = "") -> None:
    """Kram on its Upgradable filter. A running Kram is asked over D-Bus (kram.instance: it raises its window, or
    ignores the call while a dialog is open over it); otherwise a new one starts, in a systemd scope of its own like
    a desktop starts apps: as a plain child it would live in kram-tray.service's cgroup, and stopping the tray (no
    more upgrades, or the checker turned off from Kram's own settings) would kill Kram with it. `token`: the
    panel's XDG activation token, so that Wayland gives the window focus."""
    bus = Gio.bus_get_sync(Gio.BusType.SESSION)
    try:
        bus.call_sync(KRAM_BUS_NAME, "/", KRAM_BUS_NAME, "Activate", GLib.Variant("(ss)", (UPGRADABLE, token)),
                      None, Gio.DBusCallFlags.NO_AUTO_START, 3000, None)
        return
    except GLib.Error:  # no Kram running (or it did not answer): start one
        pass
    installed = Gio.DesktopAppInfo.new(f"{APP_ID}.desktop") is not None
    command = ["kram"] if installed else [sys.executable, "-m", "kram"]  # a source checkout: no .desktop file
    command.append("--upgradable")
    scope = ["systemd-run", "--user", "--scope", "--collect", "--quiet", "--slice=app.slice",
             f"--unit=app-{APP_ID}-{os.getpid()}-{time.monotonic_ns()}", "--"]
    env = dict(os.environ, XDG_ACTIVATION_TOKEN=token) if token else None
    try:
        child = subprocess.Popen(scope + command, start_new_session=True, env=env)
    except OSError:  # no systemd-run: better a Kram tied to the tray than none
        child = subprocess.Popen(command, start_new_session=True, env=env)
    GLib.child_watch_add(GLib.PRIORITY_DEFAULT, child.pid, lambda *_: child.wait())  # no zombie when Kram exits


class Tray:
    def __init__(self, loop: GLib.MainLoop) -> None:
        self.loop = loop
        self.state = read_state()
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        self.give_up = 0  # the timeout that ends the process while no tray host is there
        self.token = ""  # the panel's XDG activation token for the next click
        self.name = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
        item, menu = INTERFACES
        self._register(ITEM_PATH, item, self._item_call, self._item_property)
        self._register(MENU_PATH, menu, self._menu_call, self._menu_property)
        Gio.bus_own_name_on_connection(self.bus, self.name, Gio.BusNameOwnerFlags.NONE, None, None)
        # the panel (plasmashell) can restart: register again whenever a watcher appears
        Gio.bus_watch_name_on_connection(self.bus, WATCHER, Gio.BusNameWatcherFlags.NONE,
                                         self._watcher_appeared, self._watcher_vanished)
        self.monitor = Gio.File.new_for_path(str(state_file())).monitor_file(Gio.FileMonitorFlags.WATCH_MOVES, None)
        self.monitor.connect("changed", self._state_changed)
        # hourly, so the "information is N days old" line stays true while the icon is up
        GLib.timeout_add_seconds(3600, self._refresh)
        # no "check now": a check only re-reads the cache, it would look like asking the servers. Fresh
        # metadata is Kram's Reload, with its progress window.
        self.actions = {1: (_("Open Kram"), "system-software-install", self._open_kram)}

    def _register(self, path, interface, call, get_property) -> None:
        def method(connection, sender, path, iface, name, params, invocation):
            invocation.return_value(call(name, params.unpack()))
        def prop(connection, sender, path, iface, name):
            return get_property(name)
        register = getattr(self.bus, "register_object_with_closures2", None) or self.bus.register_object
        register(path, interface, method, prop, None)

    def _open_kram(self) -> None:
        token, self.token = self.token, ""  # one use only
        open_kram(token)

    # StatusNotifierItem

    def _watcher_appeared(self, connection, name, owner) -> None:
        if self.give_up:
            GLib.source_remove(self.give_up)
            self.give_up = 0
        self.bus.call(WATCHER, "/StatusNotifierWatcher", WATCHER, "RegisterStatusNotifierItem",
                      GLib.Variant("(s)", (self.name,)), None, Gio.DBusCallFlags.NONE, -1, None, None)

    def _watcher_vanished(self, connection, name) -> None:
        # a panel restarting comes back within seconds; a desktop without one (LXDE's lxpanel only has the old
        # XEmbed tray) never does: don't stay in memory for nothing. The hourly check starts the icon again.
        if not self.give_up:
            self.give_up = GLib.timeout_add_seconds(NO_WATCHER_GRACE, self._no_watcher)

    def _no_watcher(self) -> bool:
        print("no StatusNotifierWatcher on the session bus: this desktop shows no such tray icons; exiting",
              file=sys.stderr)
        self.loop.quit()
        return False

    def _item_call(self, name, args):
        if name == "ProvideXdgActivationToken":  # Plasma sends it just before Activate
            self.token = args[0]
        elif name in ("Activate", "SecondaryActivate"):
            self._open_kram()
        return None

    def _item_property(self, name):
        return {
            "Category": GLib.Variant("s", "SystemServices"),
            "Id": GLib.Variant("s", "kram-update-checker"),
            "Title": GLib.Variant("s", "Kram"),
            "Status": GLib.Variant("s", "Active"),
            "IconName": GLib.Variant("s", self.icon()),
            "IconThemePath": GLib.Variant("s", icon_dir()),
            "ToolTip": GLib.Variant("(sa(iiay)ss)", (self.icon(), [], "Kram", self.tooltip())),
            "ItemIsMenu": GLib.Variant("b", False),
            "Menu": GLib.Variant("o", MENU_PATH),
        }.get(name)

    def icon(self) -> str:
        return ICONS.get(self.state.get("severity"), ICONS["low"])

    def tooltip(self) -> str:
        n, security = self.state.get("count", 0), self.state.get("security", 0)
        lines = [ngettext("{n} update available", "{n} updates available", n).format(n=n)]
        if security:
            lines.append(ngettext("{n} of them is a security update", "{n} of them are security updates",
                                  security).format(n=security))
        age = self.state.get("metadata_age")
        if age is not None:
            days = (age + time.time() - self.state.get("checked_at", time.time())) // 86400
            if days >= stale_days():
                days = int(days)
                lines.append(ngettext("The package information is {days} day old",
                                      "The package information is {days} days old", days).format(days=days))
        return "\n".join(lines)

    def _state_changed(self, monitor, file, other, event) -> None:
        if event in (Gio.FileMonitorEvent.CHANGES_DONE_HINT, Gio.FileMonitorEvent.CREATED,
                     Gio.FileMonitorEvent.MOVED_IN, Gio.FileMonitorEvent.RENAMED):
            self.state = read_state()
            if not self.state.get("count"):
                self.loop.quit()
                return
            self._refresh()

    def _refresh(self) -> bool:
        for signal_name in ("NewIcon", "NewToolTip"):
            self.bus.emit_signal(None, ITEM_PATH, "org.kde.StatusNotifierItem", signal_name, None)
        return True

    # com.canonical.dbusmenu: a flat menu, items 1..n under the root 0

    def _menu_item(self, item_id: int):
        if item_id == 0:
            props = {"children-display": GLib.Variant("s", "submenu")}
            children = [GLib.Variant("(ia{sv}av)", self._menu_item(i)) for i in self.actions]
            return (0, props, children)
        label, icon, _action = self.actions[item_id]
        return (item_id, {"label": GLib.Variant("s", label), "icon-name": GLib.Variant("s", icon)}, [])

    def _menu_call(self, name, args):
        if name == "GetLayout":
            parent = args[0] if args[0] in self.actions else 0
            return GLib.Variant("(u(ia{sv}av))", (1, self._menu_item(parent)))
        if name == "GetGroupProperties":
            ids = [i for i in args[0] if i == 0 or i in self.actions]
            return GLib.Variant("(a(ia{sv}))", ([self._menu_item(i)[:2] for i in ids],))
        if name == "GetProperty":
            return GLib.Variant("(v)", (self._menu_item(args[0])[1].get(args[1], GLib.Variant("s", "")),))
        if name == "Event":
            if args[1] == "clicked" and args[0] in self.actions:
                self.actions[args[0]][2]()
            return None
        if name == "EventGroup":
            for item_id, event, _data, _time in args[0]:
                if event == "clicked" and item_id in self.actions:
                    self.actions[item_id][2]()
            return GLib.Variant("(ai)", ([],))
        if name == "AboutToShow":
            return GLib.Variant("(b)", (False,))
        if name == "AboutToShowGroup":
            return GLib.Variant("(aiai)", ([], []))
        return None

    def _menu_property(self, name):
        return {"Version": GLib.Variant("u", 3), "TextDirection": GLib.Variant("s", "ltr"),
                "Status": GLib.Variant("s", "normal"), "IconThemePath": GLib.Variant("as", [])}.get(name)


def main() -> int:
    if not read_state().get("count"):
        return 0
    loop = GLib.MainLoop()
    Tray(loop)
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal_add(GLib.PRIORITY_DEFAULT, signum, loop.quit)
    loop.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
