"""File → Transaction History: transactions load first, their packages after, the filter and the undo button."""
import os

import pytest

pytest.importorskip("PySide6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from kram.core.history import HistoryItem, HistoryTransaction
from kram.core.model import Reason
from kram.ui import history_dialog
from kram.ui.history_dialog import COL_CHANGES, HistoryDialog

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
    monkeypatch.setattr(history_dialog, "CHUNK", 2)
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
