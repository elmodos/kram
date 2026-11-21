#!/usr/bin/python3
"""Spike S5 (docs/GTK_FRONTEND.md §7.1): one sidebar widget for the flat views and the Environments tree,
kram.gtk.sidebar.Sidebar over SidebarModel and the real catalog. Screenshots of every view into OUT_DIR.

    KRAM_SPIKE_SNAPSHOT=snap.pickle python3 scripts/spikes/s5_sidebar.py OUT_DIR [--stay]
"""
import sys
from pathlib import Path

from common import snapshot, versions
from s2_s4_list import shoot

import kram.gtk  # noqa: F401
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from kram.app.sidebar import VIEWS, SidebarModel
from kram.core.marks import MarkSet
from kram.gtk import icons
from kram.gtk.loop import GtkScheduler
from kram.gtk.package_list import css


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else ".")
    out.mkdir(parents=True, exist_ok=True)
    stay = "--stay" in sys.argv
    print(versions())
    snap = snapshot()
    model = SidebarModel(GtkScheduler())
    model.marked, model.blocked = MarkSet(), {}
    chosen = []
    model.filter_changed.connect(lambda e: chosen.append(e.id))
    app = Adw.Application(application_id=None, flags=Gio.ApplicationFlags.NON_UNIQUE)

    def activate(app):
        from kram.gtk.sidebar import Sidebar
        provider = Gtk.CssProvider()
        provider.load_from_string(css())
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        win = Adw.ApplicationWindow(application=app, title="S5", default_width=300, default_height=760)
        side = Sidebar(model)
        win.set_content(side)
        win.present()
        GLib.idle_add(lambda: icons.set_scale(win.get_surface().get_scale()))
        model.set_snapshot(snap)
        steps = iter(VIEWS)

        def next_view():
            try:
                view_id = next(steps)[0]
            except StopIteration:
                env = [e for e in model.entries if e.indent][:1]
                if env:
                    print("environments: a child selected →", env[0].id)
                print("filter_changed calls:", len(chosen), chosen[-3:])
                if not stay:
                    app.quit()
                return False
            side.views.set_active_name(view_id)  # what a click on the toggle does
            if view_id == "environments":
                # unfold the first environment, as a click on its arrow does
                row = side._tree.get_row(1)
                if row is not None and row.is_expandable():
                    row.set_expanded(True)
            GLib.timeout_add(300, lambda: (shoot(win, out / f"s5-{view_id}.png"),
                                           print(view_id, "→", model.current_view, len(model.entries),
                                                 "entries, shown rows", side._tree.get_n_items(),
                                                 "current", model.current_entry_id),
                                           GLib.timeout_add(100, next_view), False)[-1])
            return False
        GLib.timeout_add(600, next_view)

    app.connect("activate", activate)
    app.run([])


if __name__ == "__main__":
    main()
