"""Repositories → Mirrors… in Qt: the table, the speed test button, the choices, and the Repositories button."""
import os
from collections import Counter

import pytest
from test_mirrors_flow import PINNED, SOURCE, A, B, C, Net, probe

from kram.app.mirrors import MirrorChoice
from kram.app.parity import Feature  # noqa: E402  (the feature marks of the parity tests)
from kram.core.mirrors import MirrorSource, SourceKind

pytest.importorskip("PySide6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from kram.core.model import Origin, RepoInfo
from kram.qt.mirrors_dialog import COL_NOTE, COL_SPEED, MirrorsDialog
from kram.qt.repos_dialog import COL_MIRROR, ReposDialog

REPO = RepoInfo("updates", "Fedora 45 - Updates", True, Origin.FEDORA, 60, 99, "/usr/share/dnf5/repos.d/fedora.repo",
                metalink="https://mirrors.example/metalink")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def shown(app, source=SOURCE, fastest=False, mirrors=(A, B, C)):
    net, applied = Net(), []
    dlg = MirrorsDialog(REPO, source, fastest, None, on_choice=applied.append, fetch=net.fetch,
                        speed_test=net.speed_test)
    dlg.applied = applied
    dlg.show()
    net.requests[0].done(list(mirrors))
    app.processEvents()
    return dlg, net


def column(dlg, col):
    return [dlg.table.item(i, col).text() for i in range(dlg.table.rowCount())]


def select(dlg, row):
    dlg.table.selectRow(row)


@pytest.mark.feature(Feature.DIALOG_MIRRORS, front="qt")
@pytest.mark.feature(Feature.DIALOG_MIRRORS_PIN, front="qt")
def test_the_list_is_shown_and_a_double_click_uses_the_mirror(app):
    dlg, _net = shown(app)
    assert dlg.windowTitle() == "Mirrors of Fedora 45 - Updates"
    assert [dlg.table.item(i, 0).text() for i in range(3)] == ["a.example/f", "b.example/f", "c.example/f"]
    assert not dlg.use_btn.isEnabled() and not dlg.automatic_btn.isEnabled()
    select(dlg, 1)
    assert dlg.use_btn.isEnabled()
    dlg.use_btn.click()
    assert dlg.applied == [MirrorChoice("updates", B.url)] and dlg.isVisible()


@pytest.mark.feature(Feature.DIALOG_MIRRORS_SPEED_TEST, front="qt")
def test_test_speed_runs_ranks_and_can_stop(app):
    dlg, net = shown(app)
    assert dlg.test_btn.text() == "Test Speed" and dlg.test_btn.isEnabled()
    dlg.test_btn.click()
    [test] = net.tests
    assert dlg.test_btn.text() == "Stop Test" and test.started
    select(dlg, 0)  # the selection stays with its mirror when the rows move
    test.probe(A, probe(0.3, 1_000_000))
    test.probe(B, probe(0.1, 8_000_000))
    test.probe(C, probe(None, error="Connection refused"))
    test.done()
    assert dlg.test_btn.text() == "Test Speed"
    assert [dlg.table.item(i, 0).text() for i in range(3)] == ["b.example/f", "a.example/f", "c.example/f"]
    assert column(dlg, COL_SPEED) == ["7.6 MB/s", "976.6 kB/s", "—"]
    assert column(dlg, COL_NOTE) == ["Fastest", "", "Connection refused"]
    assert dlg._selected_url() == A.url  # the selected row moved with its mirror
    select(dlg, 2)  # the mirror that failed
    assert not dlg.use_btn.isEnabled() and "did not answer" in dlg.use_btn.toolTip()
    dlg.test_btn.click()
    assert dlg.test_btn.text() == "Stop Test"
    dlg.test_btn.click()  # stop
    assert net.tests[1].cancelled and dlg.test_btn.text() == "Test Speed"


@pytest.mark.feature(Feature.DIALOG_MIRRORS_IN_USE, front="qt")
def test_the_pinned_mirror_is_marked_in_use_and_bold(app):
    dlg, _net = shown(app, PINNED)
    assert column(dlg, COL_NOTE) == ["", "In use", ""]
    assert [dlg.table.item(i, 0).font().bold() for i in range(3)] == [False, True, False]


@pytest.mark.feature(Feature.DIALOG_MIRRORS_AUTOMATIC, front="qt")
def test_automatic_returns_a_pinned_repository_to_its_list(app):
    dlg, _net = shown(app, PINNED)
    assert dlg.automatic_btn.isEnabled()
    dlg.automatic_btn.click()
    assert dlg.applied == [MirrorChoice("updates", None)] and dlg.isVisible()


@pytest.mark.feature(Feature.DIALOG_MIRRORS_FASTEST, front="qt")
def test_the_fastest_mirror_button_switches_dnfs_option(app):
    dlg, _net = shown(app, fastest=True)
    assert dlg.fastest_btn.text() == "Turn Off Fastest Mirror Search"
    dlg.fastest_btn.click()
    assert dlg.applied == [MirrorChoice(fastestmirror=False)] and dlg.isVisible()


@pytest.mark.feature(Feature.DIALOG_MIRRORS_APPLY_IN_PLACE, front="qt")
def test_a_choice_is_applied_while_the_dialog_stays_open_and_it_then_shows_the_new_state(app):
    dlg, _net = shown(app, fastest=False)
    select(dlg, 0)
    dlg.use_btn.click()
    assert dlg.applied == [MirrorChoice("updates", A.url)] and dlg.isVisible()
    dlg.set_state(MirrorSource(SourceKind.METALINK, SOURCE.url, A.url), True)  # after the reload
    assert column(dlg, COL_NOTE)[0] == "In use" and dlg.table.item(0, 0).font().bold()
    assert dlg.status.text() == "The repository now downloads from a.example/f."
    assert dlg.automatic_btn.isEnabled() and not dlg.use_btn.isEnabled()
    assert dlg.fastest_btn.text() == "Turn Off Fastest Mirror Search"


def test_closing_the_dialog_stops_the_test(app):
    dlg, net = shown(app)
    dlg.test_btn.click()
    dlg.reject()
    assert net.tests[0].cancelled and net.requests[0].cancelled and dlg.choice is None


@pytest.mark.feature(Feature.DIALOG_REPOSITORIES_MIRRORS, front="qt")
def test_the_repositories_dialog_offers_mirrors_for_a_repository_with_a_list(app):
    one = RepoInfo("code", "Visual Studio Code", True, Origin.THIRD_PARTY, 60, 99, "/etc/yum.repos.d/vscode.repo",
                   baseurls=("https://packages.example/",))
    asked = []
    dlg = ReposDialog([REPO, one], Counter(), None, on_mirrors=asked.append)
    dlg.show()

    def select_repo(repo_id):
        for i in range(dlg.table.rowCount()):
            if dlg.table.item(i, 0).data(0x0100) == repo_id:
                dlg.table.selectRow(i)
    select_repo("code")
    assert not dlg.mirrors_btn.isEnabled() and "single address" in dlg.mirrors_btn.toolTip()
    select_repo("updates")
    assert dlg.mirrors_btn.isEnabled()
    dlg.mirrors_btn.click()
    assert asked == ["updates"] and dlg.isVisible()  # Mirrors opens over it; it stays open


@pytest.mark.feature(Feature.DIALOG_REPOSITORIES_MIRROR_COLUMN, front="qt")
def test_the_repositories_table_shows_which_mirror_each_repository_uses(app, tmp_path):
    f = tmp_path / "fedora-updates.repo"
    f.write_text("[pinned]\nmetalink=https://mirrors.example/metalink\n")
    repos = [REPO,
             RepoInfo("pinned", "Pinned", True, Origin.FEDORA, 60, 99, str(f),
                      baseurls=("https://mirror.karneval.cz/pub/linux/fedora/",)),
             RepoInfo("code", "Visual Studio Code", True, Origin.THIRD_PARTY, 60, 99, "",
                      baseurls=("https://packages.example/",))]
    dlg = ReposDialog(repos, Counter(), None)
    shown_rows = {dlg.table.item(i, 1).text(): dlg.table.item(i, COL_MIRROR) for i in range(dlg.table.rowCount())}
    assert [(k, v.text()) for k, v in sorted(shown_rows.items())] == [
        ("code", ""), ("pinned", "mirror.karneval.cz"), ("updates", "Automatic")]
    assert shown_rows["pinned"].toolTip() == "https://mirror.karneval.cz/pub/linux/fedora/"
