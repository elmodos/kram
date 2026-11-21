#!/usr/bin/python3
"""Spike S8 (docs/GTK_FRONTEND.md §7.1): a GTK smoke test without a real display. Builds the list, the sidebar and a
doc view over made-up rows in a window, waits for its first painted frame, renders it offscreen and exits 0.

    python3 scripts/spikes/s8_smoke.py   (under xvfb-run, a headless compositor, or GDK_BACKEND=broadway)
"""
import sys

from common import fake_snapshot, versions
from gi.repository import Adw, Gdk, Gio, GLib, Graphene, Gtk

import kram.gtk  # noqa: F401


def main() -> int:
    print(versions(), "| display:", Gdk.Display.get_default() and type(Gdk.Display.get_default()).__name__)
    from kram.app.details import blocked_doc
    from kram.app.package_list import PackageList
    from kram.app.sidebar import SidebarModel
    from kram.core.marks import MarkSet
    from kram.gtk.doc_view import DocView
    from kram.gtk.loop import GtkScheduler
    from kram.gtk.package_list import PackageListView
    from kram.gtk.sidebar import Sidebar
    snap = fake_snapshot(2000)
    result = {"ok": False}
    app = Adw.Application(application_id=None, flags=Gio.ApplicationFlags.NON_UNIQUE)

    def activate(app):
        packages = PackageList()
        packages.set_rows(snap.rows, snap.basearch)
        side_model = SidebarModel(GtkScheduler())
        side_model.marked, side_model.blocked = MarkSet(), {}
        win = Adw.ApplicationWindow(application=app, default_width=1000, default_height=600)
        paned = Gtk.Paned(start_child=Sidebar(side_model), end_child=Gtk.Paned(
            orientation=Gtk.Orientation.VERTICAL, start_child=PackageListView(packages), end_child=DocView()))
        paned.get_end_child().get_end_child().set_doc(blocked_doc("nothing provides libfoo.so.1"))
        win.set_content(paned)
        side_model.set_snapshot(snap)
        win.present()
        clock = win.get_frame_clock()
        handler = []

        def painted(_c):
            clock.disconnect(handler[0])
            w, h = win.get_width(), win.get_height()
            snapshot = Gtk.Snapshot()
            Gtk.WidgetPaintable(widget=win).snapshot(snapshot, w, h)
            tex = win.get_renderer().render_texture(snapshot.to_node(), Graphene.Rect().init(0, 0, w, h))
            result["ok"] = tex.get_width() == w and len(side_model.entries) > 0
            print("painted", w, "x", h, "renderer", type(win.get_renderer()).__name__, "entries",
                  len(side_model.entries))
            app.quit()
        handler.append(clock.connect("after-paint", painted))
        GLib.timeout_add_seconds(20, lambda: (print("timed out"), app.quit()))

    app.connect("activate", activate)
    app.run([])
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
