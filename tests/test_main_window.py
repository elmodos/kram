"""Regressions of the main window and the progress dialog that show only on screen. No catalog is loaded."""
import os
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

from kram.app.parity import Feature  # noqa: E402  (the feature marks of the parity tests)

pytest.importorskip("libdnf5")
pytest.importorskip("PySide6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QDialog

from kram.app.marking import group_menu
from kram.core import net
from kram.core.marks import Action, Mark, MarkSet
from kram.core.settings import store as settings
from kram.qt import main_window
from kram.qt.actions import fill_dynamic
from kram.qt.icons import blocked_icon
from kram.qt.progress_dialog import ProgressDialog


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, monkeypatch):
    monkeypatch.setattr(main_window.MainWindow, "reload", lambda self: None)
    win = main_window.MainWindow()
    yield win
    win.dnf.shutdown()


class FakeClient(QObject):
    event = Signal(dict)
    failed = Signal(str)

    def request(self, _request):
        return True


def test_catalog_actions_are_disabled_until_it_is_loaded(window):
    actions = (window.acts.repos, window.acts.copr, window.acts.cache, window.acts.filters, window.acts.new_filter)
    assert not any(a.isEnabled() for a in actions)
    window.browser.snapshot = SimpleNamespace(n_upgradable=0)
    window.browser.update_actions()
    assert all(a.isEnabled() for a in actions)


def test_progress_belongs_to_the_dialog_that_started_it(window, monkeypatch):
    """As a child of the main window, it could be covered by the COPR or Package Cache dialog behind it."""
    parents = []

    class Progress:
        ok = True
        result = {"ok": True}

        def __init__(self, _client, _request, _title, parent):
            parents.append(parent)

        def exec(self):
            return 0

        def deleteLater(self):
            pass

    monkeypatch.setattr(main_window, "ProgressDialog", Progress)
    window.run_helper({"op": "refresh"}, "t", lambda _r: None)
    modal = QDialog(window)
    modal.setModal(True)
    modal.show()
    try:
        window.run_helper({"op": "refresh"}, "t", lambda _r: None)
    finally:
        modal.close()
    assert parents == [window, modal]


def test_stage_line_leaves_the_authentication_message(app):
    dlg = ProgressDialog(FakeClient(), {"op": "refresh"}, "t")
    waiting = dlg.stage.text()
    dlg._on_event({"event": "log", "text": "Running: x", "key": "command", "params": {"command": "x"}})
    assert dlg.stage.text() == waiting
    dlg._on_event({"event": "log", "text": "Refreshing", "key": "refreshing", "params": {}})
    assert dlg.stage.text() != waiting


@pytest.mark.parametrize(("target", "bar_hidden"), [("dnf_packages", True), ("packagekit", True), ("dnf_metadata", False)])
def test_download_bar_only_when_something_downloads(app, target, bar_hidden):
    dlg = ProgressDialog(FakeClient(), {"op": "clean_cache", "target": target}, "t")
    assert dlg.download_bar.isHidden() is bar_hidden
    assert dlg.rpm_bar.isHidden()


BODHI = {"releases": [{"version": "44", "state": "current", "id_prefix": "FEDORA", "eol": "2027-06-02"},
                      {"version": "45", "state": "current", "id_prefix": "FEDORA", "eol": "2027-12-08"}]}


@pytest.fixture
def fedora(window, monkeypatch):
    window.releases.running = 44
    window.acts.watch_releases.setChecked(True)
    return window


def button(window):
    return window.releases.act_upgrade.isVisible(), window.releases.act_upgrade.text()


@pytest.mark.feature(Feature.FEDORA_UPGRADE_BUTTON, front="qt")
def test_new_release_shows_the_button(fedora):
    fedora.show()
    assert not fedora.releases.act_upgrade.isVisible()
    fedora.releases._on_reply(BODHI)
    assert button(fedora) == (True, "Fedora 45")
    assert fedora.releases.act_upgrade.toolTip() == "Fedora 45 is available, you have 44"
    assert settings.get("distro/running_eol") == "2027-06-02"


def test_a_failed_check_keeps_the_last_result(fedora):
    fedora.releases._on_reply(BODHI)
    for payload in ("not the answer", {"releases": []}, None):
        fedora.releases._on_reply(payload)
        assert settings.get("distro/target", 0) == 45


def test_button_goes_when_the_system_gets_there_or_watching_stops(fedora):
    fedora.releases._on_reply(BODHI)
    fedora.show()
    assert fedora.releases.act_upgrade.isVisible()
    fedora.acts.watch_releases.setChecked(False)
    assert not fedora.releases.act_upgrade.isVisible()
    fedora.acts.watch_releases.setChecked(True)
    assert fedora.releases.act_upgrade.isVisible()
    fedora.releases.running = 45
    fedora.releases.update_button()
    assert not fedora.releases.act_upgrade.isVisible()


def test_only_reload_asks_and_only_when_watching(fedora, monkeypatch):
    asked = []
    monkeypatch.setattr(net, "fetch_json", lambda url, **kw: asked.append(urlsplit(url).hostname))
    monkeypatch.setattr(fedora.browser, "run_helper", lambda request, title, done=None: done and done({"ok": True}))
    fedora.browser.refresh_metadata()
    assert asked == ["bodhi.fedoraproject.org"]
    fedora.acts.watch_releases.setChecked(False)
    fedora.browser.refresh_metadata()
    assert len(asked) == 1


def test_not_fedora_has_no_setting_and_no_check(fedora, monkeypatch):
    fedora.releases.running = None
    monkeypatch.setattr(net, "fetch_json", lambda url, **kw: pytest.fail("asked Bodhi"))
    fedora.releases.check()
    fedora.releases.update_button()
    assert not fedora.releases.act_upgrade.isVisible()


def test_a_full_download_bar_keeps_moving_until_the_end(app):
    dlg = ProgressDialog(FakeClient(), {"op": "refresh"}, "t")
    dlg._on_event({"event": "download", "id": 1, "name": "a", "total": 10, "done": 0})
    dlg._on_event({"event": "download", "id": 1, "total": 10, "done": 5})
    assert dlg.download_bar.maximum() == 1000 and dlg.download_bar.value() == 500
    dlg._on_event({"event": "download", "id": 1, "end": True, "ok": True})
    assert dlg.download_bar.maximum() == 0  # the other servers and reading the metadata are still to come
    dlg._on_event({"event": "done", "ok": True})
    assert dlg.download_bar.maximum() == 1 and dlg.download_bar.value() == 1


def test_a_failure_stops_the_busy_bar(app):
    dlg = ProgressDialog(FakeClient(), {"op": "refresh"}, "t")
    assert dlg.download_bar.maximum() == 0
    dlg._on_event({"event": "done", "ok": False, "stage": "exception", "error": "boom"})
    assert dlg.download_bar.maximum() == 1


def test_helper_messages_of_kram_are_translated_and_dnf_text_is_kept(app, monkeypatch):
    from kram.app import progress

    monkeypatch.setattr(progress, "_", lambda s: {"Running: {command}": "Виконання: {command}",
                                                         "Command failed: {command}": "Збій команди: {command}"}.get(s, s))
    dlg = ProgressDialog(FakeClient(), {"op": "clean_cache", "target": "dnf_packages"}, "t")
    dlg._on_event({"event": "log", "text": "Running: dnf5 clean packages", "key": "command",
                   "params": {"command": "dnf5 clean packages"}})
    dlg._on_event({"event": "log", "text": "Odstraněno 3 souborů"})  # dnf5's own output, in its language
    dlg._on_event({"event": "done", "ok": False, "stage": "clean", "key": "command_failed",
                   "params": {"command": "dnf5 clean packages"}, "error": "Command failed: dnf5 clean packages"})
    log = dlg.log.toPlainText()
    assert "Виконання: dnf5 clean packages" in log and "Odstraněno 3 souborů" in log
    assert "Збій команди: dnf5 clean packages" in log
    dlg._on_event({"event": "done", "ok": False, "stage": "resolve", "error": "Keine Pakete zum Entfernen"})
    assert "Keine Pakete zum Entfernen" in dlg.log.toPlainText()


def test_mark_upgrades_icon_follows_whether_there_is_anything_to_mark(app, monkeypatch):
    from PySide6.QtGui import QColor, QIcon, QPixmap

    def icon(color):
        pixmap = QPixmap(16, 16)
        pixmap.fill(QColor(color))
        return QIcon(pixmap)
    themed = {"update-medium": icon("red"), "update-none": icon("blue")}
    monkeypatch.setattr(QIcon, "fromTheme",
                        staticmethod(lambda name, fallback=None: themed.get(name, fallback or QIcon())))
    monkeypatch.setattr(main_window.MainWindow, "reload", lambda self: None)
    win = main_window.MainWindow()
    try:
        action = win.acts.mark_upgrades
        assert not action.isEnabled() and action.icon().cacheKey() == themed["update-none"].cacheKey()
        win.browser.snapshot = SimpleNamespace(n_upgradable=2)
        win.browser.update_actions()
        assert action.isEnabled() and action.icon().cacheKey() == themed["update-medium"].cacheKey()
        win.browser.snapshot = SimpleNamespace(n_upgradable=0)
        win.browser.update_actions()
        assert not action.isEnabled() and action.icon().cacheKey() == themed["update-none"].cacheKey()
    finally:
        win.dnf.shutdown()


@pytest.mark.feature(Feature.STATUS_CLICK_MARKS_LIKELY, front="qt")
def test_status_icon_click_marks_the_likely_action_only_when_chosen(window, monkeypatch):
    from kram.core.marks import Action
    from kram.core.model import Origin, PkgRow, Status
    from kram.qt.package_model import COL_NAME, COL_STATUS

    menus = []

    class Menu(main_window.QMenu):
        def exec(self, *_args):
            menus.append(self)
    monkeypatch.setattr(main_window, "QMenu", Menu)
    rows = [PkgRow("new", "x86_64", "", "", "1-1", "fedora", 1, Origin.FEDORA, Status.NOT_INSTALLED, False),
            PkgRow("old", "x86_64", "", "1-1", "1-2", "fedora", 1, Origin.FEDORA, Status.UPGRADABLE, True),
            PkgRow("same", "x86_64", "", "1-1", "1-1", "fedora", 1, Origin.FEDORA, Status.INSTALLED, True)]
    window.model.set_rows(rows, "x86_64")
    status = [window.model.index(i, COL_STATUS) for i in range(3)]
    marks = window.model.marks

    window.acts.status_click.setChecked(False)
    window._on_table_click(status[0])  # Synaptic's default: the menu
    assert len(menus) == 1 and len(marks) == 0

    window.acts.status_click.setChecked(True)
    window._on_table_click(status[0])
    window._on_table_click(status[1])
    assert [marks.get(r.key).action for r in rows[:2]] == [Action.INSTALL, Action.UPGRADE] and len(menus) == 1
    window._on_table_click(status[2])  # removal, reinstallation...: no obvious one, so the menu
    assert len(menus) == 2 and rows[2].key not in marks
    window._on_table_click(status[0])
    assert rows[0].key not in marks and settings.get("table/status_click", False) is True

    window._on_double_click(window.model.index(0, COL_NAME))  # unchanged
    assert marks.get(rows[0].key).action is Action.INSTALL


def test_groups_are_changed_at_once_from_the_sidebar(window, monkeypatch):
    """A comps group is not marked (the Marked list could not show it): its menu runs the change at once, after the
    review, alone; the package marks stay for a later Apply."""
    from PySide6.QtWidgets import QMenu

    from kram.core.marks import Action
    from kram.core.model import CatalogSnapshot, GroupInfo, Origin, PkgRow, Status

    fish = PkgRow("fish", "x86_64", "", "", "1-1", "fedora", 1, Origin.FEDORA, Status.NOT_INSTALLED)
    apps = GroupInfo("kde-apps", "KDE Applications", "", False, frozenset(), optional=frozenset({"kgeography"}))
    tools = GroupInfo("development-tools", "Development Tools", "", True, frozenset())
    window.browser._on_loaded(CatalogSnapshot([fish], 0, 0, 0.0, groups=[apps, tools]))
    window.sidebar.set_view("groups")
    runs = []

    def menu_for(group):
        menu = QMenu()
        fill_dynamic(menu, group_menu(group, busy=False, run=lambda *a: runs.append(a)))
        return menu

    # Upgrade waits for the check after loading, and stays off when it finds nothing to upgrade
    menu = menu_for(tools)
    assert {a.text(): a.isEnabled() for a in menu.actions()} == {"Upgrade Group…": False, "Remove Group…": True}
    tools.upgradable = True
    menu = menu_for(tools)
    assert menu.actions()[0].isEnabled()
    menu = menu_for(apps)
    assert [a.text() for a in menu.actions()] == ["Install Group…", "Install Group with Optional Packages…"]
    menu.actions()[1].trigger()
    assert runs == [(apps, Action.INSTALL, True)]

    window.model.marks.set(fish, Action.INSTALL)
    reviewed = []
    monkeypatch.setattr(window.browser, "_review", lambda request, marked: reviewed.append((request, marked)))
    window.browser.change_group(apps, Action.INSTALL, True)
    assert reviewed == [({"op": "transaction", "group_install_optional": ["kde-apps"]}, False)]
    assert len(window.model.marks) == 1  # fish stays marked


def test_environments_are_a_tree(window):
    """The Environments view is a tree: each environment folds its groups, the optional ones in italics; the list
    shows a group's optional packages in italics."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMenu

    from kram.core.model import CatalogSnapshot, GroupInfo, Origin, PkgRow, Status
    from kram.qt.package_model import COL_NAME

    rows = [PkgRow(n, "x86_64", "", "", "1-1", "fedora", 1, Origin.FEDORA, Status.NOT_INSTALLED)
            for n in ("plasma-desktop", "kgeography")]
    kde = GroupInfo("kde-desktop", "KDE", "", False, frozenset({"plasma-desktop", "kgeography"}),
                    optional=frozenset({"kgeography"}))
    edu = GroupInfo("kde-education", "KDE Education", "", False, frozenset({"kgeography"}))
    env = GroupInfo("kde-desktop-environment", "KDE Plasma Workspaces", "", False,
                    frozenset({"plasma-desktop", "kgeography"}), optional=frozenset({"kgeography"}),
                    environment=True, groups=("kde-desktop",), optional_groups=("kde-education",))
    xfce = GroupInfo("xfce-desktop-environment", "Xfce", "", False, frozenset(), environment=True,
                     groups=("kde-desktop",))
    window.browser._on_loaded(CatalogSnapshot(rows, 0, 0, 0.0, groups=[kde, edu], environments=[env, xfce]))
    sidebar = window.sidebar
    sidebar.set_view("environments")
    tree = sidebar.list
    assert tree.topLevelItemCount() == 2 and tree.rootIsDecorated()
    top = tree.topLevelItem(0)
    assert sidebar.current_entry_id == "env:kde-desktop-environment"  # the first one, no "All environments"
    assert top.childCount() == 2 and not top.isExpanded()
    assert top.child(1).font(0).italic() and not top.child(0).font(0).italic()

    top.setExpanded(True)
    tree.setCurrentItem(top.child(0))
    assert sidebar.current_entry_id == "envgroup:kde-desktop-environment:kde-desktop"
    sidebar.refresh_counts()  # rebuilt: the fold and the selection stay
    top = tree.topLevelItem(0)
    assert top.isExpanded() and not tree.topLevelItem(1).isExpanded()
    assert sidebar.current_entry_id == "envgroup:kde-desktop-environment:kde-desktop"

    names = {window.model.index(i, COL_NAME).data(): window.model.index(i, COL_NAME) for i in range(2)}
    assert names["kgeography"].data(Qt.ItemDataRole.FontRole).italic()
    assert names["plasma-desktop"].data(Qt.ItemDataRole.FontRole) is None
    assert "Optional in this group" in names["kgeography"].data(Qt.ItemDataRole.ToolTipRole)

    menu = QMenu()
    fill_dynamic(menu, group_menu(env, busy=False, run=lambda *a: None))
    assert [a.text() for a in menu.actions()] == ["Install Environment…",
                                                  "Install Environment with Optional Groups…"]

    sidebar.set_view("origin")  # the other views stay open, without arrows
    assert not tree.rootIsDecorated()

def test_a_provides_search_typed_over_is_skipped_not_run(window, monkeypatch):
    from kram.core.model import CatalogSnapshot, Origin, PkgRow, Status
    from kram.core.search import Mode, NarrowingSearch, SearchIndex

    rows = [PkgRow("vulkan-loader", "x86_64", "Vulkan", "1-1", "1-1", "fedora", 1, Origin.FEDORA, Status.INSTALLED)]
    window.browser.snapshot = CatalogSnapshot(rows, 1, 0, 0.0)
    window.model.set_rows(rows, "x86_64")
    from kram.core.filters import FilterEntry

    window.browser.filter = FilterEntry("status:all", "All", lambda _row: True)
    window.browser.index = SearchIndex(rows)
    window.browser.narrowing = NarrowingSearch(window.browser.index)
    window.browser.key_index = {rows[0].key: 0}
    jobs, asked = [], []
    monkeypatch.setattr(window.dnf, "submit", lambda fn, done, _error=None: jobs.append((fn, done)))
    monkeypatch.setattr(window.catalog, "search_provides", lambda text: asked.append(text) or [rows[0].key])
    window.search.mode_box.setCurrentIndex(Mode.PROVIDES)
    searches = []  # other jobs load the details of the selected row
    for text in ("vulk", "vulkan"):
        window.search.edit.setText(text)
        before = len(jobs)
        window.browser.apply_filter()
        searches.append(jobs[before])
        if text == "vulk":
            assert "indexes what packages provide" in window.status.text()  # the first one may take a moment
    answers = [fn() for fn, _done in searches]  # the dnf thread, in order
    assert answers[0] is None and asked == ["vulkan"]  # the first was typed over before its turn came
    for (_fn, done), answer in zip(searches, answers, strict=True):
        done(answer)
    assert window.model.rowCount() == 1


def test_the_sidebar_filter_is_not_worked_out_again_for_every_keystroke(window, monkeypatch):
    from kram.core.filters import FilterEntry
    from kram.core.model import CatalogSnapshot, Origin, PkgRow, Status
    from kram.qt.package_view import PackageView

    assert isinstance(window.table, PackageView)
    rows = [PkgRow(n, "x86_64", "", "", "1-1", "fedora", 1, Origin.FEDORA, Status.NOT_INSTALLED) for n in "abc"]
    window.browser.snapshot = CatalogSnapshot(rows, 0, 0, 0.0)
    calls = []

    def entry(entry_id):
        return FilterEntry(entry_id, entry_id, lambda r: calls.append(r.name) or r.name != "b")
    window.browser.filter = entry("status:all")
    assert window.browser._candidates() == [0, 2] and len(calls) == 3
    assert window.browser._candidates() == [0, 2] and len(calls) == 3  # the same entry and catalog: kept
    window.browser.filter = entry("status:all")  # rebuilt entry (new counts, edited custom filter)
    window.browser._candidates()
    assert len(calls) == 6
    window.browser.snapshot = CatalogSnapshot(rows, 0, 0, 0.0)  # reloaded catalog
    window.browser._candidates()
    assert len(calls) == 9
    window.browser.filter = entry("status:marked")  # follows the marks as they change: never kept
    window.browser._candidates()
    window.browser._candidates()
    assert len(calls) == 15


@pytest.mark.feature(Feature.DETAILS_TABS, front="qt")
def test_details_wait_for_the_cursor_to_rest(window, monkeypatch):
    from kram.core.model import Origin, PkgRow, Status

    rows = [PkgRow(n, "x86_64", "", "1-1", "1-1", "fedora", 1, Origin.FEDORA, Status.INSTALLED) for n in "abc"]
    window.model.set_rows(rows, "x86_64")
    window.model.set_visible([0, 1, 2], ranked=False)
    jobs, asked, shown = [], [], []
    monkeypatch.setattr(window.dnf, "submit", lambda fn, done, _error=None: jobs.append((fn, done)))
    monkeypatch.setattr(window.catalog, "details", lambda key: asked.append(key) or key)
    monkeypatch.setattr(window.details, "show_package", lambda row, d: shown.append(row.key))
    for n in range(3):  # the cursor runs down the list
        window.table.setCurrentIndex(window.model.index(n, 0))
    assert jobs == [] and window.details_loader.timer.active
    window.details_loader.timer.stop()
    window.details_loader.load()
    assert len(jobs) == 1
    window.table.setCurrentIndex(window.model.index(0, 0))  # moved on while the job waited its turn
    fn, done = jobs[0]
    done(fn())
    assert asked == [] and shown == []
    window.details_loader.timer.stop()
    window.details_loader.load()
    fn, done = jobs[1]
    done(fn())
    assert asked == shown == [("a", "x86_64")]


def test_upgrades_that_cannot_be_installed_are_dimmed_and_not_marked_by_mark_all(window):
    from PySide6.QtCore import Qt

    from kram.core.marks import Action
    from kram.core.model import CatalogSnapshot, Origin, PkgRow, Status
    from kram.qt.package_model import COL_CANDIDATE, COL_STATUS

    rows = [PkgRow("ffmpeg", "x86_64", "", "9.0.2-3", "9.0.2-4", "rpmfusion-free-updates", 1, Origin.THIRD_PARTY,
                   Status.UPGRADABLE, True),
            PkgRow("gjs", "x86_64", "", "1.90.1-1", "1.90.1-2", "updates", 1, Origin.FEDORA, Status.UPGRADABLE)]
    window.browser.snapshot = CatalogSnapshot(rows, 2, 2, 0.0)
    window.marker.set_snapshot(window.browser.snapshot)
    window.model.set_rows(rows, "x86_64")
    ffmpeg, gjs = (window.model.index(i, COL_CANDIDATE) for i in range(2))
    assert ffmpeg.data(Qt.ItemDataRole.FontRole).bold() and ffmpeg.data(Qt.ItemDataRole.ForegroundRole) is None

    why = ("Problem: package ffmpeg-9.0.2-4.fc45.x86_64 from rpmfusion-free-updates requires ffmpeg-libs(x86-64) = "
           "9.0.2-4.fc45, but none of the providers can be installed\n"
           "  - cannot install the best update candidate for package ffmpeg-9.0.2-3.fc45.x86_64\n"
           "  - nothing provides liboapv.so.11()(64bit) needed by ffmpeg-libs-9.0.2-4.fc45.x86_64 from rpmfusion-free-updates")
    window.model.set_blocked({rows[0].key: why})
    assert ffmpeg.data(Qt.ItemDataRole.FontRole) is None and ffmpeg.data(Qt.ItemDataRole.ForegroundRole) is not None
    assert ffmpeg.data(Qt.ItemDataRole.DecorationRole).cacheKey() == blocked_icon().cacheKey()
    assert gjs.data(Qt.ItemDataRole.DecorationRole).cacheKey() != blocked_icon().cacheKey()
    assert ffmpeg.data(Qt.ItemDataRole.ToolTipRole) == (
        "The upgrade cannot be installed now\n"
        "nothing provides liboapv.so.11()(64bit) needed by ffmpeg-libs-9.0.2-4.fc45.x86_64 from rpmfusion-free-updates")
    assert "cannot be installed now" in window.model.index(0, COL_STATUS).data(Qt.ItemDataRole.ToolTipRole)
    assert gjs.data(Qt.ItemDataRole.FontRole).bold() and gjs.data(Qt.ItemDataRole.ToolTipRole) is None

    # the dependencies tab gets the cross and the resolver's message, also when the cursor was there first
    tabs = window.details
    deps = tabs.indexOf(tabs.deps)
    window.model.set_blocked({})
    window.details_loader.follow(rows[0])
    assert tabs.tabIcon(deps).isNull() and tabs.deps.toPlainText() == ""
    window.browser._on_blocked({rows[0].key: why})
    assert tabs.tabIcon(deps).cacheKey() == blocked_icon().cacheKey()
    text = tabs.deps.toPlainText()
    assert text.startswith("The upgrade cannot be installed now\nnothing provides liboapv.so.11()(64bit)")
    assert "cannot install the best update candidate" in text
    window.details_loader.follow(rows[1])
    assert tabs.tabIcon(deps).isNull() and tabs.tabToolTip(deps) == ""

    window.marker.mark_all_upgrades()
    marks = window.model.marks
    assert rows[0].key not in marks and marks.get(rows[1].key).action is Action.UPGRADE
    assert "1 upgrade left out" in window.statusBar().currentMessage()

    # by hand it can still be marked: the Apply dialog then says why it cannot be carried out
    assert marks.set(rows[0], Action.UPGRADE)

    window.model.set_rows(rows, "x86_64")  # a reload starts over; the new resolve fills it again
    assert window.model.blocked == {}


def test_blocked_without_reason_is_still_marked_until_it_is_looked_up(window):
    """Past MAX_BLOCKED_REASONS the resolve gives no reason: the cross and the title stay, and the reason is kept
    once the selected row asks for it."""
    from PySide6.QtCore import Qt

    from kram.core.model import CatalogSnapshot, Origin, PkgRow, Status
    from kram.qt.icons import blocked_icon
    from kram.qt.package_model import COL_CANDIDATE

    rows = [PkgRow("kernel", "x86_64", "", "7.2.11-300.fc45", "7.3.4-300.fc45", "updates", 1, Origin.FEDORA,
                   Status.UPGRADABLE)]
    window.browser.snapshot = CatalogSnapshot(rows, 1, 1, 0.0)
    window.marker.set_snapshot(window.browser.snapshot)
    window.model.set_rows(rows, "x86_64")
    cell = window.model.index(0, COL_CANDIDATE)

    window.browser._on_blocked({rows[0].key: ""})
    assert cell.data(Qt.ItemDataRole.DecorationRole).cacheKey() == blocked_icon().cacheKey()
    assert cell.data(Qt.ItemDataRole.ToolTipRole) == "The upgrade cannot be installed now"
    tabs = window.details
    deps = tabs.indexOf(tabs.deps)
    window.details_loader.follow(rows[0])
    assert tabs.tabIcon(deps).cacheKey() == blocked_icon().cacheKey()

    why = "Problem: nothing provides liboapv.so.11()(64bit)"
    window.model.set_blocked_reason(rows[0].key, why)
    assert window.model.blocked == {rows[0].key: why}
    assert "nothing provides" in cell.data(Qt.ItemDataRole.ToolTipRole)
    window.details_loader._show_reason(rows[0], why)
    assert "nothing provides" in tabs.deps.toPlainText()


def test_status_entry_and_menu_for_upgrades_that_cannot_be_installed(window):
    """Status → Cannot be upgraded now fills in when the resolve arrives, also when it was selected before (a
    reload restores it); the package menu then offers the reason on the Dependencies tab."""
    from kram.core.model import CatalogSnapshot, Origin, PkgRow, Status

    rows = [PkgRow("ffmpeg", "x86_64", "", "9.0.2-3", "9.0.2-4", "rpmfusion-free-updates", 1, Origin.THIRD_PARTY,
                   Status.UPGRADABLE),
            PkgRow("gjs", "x86_64", "", "1.90.1-1", "1.90.1-2", "updates", 1, Origin.FEDORA, Status.UPGRADABLE)]
    snap = CatalogSnapshot(rows, 2, 2, 0.0)
    window.browser.snapshot = snap
    window.marker.set_snapshot(snap)
    window.model.set_rows(rows, "x86_64")
    window.browser.key_index = {r.key: i for i, r in enumerate(rows)}
    window.sidebar.set_snapshot(snap)
    assert window.sidebar.item_of("status:blocked") is None  # nothing blocked: no entry
    window.sidebar.select("status", "status:blocked")  # kept while selected, and empty until the resolve
    assert window.browser.filter.id == "status:blocked" and window.model.rowCount() == 0

    window.browser._on_blocked({rows[0].key: "nothing provides liboapv.so.11()(64bit)"})
    assert window.model.rowCount() == 1 and window.model.row_at(window.model.index(0, 0)) is rows[0]
    assert window.sidebar.item_of("status:blocked").text(0).endswith("(1)")

    window.select_key(rows[0].key)
    window.browser.update_actions()
    assert window.acts.why_blocked.isVisible()
    window.acts.why_blocked.trigger()
    assert window.details.currentWidget() is window.details.deps

    window.sidebar.select("status", "status:upgradable")
    window.select_key(rows[1].key)
    window.browser.update_actions()
    assert not window.acts.why_blocked.isVisible()


def test_reason_of_a_blocked_upgrade_is_asked_for_once(app):
    """Past MAX_BLOCKED_REASONS the selected row asks for its reason: once, also when the resolver gives none."""
    from kram.app.details import DetailsLoader
    from kram.app.scheduler import FakeScheduler
    from kram.core.model import Origin, PkgRow, Status
    from kram.qt.details import DetailsTabs

    row = PkgRow("kernel", "x86_64", "", "7.2.11-300.fc45", "7.3.4-300.fc45", "updates", 1, Origin.FEDORA,
                 Status.UPGRADABLE)
    asked = []

    class Catalog:
        def details(self, _key):
            return None

        def blocked_reason(self, key):
            asked.append(key)
            return ""

    class Dnf:  # runs each job at once
        def submit(self, fn, done, _error=None):
            done(fn())

    blocked = {row.key: ""}
    tabs = DetailsTabs()
    loader = DetailsLoader(tabs, Catalog(), Dnf(), blocked.get, blocked.__setitem__, FakeScheduler())
    for _ in range(2):
        loader.follow(row)
        loader.load()
    assert asked == [row.key]
    assert tabs.tabIcon(tabs.indexOf(tabs.deps)).cacheKey() == blocked_icon().cacheKey()
    loader.refresh_blocked()  # a new resolve of the blocked upgrades: asked again
    assert asked == [row.key, row.key]

def test_long_dependency_lists_are_cut(app):
    """kernel-core provides some 16000 capabilities: the whole list froze the window for seconds."""
    from kram.core.model import Origin, PkgDetails, PkgRow, Status
    from kram.qt.details import MAX_DEP_ITEMS, DetailsTabs

    row = PkgRow("kernel-core", "x86_64", "", "7.3.4-300.fc45", "7.3.4-300.fc45", "updates", 1, Origin.FEDORA,
                 Status.INSTALLED)
    provides = [f"kmod(m{i}.ko)" for i in range(MAX_DEP_ITEMS + 250)]
    d = PkgDetails("kernel-core-7.3.4-300.fc45.x86_64", "", "", "", "", "", "", "", 0, None, "updates", "", 0, None,
                   None, ["bash"], [], [], provides, [], [], [], [], True, [], [])
    tabs = DetailsTabs()
    tabs.show_package(row, d)
    text = tabs.deps.toPlainText()
    assert f"Provides ({MAX_DEP_ITEMS + 250})" in text and "…and 250 more" in text
    assert f"kmod(m{MAX_DEP_ITEMS - 1}.ko)" in text and f"kmod(m{MAX_DEP_ITEMS}.ko)" not in text

def test_mark_unneeded_marks_what_autoremove_would_remove(window):
    from kram.core.marks import Action
    from kram.core.model import Origin, PkgRow, Status

    rows = [PkgRow("lib-old", "x86_64", "", "1-1", "1-1", "fedora", 1, Origin.FEDORA, Status.UNNEEDED, False),
            PkgRow("tool", "x86_64", "", "1-1", "1-1", "fedora", 1, Origin.FEDORA, Status.INSTALLED, True),
            # orphaned, still what autoremove removes
            PkgRow("lib-gone", "x86_64", "", "1-1", "", "", 1, Origin.UNKNOWN, Status.ORPHAN, False, unneeded=True)]
    window.model.set_rows(rows, "x86_64")
    window.browser.update_actions()
    assert not window.acts.mark_unneeded.isEnabled()  # nothing loaded yet
    window.marker.unneeded = [r for r in rows if r.unneeded]  # as a loaded catalog gives them
    window.browser.update_actions()
    assert window.acts.mark_unneeded.isEnabled()
    window.acts.mark_unneeded.trigger()
    marks = window.model.marks
    assert {k: marks.get(k).action for k in (r.key for r in rows) if k in marks} == {
        rows[0].key: Action.REMOVE, rows[2].key: Action.REMOVE}
    assert window.statusBar().currentMessage() == "2 unneeded dependencies marked for removal"
    assert window.acts.apply.isEnabled()


def test_sidebar_refreshes_only_an_enabled_repo(window, monkeypatch):
    from kram.core.filters import FilterEntry
    from kram.core.model import Origin, RepoInfo
    repos = [RepoInfo("copr:a", "a", True, Origin.COPR, 60), RepoInfo("old", "old", False, Origin.THIRD_PARTY, None)]
    window.browser.snapshot = SimpleNamespace(n_upgradable=0, repos=repos)

    def entry(entry_id):
        return FilterEntry(entry_id, "", lambda _r: True)
    assert window.browser.enabled_repo(entry("repo:copr:a")) == "copr:a"
    assert window.browser.enabled_repo(entry("repo:old")) is None   # disabled: nothing to refresh
    assert window.browser.enabled_repo(entry("origin:copr")) is None
    sent, reloads = [], []
    monkeypatch.setattr(window.browser, "run_helper", lambda request, _title, done=None: (sent.append(request), done({"ok": True})))
    monkeypatch.setattr(window.browser, "reload", lambda: reloads.append(1))
    window.browser.refresh_repo_metadata("copr:a")
    assert sent == [{"op": "refresh", "repos": ["copr:a"]}] and reloads == [1]


# ---------------------------------------------------------------- the apply flow (audit items 2, 3 and 10)

class FakeMarks(MarkSet):
    """The real MarkSet (so a method it lacks fails here too), with a request that needs no PkgRows."""
    def __init__(self, keys):
        super().__init__()
        for key in keys:
            self.add(key)

    def add(self, key):
        self.restore(key, Mark(Action.INSTALL))

    def request(self, _rows):
        return {"install": sorted(k[0] for k, _ in self.items())}


def _marked_window(window, monkeypatch):
    """A window with one mark and a dnf worker that keeps the jobs instead of running them."""
    jobs = []
    monkeypatch.setattr(window.dnf, "submit", lambda fn, done, failed=None: jobs.append((fn, done, failed)))
    window.browser.snapshot = SimpleNamespace(rows=[], n_upgradable=0, n_installed=0, load_seconds=0.0, basearch="x86_64",
                                      repos=[])
    window.model.marks = FakeMarks([("fish", "x86_64")])
    return jobs


def test_apply_twice_before_the_preview_resolves_once(window, monkeypatch):
    jobs = _marked_window(window, monkeypatch)
    window.browser.apply()
    window.browser.apply()
    assert len(jobs) == 1 and window.browser.busy()
    assert not window.acts.apply.isEnabled()


def test_no_refresh_while_the_marks_are_resolved(window, monkeypatch):
    _marked_window(window, monkeypatch)
    started = []
    monkeypatch.setattr(window.browser, "run_helper", lambda request, title, done=None: started.append(request))
    window.browser.apply()
    window.browser.refresh_metadata()
    assert started == []


def test_a_failed_resolve_clears_the_status_and_allows_a_retry(window, monkeypatch):
    jobs = _marked_window(window, monkeypatch)
    monkeypatch.setattr(main_window.QMessageBox, "critical", lambda *a: None)
    window.browser.apply()
    jobs[0][2](RuntimeError("boom"))
    assert not window.browser.busy() and "Resolving" not in window.status.text()
    window.browser.apply()
    assert len(jobs) == 2


def _preview_flow(window, monkeypatch, helper_ok):
    """apply(), then a mark added before the preview arrives, then the user accepts and the helper runs."""
    jobs = _marked_window(window, monkeypatch)
    rows = [SimpleNamespace(key=("fish", "x86_64")), SimpleNamespace(key=("vim", "x86_64"))]
    window.browser.snapshot.rows = rows
    reloads, unmarked = [], []
    monkeypatch.setattr(window.browser, "reload", lambda: reloads.append(1))
    monkeypatch.setattr(window.marker, "unmark", lambda rs: unmarked.extend(r.key for r in rs))
    monkeypatch.setattr(window.browser, "run_helper", lambda request, title, done=None: done({"ok": True} if helper_ok else None))

    class Accepting:
        Accepted = 1

        def __init__(self, _preview, request, *_args, **_kwargs):
            self.review = SimpleNamespace(result=lambda: request)

        def exec(self):
            return 1

        def deleteLater(self):
            pass
    monkeypatch.setattr(main_window, "ApplyDialog", Accepting)
    window.browser.apply()
    window.model.marks.add(("vim", "x86_64"))  # marked while the first request resolved
    jobs[0][1](SimpleNamespace(ok=True))
    return reloads, unmarked


def test_a_failed_apply_reloads_and_keeps_the_marks(window, monkeypatch):
    reloads, unmarked = _preview_flow(window, monkeypatch, helper_ok=False)
    assert reloads == [1] and unmarked == []


def test_a_successful_apply_unmarks_only_what_it_applied(window, monkeypatch):
    reloads, unmarked = _preview_flow(window, monkeypatch, helper_ok=True)
    assert reloads == [1] and unmarked == [("fish", "x86_64")]


def test_a_progress_dialog_for_a_refused_request_stays_disconnected(app, monkeypatch):
    from kram.qt.progress_dialog import ProgressDialog

    class Busy(FakeClient):
        def request(self, _request):
            return False
    warned = []
    monkeypatch.setattr(main_window.QMessageBox, "warning", lambda *a: warned.append(a))
    import kram.qt.progress_dialog as progress_dialog
    monkeypatch.setattr(progress_dialog.QMessageBox, "warning", lambda *a: warned.append(a))
    client = Busy()
    dlg = ProgressDialog(client, {"op": "refresh"}, "t")
    assert dlg.exec() == QDialog.DialogCode.Rejected and warned
    seen = []
    monkeypatch.setattr(dlg.progress, "on_event", seen.append)
    client.event.emit({"event": "question", "id": 1})
    assert seen == []


def test_dialogs_are_deleted_after_use(window, monkeypatch):
    from PySide6.QtCore import QCoreApplication, QEvent

    from kram.qt.progress_dialog import ProgressDialog

    monkeypatch.setattr(ProgressDialog, "exec", lambda self: 0)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    before = len(window.findChildren(QDialog))
    for _ in range(20):
        window.run_helper({"op": "refresh"}, "t", lambda _r: None)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert len(window.findChildren(QDialog)) == before


def test_a_late_result_for_a_closed_apply_dialog_is_dropped(app):
    from kram.core.model import TransactionPreview
    from kram.qt.apply_dialog import ApplyDialog

    waiting = []
    preview = TransactionPreview(items=[], problems=[], download_size=0, size_change=0)
    dlg = ApplyDialog(preview, {"op": "transaction"}, resolve=lambda req, done, failed: waiting.append((done, failed)))
    dlg.review.recs_changed()
    dlg.done(0)
    done, failed = waiting[0]
    done(preview)  # nothing raises, nothing is shown
    failed(RuntimeError("late"))


def test_marking_recounts_only_the_marked_entry(window, monkeypatch):
    from kram.app import sidebar as sidebar_module
    from kram.core.model import CatalogSnapshot, Origin, PkgRow, Status

    rows = [PkgRow(n, "x86_64", "", "", "1-1", "fedora", 1, Origin.FEDORA, Status.NOT_INSTALLED)
            for n in ("fish", "vim")]
    window.browser._on_loaded(CatalogSnapshot(rows, 0, 0, 0.0))
    window.sidebar.set_view("status")
    calls = []
    real = sidebar_module.status_filters
    monkeypatch.setattr(sidebar_module, "status_filters", lambda *a: calls.append(1) or real(*a))
    window.marker.mark([rows[0]], Action.INSTALL)
    assert calls == []  # the status predicates did not run again over the catalog
    marked = window.sidebar.item_of("status:marked")
    assert marked.text(0).endswith("(1)")
