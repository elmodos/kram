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
