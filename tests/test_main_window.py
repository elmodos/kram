"""Regressions of the main window and the progress dialog that show only on screen. No catalog is loaded."""
import os
from types import SimpleNamespace

import pytest

pytest.importorskip("libdnf5")
pytest.importorskip("PySide6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QNetworkRequest
from PySide6.QtWidgets import QApplication, QDialog

from kram.ui import actions, main_window, release_watch
from kram.ui.icons import blocked_icon
from kram.ui.progress_dialog import ProgressDialog


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
        pass


def test_catalog_actions_are_disabled_until_it_is_loaded(window):
    actions = (window.acts.repos, window.acts.copr, window.acts.cache, window.acts.filters, window.acts.new_filter)
    assert not any(a.isEnabled() for a in actions)
    window.snapshot = SimpleNamespace(n_upgradable=0)
    window._update_actions()
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

    monkeypatch.setattr(main_window, "ProgressDialog", Progress)
    window._run_helper({"op": "refresh"}, "t")
    modal = QDialog(window)
    modal.setModal(True)
    modal.show()
    try:
        window._run_helper({"op": "refresh"}, "t")
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


class FakeSettings:
    values: dict = {}

    def value(self, key, default=None, type=None):  # noqa: A002 - QSettings' own name
        return self.values.get(key, default)

    def setValue(self, key, value):
        self.values[key] = value


class BodhiReply:
    def __init__(self, body=b"", failed=False):
        self.body, self.failed = body, failed

    def deleteLater(self):
        pass

    def error(self):
        return release_watch.QNetworkReply.TimeoutError if self.failed else release_watch.QNetworkReply.NoError

    def readAll(self):
        return self.body


BODHI = (b'{"releases": [{"version": "44", "state": "current", "id_prefix": "FEDORA", "eol": "2027-06-02"},'
         b'{"version": "45", "state": "current", "id_prefix": "FEDORA", "eol": "2027-12-08"}]}')


@pytest.fixture
def fedora(window, monkeypatch):
    monkeypatch.setattr(release_watch, "QSettings", FakeSettings)
    monkeypatch.setattr(FakeSettings, "values", {})
    window.releases.running = 44
    window.releases.act_watch.setChecked(True)
    return window


def button(window):
    return window.releases.act_upgrade.isVisible(), window.releases.act_upgrade.text()


def test_new_release_shows_the_button(fedora):
    fedora.show()
    assert not fedora.releases.act_upgrade.isVisible()
    fedora.releases._on_reply(BodhiReply(BODHI))
    assert button(fedora) == (True, "Fedora 45")
    assert fedora.releases.act_upgrade.toolTip() == "Fedora 45 is available, you have 44"
    assert FakeSettings.values["distro/running_eol"] == "2027-06-02"


def test_a_failed_check_keeps_the_last_result(fedora):
    fedora.releases._on_reply(BodhiReply(BODHI))
    for reply in (BodhiReply(failed=True), BodhiReply(b"not json"), BodhiReply(b'{"releases": []}')):
        fedora.releases._on_reply(reply)
        assert FakeSettings.values["distro/target"] == 45


def test_button_goes_when_the_system_gets_there_or_watching_stops(fedora):
    fedora.releases._on_reply(BodhiReply(BODHI))
    fedora.show()
    assert fedora.releases.act_upgrade.isVisible()
    fedora.releases.act_watch.setChecked(False)
    assert not fedora.releases.act_upgrade.isVisible()
    fedora.releases.act_watch.setChecked(True)
    assert fedora.releases.act_upgrade.isVisible()
    fedora.releases.running = 45
    fedora.releases.update_button()
    assert not fedora.releases.act_upgrade.isVisible()


def test_only_reload_asks_and_only_when_watching(fedora, monkeypatch):
    asked = []
    agents = []

    def get(request):
        asked.append(request.url().host())
        agents.append((request.header(QNetworkRequest.KnownHeaders.UserAgentHeader),
                       bytes(request.rawHeader("Accept"))))
        return BodhiReplySignal()
    monkeypatch.setattr(fedora.releases._net, "get", get)
    monkeypatch.setattr(fedora, "_run_helper", lambda *_args: True)
    fedora.refresh_metadata()
    assert asked == ["bodhi.fedoraproject.org"]
    # Bodhi answers anything that looks like a browser with an HTML bot check
    assert agents[0][0].startswith("Kram/") and agents[0][1] == b"application/json"
    fedora.releases.act_watch.setChecked(False)
    fedora.refresh_metadata()
    assert len(asked) == 1


class BodhiReplySignal:
    finished = SimpleNamespace(connect=lambda _slot: None)


def test_not_fedora_has_no_setting_and_no_check(fedora, monkeypatch):
    fedora.releases.running = None
    monkeypatch.setattr(fedora.releases._net, "get", lambda _request: pytest.fail("asked Bodhi"))
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
    from kram.ui import progress_dialog

    monkeypatch.setattr(progress_dialog, "_", lambda s: {"Running: {command}": "Виконання: {command}",
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
    monkeypatch.setattr(main_window.QIcon, "fromTheme",
                        staticmethod(lambda name, fallback=None: themed.get(name, fallback or QIcon())))
    monkeypatch.setattr(main_window.MainWindow, "reload", lambda self: None)
    win = main_window.MainWindow()
    try:
        action = win.acts.mark_upgrades
        assert not action.isEnabled() and action.icon().cacheKey() == themed["update-none"].cacheKey()
        win.snapshot = SimpleNamespace(n_upgradable=2)
        win._update_actions()
        assert action.isEnabled() and action.icon().cacheKey() == themed["update-medium"].cacheKey()
        win.snapshot = SimpleNamespace(n_upgradable=0)
        win._update_actions()
        assert not action.isEnabled() and action.icon().cacheKey() == themed["update-none"].cacheKey()
    finally:
        win.dnf.shutdown()


def test_status_icon_click_marks_the_likely_action_only_when_chosen(window, monkeypatch):
    from kram.core.marks import Action
    from kram.core.model import Origin, PkgRow, Status
    from kram.ui.package_model import COL_NAME, COL_STATUS

    monkeypatch.setattr(actions, "QSettings", FakeSettings)
    monkeypatch.setattr(FakeSettings, "values", {})
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
    assert rows[0].key not in marks and FakeSettings.values["table/status_click"] is True

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
    window._on_loaded(CatalogSnapshot([fish], 0, 0, 0.0, groups=[apps, tools]))
    window.sidebar.set_view("groups")
    runs = []

    def menu_for(group):
        menu = QMenu()
        window.marker.fill_group_menu(menu, group, busy=False, run=lambda *a: runs.append(a))
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
    monkeypatch.setattr(window, "_review", lambda request, marked: reviewed.append((request, marked)))
    window.change_group(apps, Action.INSTALL, True)
    assert reviewed == [({"op": "transaction", "group_install_optional": ["kde-apps"]}, False)]
    assert len(window.model.marks) == 1  # fish stays marked


def test_environments_are_a_tree(window):
    """The Environments view is a tree: each environment folds its groups, the optional ones in italics; the list
    shows a group's optional packages in italics."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMenu

    from kram.core.model import CatalogSnapshot, GroupInfo, Origin, PkgRow, Status
    from kram.ui.package_model import COL_NAME

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
    window._on_loaded(CatalogSnapshot(rows, 0, 0, 0.0, groups=[kde, edu], environments=[env, xfce]))
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
    window.marker.fill_group_menu(menu, env, busy=False, run=lambda *a: None)
    assert [a.text() for a in menu.actions()] == ["Install Environment…",
                                                  "Install Environment with Optional Groups…"]

    sidebar.set_view("origin")  # the other views stay open, without arrows
    assert not tree.rootIsDecorated()

def test_a_provides_search_typed_over_is_skipped_not_run(window, monkeypatch):
    from kram.core.model import CatalogSnapshot, Origin, PkgRow, Status
    from kram.core.search import Mode, NarrowingSearch, SearchIndex

    rows = [PkgRow("vulkan-loader", "x86_64", "Vulkan", "1-1", "1-1", "fedora", 1, Origin.FEDORA, Status.INSTALLED)]
    window.snapshot = CatalogSnapshot(rows, 1, 0, 0.0)
    window.model.set_rows(rows, "x86_64")
    from kram.core.filters import FilterEntry

    window.filter = FilterEntry("status:all", "All", lambda _row: True)
    window.index = SearchIndex(rows)
    window.narrowing = NarrowingSearch(window.index)
    window.key_index = {rows[0].key: 0}
    jobs, asked = [], []
    monkeypatch.setattr(window.dnf, "submit", lambda fn, done, _error=None: jobs.append((fn, done)))
    monkeypatch.setattr(window.catalog, "search_provides", lambda text: asked.append(text) or [rows[0].key])
    window.search.mode_box.setCurrentIndex(Mode.PROVIDES)
    searches = []  # other jobs load the details of the selected row
    for text in ("vulk", "vulkan"):
        window.search.edit.setText(text)
        before = len(jobs)
        window.apply_filter()
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
    from kram.ui.package_view import PackageView

    assert isinstance(window.table, PackageView)
    rows = [PkgRow(n, "x86_64", "", "", "1-1", "fedora", 1, Origin.FEDORA, Status.NOT_INSTALLED) for n in "abc"]
    window.snapshot = CatalogSnapshot(rows, 0, 0, 0.0)
    calls = []

    def entry(entry_id):
        return FilterEntry(entry_id, entry_id, lambda r: calls.append(r.name) or r.name != "b")
    window.filter = entry("status:all")
    assert window._candidates() == [0, 2] and len(calls) == 3
    assert window._candidates() == [0, 2] and len(calls) == 3  # the same entry and catalog: kept
    window.filter = entry("status:all")  # rebuilt entry (new counts, edited custom filter)
    window._candidates()
    assert len(calls) == 6
    window.snapshot = CatalogSnapshot(rows, 0, 0, 0.0)  # reloaded catalog
    window._candidates()
    assert len(calls) == 9
    window.filter = entry("status:marked")  # follows the marks as they change: never kept
    window._candidates()
    window._candidates()
    assert len(calls) == 15


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
    assert jobs == [] and window.details_loader.timer.isActive()
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
    from kram.ui.package_model import COL_CANDIDATE, COL_STATUS

    rows = [PkgRow("ffmpeg", "x86_64", "", "9.0.2-3", "9.0.2-4", "rpmfusion-free-updates", 1, Origin.THIRD_PARTY,
                   Status.UPGRADABLE, True),
            PkgRow("gjs", "x86_64", "", "1.90.1-1", "1.90.1-2", "updates", 1, Origin.FEDORA, Status.UPGRADABLE)]
    window.snapshot = CatalogSnapshot(rows, 2, 2, 0.0)
    window.marker.set_snapshot(window.snapshot)
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
    window._on_blocked({rows[0].key: why})
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


def test_mark_unneeded_marks_what_autoremove_would_remove(window):
    from kram.core.marks import Action
    from kram.core.model import Origin, PkgRow, Status

    rows = [PkgRow("lib-old", "x86_64", "", "1-1", "1-1", "fedora", 1, Origin.FEDORA, Status.UNNEEDED, False),
            PkgRow("tool", "x86_64", "", "1-1", "1-1", "fedora", 1, Origin.FEDORA, Status.INSTALLED, True),
            # orphaned, still what autoremove removes
            PkgRow("lib-gone", "x86_64", "", "1-1", "", "", 1, Origin.UNKNOWN, Status.ORPHAN, False, unneeded=True)]
    window.model.set_rows(rows, "x86_64")
    window._update_actions()
    assert not window.acts.mark_unneeded.isEnabled()  # nothing loaded yet
    window.marker.unneeded = [r for r in rows if r.unneeded]  # as a loaded catalog gives them
    window._update_actions()
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
    window.snapshot = SimpleNamespace(n_upgradable=0, repos=repos)

    def entry(entry_id):
        return FilterEntry(entry_id, "", lambda _r: True)
    assert window._enabled_repo(entry("repo:copr:a")) == "copr:a"
    assert window._enabled_repo(entry("repo:old")) is None   # disabled: nothing to refresh
    assert window._enabled_repo(entry("origin:copr")) is None
    sent, reloads = [], []
    monkeypatch.setattr(window, "_run_helper", lambda request, _title: sent.append(request) or True)
    monkeypatch.setattr(window, "reload", lambda: reloads.append(1))
    window.refresh_repo_metadata("copr:a")
    assert sent == [{"op": "refresh", "repos": ["copr:a"]}] and reloads == [1]
