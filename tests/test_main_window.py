"""Regressions of the main window and the progress dialog that show only on screen. No catalog is loaded."""
import os
from types import SimpleNamespace

import pytest

pytest.importorskip("libdnf5")
pytest.importorskip("PySide6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
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
    actions = (window.act_repos, window.act_copr, window.act_cache)
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
