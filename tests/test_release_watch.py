"""kram.app.release_watch without a toolkit: what the Fedora N button shows, from Bodhi's answer."""
import pytest

from kram.app import preferences, release_watch
from kram.app.parity import Feature  # noqa: E402  (the feature marks of the parity tests)
from kram.core import net
from kram.core.settings import store as settings

BODHI = {"releases": [{"version": "44", "state": "current", "id_prefix": "FEDORA", "eol": "2027-06-02"},
                      {"version": "45", "state": "current", "id_prefix": "FEDORA", "eol": "2027-12-08"}]}


def watcher(monkeypatch, answer):
    asked = []

    def fetch_json(url, *, done, failed, **kw):
        asked.append(url)
        if isinstance(answer, net.NetError):
            failed(answer)
        else:
            done(answer)
    monkeypatch.setattr(net, "fetch_json", fetch_json)
    w = release_watch.ReleaseWatcher(post=lambda fn: fn())
    w.running = 44
    changes = []
    w.changed.connect(lambda: changes.append(w.button()))
    return w, asked, changes


@pytest.mark.feature(Feature.RELEASE_WATCH, front="qt")
@pytest.mark.feature(Feature.SETTINGS_WATCH_RELEASES, front="qt")
def test_only_a_watcher_asks_and_the_button_follows(monkeypatch):
    w, asked, changes = watcher(monkeypatch, BODHI)
    preferences.set_value(preferences.WATCH_RELEASES, False)
    w.check()
    assert asked == [] and not w.button().visible
    preferences.set_value(preferences.WATCH_RELEASES, True)
    w.check()
    assert len(asked) == 1 and changes[-1].visible and changes[-1].text == "Fedora 45"
    assert changes[-1].tooltip == "Fedora 45 is available, you have 44" and w.running_eol() == "2027-06-02"
    w.running = 45
    assert not w.button().visible and w.target() is None


def test_a_failure_or_an_unknown_answer_keeps_the_last_result(monkeypatch):
    preferences.set_value(preferences.WATCH_RELEASES, True)
    settings.set("distro/target", 45)
    for answer in (net.NetError("Operation timed out"), {"releases": []}, "html"):
        w, _asked, changes = watcher(monkeypatch, answer)
        w.check()
        assert changes == [] and w.target() == 45
