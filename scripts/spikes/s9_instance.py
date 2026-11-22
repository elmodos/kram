#!/usr/bin/python3
"""Spike S9 (docs/GTK_FRONTEND.md §7.1): one Kram per session with Adw.Application, plus the Activate(view, token)
method at "/" that the tray calls (kram/instance.py), and the focus that comes with the token.

    python3 scripts/spikes/s9_instance.py [--upgradable] [--id APP_ID]

The first run opens a window and serves; a second run hands its command line over to the first (GApplication's own
remote activation) and exits. The tray's call can be imitated with:

    gdbus call --session --dest APP_ID --object-path / --method APP_ID.Activate upgradable ""

--id defaults to a test id so that it does not meet a real Kram; pass io.github.elmodos.Kram (with no Kram running)
to try a click on the tray icon.
"""
import os
import sys

import common  # noqa: F401
from gi.repository import Adw, Gio, GLib, Gtk

from kram import instance

XML = f"""<node><interface name="{{iface}}">
  <method name="{instance.METHOD}"><arg type="s" name="view" direction="in"/><arg type="s" name="token" direction="in"/></method>
</interface></node>"""


class App(Adw.Application):
    def __init__(self, app_id: str):
        super().__init__(application_id=app_id, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.app_id = app_id
        self.win = None
        self.label = None
        self._registration = 0

    def do_dbus_register(self, connection, object_path):
        Adw.Application.do_dbus_register(self, connection, object_path)
        info = Gio.DBusNodeInfo.new_for_xml(XML.format(iface=self.app_id))
        self._registration = connection.register_object(instance.PATH, info.interfaces[0], self._call, None, None)
        print(f"[{os.getpid()}] serving {self.app_id} at {object_path} and {instance.METHOD} at {instance.PATH}")
        return True

    def do_dbus_unregister(self, connection, object_path):
        if self._registration:
            connection.unregister_object(self._registration)
            self._registration = 0
        Adw.Application.do_dbus_unregister(self, connection, object_path)

    def _call(self, _conn, _sender, _path, _iface, method, params, invocation):
        view, token = params.unpack()
        print(f"[{os.getpid()}] {method}(view={view!r}, token={'yes' if token else 'none'})")
        invocation.return_value(None)
        self.show(view, token)

    def do_command_line(self, command_line):
        args = command_line.get_arguments()[1:]
        remote = command_line.get_is_remote()
        view = instance.UPGRADABLE if "--upgradable" in args else ""
        # a remote command line brings the second process's XDG_ACTIVATION_TOKEN in its platform data
        data = command_line.get_platform_data()
        token = (data.unpack() if data is not None else {}).get("activation-token", "")
        print(f"[{os.getpid()}] command line {args} remote={remote} token={'yes' if token else 'none'}")
        self.show(view, token or "")
        return 0

    def show(self, view: str, token: str = ""):
        if self.win is None:
            self.win = Adw.ApplicationWindow(application=self, title="S9", default_width=500, default_height=200)
            self.label = Gtk.Label()
            self.win.set_content(self.label)
        self.label.set_text(f"view: {view or '(keep)'}\nlast request: {GLib.DateTime.new_now_local().format('%T')}")
        if token:
            self.win.set_startup_id(token)  # Wayland: present() activates with this token
        self.win.present()


def main():
    args = sys.argv[1:]
    app_id = args[args.index("--id") + 1] if "--id" in args else "io.github.elmodos.KramSpike"
    argv = [sys.argv[0]] + [a for a in args if a == "--upgradable"]
    sys.exit(App(app_id).run(argv))


if __name__ == "__main__":
    main()
