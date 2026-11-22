"""File → Transaction History: transactions load first, their packages after, the filter and the undo button."""
import os

import pytest

from kram.app.parity import Feature  # noqa: E402  (the feature marks of the parity tests)

pytest.importorskip("PySide6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from kram.app import history
from kram.core.history import HistoryItem, HistoryTransaction
from kram.core.model import Reason
from kram.qt.history_dialog import COL_CHANGES, HistoryDialog

TRANSACTIONS = [HistoryTransaction(3, 1795000000, 0, "dnf5 remove fish", "", True),
                HistoryTransaction(2, 1794000000, 1000, "kram", "", False),
                HistoryTransaction(1, 1793000000, 1000, "kram", "", True)]
ITEMS = {
    3: (HistoryItem("fish", "x86_64", "4.0-1", "remove", Reason.USER, "@System"),),
    2: (HistoryItem("vim", "x86_64", "9.1-2", "upgrade", Reason.USER, "updates"),),
    1: (HistoryItem("vim", "x86_64", "9.1-2", "upgrade", Reason.USER, "updates"),
        HistoryItem("vim", "x86_64", "9.1-1", "replaced", Reason.USER, "@System"),
        HistoryItem("fish", "x86_64", "4.0-1", "install", Reason.USER, "fedora"),
        HistoryItem("ncurses-term", "noarch", "6.5-1", "install", Reason.DEPENDENCY, "fedora")),
}


class SyncWorker:
    def submit(self, fn, on_done, on_error=None):
        on_done(fn())


class FakeCatalog:
    def __init__(self):
        self.asked: list[list[int]] = []

    def history(self):
        return TRANSACTIONS

    def history_items(self, ids):
        self.asked.append(list(ids))
        return {i: ITEMS[i] for i in ids}


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def dialog(app, monkeypatch):
    monkeypatch.setattr(history, "CHUNK", 2)
    catalog = FakeCatalog()
    dlg = HistoryDialog(SyncWorker(), catalog, None)
    dlg.reload()
    for _ in range(5):
        app.processEvents()
    yield dlg, catalog
    dlg.deleteLater()


def test_loads_transactions_then_their_packages_in_chunks(dialog):
    dlg, catalog = dialog
    assert [dlg.list.topLevelItem(i).text(0) for i in range(3)] == ["3", "2", "1"]
    # the current (newest) transaction at once, then the rest in chunks, each read once
    assert catalog.asked == [[3], [2, 1]]
    assert dlg._items[1].text(COL_CHANGES) == "2 installed, 1 upgraded"
    assert dlg.state.text() == "3 transactions"


def test_shows_the_packages_of_the_current_transaction(dialog):
    dlg, _catalog = dialog
    dlg.list.setCurrentItem(dlg._items[1])
    rows = [[dlg.packages.topLevelItem(i).text(c) for c in range(5)] for i in range(dlg.packages.topLevelItemCount())]
    assert rows == [["Install", "fish.x86_64", "4.0-1", "fedora", "user"],
                    ["Install", "ncurses-term.noarch", "6.5-1", "fedora", "dependency"],
                    ["Upgrade", "vim.x86_64", "9.1-1 → 9.1-2", "updates", "user"]]


@pytest.mark.feature(Feature.HISTORY_WINDOW, front="qt")
def test_filter_by_package_name(dialog):
    dlg, _catalog = dialog
    dlg.filter.setText("FISH")
    assert [tid for tid, item in dlg._items.items() if not item.isHidden()] == [3, 1]
    assert dlg.state.text() == "2 of 3 transactions"
    dlg.list.setCurrentItem(dlg._items[1])
    assert dlg.packages.topLevelItem(0).font(1).bold() and not dlg.packages.topLevelItem(2).font(1).bold()


def test_undo_needs_a_finished_transaction_and_a_catalog(dialog):
    dlg, _catalog = dialog
    asked = []
    dlg.undoRequested.connect(asked.append)
    dlg.list.setCurrentItem(dlg._items[1])
    assert not dlg.undo.isEnabled()  # no catalog yet
    dlg.set_marking(True, False)
    assert dlg.undo.isEnabled()
    dlg.undo.click()
    assert asked == [1]
    dlg.set_marking(True, True)  # applying changes
    assert not dlg.undo.isEnabled()
    dlg.set_marking(True, False)
    dlg.list.setCurrentItem(dlg._items[2])  # failed
    assert not dlg.undo.isEnabled()


def test_a_transaction_with_groups_is_undone_whole(app, monkeypatch):
    """Groups show above the packages; the button then reverts the transaction instead of marking."""
    monkeypatch.setitem(ITEMS, 1, ITEMS[1] + (
        HistoryItem("Sway Desktop", "sway-desktop-environment", "", "install", Reason.USER, "", comps="environment"),))
    dlg = HistoryDialog(SyncWorker(), FakeCatalog(), None)
    dlg.reload()
    for _ in range(5):
        app.processEvents()
    dlg.set_marking(True, False)
    dlg.list.setCurrentItem(dlg._items[1])
    assert dlg._items[1].text(COL_CHANGES).startswith("1 environment; ")
    assert dlg.packages.topLevelItem(0).text(1) == "Sway Desktop (environment)"
    assert dlg.undo.text() == "Undo Transaction…" and dlg.undo.isEnabled()
    dlg.list.setCurrentItem(dlg._items[3])
    assert dlg.undo.text() == "Mark Changes to Undo"


def test_double_clicking_a_group_row_shows_no_package(app, monkeypatch):
    monkeypatch.setattr(history, "CHUNK", 2)

    class GroupsCatalog(FakeCatalog):
        def history(self):
            return [HistoryTransaction(5, 1796000000, 0, "kram", "", True)]

        def history_items(self, ids):
            return {5: (HistoryItem("kde-apps", "kde-apps", "", "install", Reason.USER, "", comps="group"),)}

    dlg = HistoryDialog(SyncWorker(), GroupsCatalog(), None)
    shown = []
    dlg.showPackage.connect(shown.append)
    dlg.reload()
    for _ in range(5):
        app.processEvents()
    dlg.list.setCurrentItem(dlg._items[5])
    dlg._on_package_double_click(dlg.packages.topLevelItem(0), 0)
    assert shown == []
    dlg.deleteLater()


def test_history_without_a_toolkit(monkeypatch):
    """kram.app.history drives any view: the current one moves off a transaction the filter hides."""
    from kram.app.scheduler import FakeScheduler

    class View:
        def __init__(self):
            self.current, self.hidden, self.state, self.undo = None, set(), "", None

        def show_transactions(self, lines):
            self.lines = lines

        def set_changes(self, tid, text):
            pass

        def set_current(self, tid):
            self.current = tid
            h.current_changed(tid)

        def show_packages(self, lines):
            self.packages = lines

        def set_hidden(self, hidden):
            self.hidden = hidden

        def show_state(self, text):
            self.state = text

        def show_undo(self, button):
            self.undo = button

    monkeypatch.setattr(history, "CHUNK", 2)
    view, scheduler = View(), FakeScheduler()
    h = history.History(SyncWorker(), FakeCatalog(), scheduler, view, user_name=lambda uid: f"u{uid}")
    h.reload()
    scheduler.run_idle()
    assert [line.user for line in view.lines] == ["u0", "u1000", "u1000"] and view.lines[1].failed
    assert view.current == 3 and view.state == "3 transactions"
    h.set_filter("vim")
    assert view.hidden == {3} and view.current == 2 and view.state == "2 of 3 transactions"
    h.set_marking(True, False)
    assert not view.undo.enabled  # 2 failed
    h.current_changed(1)
    assert view.undo.enabled and [p.bold for p in view.packages] == [False, False, True]
