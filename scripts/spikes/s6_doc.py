#!/usr/bin/python3
"""Spike S6 (docs/GTK_FRONTEND.md §7.1): the Dependencies tab of kernel-core (thousands of provides, cut to 1000 per
section) through kram.gtk.doc_view.DocView. Loads the real catalog (read-only) for the package's details.

    python3 scripts/spikes/s6_doc.py OUT_DIR [package] [--stay]
"""
import sys
from pathlib import Path

from common import Stopwatch, versions
from s2_s4_list import shoot

import kram.gtk  # noqa: F401
from gi.repository import Adw, Gio, GLib, Gtk

from kram.app.details import dependencies_doc
from kram.core.catalog import Catalog


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    out = Path(args[0] if args else ".")
    out.mkdir(parents=True, exist_ok=True)
    name = args[1] if len(args) > 1 else "kernel-core"
    stay = "--stay" in sys.argv
    print(versions())
    catalog = Catalog()
    snap = catalog.load()
    row = next(r for r in snap.rows if r.name == name and r.arch == snap.basearch)
    d = catalog.details(row.key)
    sw = Stopwatch()
    doc = dependencies_doc(d)
    print(f"{name}: doc built in {sw.ms():.0f} ms;", ", ".join(f"{b.title} {b.count} (shown {len(b.items)})"
                                                               for b in doc.blocks if hasattr(b, "count")))
    app = Adw.Application(application_id=None, flags=Gio.ApplicationFlags.NON_UNIQUE)

    def activate(app):
        from kram.gtk.doc_view import DocView
        win = Adw.ApplicationWindow(application=app, title="S6", default_width=900, default_height=700)
        view = DocView()
        view.on_link = lambda kind, target: print("link:", kind, target)
        win.set_content(Gtk.ScrolledWindow(child=view))
        win.present()

        def show():
            sw = Stopwatch()
            view.set_doc(doc)
            built = sw.ms()
            clock = win.get_frame_clock()
            handler = []

            def painted(_c):
                clock.disconnect(handler[0])
                print(f"set_doc {built:.0f} ms, painted after {sw.ms():.0f} ms")
                shoot(win, out / "s6.png")
                # again, as when the selection moves to another big package
                sw2 = Stopwatch()
                view.set_doc(doc)
                print(f"second set_doc {sw2.ms():.0f} ms")
                if not stay:
                    GLib.timeout_add(200, app.quit)
            handler.append(clock.connect("after-paint", painted))
            return False
        GLib.timeout_add(500, show)

    app.connect("activate", activate)
    app.run([])


if __name__ == "__main__":
    main()
