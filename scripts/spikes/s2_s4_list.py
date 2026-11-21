#!/usr/bin/python3
"""Spikes S2, S3, S4 (docs/GTK_FRONTEND.md §7.1) on kram.gtk.package_list.PackageListView over the real catalog.

    KRAM_SPIKE_SNAPSHOT=snap.pickle python3 scripts/spikes/s2_s4_list.py OUT_DIR [--stay]

S2: sorting by PackageList with the header's indicator (programmatic and through the column view's sorter, which is
what a header click changes); ranked shows none. S3: marked rows tinted, per-cell tooltips; screenshots in both
themes into OUT_DIR. S4: the status cell's menu, the context menu, activation; with --stay the window stays open to
try them by hand (click the S column, right-click a row of a multi-selection, double-click a row).
"""
import sys
from pathlib import Path

from common import snapshot, versions
from gi.repository import Adw, Gdk, Gio, GLib, Graphene, Gtk

import kram.gtk  # noqa: F401
from kram.app.actions import package_menu_items
from kram.app.columns import COL_NAME, COL_SUMMARY
from kram.app.package_list import PackageList
from kram.core.marks import Action
from kram.core.model import Status
from kram.gtk import icons
from kram.gtk.package_list import PackageListView, css


def menu_model() -> Gio.Menu:
    from kram.app.actions import action_defs
    labels = {d.id: d.label for d in action_defs()}
    menu, section = Gio.Menu(), Gio.Menu()
    for item in package_menu_items():
        if item.separator:
            menu.append_section(None, section)
            section = Gio.Menu()
        elif item.action:
            section.append(labels[item.action], "win.noop")
        elif item.submenu:
            section.append_submenu(item.submenu.title, Gio.Menu())
    menu.append_section(None, section)
    return menu


def shoot(win: Gtk.Window, path: Path) -> None:
    paintable = Gtk.WidgetPaintable(widget=win)
    w, h = win.get_width(), win.get_height()
    snap = Gtk.Snapshot()
    paintable.snapshot(snap, w, h)
    node = snap.to_node()
    tex = win.get_renderer().render_texture(node, Graphene.Rect().init(0, 0, w, h))
    tex.save_to_png(str(path))


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else ".")
    out.mkdir(parents=True, exist_ok=True)
    stay = "--stay" in sys.argv
    print(versions())
    snap = snapshot()
    packages = PackageList()
    packages.set_rows(snap.rows, snap.basearch)
    app = Adw.Application(application_id=None, flags=Gio.ApplicationFlags.NON_UNIQUE)
    log = []

    def activate(app):
        provider = Gtk.CssProvider()
        provider.load_from_string(css())
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        win = Adw.ApplicationWindow(application=app, title="S2–S4", default_width=1320, default_height=700)
        win.add_action(Gio.SimpleAction(name="noop"))
        view = PackageListView(packages)
        win.set_content(view)
        popover = Gtk.PopoverMenu.new_from_model(menu_model())
        popover.set_has_arrow(False)

        def popup(widget, x, y):
            if popover.get_parent() is not None:
                popover.unparent()
            popover.set_parent(widget)
            rect = Gdk.Rectangle()
            rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
            popover.set_pointing_to(rect)
            popover.popup()

        def status_click(pos, widget):
            log.append(("status", packages.row(pos).name))
            popup(widget, 0, widget.get_height())

        def context(pos, widget, x, y):
            log.append(("context", packages.row(pos).name, len(view.selected_positions())))
            popup(widget, x, y)

        def sorted_by(column, descending):
            log.append(("sort", column, descending))
            packages.sort(column, descending)

        view.on_status_click = status_click
        view.on_context_menu = context
        view.on_activate = lambda pos: log.append(("activate", packages.row(pos).name))
        view.on_sort = sorted_by
        view.on_current = lambda pos: log.append(("current", pos))
        win.present()

        def scale_changed(*_a):
            surface = win.get_surface()
            if surface is not None:
                icons.set_scale(surface.get_scale())
        win.connect("realize", lambda w: w.get_surface().connect("notify::scale", scale_changed))
        GLib.idle_add(scale_changed)

        def checks():
            # marks: one row per action, among the first rows
            todo = list(Action)
            for i in range(2, len(packages), 3):
                for action in todo:
                    if packages.marks.set(packages.row(i), action):
                        todo.remove(action)
                        break
                if not todo or i > 400:
                    break
            packages.marks_changed()
            # S2: the indicator follows the sort; a sorter change (a header click) sorts through PackageList
            view.show_sort((COL_SUMMARY, True))
            s = view.view.get_sorter()
            print("S2 show_sort(summary, desc): indicator on column",
                  s.get_primary_sort_column().get_id(), s.get_primary_sort_order().value_nick, "| on_sort calls:",
                  sum(1 for e in log if e[0] == "sort"))
            view.view.sort_by_column(view.columns[COL_NAME], Gtk.SortType.DESCENDING)  # what a header click does
            print("S2 header sort (name, desc):", [e for e in log if e[0] == "sort"],
                  "| first rows now:", [packages.row(i).name for i in range(3)])
            view.show_sort(None)
            print("S2 ranked: indicator column", s.get_primary_sort_column())
            view.view.sort_by_column(view.columns[COL_SUMMARY], Gtk.SortType.ASCENDING)  # a second header click
            shown = [c.get_title() for c in view.columns if s.get_n_sort_columns() and c in
                     [s.get_nth_sort_column(i)[0] for i in range(s.get_n_sort_columns())]]
            print("S2 after a second header click, columns with an indicator:", shown)
            view.show_sort((COL_NAME, False))
            packages.sort(COL_NAME, False)
            installed = [i for i in range(len(packages)) if packages.row(i).installed][:8]
            for i, action in zip(installed, (Action.REMOVE, Action.REINSTALL, Action.MARK_DEP), strict=False):
                packages.marks.set(packages.row(i), action)
            packages.marks_changed()
            view.select(3)
            print("S4 select(3): current", view.current(), "selected", view.selected_positions())
            GLib.timeout_add(400, shots)

        def shots():
            style = Adw.StyleManager.get_default()
            for scheme, name in ((Adw.ColorScheme.FORCE_LIGHT, "light"), (Adw.ColorScheme.FORCE_DARK, "dark")):
                style.set_color_scheme(scheme)
                while GLib.MainContext.default().iteration(False):
                    pass
                shoot(win, out / f"s3-{name}.png")
            style.set_color_scheme(Adw.ColorScheme.DEFAULT)
            r = packages.row(2)
            print("S3 tooltip of the status cell of", r.name, "→",
                  repr(next(c.box.get_tooltip_text() for c in view._bound.values() if c.pos == 2 and c.col == 0)))
            print("screenshots in", out)
            if not stay:
                app.quit()
            return False

        GLib.timeout_add(800, checks)

    app.connect("activate", activate)
    app.run([])
    print("events:", [e for e in log if e[0] != "current"][:20])
    _ = Status


if __name__ == "__main__":
    main()
