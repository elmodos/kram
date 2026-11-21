"""The GTK front end: smoke tests of its widgets and the main window over a made-up catalog.

Skipped without GTK 4, libadwaita ≥ 1.7 (Adw.ToggleGroup) and a display. Without a desktop they run under
broadway (spike S8): `gtk4-broadwayd :5 & GDK_BACKEND=broadway BROADWAY_DISPLAY=:5 pytest tests/test_gtk.py`.
"""
import time
from types import SimpleNamespace

import pytest

gi = pytest.importorskip("gi")
try:
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, GLib, Gtk
except (ImportError, ValueError) as e:  # ValueError: the typelib of that version is not there
    pytest.skip(f"GTK 4 / libadwaita: {e}", allow_module_level=True)
if (Adw.get_major_version(), Adw.get_minor_version()) < (1, 7):
    pytest.skip("libadwaita < 1.7 has no ToggleGroup", allow_module_level=True)
if not Gtk.init_check() or Gdk.Display.get_default() is None:
    pytest.skip("no display for GTK", allow_module_level=True)

from kram.app import preferences  # noqa: E402
from kram.app.actions import action_defs  # noqa: E402
from kram.app.package_list import PackageList  # noqa: E402
from kram.core.marks import Action  # noqa: E402
from kram.core.model import CatalogSnapshot, Origin, PkgRow, Status  # noqa: E402

Adw.init()


def rows(n: int) -> list[PkgRow]:
    return [PkgRow(f"pkg{i:04d}", "x86_64", f"Summary {i}", "1.0-1" if i % 3 == 0 else "", "1.0-1", "fedora",
                   1000 * i, Origin.FEDORA, Status.INSTALLED if i % 3 == 0 else Status.NOT_INSTALLED)
            for i in range(n)]


def spin(until=lambda: False, seconds: float = 3.0) -> None:
    """Run the main loop until `until()` holds or the time is up."""
    end = time.monotonic() + seconds
    ctx = GLib.MainContext.default()
    while time.monotonic() < end and not until():
        ctx.iteration(False)
        time.sleep(0.005)


def test_accelerators_are_gtks():
    from kram.gtk.actions import accel
    assert accel("Ctrl+Shift+Z") == "<Control><Shift>z"
    assert accel("Ins") == "Insert" and accel("Del") == "Delete" and accel("Alt+Left") == "<Alt>Left"
    for d in action_defs():
        for s in d.shortcuts:
            assert Gtk.accelerator_parse(accel(s))[0], s


def test_painted_icons_draw_at_every_scale():
    from kram.gtk import icons
    for scale in (1.0, 1.25, 1.5, 2.0):
        for ref in (("status", Status.UPGRADABLE), ("mark", Action.REMOVE), ("origin", Origin.COPR), ("blocked",)):
            tex = icons.texture(icons.drawer(ref), 16, scale)
            assert tex.get_width() == round(16 * scale + 0.4999)


def test_an_empty_shown_list_fills_without_criticals():
    """Spike S3's trap: a realized, empty list that fills (the first catalog load) made GTK abort while the row
    tints changed GTK's own row widgets."""
    from kram.gtk.package_list import PackageListView
    packages = PackageList()
    win = Gtk.Window(default_width=800, default_height=400)
    view = PackageListView(packages)
    win.set_child(view)
    win.present()
    spin(seconds=0.3)
    data = rows(500)
    packages.set_rows(data, "x86_64")
    packages.marks.set(data[1], Action.INSTALL)
    packages.marks_changed()
    spin(seconds=0.3)
    assert view.store.get_n_items() == 500
    tinted = [c for c in view._bound.values() if c.pos == 1 and c.box.has_css_class("kram-mark-install")]
    assert tinted
    packages.set_visible([5])
    spin(seconds=0.2)
    assert view.store.get_n_items() == 1
    win.destroy()


def test_the_header_shows_one_sort_and_sorts_through_the_list():
    from kram.app.columns import COL_NAME, COL_SUMMARY
    from kram.gtk.package_list import PackageListView
    packages = PackageList()
    packages.set_rows(rows(50), "x86_64")
    view = PackageListView(packages)
    sorted_by = []
    view.on_sort = lambda column, descending: sorted_by.append((column, descending))
    view.show_sort((COL_SUMMARY, True))
    assert sorted_by == []  # showing the sort sorts nothing
    view.view.sort_by_column(view.columns[COL_NAME], Gtk.SortType.DESCENDING)  # a header click
    assert sorted_by == [(COL_NAME, True)]
    sorter = view.view.get_sorter()
    assert sorter.get_n_sort_columns() == 1
    view.show_sort(None)
    assert sorter.get_primary_sort_column() is None


def test_the_settings_menu_has_exactly_the_gtk_preferences(monkeypatch):
    """§4.1a: a preference of the registry shows up in the GTK menus with no GTK code, and only those for GTK."""
    from kram.gtk.actions import WindowActions, pref_action_name
    app = Adw.Application()
    win = Gtk.ApplicationWindow()
    acts = WindowActions(win, app)
    menu = acts.menu_bar()
    found = set()

    def walk(model):
        for i in range(model.get_n_items()):
            action = model.get_item_attribute_value(i, "action", None)
            if action is not None:
                found.add(action.get_string())
            for link in ("section", "submenu"):
                if (sub := model.get_item_link(i, link)) is not None:
                    walk(sub)
    walk(menu)
    wanted = {f"win.{pref_action_name(p)}" for p in preferences.prefs_for("gtk") if p.kind == "bool" and p.visible()}
    assert {a for a in found if a.startswith("win.pref-")} == wanted
    assert "win.pref-gtk-menubar" in wanted and not any("toolbar" in a for a in found)


def test_the_main_window_shows_the_catalog(monkeypatch):
    import kram.gtk.window as window_module
    from kram.app.browser import Browser
    snap = CatalogSnapshot(rows(300), 100, 0, 0.1)
    catalog = SimpleNamespace(load=lambda *a, **k: snap, blocked_upgrades=lambda: {},
                              details=lambda key: (_ for _ in ()).throw(LookupError(key)))
    monkeypatch.setattr(window_module, "Browser",
                        lambda view, ui, scheduler, details, post: Browser(view, ui, scheduler, details, post,
                                                                           catalog=catalog))
    from kram.gtk.app import KramApplication
    app = KramApplication()
    app.register(None)
    from kram.gtk.window import MainWindow
    win = MainWindow(app)
    win.present()
    spin(lambda: win.browser.snapshot is not None and len(win.list.selected_positions()) == 1, 5)
    assert len(win.browser.packages) == 300
    assert win.current_key() == ("pkg0000", "x86_64")
    assert "300" in win.status.text()
    win.browser.sidebar.select("status", "status:installed")
    spin(lambda: len(win.browser.packages) == 100, 3)
    assert len(win.browser.packages) == 100
    # the menu bar setting hides the header bar's menu button (D12)
    preferences.set_value(preferences.MENU_BAR, True)
    assert win.menu_bar.get_visible() and not win.menu_button.get_visible()
    preferences.set_value(preferences.MENU_BAR, False)
    assert win.menu_button.get_visible()
    win.close()
    spin(seconds=0.3)
