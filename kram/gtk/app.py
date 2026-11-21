"""The GTK application: one Kram per session (spike S9). The first Kram owns the bus name APP_ID through
GApplication; a second `kram` hands its command line to it (GApplication's own remote activation, with the
XDG activation token as platform data) and exits. The tray calls Activate(view, token) at "/" (kram/instance.py),
exported here next to GApplication's own interfaces."""
import sys
from pathlib import Path

from gi.repository import Adw, Gdk, Gio, Gtk

from .. import APP_ID, instance
from .package_list import css

INSTANCE_XML = f"""<node><interface name="{instance.INTERFACE}">
  <method name="{instance.METHOD}"><arg type="s" name="view" direction="in"/><arg type="s" name="token" direction="in"/></method>
</interface></node>"""
EXTRA_CSS = """
entry.kram-filtering { outline: 2px solid alpha(var(--accent-color), 0.6); outline-offset: -2px; }
"""


class KramApplication(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.window = None
        self._registration = 0

    # ---------------------------------------------------------------- the tray's Activate

    def do_dbus_register(self, connection: Gio.DBusConnection, object_path: str) -> bool:
        if not Adw.Application.do_dbus_register(self, connection, object_path):
            return False
        info = Gio.DBusNodeInfo.new_for_xml(INSTANCE_XML)
        try:
            self._registration = connection.register_object(instance.PATH, info.interfaces[0], self._call, None,
                                                            None)
        except Exception:  # noqa: BLE001 - a second instance on a bus where "/" is taken: it hands over anyway
            self._registration = 0
        return True

    def do_dbus_unregister(self, connection: Gio.DBusConnection, object_path: str) -> None:
        if self._registration:
            connection.unregister_object(self._registration)
            self._registration = 0
        Adw.Application.do_dbus_unregister(self, connection, object_path)

    def _call(self, _conn, _sender, _path, _iface, method, params, invocation) -> None:
        if method != instance.METHOD:
            return
        view, token = params.unpack()
        invocation.return_value(None)
        self._show(view, token)

    # ---------------------------------------------------------------- start

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_string(css() + EXTRA_CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        # a source checkout: the icon next to the package, as the Qt front end does
        source_icons = Path(__file__).resolve().parents[2] / "data"
        if (source_icons / f"{APP_ID}.svg").exists():
            Gtk.IconTheme.get_for_display(Gdk.Display.get_default()).add_search_path(str(source_icons))

    def do_command_line(self, command_line: Gio.ApplicationCommandLine) -> int:
        args = command_line.get_arguments()[1:]
        view = instance.UPGRADABLE if "--upgradable" in args else ""
        data = command_line.get_platform_data()
        token = (data.unpack() if data is not None else {}).get("activation-token", "")
        self._show(view, token)
        return 0

    def _show(self, view: str, token: str = "") -> None:
        if self.window is None:
            from .window import MainWindow
            self.window = MainWindow(self)
            self.window.connect("destroy", lambda _w: setattr(self, "window", None))
            self.window.show_view(view)
            self.window.present()
        else:
            self.window.activate_from_outside(view, token)


def main(argv: list[str] | None = None) -> int:
    return KramApplication().run(argv if argv is not None else sys.argv)
