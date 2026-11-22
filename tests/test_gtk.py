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

from kram.app.parity import Feature  # noqa: E402  (the feature marks of the parity tests)

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


@pytest.mark.feature(Feature.MARK_INSTALL_REMOVE, front="gtk")
@pytest.mark.feature(Feature.MENU_ACCELERATORS, front="gtk")
def test_accelerators_are_gtks():
    from kram.gtk.actions import accel
    assert accel("Ctrl+Shift+Z") == "<Control><Shift>z"
    assert accel("Ins") == "Insert" and accel("Del") == "Delete" and accel("Alt+Left") == "<Alt>Left"
    for d in action_defs():
        for s in d.shortcuts:
            assert Gtk.accelerator_parse(accel(s))[0], s


@pytest.mark.feature(Feature.ICON_NON_PIXELATED, front="gtk")
def test_painted_icons_draw_at_every_scale():
    """The vectors draw onto a surface of any screen scale, and the icon fills its box."""
    import cairo

    from kram.gtk import icons
    for scale in (1.0, 1.25, 1.5, 2.0):
        for ref in (("status", Status.UPGRADABLE), ("mark", Action.REMOVE), ("origin", Origin.COPR), ("blocked",)):
            side = 16
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, round(side * scale), round(side * scale))
            surface.set_device_scale(scale, scale)
            icons.paint(cairo.Context(surface), icons.drawer(ref), 0, 0, side)
            surface.flush()
            assert any(surface.get_data()), ref  # something was drawn


@pytest.mark.feature(Feature.LIST_ROW_TINT, front="gtk")
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


@pytest.mark.feature(Feature.LIST_SORT, front="gtk")
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


@pytest.mark.feature(Feature.SETTINGS_REGISTRY, front="gtk")
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


@pytest.mark.feature(Feature.MENU_BAR, front="gtk")
@pytest.mark.feature(Feature.MENU_HAMBURGER, front="gtk")
@pytest.mark.feature(Feature.SETTINGS_MENU_BAR, front="gtk")
@pytest.mark.feature(Feature.SIDEBAR_VIEWS, front="gtk")
@pytest.mark.feature(Feature.WINDOW_STATUS_BAR, front="gtk")
def test_the_main_window_shows_the_catalog(monkeypatch):
    import kram.gtk.window as window_module
    from kram.app.browser import Browser
    snap = CatalogSnapshot(rows(300), 100, 0, 0.1)
    catalog = SimpleNamespace(load=lambda *a, **k: snap, blocked_upgrades=lambda: {},
                              details=lambda key: (_ for _ in ()).throw(LookupError(key)))
    monkeypatch.setattr(window_module, "Browser",
                        lambda view, ui, scheduler, details, post, **kw: Browser(view, ui, scheduler, details, post,
                                                                                 catalog=catalog, **kw))
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


@pytest.mark.feature(Feature.DIALOG_APPLY_CONFLICTS, front="gtk")
def test_the_gtk_window_names_its_package_and_closes_when_it_is_removed(monkeypatch):
    """The offer itself is the Browser's (tests/test_browser.py); the window says which package it is and closes."""
    import kram.gtk.window as window_module
    from kram.app.browser import Browser
    snap = CatalogSnapshot(rows(3), 1, 0, 0.1)
    catalog = SimpleNamespace(load=lambda *a, **k: snap, blocked_upgrades=lambda: {},
                              details=lambda key: (_ for _ in ()).throw(LookupError(key)))
    monkeypatch.setattr(window_module, "Browser",
                        lambda view, ui, scheduler, details, post, **kw: Browser(view, ui, scheduler, details, post,
                                                                                 catalog=catalog, **kw))
    from kram.gtk.app import KramApplication
    app = KramApplication()
    app.register(None)
    from kram.gtk.window import MainWindow
    win = MainWindow(app)
    win.present()
    spin(lambda: win.browser.snapshot is not None, 5)
    assert win.browser.front_package == "kram-gtk"
    win.quit()
    spin(lambda: not win.get_visible(), 3)
    assert not win.get_visible()


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


@pytest.mark.feature(Feature.DIALOG_APPLY, front="gtk")
@pytest.mark.feature(Feature.DIALOG_APPLY_COMMAND, front="gtk")
@pytest.mark.feature(Feature.DIALOG_APPLY_DOWNLOAD_ONLY, front="gtk")
@pytest.mark.feature(Feature.DIALOG_APPLY_RECOMMENDATIONS, front="gtk")
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


@pytest.mark.feature(Feature.DIALOG_PROGRESS, front="gtk")
@pytest.mark.feature(Feature.DIALOG_PROGRESS_CLOSE_LOCK, front="gtk")
@pytest.mark.feature(Feature.DIALOG_PROGRESS_LOG, front="gtk")
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


@pytest.mark.feature(Feature.DIALOG_PROGRESS_AUTO_CLOSE, front="gtk")
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


@pytest.mark.feature(Feature.DIALOG_NOTIFICATIONS, front="gtk")
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


@pytest.mark.feature(Feature.DIALOG_CLEANUP, front="gtk")
@pytest.mark.feature(Feature.DIALOG_CLEANUP_CACHES, front="gtk")
@pytest.mark.feature(Feature.DIALOG_CLEANUP_LEFTOVERS, front="gtk")
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


@pytest.mark.feature(Feature.DIALOG_WHATS_NEW, front="gtk")
def test_the_release_notes_go_to_the_about_dialog():
    from kram.core.releases import Release, load
    from kram.gtk.doc_view import release_notes
    notes = release_notes([Release("1.0", "2026-01-01", ["Fixes <things> & more."], ["One", "Two"])])
    assert notes == ("<p><em>1.0 — 2026-01-01</em></p><p>Fixes &lt;things&gt; &amp; more.</p>"
                     "<ul><li>One</li><li>Two</li></ul>")
    about = Adw.AboutDialog()
    about.set_release_notes(release_notes(load()))  # the shipped metainfo parses
    assert about.get_release_notes()


def _repos():
    from kram.core.model import Origin, RepoInfo
    return [RepoInfo("fedora", "Fedora 44 - x86_64", True, Origin.FEDORA, 60, 99, "/etc/yum.repos.d/fedora.repo"),
            RepoInfo("fedora-debuginfo", "Fedora 44 - Debug", False, Origin.FEDORA, 60, 99,
                     "/etc/yum.repos.d/fedora.repo"),
            RepoInfo("code", "Visual Studio Code", True, Origin.THIRD_PARTY, 60, 99, "/etc/yum.repos.d/vscode.repo")]


def _select_repo(dlg, repo_id: str) -> None:
    for i in range(dlg.selection.get_n_items()):
        if dlg.selection.get_item(i).data.repo.id == repo_id:
            dlg.selection.set_selected(i)
            return
    raise AssertionError(repo_id)


@pytest.mark.feature(Feature.DIALOG_REPOSITORIES, front="gtk")
@pytest.mark.feature(Feature.DIALOG_REPOSITORIES_FILTER, front="gtk")
@pytest.mark.feature(Feature.DIALOG_REPOSITORIES_SHOW_AUX, front="gtk")
def test_the_repositories_dialog_toggles_filters_and_chooses():
    from collections import Counter

    from kram.app.ports import RecordingUi
    from kram.gtk.dialogs.repos import ReposDialog
    win = Gtk.Window(default_width=1200, default_height=700)
    win.present()
    closed = []
    dlg = ReposDialog(_repos(), Counter({"fedora": 70000, "code": 3}), lambda d, ok: closed.append((d, ok)),
                      listed=Counter({"code": 3}), installed=Counter({"code": 1}))
    dlg.present(win)
    spin(seconds=0.3)
    assert dlg.selection.get_n_items() == 2  # no debuginfo repository unless asked for
    dlg.show_aux.set_active(True)
    assert dlg.selection.get_n_items() == 3
    dlg.filter.set_text("visual")
    spin(lambda: dlg.selection.get_n_items() == 1, 2)
    assert dlg.selection.get_item(0).data.repo.id == "code"
    dlg.filter.set_text("")
    spin(lambda: dlg.selection.get_n_items() == 3, 2)
    # the checkbox of a row
    assert not dlg.apply_btn.get_sensitive()
    check = next(w for w in _walk(dlg.table) if isinstance(w, Gtk.CheckButton) and w.repo_id == "code")
    check.set_active(False)
    assert dlg.changes() == {"code": False} and dlg.apply_btn.get_sensitive()
    check.set_active(True)
    # the menu of a repository
    menu = dlg.menu_model("code")
    labels = [menu.get_item_link(s, "section").get_item_attribute_value(i, "label", None).get_string()
              for s in range(menu.get_n_items()) for i in range(menu.get_item_link(s, "section").get_n_items())]
    assert labels == ["Show Packages", "Remove Repository…", "Copy Path", "Show in File Manager"]
    # removing it closes with the choice
    dlg.repos._ui = RecordingUi(["remove"])
    _select_repo(dlg, "code")
    assert dlg.remove_btn.get_sensitive()
    dlg.remove_btn.emit("clicked")
    spin(lambda: bool(closed), 2)
    assert closed and closed[0][1] is False and dlg.remove_repos == ["code"]
    win.destroy()


def test_the_repositories_dialog_applies():
    from collections import Counter

    from kram.gtk.dialogs.repos import ReposDialog
    win = Gtk.Window()
    win.present()
    closed = []
    dlg = ReposDialog(_repos(), Counter(), lambda d, ok: closed.append(ok))
    dlg.present(win)
    dlg.repos.set_enabled("fedora", False)
    dlg._update_buttons()
    dlg.apply_btn.emit("clicked")
    spin(lambda: bool(closed), 2)
    assert closed == [True] and dlg.changes() == {"fedora": False}
    win.destroy()


@pytest.mark.feature(Feature.DIALOG_COPR, front="gtk")
@pytest.mark.feature(Feature.DIALOG_COPR_ENABLE_FROM_SEARCH, front="gtk")
@pytest.mark.feature(Feature.DIALOG_COPR_PACKAGES, front="gtk")
def test_the_copr_dialog_lists_searches_and_enables(monkeypatch):
    import json
    from collections import Counter

    from kram.core import net
    from kram.core.model import Origin, RepoInfo
    from kram.gtk.dialogs.copr import CoprDialog
    repo = "copr:copr.fedorainfracloud.org:elmodos:Kram"
    snap = SimpleNamespace(rows=[SimpleNamespace(installed=True, origin_repo=repo)],
                           repos=[RepoInfo(repo, "Kram", True, Origin.COPR, 60)], releasever="45", basearch="x86_64")
    payload = {"items": [{"full_name": "a/tool", "description": "d", "chroot_repos": {"fedora-45-x86_64": ""}}]}
    monkeypatch.setattr(net, "fetch", lambda url, *, done, **kw: done(json.dumps(payload).encode()))
    win = Gtk.Window()
    win.present()
    helper, shown = [], []
    dlg = CoprDialog(lambda req, title: helper.append(req), shown.append)
    dlg.present(win)
    dlg.set_catalog(snap, Counter({repo: 7}))
    assert dlg.enabled_selection.get_n_items() == 1 and not dlg.disable_btn.get_sensitive()
    dlg.enabled_selection.set_selected(0)
    assert dlg.disable_btn.get_sensitive() and not dlg.enable_btn.get_sensitive()
    dlg.disable_btn.emit("clicked")
    assert helper == [{"op": "copr", "action": "disable", "project": "elmodos/Kram"}]
    dlg.set_catalog(snap, Counter({repo: 7}))  # the reload after it keeps the selection
    assert dlg._selected_project().repo_id == repo
    dlg.query.set_text("tool")
    dlg.search_btn.emit("clicked")
    spin(lambda: dlg.results_selection.get_n_items() == 1, 2)
    assert dlg._selected_result().full_name == "a/tool" and dlg.add_btn.get_sensitive()
    dlg.add_btn.emit("clicked")
    assert helper[-1] == {"op": "copr", "action": "enable", "project": "a/tool"}
    dlg.packages_btn.emit("clicked")
    spin(seconds=0.2)
    assert shown == [repo]
    win.destroy()


@pytest.mark.feature(Feature.DIALOG_CUSTOM_FILTERS, front="gtk")
@pytest.mark.feature(Feature.DIALOG_CUSTOM_FILTERS_COUNT, front="gtk")
def test_the_custom_filters_dialog_edits_a_copy():
    from kram.core.custom_filters import Condition, CustomFilter, Field, Op
    from kram.gtk.dialogs.filters import FiltersDialog
    snap = CatalogSnapshot(rows(30), 10, 0, 0.1)
    filters = [CustomFilter("Big", [Condition(Field.NAME, Op.CONTAINS, "pkg001")]), CustomFilter("Other")]
    win = Gtk.Window(default_width=1000, default_height=600)
    win.present()
    results = []
    dlg = FiltersDialog(filters, snap, results.append, select="Big")
    dlg.present(win)
    spin(lambda: "match" in dlg.count.get_text(), 2)
    assert dlg.name.get_text() == "Big" and len(dlg._rows) == 1
    assert dlg.count.get_text() == "10 packages match"  # pkg0010 … pkg0019
    dlg._rows[0].entry.set_text("pkg0012")
    spin(lambda: dlg.count.get_text() == "1 package matches", 2)
    dlg.name.set_text("Twelve")
    assert dlg.list.get_row_at_index(0).get_child().get_text() == "Twelve"
    dlg.list.select_row(dlg.list.get_row_at_index(1))
    assert dlg.name.get_text() == "Other" and dlg._rows == []
    dlg._add_row(Condition(Field.ARCH, Op.IS, "x86_64"))
    dlg.delete_btn.emit("clicked")  # Other goes
    assert [f.name for f in dlg.filters()] == ["Twelve"] and dlg.name.get_text() == "Twelve"
    dlg._add(CustomFilter(dlg.edit.unique("Twelve")))
    assert dlg.name.get_text() == "Twelve 2"
    dlg.name.set_text("")
    dlg._accept(None)  # no name: it says so and stays
    spin(seconds=0.1)
    assert results == []
    dlg.name.set_text("Mine")
    dlg._accept(None)
    spin(lambda: bool(results), 2)
    saved, current = results[0]
    assert [f.name for f in saved] == ["Twelve", "Mine"] and current == "Mine"
    assert saved[0].conditions == [Condition(Field.NAME, Op.CONTAINS, "pkg0012")]
    assert filters[0].name == "Big"  # the caller's list is not touched
    win.destroy()


@pytest.mark.feature(Feature.DIALOG_HISTORY, front="gtk")
@pytest.mark.feature(Feature.DIALOG_HISTORY_FILTER, front="gtk")
@pytest.mark.feature(Feature.DIALOG_HISTORY_UNDO, front="gtk")
def test_the_history_window_loads_filters_and_undoes(monkeypatch):
    from kram.app import history
    from kram.core.history import HistoryItem, HistoryTransaction
    from kram.core.model import Reason
    from kram.gtk.dialogs.history import HistoryWindow
    transactions = [HistoryTransaction(3, 1795000000, 0, "dnf5 remove fish", "", True),
                    HistoryTransaction(2, 1794000000, 1000, "kram", "", False),
                    HistoryTransaction(1, 1793000000, 1000, "kram", "", True)]
    items = {3: (HistoryItem("fish", "x86_64", "4.0-1", "remove", Reason.USER, "@System"),),
             2: (HistoryItem("vim", "x86_64", "9.1-2", "upgrade", Reason.USER, "updates"),),
             1: (HistoryItem("vim", "x86_64", "9.1-2", "upgrade", Reason.USER, "updates"),
                 HistoryItem("vim", "x86_64", "9.1-1", "replaced", Reason.USER, "@System"),
                 HistoryItem("fish", "x86_64", "4.0-1", "install", Reason.USER, "fedora"))}
    catalog = SimpleNamespace(history=lambda: transactions, history_items=lambda ids: {i: items[i] for i in ids})
    worker = SimpleNamespace(submit=lambda fn, done, failed=None: done(fn()))
    monkeypatch.setattr(history, "CHUNK", 2)
    parent = Gtk.Window()
    win = HistoryWindow(worker, catalog, parent)
    win.reload()
    win.present()
    spin(lambda: win.state.get_text() == "3 transactions", 2)
    ids = [win.selection.get_item(i).data.id for i in range(win.selection.get_n_items())]
    assert ids == [3, 2, 1] and win._store.get_item(2).data.changes == "1 installed, 1 upgraded"
    assert win.history.current == 3  # the newest, as it loaded
    win.set_current(1)
    shown = [(p.action, p.package, p.version) for p in
             (win.package_selection.get_item(i).data for i in range(win.package_selection.get_n_items()))]
    assert shown == [("Install", "fish.x86_64", "4.0-1"), ("Upgrade", "vim.x86_64", "9.1-1 → 9.1-2")]
    opened = []
    win.on_show_package = opened.append
    win._activated(win.packages, 0)
    assert opened == [("fish", "x86_64")]
    win.show_package_name("FISH")
    assert win.selection.get_n_items() == 2 and win.state.get_text() == "2 of 3 transactions"
    undone = []
    win.on_undo = undone.append
    assert not win.undo.get_sensitive()  # no catalog yet
    win.set_marking(True, False)
    assert win.undo.get_sensitive()
    win.undo.emit("clicked")
    assert undone == [1]
    win.close()
    assert not win.get_visible()  # hidden, kept for the next time
    win.destroy()
    parent.destroy()


@pytest.mark.feature(Feature.DIALOG_INSTALL_FILE, front="gtk")
@pytest.mark.feature(Feature.DIALOG_INSTALL_FILE_COMMAND, front="gtk")
def test_the_install_dialog_shows_the_file_and_installs_it(monkeypatch):
    from test_install_flow import Catalog, Sync, make_rpm

    from kram.app import install
    from kram.core import local_rpm
    from kram.gtk.dialogs import install as install_dialog
    rpm = make_rpm()
    monkeypatch.setattr(local_rpm, "read", lambda path: rpm)
    monkeypatch.setattr(install, "DnfWorker", lambda post, name: Sync())
    monkeypatch.setattr(install_dialog, "post", lambda fn: fn())
    win = Adw.ApplicationWindow(default_width=900, default_height=780)
    win.present()
    closed = []
    helper = SimpleNamespace(busy=False)
    dlg = install_dialog.InstallDialog(rpm.path, Catalog(), Sync(), helper, marks=2, done=closed.append)
    dlg.present(win)
    page = dlg.page
    spin(lambda: page.install.get_sensitive(), 2)
    assert "tool" in page.title.get_text() and "2.0-1.x86_64" in page.title.get_text()
    assert page.install.get_child().get_label() == "Upgrade" and page.cmd_box.get_visible()
    assert "sudo dnf5 install /tmp/tool-2.0-1.x86_64.rpm" == page.cmd.get_text()
    assert "Signed by Fedora." in page.notes_text() and "tool" in _texts(page.changes)
    ran = []
    page.run_transaction = lambda request, title, done: ran.append((request, done))
    page.install.emit("clicked")
    request, done = ran[0]
    assert request["op"] == "local_install"
    done(True)
    spin(lambda: bool(closed), 2)
    assert closed == [True]  # it ran: the main window reloads
    win.destroy()


def test_kram_file_rpm_runs_the_installer_on_its_own():
    from kram.gtk.app import file_argument
    assert file_argument(["--upgradable"]) is None
    assert file_argument(["/tmp/a.rpm"]) == "/tmp/a.rpm"
    assert file_argument(["file:///tmp/my%20a.rpm"]) == "/tmp/my a.rpm"


@pytest.mark.feature(Feature.RELEASE_BUTTON, front="gtk")
@pytest.mark.feature(Feature.RELEASE_DIALOG, front="gtk")
def test_the_fedora_upgrade_dialog_checks_and_cannot_close_meanwhile():
    from kram.gtk.dialogs.upgrade import UpgradeDialog
    snap = SimpleNamespace(basearch="x86_64", rows=[], repos=[])
    jobs = []
    dnf = SimpleNamespace(submit=lambda fn, done, failed=None: jobs.append((done, failed)))
    win = Adw.ApplicationWindow()
    win.present()
    dlg = UpgradeDialog(46, 45, "2026-12-01", snap, dnf)
    dlg.present(win)
    assert dlg.tree.get_model().get_n_items() == 1  # "No COPR projects are enabled."
    dlg.check.emit("clicked")
    assert jobs and not dlg.get_can_close() and dlg.cancel_button.get_visible() and dlg.log_box.get_visible()
    dlg.upgrade._on_report("progress", {"done": 5, "total": 10})
    assert 0.4 < dlg.busy.get_fraction() < 0.6
    from kram.core import upgrade_audit
    jobs[0][1](upgrade_audit.Cancelled())
    assert dlg.get_can_close() and dlg.check.get_visible()
    win.destroy()


@pytest.mark.feature(Feature.RELEASE_BUTTON, front="gtk")
@pytest.mark.feature(Feature.RELEASE_WATCH, front="gtk")
@pytest.mark.feature(Feature.SETTINGS_WATCH_RELEASES, front="gtk")
def test_the_release_button_follows_the_last_check():
    from kram.gtk.window import MainWindow
    win = SimpleNamespace(releases=SimpleNamespace(button=lambda: SimpleNamespace(visible=True, text="Fedora 46",
                                                                                   tooltip="tip")),
                          upgrade_button=Gtk.Button(child=Adw.ButtonContent(label="Fedora")))
    MainWindow.update_release_button(win)
    assert win.upgrade_button.get_visible() and win.upgrade_button.get_child().get_label() == "Fedora 46"


@pytest.mark.feature(Feature.DETAILS_FILES_COPY_PATH, front="gtk")
@pytest.mark.feature(Feature.DETAILS_FILES_FILTER, front="gtk")
@pytest.mark.feature(Feature.DETAILS_FILES_LIST, front="gtk")
@pytest.mark.feature(Feature.DETAILS_FILES_TREE, front="gtk")
def test_the_files_tab_shows_a_tree_or_a_list_and_filters():
    from kram.app.ports import RecordingUi
    from kram.core.file_tree import path_filter
    from kram.gtk.files import FileList, name_markup
    ui = RecordingUi([])
    files = FileList(ui)
    win = Gtk.Window(child=files, default_width=600, default_height=400)
    files.set_files(["/usr/bin/tool", "/usr/lib64/libtool.so.1", "/usr/share/doc/tool/README"], True)
    assert files._stale  # not built while hidden
    win.present()
    spin(lambda: not files._stale, 2)
    names = [files.selection.get_item(i).get_item().name for i in range(files.selection.get_n_items())]
    assert names[:3] == ["usr", "bin", "tool"] and files.count.get_text() == "3 files"  # every folder open
    files.list_button.set_active(True)
    paths = [files.selection.get_item(i).path for i in range(files.selection.get_n_items())]
    assert paths == ["/usr/bin/tool", "/usr/lib64/libtool.so.1", "/usr/share/doc/tool/README"]
    files.filter.set_text("*.so*")
    spin(lambda: files.count.get_text() == "1 of 3 files", 2)
    files.selection.select_item(0, True)
    files.copy_paths()
    assert ui.calls[-1] == ("copy", "/usr/lib64/libtool.so.1")
    assert name_markup("libtool.so", "/usr/lib/libtool.so", path_filter("tool")) == "lib<b>tool</b>.so"
    win.destroy()


@pytest.mark.feature(Feature.LIST_COLUMNS, front="gtk")
def test_the_column_menu_hides_columns_and_the_state_comes_back():
    from kram.app.columns import COL_DOWNLOAD, COL_NAME, COL_REPO, COL_STATUS
    from kram.gtk.package_list import PackageListView
    packages = PackageList()
    view = PackageListView(packages)
    assert not view.columns[COL_DOWNLOAD].get_visible()  # until the user shows it
    view.activate_action("columns.show-%d" % COL_REPO, None)
    assert not view.columns[COL_REPO].get_visible()
    view.view.insert_column(0, view.columns[COL_NAME])
    view.columns[COL_NAME].set_fixed_width(321)
    state = view.column_state()
    assert state["order"][0] == COL_NAME and COL_REPO in state["hidden"] and state["widths"][str(COL_NAME)] == 321
    other = PackageListView(PackageList())
    other.restore_columns(state)
    assert other.column_state() == state
    other.restore_columns({"order": "junk"})  # a broken setting changes nothing
    assert other.column_state() == state
    assert other.view.get_columns().get_item(1).get_id() == str(COL_STATUS)


@pytest.mark.feature(Feature.DIALOG_ABOUT_TOOLKIT, front="gtk")
def test_the_gtk_front_end_names_gtk_and_libadwaita():
    from kram.gtk.window import toolkit_versions
    text = toolkit_versions()
    assert text.startswith("GTK 4.") and ", libadwaita 1." in text


@pytest.mark.feature(Feature.SIDEBAR_SECTION_ICONS, front="gtk")
def test_every_section_button_has_an_icon_the_theme_has():
    from kram.app.sidebar import VIEWS
    from kram.gtk.sidebar import VIEW_ICONS
    theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
    assert [view_id for view_id, _label, _b in VIEWS] == list(VIEW_ICONS)
    missing = [name for name in VIEW_ICONS.values() if not theme.has_icon(name)]
    assert not missing, f"icons the theme lacks: {missing}"


def test_tab_leaves_the_package_table_for_the_next_widget():
    """The table's own keyboard focus would walk its rows; Tab must move to the widget after it (and Shift+Tab back)."""
    from kram.gtk.package_list import PackageListView
    packages = PackageList()
    packages.set_rows(rows(200), "x86_64")
    before = Gtk.Button(label="before")
    view = PackageListView(packages)
    after = Gtk.Button(label="after")
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    for w in (before, view, after):
        box.append(w)
    win = Gtk.Window(child=box, default_width=600, default_height=400)
    win.present()
    spin(seconds=0.3)
    view.view.grab_focus()
    keys = next(c for c in view.observe_controllers() if isinstance(c, Gtk.EventControllerKey))
    assert keys.emit("key-pressed", Gdk.KEY_Tab, 0, Gdk.ModifierType(0)) is True
    spin(seconds=0.1)
    assert win.get_focus() is after
    assert keys.emit("key-pressed", Gdk.KEY_Tab, 0, Gdk.ModifierType.SHIFT_MASK) is True
    spin(seconds=0.1)
    assert win.get_focus() is before
    win.destroy()


def _bound_cells(view):
    """The cells the list currently shows, once it has drawn: (position, column, cell)."""
    return [(c.pos, c.col, c) for c in view._bound.values() if c.pos >= 0]


@pytest.mark.feature(Feature.LIST_CONTEXT_MENU, front="gtk")
def test_a_right_click_on_a_row_selects_it_and_opens_its_menu():
    from kram.gtk.package_list import PackageListView
    packages = PackageList()
    packages.set_rows(rows(20), "x86_64")
    view = PackageListView(packages)
    win = Gtk.Window(child=view, default_width=600, default_height=300)
    win.present()
    spin(seconds=0.3)
    opened = []
    view.on_context_menu = lambda pos, widget, x, y: opened.append(pos)
    pos, _col, cell = next(c for c in _bound_cells(view) if c[0] == 4)
    gesture = SimpleNamespace(get_current_button=lambda: Gdk.BUTTON_SECONDARY, set_state=lambda state: None)
    view._pressed(gesture, 1, 5.0, 5.0, cell)
    assert opened == [4] and view.selected_positions() == [4]
    win.destroy()


@pytest.mark.feature(Feature.LIST_STATUS_CLICK, front="gtk")
def test_a_click_on_the_status_cell_is_the_status_click():
    from kram.app.columns import COL_STATUS
    from kram.gtk.package_list import PackageListView
    packages = PackageList()
    packages.set_rows(rows(20), "x86_64")
    view = PackageListView(packages)
    win = Gtk.Window(child=view, default_width=600, default_height=300)
    win.present()
    spin(seconds=0.3)
    clicked = []
    view.on_status_click = lambda pos, widget: clicked.append(pos)
    pos, _col, cell = next(c for c in _bound_cells(view) if c[1] == COL_STATUS and c[0] == 2)
    gesture = SimpleNamespace(get_current_button=lambda: Gdk.BUTTON_PRIMARY, set_state=lambda state: None)
    view._pressed(gesture, 1, 5.0, 5.0, cell)
    assert clicked == [2]
    win.destroy()


@pytest.mark.feature(Feature.LIST_DOUBLE_CLICK_MARK, front="gtk")
def test_activating_a_row_is_the_likely_mark():
    from kram.gtk.package_list import PackageListView
    packages = PackageList()
    packages.set_rows(rows(20), "x86_64")
    view = PackageListView(packages)
    activated = []
    view.on_activate = activated.append
    view.view.emit("activate", 3)  # what a double click or Enter on a row emits
    assert activated == [3]


@pytest.mark.feature(Feature.LIST_MULTI_SELECT, front="gtk")
def test_several_rows_are_selected_at_once():
    from kram.gtk.package_list import PackageListView
    packages = PackageList()
    packages.set_rows(rows(20), "x86_64")
    view = PackageListView(packages)
    win = Gtk.Window(child=view, default_width=600, default_height=300)
    win.present()
    spin(seconds=0.2)
    view.selection.select_range(2, 3, True)  # rows 2, 3, 4
    assert view.selected_positions() == [2, 3, 4]
    win.destroy()


@pytest.mark.feature(Feature.SEARCH_BAR, front="gtk")
def test_the_search_field_and_its_mode_go_to_the_controller():
    from kram.core.mainloop import Signal
    from kram.core.search import Mode
    from kram.gtk.search import SearchBox
    calls = []
    controller = SimpleNamespace(shown=Signal(), filtering=False, edited=lambda text: calls.append(("edited", text)),
                                 mode_chosen=lambda mode: calls.append(("mode", mode)),
                                 submit=lambda: calls.append(("submit",)))
    box = SearchBox(controller)
    box.entry.set_text("kram")
    spin(lambda: ("edited", "kram") in calls, 2)  # the search field reports after a moment, on the main loop
    assert ("edited", "kram") in calls
    box.mode_box.set_selected(int(Mode.FILE))
    assert ("mode", int(Mode.FILE)) in calls
    controller.shown.emit("", Mode.NAME)  # the controller shows the search it holds: the field follows
    assert box.entry.get_text() == "" and box.mode_box.get_selected() == int(Mode.NAME)


@pytest.mark.feature(Feature.DETAILS_VERSIONS, front="gtk")
def test_the_versions_tab_lists_each_version_with_its_state():
    from kram.app.details import VersionRow
    from kram.gtk.details import DetailsView
    details = DetailsView()
    details._set_versions([VersionRow("5.3-1", "@System", "installed", True, False),
                           VersionRow("5.4-1", "fedora", "candidate", True, False),
                           VersionRow("5.2-1", "fedora", "excluded by the version lock", False, True)])
    model = details.versions.get_model()
    assert model.get_n_items() == 3
    rows_ = [model.get_item(i).data for i in range(model.get_n_items())]
    assert [r.evr for r in rows_] == ["5.3-1", "5.4-1", "5.2-1"] and rows_[2].dimmed


@pytest.mark.feature(Feature.INSTALL_FILE_DROP, front="gtk")
def test_an_rpm_dropped_on_the_window_opens_the_installer(monkeypatch):
    import kram.gtk.window as window_module
    from kram.app.browser import Browser
    from kram.gtk.app import KramApplication
    from kram.gtk.window import MainWindow
    snap = CatalogSnapshot(rows(30), 10, 0, 0.1)
    catalog = SimpleNamespace(load=lambda *a, **k: snap, blocked_upgrades=lambda: {},
                              details=lambda key: (_ for _ in ()).throw(LookupError(key)))
    monkeypatch.setattr(window_module, "Browser",
                        lambda view, ui, scheduler, details, post, **kw: Browser(view, ui, scheduler, details, post,
                                                                                 catalog=catalog, **kw))
    app = KramApplication()
    app.register(None)
    win = MainWindow(app)
    win.present()
    spin(lambda: win.browser.snapshot is not None, 3)
    opened = []
    monkeypatch.setattr(win, "open_package_file", lambda path=None: opened.append(path))
    monkeypatch.setattr(win.browser, "can_open_file", lambda: True)
    from gi.repository import Gio
    files = Gdk.FileList.new_from_array([Gio.File.new_for_path("/tmp/tool-1.0-1.x86_64.rpm")])
    assert win._dropped(None, files, 0, 0) is True
    spin(lambda: bool(opened), 2)
    assert opened == ["/tmp/tool-1.0-1.x86_64.rpm"]
    other = Gdk.FileList.new_from_array([Gio.File.new_for_path("/tmp/notes.txt")])
    assert win._dropped(None, other, 0, 0) is False
    win.close()
    spin(seconds=0.2)
