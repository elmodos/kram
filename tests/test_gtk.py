"""The GTK front end: smoke tests of its widgets and the main window over a made-up catalog.

Skipped without GTK 4 and libadwaita ≥ 1.7 (Adw.ToggleGroup). Without a desktop (the kram-test container, a
build's %check) the module starts GTK's own broadway display server for itself (spike S8): no X server or
compositor needed, gtk4 ships it.
"""
import atexit
import os
import shutil
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

gi = pytest.importorskip("gi")
from gi.repository import GLib  # noqa: E402  (GLib alone does not initialize GTK)


def _start_broadway() -> None:
    """No display: run gtk4-broadwayd on a display of our own, and point GDK at it (before GTK opens one)."""
    daemon = shutil.which("gtk4-broadwayd")
    if daemon is None or os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"):
        return
    # where GDK will look for the daemon's socket: GLib has settled it already (~/.cache without XDG_RUNTIME_DIR)
    runtime = Path(GLib.get_user_runtime_dir())
    runtime.mkdir(parents=True, exist_ok=True)
    display = f":{40 + os.getpid() % 50}"
    before = set(runtime.iterdir())
    proc = subprocess.Popen([daemon, display], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            env={**os.environ, "XDG_RUNTIME_DIR": str(runtime)})
    atexit.register(proc.terminate)
    end = time.monotonic() + 5
    while time.monotonic() < end and proc.poll() is None and set(runtime.iterdir()) == before:
        time.sleep(0.05)  # its socket appears in the runtime directory once it listens
    os.environ["GDK_BACKEND"] = "broadway"
    os.environ["BROADWAY_DISPLAY"] = display


# before GTK is imported: PyGObject's Gtk opens the display at import time
_start_broadway()
try:
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gtk
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


def _review_preview(with_kvm: bool = True):
    from kram.core.model import PreviewItem, Recommendation, TransactionPreview
    items = [PreviewItem("install", "virt-manager", "noarch", "5.1-1", "", "fedora", 700, 2000, "user")]
    if with_kvm:
        items.append(PreviewItem("install", "kvm", "x86_64", "1-1", "", "fedora", 50, 9000, "weak"))
    recs = [Recommendation("kvm", ["virt-manager"], True, ["kvm"] if with_kvm else [], ["kvm"], size=9000, count=1,
                           exact=True)]
    return TransactionPreview(items, [], 100, 11000, recs)


def _texts(widget: Gtk.Widget) -> list[str]:
    """Every label's text under `widget`, in order."""
    out = []
    if isinstance(widget, Gtk.Label):
        out.append(widget.get_text())
    child = widget.get_first_child()
    while child is not None:
        out += _texts(child)
        child = child.get_next_sibling()
    return out


def test_the_apply_dialog_reviews_and_resolves_again():
    from kram.gtk.dialogs.apply import ApplyDialog
    win = Gtk.Window(default_width=900, default_height=700)
    win.present()
    waiting, results = [], []
    dlg = ApplyDialog(_review_preview(), {"op": "transaction", "install": ["virt-manager"]}, "x86_64",
                      results.append, resolve=lambda req, done, failed: waiting.append((req, done)))
    dlg.present(win)
    spin(seconds=0.3)
    shown = _texts(dlg.tree)
    assert "To be installed (1)" in shown and "virt-manager" in shown and "kvm" in shown
    assert dlg.ok.get_sensitive() and "virt-manager" in dlg.cmd.get_buffer().props.text
    # unchecking the recommendation resolves again without it
    check = next(w for w in _walk(dlg.recs) if isinstance(w, Gtk.CheckButton) and w.get_visible())
    check.set_active(False)
    assert waiting and waiting[-1][0]["exclude_weak"] == ["kvm"] and not dlg.ok.get_sensitive()
    waiting[-1][1](_review_preview(with_kvm=False))
    spin(seconds=0.2)
    assert dlg.ok.get_sensitive() and "kvm" not in _texts(dlg.tree)
    dlg.download_only.set_active(True)
    dlg.ok.emit("clicked")
    spin(lambda: bool(results), 2)
    assert results == [{"op": "transaction", "install": ["virt-manager"], "exclude_weak": ["kvm"],
                        "download_only": True}]
    win.destroy()


def test_the_apply_dialog_cancelled_runs_nothing():
    from kram.gtk.dialogs.apply import ApplyDialog
    win = Gtk.Window()
    win.present()
    results = []
    dlg = ApplyDialog(_review_preview(), {"op": "transaction"}, "x86_64", results.append)
    dlg.present(win)
    spin(seconds=0.1)
    dlg.close()
    spin(lambda: bool(results), 2)
    assert results == [None]
    win.destroy()


def _walk(widget: Gtk.Widget):
    yield widget
    child = widget.get_first_child()
    while child is not None:
        yield from _walk(child)
        child = child.get_next_sibling()


def test_the_progress_dialog_follows_the_helper_and_stays_until_it_is_done():
    from kram.core.mainloop import Signal
    from kram.gtk.dialogs.progress import ProgressDialog
    win = Gtk.Window()
    win.present()
    client = SimpleNamespace(event=Signal(), failed=Signal(), request=lambda _r: True, answer=lambda *a: None)
    finished = []
    dlg = ProgressDialog(client, {"op": "transaction"}, "Applying changes", lambda ok, r: finished.append((ok, r)))
    dlg.auto_close.set_active(False)
    assert dlg.start()
    dlg.present(win)
    client.event.emit({"event": "resolved", "items": [{"action": "Install", "nevra": "a-1-1.noarch"}]})
    client.event.emit({"event": "download", "id": 1, "name": "a", "done": 50, "total": 100})
    assert 0.4 < dlg.download_bar.get_fraction() < 0.6
    client.event.emit({"event": "rpm", "step": "install", "nevra": "a-1-1.noarch", "done": 0})
    assert "a-1-1.noarch" in dlg.stage.get_text() and dlg.rpm_bar.get_fraction() == 1.0
    dlg.close()  # mid-transaction: refused
    spin(seconds=0.2)
    assert not finished and not dlg.close_button.get_sensitive()
    client.event.emit({"event": "done", "ok": True})
    assert dlg.close_button.get_sensitive() and "a-1-1.noarch" in dlg.log.get_buffer().props.text
    dlg.close_button.emit("clicked")
    spin(lambda: bool(finished), 2)
    assert finished == [(True, {"event": "done", "ok": True})] and not client.event._slots
    win.destroy()


def test_the_progress_dialog_closes_itself_after_a_success_if_asked():
    from kram.core.mainloop import Signal
    from kram.gtk.dialogs.progress import ProgressDialog
    win = Gtk.Window()
    win.present()
    client = SimpleNamespace(event=Signal(), failed=Signal(), request=lambda _r: True, answer=lambda *a: None)
    finished = []
    dlg = ProgressDialog(client, {"op": "refresh"}, "Refreshing metadata", lambda ok, r: finished.append(ok))
    assert not dlg.rpm_bar.get_visible()
    dlg.auto_close.set_active(True)
    dlg.start()
    dlg.present(win)
    client.failed.emit("pkexec died")
    spin(seconds=0.1)
    assert not finished and "error" in dlg.stage.get_css_classes()  # a failure stays on screen
    dlg.close()
    spin(lambda: bool(finished), 2)
    assert finished == [False]
    win.destroy()


def test_the_notifier_dialog_turns_things_on_and_off(monkeypatch, tmp_path):
    from kram.app.ports import FakeBus
    from kram.gtk.dialogs import notifier as notifier_dialog
    from kram.notifier import control
    system = tmp_path / "xdg-autostart"
    system.mkdir()
    (system / "org.kde.discover.notifier.desktop").write_text("[Desktop Entry]\nExec=DiscoverNotifier\n")
    monkeypatch.setattr(control, "SYSTEM_AUTOSTART", system)
    calls = []
    monkeypatch.setattr(control, "checker_enabled", lambda: bool(calls) and calls[-1])
    monkeypatch.setattr(control, "set_checker_enabled", lambda on: calls.append(on) or "")
    monkeypatch.setattr(control, "fedora_timer_state", lambda: "disabled")
    monkeypatch.setattr(notifier_dialog, "bus", FakeBus())
    dialog = notifier_dialog.NotifierDialog()
    assert dialog.fedora_button.get_visible() and not dialog.stale_days.get_sensitive()
    dialog.enabled.set_active(True)
    assert calls == [True] and dialog.stale_days.get_sensitive()
    [row] = dialog.rows  # Discover only: GNOME Software is not "installed"
    row.toggle.emit("clicked")
    assert row.notifier.turned_off() and row.toggle.get_child().get_label() == "Turn Back On"
    row.toggle.emit("clicked")
    assert not row.notifier.turned_off()


def test_the_cleanup_dialog_shows_the_caches_and_the_leftovers():
    from kram.app.cache import CacheLine, LeftoverLine
    from kram.gtk.dialogs.cache import CacheDialog
    dnf = SimpleNamespace(submit=lambda fn, done, failed=None: None)  # nothing comes back: the view is fed below
    cleaned = []
    dlg = CacheDialog(dnf, lambda target, done: cleaned.append(target), helper=lambda *a: None)
    assert dlg.rows["dnf_packages"].size.get_text() == "…" and not dlg.rows["dnf_packages"].button.get_sensitive()
    dlg.show_caches([CacheLine("dnf_packages", True, "/var/cache/libdnf5", "/var/cache/libdnf5", "12 MB", "3 files",
                               True), CacheLine("packagekit", False)])
    row = dlg.rows["dnf_packages"]
    assert row.size.get_text() == "12 MB" and row.button.get_sensitive() and not dlg.rows["packagekit"].get_visible()
    row.button.emit("clicked")
    assert cleaned == ["dnf_packages"]
    leftover = SimpleNamespace(path="/etc/foo.conf.rpmsave", current="/etc/foo.conf")
    dlg.show_leftovers([LeftoverLine(leftover, ("text-x-generic",), "Your earlier version", "1.1.2026\n1 KB", True,
                                     "", True)], "1 file found.", True, False)
    assert [r.get_title() for r in dlg.leftover_rows] == ["/etc/foo.conf.rpmsave"]
    assert dlg.search_root_btn.get_visible() and not dlg.delete_unused_btn.get_sensitive()
    dlg.show_leftovers([], "Nothing found.", False, False)
    assert dlg.leftover_rows == [] and dlg.leftovers_status.get_title() == "Nothing found."


def test_the_release_notes_go_to_the_about_dialog():
    from kram.core.releases import Release, load
    from kram.gtk.doc_view import release_notes
    notes = release_notes([Release("1.0", "2026-01-01", ["Fixes <things> & more."], ["One", "Two"])])
    assert notes == ("<p><em>1.0 — 2026-01-01</em></p><p>Fixes &lt;things&gt; &amp; more.</p>"
                     "<ul><li>One</li><li>Two</li></ul>")
    about = Adw.AboutDialog()
    about.set_release_notes(release_notes(load()))  # the shipped metainfo parses
    assert about.get_release_notes()
