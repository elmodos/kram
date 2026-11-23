"""kram.app.mirrors without a toolkit: the list, the test, the choice; and the repository dialog's Mirrors… button."""
from collections import Counter
from types import SimpleNamespace

from kram.app import mirrors as app
from kram.app.mirrors import MirrorChoice, Mirrors
from kram.app.ports import RecordingUi
from kram.app.repos import Repos
from kram.core.mirrors import Mirror, MirrorSource, Probe, SourceKind
from kram.core.model import Origin, RepoInfo
from kram.core.net import NetError

A = Mirror("https://a.example/f/", "https", "DE")
B = Mirror("https://b.example/f/", "https", "NL")
C = Mirror("http://c.example/f/", "http", "CZ")
SOURCE = MirrorSource(SourceKind.METALINK, "https://mirrors.example/metalink", "")
PINNED = MirrorSource(SourceKind.METALINK, "https://mirrors.example/metalink", "https://b.example/f")


class View:
    def __init__(self):
        self.lines, self.status, self.testing, self.applied, self.fastest = [], "", False, [], ("", "")

    def show_lines(self, lines):
        self.lines = lines

    def show_status(self, text):
        self.status = text

    def set_testing(self, on):
        self.testing = on

    def show_fastest(self, text, button):
        self.fastest = (text, button)


class Net:
    """The network of a dialog: `fetch` and `speed_test`, driven by hand."""

    def __init__(self):
        self.requests, self.tests = [], []

    def fetch(self, source, *, post, done, failed):
        request = SimpleNamespace(done=done, failed=failed, cancelled=False)
        request.cancel = lambda: setattr(request, "cancelled", True)
        self.requests.append(request)
        return request

    def speed_test(self, mirrors, post, on_probe, on_done):
        test = SimpleNamespace(mirrors=mirrors, probe=on_probe, done=on_done, started=False, cancelled=False)
        test.start = lambda: setattr(test, "started", True)
        test.cancel = lambda: setattr(test, "cancelled", True)
        self.tests.append(test)
        return test


def dialog(source=SOURCE, mirrors=(A, B, C), answers=(), fastest=False):
    net, view, ui = Net(), View(), RecordingUi(list(answers))
    m = Mirrors("updates", source, fastest, view, ui, lambda fn: fn(), on_choice=view.applied.append,
                fetch=net.fetch, speed_test=net.speed_test)
    m.start()
    if mirrors is not None:
        net.requests[0].done(list(mirrors))
    return m, view, net, ui


def probe(latency, speed=None, revision=10, error=""):
    return Probe(latency_s=latency, speed_bps=speed, revision=revision, sample="repodata/p", error=error)


def test_the_list_is_shown_as_the_metalink_gives_it():
    m, view, *_ = dialog()
    assert [(ln.name, ln.country, ln.protocol, ln.response, ln.speed, ln.note) for ln in view.lines] == [
        ("a.example/f", "DE", "HTTPS", "—", "—", ""), ("b.example/f", "NL", "HTTPS", "—", "—", ""),
        ("c.example/f", "CZ", "HTTP", "—", "—", "")]
    assert view.status == "3 mirrors. Test the speed to see which is the quickest."


def test_a_list_that_cannot_be_had_says_why():
    m, view, net, _ui = dialog(mirrors=None)
    assert view.status == "Loading the list of mirrors…"
    net.requests[0].failed(NetError("HTTP 503: Service Unavailable"))
    assert view.status == "Could not get the list of mirrors: HTTP 503: Service Unavailable"
    assert not m.buttons(None).test


def test_the_pinned_mirror_is_in_use_even_when_the_list_no_longer_has_it():
    m, view, *_ = dialog(PINNED, mirrors=(A, C))
    assert [ln.note for ln in view.lines] == ["", "", "In use"] and view.lines[2].current
    assert view.lines[2].mirror.url == "https://b.example/f/"


def test_a_test_ranks_the_mirrors_when_it_is_over_and_not_before():
    m, view, net, _ui = dialog()
    m.toggle_test()
    [test] = net.tests
    assert test.started and view.testing and test.mirrors == [A, B, C]
    test.probe(A, probe(0.3))
    test.probe(B, probe(0.05))
    test.probe(C, probe(None, error="Connection refused"))
    assert [ln.name for ln in view.lines] == ["a.example/f", "b.example/f", "c.example/f"]  # the list's own order
    assert view.status == "Testing the mirrors… 3 of 3 answered"
    test.probe(A, probe(0.3, 2_000_000))
    test.probe(B, probe(0.05, 9_000_000))
    test.done()
    assert not view.testing
    assert [(ln.name, ln.response, ln.speed, ln.note) for ln in view.lines] == [
        ("b.example/f", "50 ms", "8.6 MB/s", "Fastest"), ("a.example/f", "300 ms", "1.9 MB/s", ""),
        ("c.example/f", "—", "—", "Connection refused")]
    assert view.status == "2 of 3 mirrors answered. The quickest is first."


def test_a_mirror_with_older_metadata_is_marked_and_ranked_below():
    m, view, net, _ui = dialog(mirrors=(A, B))
    m.test()
    test = net.tests[0]
    test.probe(A, probe(0.1, 50_000_000, revision=7))
    test.probe(B, probe(0.2, 1_000_000, revision=9))
    test.done()
    assert [(ln.name, ln.note) for ln in view.lines] == [("b.example/f", "Fastest"), ("a.example/f", "Out of date")]


def test_stopping_a_test_keeps_what_it_found():
    m, view, net, _ui = dialog(mirrors=(A, B))
    m.toggle_test()
    net.tests[0].probe(A, probe(0.1))
    m.toggle_test()
    assert net.tests[0].cancelled and not view.testing and view.status == "The test was stopped."
    assert view.lines[0].response == "100 ms"
    net.tests[0].probe(B, probe(0.2))  # a late answer of the stopped test
    assert view.lines[1].response == "—"
    m.toggle_test()
    assert len(net.tests) == 2 and view.lines[0].response == "—"  # a new test starts clean


def test_using_a_mirror_closes_with_the_choice():
    m, view, net, ui = dialog()
    m.use(A.url)
    assert m.choice == MirrorChoice("updates", A.url) and len(view.applied) == 1 and not ui.calls


def test_a_mirror_that_failed_or_is_in_use_cannot_be_used_and_nothing_is_selected_by_default():
    m, view, net, ui = dialog(PINNED, mirrors=(A, B))
    m.test()
    net.tests[0].probe(A, probe(None, error="timed out"))
    assert not m.buttons(None).use.enabled and m.buttons(None).use.tooltip == "Select a mirror."
    assert m.buttons(A.url).use.tooltip == "This mirror did not answer the test."
    assert m.buttons(B.url).use.tooltip == "The repository already uses this mirror."
    m.use(A.url)
    m.use(B.url)
    m.use(None)
    assert m.choice is None and not view.applied


def test_a_plain_http_or_out_of_date_mirror_asks_first():
    m, view, net, ui = dialog(answers=["cancel", "use"])
    m.use(C.url)
    assert m.choice is None and ui.calls[0][1].informative == "It is not reached over https."
    m.use(C.url)
    assert m.choice == MirrorChoice("updates", C.url) and len(view.applied) == 1

    m, view, net, ui = dialog(mirrors=(A, B), answers=["use"])
    m.test()
    net.tests[0].probe(A, probe(0.1, 1, revision=1))
    net.tests[0].probe(B, probe(0.1, 1, revision=2))
    m.use(A.url)
    assert "older than another mirror's" in ui.calls[0][1].informative and m.choice.baseurl == A.url


def test_automatic_is_for_a_pinned_repository_only():
    m, view, *_ = dialog()
    assert not m.buttons(None).automatic.enabled
    m.use_automatic()
    assert m.choice is None
    m, view, *_ = dialog(PINNED)
    assert m.buttons(None).automatic.enabled
    m.use_automatic()
    assert m.choice == MirrorChoice("updates", None) and len(view.applied) == 1


def test_the_fastest_mirror_option_flips_and_is_applied():
    m, view, *_ = dialog(fastest=False)
    assert m.fastest_button_text() == "Turn On Fastest Mirror Search"
    m.toggle_fastest()
    assert m.choice == MirrorChoice(fastestmirror=True) and not m.choice.repo
    m, view, *_ = dialog(fastest=True)
    assert m.fastest_button_text() == "Turn Off Fastest Mirror Search" and "fastest" in m.fastest_text()
    m.toggle_fastest()
    assert m.choice == MirrorChoice(fastestmirror=False)


def test_closing_stops_the_list_and_the_test_and_drops_what_comes_late():
    m, view, net, _ui = dialog(mirrors=None)
    m.close()
    assert net.requests[0].cancelled
    net.requests[0].done([A])
    assert view.lines == []
    m, view, net, _ui = dialog()
    m.test()
    m.close()
    assert net.tests[0].cancelled
    net.tests[0].probe(A, probe(0.1))
    assert view.lines[0].response == "—"



def test_after_a_pin_is_applied_the_dialog_shows_it_and_keeps_what_the_test_found():
    m, view, net, _ui = dialog()
    m.test()
    net.tests[0].probe(A, probe(0.1, 5_000_000))
    net.tests[0].done()
    m.use(A.url)
    assert view.applied == [MirrorChoice("updates", A.url)]
    m.update(MirrorSource(SourceKind.METALINK, SOURCE.url, A.url), False)  # the reload after the helper
    line = next(ln for ln in view.lines if ln.mirror == A)
    assert line.current and line.note == "In use. Fastest" and line.speed == "4.8 MB/s"
    assert view.status == "The repository now downloads from a.example/f."
    assert m.buttons(None).automatic.enabled and not m.buttons(A.url).use.enabled and m.choice is None
    m.use_automatic()
    m.update(SOURCE, False)
    assert view.status == "The repository takes its mirrors from the list again."
    assert not any(ln.current for ln in view.lines)


def test_a_change_that_did_not_happen_says_nothing_and_the_option_follows_the_reload():
    m, view, *_ = dialog()
    m.use(A.url)
    m.update(SOURCE, False)  # the helper failed: still automatic
    assert view.status == "3 mirrors. Test the speed to see which is the quickest."
    assert not any(ln.current for ln in view.lines)
    m.toggle_fastest()
    m.update(SOURCE, True)
    assert view.fastest == (m.fastest_text(), "Turn Off Fastest Mirror Search")


# --------------------------------------------------------------------------- the repositories dialog's button

def repos_presenter(repos, variables=None, changed=False):
    p = Repos(repos, Counter(), RecordingUi(), SimpleNamespace(close_with_choice=lambda: None),
              variables=variables or {})
    if changed:
        p.set_enabled(repos[0].id, not repos[0].enabled)
    return p


def test_mirrors_is_offered_for_a_repository_with_a_list_only(tmp_path):
    f = tmp_path / "fedora.repo"
    f.write_text("[pinned]\nmetalink=https://ml/$releasever\n")
    repos = [RepoInfo("updates", "Updates", True, Origin.FEDORA, 60, 99, "", metalink="https://ml/x"),
             RepoInfo("code", "Code", True, Origin.THIRD_PARTY, 60, 99, "", baseurls=("https://one/",)),
             RepoInfo("pinned", "Pinned", True, Origin.FEDORA, 60, 99, str(f), baseurls=("https://b.example/f/",)),
             RepoInfo("old", "Old", True, Origin.THIRD_PARTY, 60, 99, "", mirrorlist="https://list/")]
    p = repos_presenter(repos)
    assert p.mirrors_action("updates").enabled and p.mirrors_action("old").enabled and p.mirrors_action("pinned").enabled
    assert p.mirrors_action("code").tooltip.startswith("This repository has a single address")
    assert not p.mirrors_action(None).enabled
    p.show_mirrors("code")
    assert p.mirror_repo is None
    p.show_mirrors("updates")
    assert p.mirror_repo == "updates"


def test_mirrors_waits_for_the_pending_changes():
    repos = [RepoInfo("updates", "Updates", True, Origin.FEDORA, 60, 99, "", metalink="https://ml/x")]
    p = repos_presenter(repos, changed=True)
    assert p.mirrors_action("updates").tooltip == "Apply or undo the changes first."


def test_the_dialog_title_names_the_repository():
    assert app.dialog_title(SimpleNamespace(id="updates", name="Fedora 45 - Updates")) == "Mirrors of Fedora 45 - Updates"
    assert app.dialog_title(SimpleNamespace(id="updates", name="")) == "Mirrors of updates"
