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

from kram.ui import main_window
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
    actions = (window.act_repos, window.act_copr, window.act_cache, window.act_filters, window.act_new_filter)
    assert not any(a.isEnabled() for a in actions)
    window.snapshot = SimpleNamespace(n_upgradable=0)
    window._update_actions()
    assert all(a.isEnabled() for a in actions)


def test_progress_belongs_to_the_dialog_that_started_it(window, monkeypatch):
    """As a child of the main window, it could be covered by the COPR or Package Cache dialog behind it."""
    parents = []

    class Progress:
        ok = True

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
        return main_window.QNetworkReply.TimeoutError if self.failed else main_window.QNetworkReply.NoError

    def readAll(self):
        return self.body


BODHI = (b'{"releases": [{"version": "44", "state": "current", "id_prefix": "FEDORA", "eol": "2027-06-02"},'
         b'{"version": "45", "state": "current", "id_prefix": "FEDORA", "eol": "2027-12-08"}]}')


@pytest.fixture
def fedora(window, monkeypatch):
    monkeypatch.setattr(main_window, "QSettings", FakeSettings)
    monkeypatch.setattr(FakeSettings, "values", {})
    window.running_fedora = 44
    window.act_watch_releases.setChecked(True)
    return window


def button(window):
    return window.act_upgrade.isVisible(), window.act_upgrade.text()


def test_new_release_shows_the_button(fedora):
    fedora.show()
    assert not fedora.act_upgrade.isVisible()
    fedora._on_release_check(BodhiReply(BODHI))
    assert button(fedora) == (True, "Fedora 45")
    assert fedora.act_upgrade.toolTip() == "Fedora 45 is available, you have 44"
    assert FakeSettings.values["distro/running_eol"] == "2027-06-02"


def test_a_failed_check_keeps_the_last_result(fedora):
    fedora._on_release_check(BodhiReply(BODHI))
    for reply in (BodhiReply(failed=True), BodhiReply(b"not json"), BodhiReply(b'{"releases": []}')):
        fedora._on_release_check(reply)
        assert FakeSettings.values["distro/target"] == 45


def test_button_goes_when_the_system_gets_there_or_watching_stops(fedora):
    fedora._on_release_check(BodhiReply(BODHI))
    fedora.show()
    assert fedora.act_upgrade.isVisible()
    fedora.act_watch_releases.setChecked(False)
    assert not fedora.act_upgrade.isVisible()
    fedora.act_watch_releases.setChecked(True)
    assert fedora.act_upgrade.isVisible()
    fedora.running_fedora = 45
    fedora._update_upgrade_button()
    assert not fedora.act_upgrade.isVisible()


def test_only_reload_asks_and_only_when_watching(fedora, monkeypatch):
    asked = []
    agents = []

    def get(request):
        asked.append(request.url().host())
        agents.append((request.header(QNetworkRequest.UserAgentHeader),
                       bytes(request.rawHeader("Accept"))))
        return BodhiReplySignal()
    monkeypatch.setattr(fedora._net, "get", get)
    monkeypatch.setattr(fedora, "_run_helper", lambda *_args: True)
    fedora.refresh_metadata()
    assert asked == ["bodhi.fedoraproject.org"]
    # Bodhi answers anything that looks like a browser with an HTML bot check
    assert agents[0][0].startswith("Kram/") and agents[0][1] == b"application/json"
    fedora.act_watch_releases.setChecked(False)
    fedora.refresh_metadata()
    assert len(asked) == 1


class BodhiReplySignal:
    finished = SimpleNamespace(connect=lambda _slot: None)


def test_not_fedora_has_no_setting_and_no_check(fedora, monkeypatch):
    fedora.running_fedora = None
    monkeypatch.setattr(fedora._net, "get", lambda _request: pytest.fail("asked Bodhi"))
    fedora._check_fedora_release()
    fedora._update_upgrade_button()
    assert not fedora.act_upgrade.isVisible()


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
        action = win.act_mark_upgrades
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

    monkeypatch.setattr(main_window, "QSettings", FakeSettings)
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

    window.act_status_click.setChecked(False)
    window._on_table_click(status[0])  # Synaptic's default: the menu
    assert len(menus) == 1 and len(marks) == 0

    window.act_status_click.setChecked(True)
    window._on_table_click(status[0])
    window._on_table_click(status[1])
    assert [marks.get(r.key).action for r in rows[:2]] == [Action.INSTALL, Action.UPGRADE] and len(menus) == 1
    window._on_table_click(status[2])  # removal, reinstallation...: no obvious one, so the menu
    assert len(menus) == 2 and rows[2].key not in marks
    window._on_table_click(status[0])
    assert rows[0].key not in marks and FakeSettings.values["table/status_click"] is True

    window._on_double_click(window.model.index(0, COL_NAME))  # unchanged
    assert marks.get(rows[0].key).action is Action.INSTALL


def test_group_marks_from_the_sidebar(window):
    """A comps group is marked from its sidebar menu, shown there like a marked package and sent to the helper."""
    from PySide6.QtWidgets import QMenu

    from kram.core.marks import Action
    from kram.core.model import CatalogSnapshot, GroupInfo, TransactionPreview
    from kram.ui.apply_dialog import ApplyDialog

    apps = GroupInfo("kde-apps", "KDE Applications", "", False, frozenset())
    tools = GroupInfo("development-tools", "Development Tools", "", True, frozenset())
    window._on_loaded(CatalogSnapshot([], 0, 0, 0.0, groups=[apps, tools]))
    window.sidebar.set_view("groups")
    def menu_for(group):
        menu = QMenu()
        window._group_menu(menu, group)
        return {a.text(): a.isEnabled() for a in menu.actions()}

    # Upgrade waits for the check after loading, and stays off when it finds nothing to upgrade
    assert menu_for(tools) == {"Mark Group for Upgrade": False, "Mark Group for Removal": True, "Unmark Group": False}
    tools.upgradable = False
    assert not menu_for(tools)["Mark Group for Upgrade"]
    tools.upgradable = True
    assert menu_for(tools)["Mark Group for Upgrade"]

    window.mark_group(apps, Action.INSTALL)
    window.mark_group(tools, Action.REMOVE)
    assert window.act_apply.isEnabled()
    item = next(window.sidebar.list.item(n) for n, e in enumerate(window.sidebar._entries) if e.group == "kde-apps")
    assert "Marked: install" in item.toolTip()
    assert window.model.marks.request({}) == {"group_install": ["kde-apps"], "group_remove": ["development-tools"]}

    preview = TransactionPreview([], [], 0, 0)
    dlg = ApplyDialog(preview, {"op": "transaction", **window.model.marks.request({})})
    assert "sudo dnf5 group install kde-apps" in dlg.cmd.toPlainText()

    # after a reload the removed group is gone: its mark goes too
    window._on_loaded(CatalogSnapshot([], 0, 0, 0.0, groups=[apps]))
    assert window.model.marks.request({}) == {"group_install": ["kde-apps"]}
    window.unmark_all()
    assert not window.act_apply.isEnabled()


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
    window.search_mode.setCurrentIndex(Mode.PROVIDES)
    searches = []  # other jobs load the details of the selected row
    for text in ("vulk", "vulkan"):
        window.search.setText(text)
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
    assert jobs == [] and window._details_timer.isActive()
    window._details_timer.stop()
    window._load_details()
    assert len(jobs) == 1
    window.table.setCurrentIndex(window.model.index(0, 0))  # moved on while the job waited its turn
    fn, done = jobs[0]
    done(fn())
    assert asked == [] and shown == []
    window._details_timer.stop()
    window._load_details()
    fn, done = jobs[1]
    done(fn())
    assert asked == shown == [("a", "x86_64")]
