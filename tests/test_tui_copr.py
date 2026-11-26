"""The terminal front end's COPR dialog (docs/TUI_SPEC.md §10.6, kram.tui.dialogs.copr), from the window over a
made-up catalog, a fake helper and a fake Copr search, as tests/test_gtk.py tests the GTK one: the projects on this
system, the search with its results, enabling a result and a typed project, the question before a project with no
build for this Fedora, disabling, removing with Show packages, a network error and the retry, and the change run
over the dialog, which then shows the new state.
"""
import asyncio
import dataclasses
import json
import sys
from collections import Counter

import pytest

pytest.importorskip("textual")

from test_tui_repos import FAKE_HELPER, WIDE, finish, press, text, until  # noqa: E402
from test_tui_window import use_catalog  # noqa: E402

from kram.app.parity import Feature  # noqa: E402
from kram.core import net  # noqa: E402
from kram.core.model import CatalogSnapshot, Origin, PkgRow, RepoInfo, Status  # noqa: E402
from kram.core.settings import store as settings  # noqa: E402
from kram.tui import root  # noqa: E402
from kram.tui import window as window_module  # noqa: E402
from kram.tui.dialogs.copr import CoprDialog  # noqa: E402
from kram.tui.dialogs.progress import AUTO_CLOSE_KEY  # noqa: E402
from kram.tui.dialogs.question import QuestionDialog  # noqa: E402
from kram.tui.widgets import Button  # noqa: E402

KRAM = "copr:copr.fedorainfracloud.org:elmodos:Kram"
OLD = "copr:copr.fedorainfracloud.org:someone:old"
RESULTS = [
    {"full_name": "a/tool", "description": "A tool\nfor things", "chroot_repos": {"fedora-45-x86_64": ""}},
    {"full_name": "b/legacy", "description": "Old builds only", "chroot_repos": {"fedora-42-x86_64": ""}},
]


@pytest.fixture
def helper(tmp_path, monkeypatch):
    """The window's own client over a fake helper, as tests/test_tui_repos.py has it; returns the requests."""
    script, seen = tmp_path / "helper.py", tmp_path / "requests"
    script.write_text(FAKE_HELPER)
    monkeypatch.setenv("KRAM_HELPER_NO_PKEXEC", "1")
    monkeypatch.setattr(root.TuiHelperClient, "_command", lambda self: [sys.executable, "-I", str(script), str(seen)])
    monkeypatch.setattr(window_module, "is_root", lambda: False)
    return lambda: [json.loads(line) for line in seen.read_text().splitlines()] if seen.exists() else []


def repos(*, kram_on: bool = True, old: bool = True, extra: tuple[RepoInfo, ...] = ()) -> list[RepoInfo]:
    found = [RepoInfo("fedora", "Fedora 45", True, Origin.FEDORA, 3600, 99, "/usr/share/dnf5/repos.d/fedora.repo"),
             RepoInfo(KRAM, "Copr repo for Kram", kram_on, Origin.COPR, 60, 99, "/etc/yum.repos.d/kram.repo")]
    if old:
        found.append(RepoInfo(OLD, "Copr repo for old", False, Origin.COPR, None, 99, "/etc/yum.repos.d/old.repo"))
    return found + list(extra)


def snap(found: list[RepoInfo]) -> CatalogSnapshot:
    rows = [PkgRow("kram", "noarch", "Kram", "1.0-1", "1.0-1", KRAM, 1000, Origin.COPR, Status.INSTALLED,
                   from_repo_id=KRAM),
            PkgRow("kram-tui", "noarch", "Kram TUI", "1.0-1", "1.0-1", KRAM, 1000, Origin.COPR, Status.INSTALLED,
                   from_repo_id=KRAM),
            PkgRow("pkg", "x86_64", "A package", "", "1.0-1", "fedora", 1000, Origin.FEDORA, Status.NOT_INSTALLED)]
    return CatalogSnapshot(rows, 2, 0, 0.1, descriptions=[""] * len(rows), repos=found, releasever="45")


class Copr:
    """The Copr search API: each answer is the next of `answers` (a list of results, or a NetError)."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.queries: list[str] = []

    def fetch(self, url, *, params, post, done, failed, **_kw):
        self.queries.append(params["query"])
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, net.NetError):
            post(lambda: failed(answer))
        else:
            post(lambda: done(json.dumps({"items": answer}).encode()))
        return net.Request()


def run(monkeypatch, test, snaps: list[CatalogSnapshot], copr: Copr | None = None, size=WIDE):
    """`test(app, pilot)` in the window; every load gives the next of `snaps` (the last one again at the end)."""
    loads = []

    def load(*_a, **_k):
        loads.append(1)
        return snaps[min(len(loads), len(snaps)) - 1]
    settings.set(AUTO_CLOSE_KEY, False)  # the progress dialog stays until Close
    use_catalog(monkeypatch, snaps[0], load=load, repo_package_counts=lambda: Counter({KRAM: 7, "fedora": 100}))
    copr = copr or Copr(RESULTS)
    monkeypatch.setattr(net, "fetch", copr.fetch)
    from kram.tui.app import KramApp
    app = KramApp()

    async def go():
        async with app.run_test(size=size) as pilot:
            await until(pilot, lambda: app.main.browser.snapshot is not None and app.main.browser.filter is not None)
            await pilot.pause()
            await test(app, pilot)
            app.main.browser.helper.stop()
    asyncio.run(go())
    return app


async def open_copr(app, pilot, projects: bool = True) -> CoprDialog:
    app.main.run_action("copr")
    await until(pilot, lambda: isinstance(app.screen, CoprDialog) and app.screen._ready
                and (bool(app.screen.projects) or not projects))
    await pilot.pause()
    return app.screen


def lines(table) -> list[str]:
    return [table.render_line(y).text.rstrip() for y in range(len(table.keys) + 1)]


def builds_style(dialog, row: int):
    """The style of the Builds cell of a result's row."""
    strip = dialog.result_table.render_line(row + 1)
    g = dialog.app.glyphs
    return next(s.style for s in strip if s.text.strip().startswith((g.yes, g.no)))


async def search(app, pilot, dialog, words: str) -> None:
    field = dialog.query_one("#copr-search")
    field.focus()
    field.value = words
    await field.action_submit()  # Enter
    await until(pilot, lambda: not dialog.searching and dialog.status != "Searching… Copr can take up to a minute "
                                                                          "to answer.")
    await pilot.pause()


# ---------------------------------------------------------------- the projects and the search

@pytest.mark.feature(Feature.DIALOG_COPR, front="tui")
def test_the_projects_on_this_system_and_the_search(monkeypatch):
    async def test(app, pilot):
        dialog = await open_copr(app, pilot)
        assert dialog.query_one("#copr-box").border_title == "COPR repositories"
        header, kram, old = lines(dialog.project_table)
        assert header.split() == ["On", "Project", "Packages", "Installed"]
        assert kram.split() == ["[x]", "elmodos/Kram", "7", "2"]
        assert old.split() == ["[", "]", "someone/old", "0"]  # off: its packages are not loaded
        assert not dialog.query_one("#no-projects").display
        assert dialog.focused is dialog.query_one("#copr-search")
        # the project under the cursor: on, so Disable
        assert dialog.query_one("#toggle", Button).label == "Disable"
        assert not dialog.query_one("#enable", Button).enabled
        assert not text(dialog, "why") and dialog.result_table.keys == []  # nothing searched yet
        await search(app, pilot, dialog, "tool")
        assert dialog.status == "2 projects found." and not dialog.failed
        header, tool, legacy = lines(dialog.result_table)
        assert header.split() == ["Project", "Builds", "for", "this", "system", "Description"]
        g = app.glyphs  # "+" and "-" where the terminal is not UTF-8
        assert tool.split() == ["a/tool", g.yes, "fedora-45-x86_64", "A", "tool", "for", "things"]
        assert legacy.split()[:3] == ["b/legacy", g.no, "fedora-45-x86_64"]
        ok, danger = builds_style(dialog, 0), builds_style(dialog, 1)
        assert ok.color != danger.color  # the ok and danger roles
        # the first result has the cursor and the focus; Enable is on for it
        assert dialog.focused is dialog.result_table and dialog.selected_result().full_name == "a/tool"
        assert dialog.query_one("#enable", Button).enabled and not text(dialog, "why")
        dialog.result_table.go(1)
        await pilot.pause()
        assert text(dialog, "why") == "Builds exist for: fedora-42-x86_64"
    run(monkeypatch, test, [snap(repos())])


def test_without_projects_a_line_says_to_search_and_ascii_has_its_glyphs(monkeypatch):
    monkeypatch.setenv("LANG", "C")
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LC_CTYPE", raising=False)

    async def test(app, pilot):
        dialog = await open_copr(app, pilot, projects=False)
        await until(pilot, lambda: dialog.query_one("#no-projects").display)
        assert text(dialog, "no-projects") == "No COPR projects yet. Search for one below."
        assert not dialog.project_table.display
        assert not dialog.query_one("#packages", Button).enabled and not dialog.query_one("#remove", Button).enabled
        await search(app, pilot, dialog, "tool")
        _header, tool, legacy = lines(dialog.result_table)
        assert tool.split()[1:3] == ["+", "fedora-45-x86_64"] and legacy.split()[1] == "-"
    run(monkeypatch, test, [snap(repos(kram_on=True, old=False)[:1])])


# ---------------------------------------------------------------- enabling

@pytest.mark.feature(Feature.DIALOG_COPR_ENABLE_FROM_SEARCH, front="tui")
def test_enable_a_result_runs_over_the_dialog_and_the_reload_shows_it(monkeypatch, helper):
    tool = RepoInfo("copr:copr.fedorainfracloud.org:a:tool", "Copr repo for tool", True, Origin.COPR, 60, 99,
                    "/etc/yum.repos.d/tool.repo")

    async def test(app, pilot):
        dialog = await open_copr(app, pilot)
        await search(app, pilot, dialog, "tool")
        dialog.action_enable()  # ctrl+e
        progress = await finish(app, pilot, CoprDialog)
        assert progress.title_text == "Enabling a/tool"
        assert helper() == [{"op": "copr", "action": "enable", "project": "a/tool"}]
        # the reload: the new project is in the table, the result says it is enabled and Enable is off
        await until(pilot, lambda: "copr:copr.fedorainfracloud.org:a:tool" in dialog.projects)
        await pilot.pause()
        assert [dialog.projects[i].project for i in dialog.project_table.keys] == ["a/tool", "elmodos/Kram",
                                                                                   "someone/old"]
        assert lines(dialog.project_table)[1].split()[:2] == ["[x]", "a/tool"]
        assert lines(dialog.result_table)[1].split()[:2] == ["a/tool", "(enabled)"]
        assert not dialog.query_one("#enable", Button).enabled
        assert text(dialog, "why") == "Enable selected: a/tool is already enabled"
        assert app.screen is dialog
    run(monkeypatch, test, [snap(repos()), snap(repos(extra=(tool,)))])


@pytest.mark.feature(Feature.DIALOG_COPR_ENABLE_FROM_SEARCH, front="tui")
def test_a_typed_owner_and_project_is_enabled_without_a_search(monkeypatch, helper):
    async def test(app, pilot):
        dialog = await open_copr(app, pilot)
        app.focused.value = "elmodos/kram"  # typed in the line, which has the focus
        await pilot.pause()
        assert not dialog.query_one("#enable", Button).enabled  # on already
        assert text(dialog, "why") == "Enable selected: elmodos/kram is already enabled"
        app.focused.value = "elmodos/other"
        await pilot.pause()
        assert dialog.query_one("#enable", Button).enabled and not text(dialog, "why")
        await pilot.press("ctrl+e")  # in the line: not its own end-of-line key
        await finish(app, pilot, CoprDialog)
        assert helper() == [{"op": "copr", "action": "enable", "project": "elmodos/other"}]
        # after a search, an owner/project typed in the line wins over the results
        await search(app, pilot, dialog, "tool")
        dialog.query_one("#copr-search").focus()
        dialog.query_one("#copr-search").value = "x/y"
        await pilot.pause()
        assert dialog.selected_result() is None
        await press(pilot, dialog, "enable")
        await finish(app, pilot, CoprDialog)
        assert helper()[-1] == {"op": "copr", "action": "enable", "project": "x/y"}
    run(monkeypatch, test, [snap(repos())])


@pytest.mark.feature(Feature.DIALOG_COPR_NO_BUILD_QUESTION, front="tui")
def test_a_project_without_a_build_for_this_fedora_asks_first(monkeypatch, helper):
    async def test(app, pilot):
        dialog = await open_copr(app, pilot)
        await search(app, pilot, dialog, "legacy")
        dialog.result_table.go(next(i for i, r in enumerate(dialog.results) if r.project.full_name == "b/legacy"))
        dialog.action_activate()  # Enter on a result enables it
        await pilot.pause()
        question = app.screen
        assert isinstance(question, QuestionDialog) and question.question.title == "No builds for this system"
        assert question.question.text == ("b/legacy has no builds for Fedora 45 (x86_64). Enable it anyway?")
        question.action_cancel()  # Esc: No
        await until(pilot, lambda: app.screen is dialog)
        await pilot.pause()
        assert helper() == []
        dialog.action_enable()
        await until(pilot, lambda: isinstance(app.screen, QuestionDialog))
        app.screen.dismiss("yes")
        await finish(app, pilot, CoprDialog)
        assert helper() == [{"op": "copr", "action": "enable", "project": "b/legacy"}]
    run(monkeypatch, test, [snap(repos())])


# ---------------------------------------------------------------- the projects' buttons

def test_disable_and_enable_a_project_of_this_system(monkeypatch, helper):
    off = [dataclasses.replace(r, enabled=False) if r.id == KRAM else r for r in repos()]

    async def test(app, pilot):
        dialog = await open_copr(app, pilot)
        await press(pilot, dialog, "toggle")
        progress = await finish(app, pilot, CoprDialog)
        assert progress.title_text == "Disabling elmodos/Kram"
        assert helper() == [{"op": "copr", "action": "disable", "project": "elmodos/Kram"}]
        await until(pilot, lambda: not dialog.projects[KRAM].enabled)
        await pilot.pause()
        # the cursor stays on its project; the button now turns it back on
        assert dialog.project_table.current == KRAM and dialog.query_one("#toggle", Button).label == "Enable"
        assert lines(dialog.project_table)[1].split()[:3] == ["[", "]", "elmodos/Kram"]
        await press(pilot, dialog, "toggle")
        await finish(app, pilot, CoprDialog)
        assert helper()[-1] == {"op": "copr", "action": "enable", "project": "elmodos/Kram"}
    run(monkeypatch, test, [snap(repos()), snap(off), snap(repos())])


@pytest.mark.feature(Feature.DIALOG_COPR_REMOVE_QUESTION, front="tui")
@pytest.mark.feature(Feature.DIALOG_COPR_PACKAGES, front="tui")
def test_remove_asks_with_show_packages_and_packages_closes_the_dialog(monkeypatch, helper):
    async def test(app, pilot):
        dialog = await open_copr(app, pilot)
        await press(pilot, dialog, "remove")
        question = app.screen
        assert isinstance(question, QuestionDialog) and question.question.title == "Remove COPR project"
        assert question.question.text == "Remove the elmodos/Kram repository from the system?"
        assert question.question.informative.startswith("2 installed packages come from it.")
        assert [b.id for b in question.question.buttons] == ["remove", "show", "cancel"]
        # Show packages: the dialog closes and the window shows the project's packages
        button = next(b for b, answer in question._answers.items() if answer == "show")
        button.action_press()
        await until(pilot, lambda: len(app.screen_stack) == 1)
        await pilot.pause()
        assert app.main.browser.filter.id == f"repo:{KRAM}"
        assert {app.main.browser.packages.row(i).name for i in range(len(app.main.browser.packages))} == \
            {"kram", "kram-tui"}
        assert helper() == []
        # Packages, and a removal of a project nothing is installed from: no Show packages
        dialog = await open_copr(app, pilot)
        dialog.project_table.select_key(OLD)
        await pilot.pause()
        await press(pilot, dialog, "remove")
        question = app.screen
        assert {b.id for b in question.question.buttons} == {"remove", "cancel"}
        assert not question.question.informative
        button = next(b for b, answer in question._answers.items() if answer == "remove")
        button.action_press()
        progress = await finish(app, pilot, CoprDialog)
        assert progress.title_text == "Removing someone/old"
        assert helper() == [{"op": "copr", "action": "remove", "project": "someone/old"}]
        await until(pilot, lambda: OLD not in dialog.projects)
        await press(pilot, dialog, "packages")
        await until(pilot, lambda: len(app.screen_stack) == 1)
        assert app.main.browser.filter.id == f"repo:{KRAM}"
    run(monkeypatch, test, [snap(repos()), snap(repos(old=False))])


# ---------------------------------------------------------------- the network

def test_a_network_error_stays_on_the_status_line_and_ctrl_r_tries_again(monkeypatch):
    copr = Copr(net.NetError("Could not connect: no route to host"), RESULTS)

    async def test(app, pilot):
        dialog = await open_copr(app, pilot)
        await search(app, pilot, dialog, "tool")
        assert dialog.failed and text(dialog, "status") == ("Search failed: Could not connect: no route to host  "
                                                            "ctrl+r try again")
        assert lines(dialog.result_table) == [lines(dialog.result_table)[0]]  # no results
        dialog.action_retry()  # ctrl+r
        await until(pilot, lambda: dialog.status == "2 projects found.")
        assert copr.queries == ["tool", "tool"] and not dialog.failed
        assert text(dialog, "status") == "2 projects found."
        dialog.action_retry()  # nothing to try again
        await pilot.pause()
        assert copr.queries == ["tool", "tool"]
    run(monkeypatch, test, [snap(repos())], copr=copr)


def test_esc_closes_it_and_the_window_lets_it_go(monkeypatch):
    async def test(app, pilot):
        listeners = len(app.main.browser.catalog_loaded._slots)
        dialog = await open_copr(app, pilot)
        assert len(app.main.browser.catalog_loaded._slots) == listeners + 1  # the new state after a change
        dialog.action_close()  # Esc
        await until(pilot, lambda: len(app.screen_stack) == 1)
        await pilot.pause()
        assert dialog.copr._closed  # a search that answers later is dropped
        assert len(app.main.browser.catalog_loaded._slots) == listeners
    run(monkeypatch, test, [snap(repos())])


@pytest.mark.parametrize("size", [(64, 22)])
def test_a_narrow_dialog_keeps_its_buttons(monkeypatch, size):
    async def test(app, pilot):
        dialog = await open_copr(app, pilot)
        await search(app, pilot, dialog, "tool")
        box = dialog.query_one("#copr-box").region
        for name in ("packages", "toggle", "remove", "enable"):
            assert dialog.query_one(f"#{name}", Button).region.bottom <= box.bottom
        header, tool, _legacy = lines(dialog.result_table)
        assert header.split()[0] == "Project" and "Descrip" in header
        assert f"{app.glyphs.yes} fedora-45-x86_64" in tool  # the chroot is not cut
    run(monkeypatch, test, [snap(repos())], size=size)
