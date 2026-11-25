"""The terminal front end's Repositories and Mirrors dialogs (docs/TUI_SPEC.md §10.4, §10.5, kram.tui.dialogs.repos,
kram.tui.dialogs.mirrors), from the window over a made-up catalog and a fake helper, as tests/test_gtk.py tests the GTK
ones: the table and its changes, the filter, debuginfo and source repositories, Apply through the progress dialog,
closing with changes, a removal and a mirror change run over the dialogs, which then show the new state; the mirrors
over a fake network (tests/test_mirrors_flow.py): the speed test, pinning, Automatic and dnf's fastest-mirror option.
"""
import asyncio
import dataclasses
import json
import sys
from collections import Counter

import pytest

pytest.importorskip("textual")

from test_mirrors_flow import A, B, C, Net, probe  # noqa: E402
from test_tui_window import use_catalog  # noqa: E402

from kram.app import browser as browser_module  # noqa: E402
from kram.app.parity import Feature  # noqa: E402
from kram.core.model import CatalogSnapshot, Origin, PkgRow, RepoInfo, Status  # noqa: E402
from kram.core.settings import store as settings  # noqa: E402
from kram.tui import root  # noqa: E402
from kram.tui import window as window_module  # noqa: E402
from kram.tui.app import KramApp  # noqa: E402
from kram.tui.dialogs.apply import Lines  # noqa: E402
from kram.tui.dialogs.mirrors import MirrorsDialog  # noqa: E402
from kram.tui.dialogs.progress import AUTO_CLOSE_KEY, ProgressDialog  # noqa: E402
from kram.tui.dialogs.question import QuestionDialog  # noqa: E402
from kram.tui.dialogs.repos import ReposDialog, age_text  # noqa: E402
from kram.tui.widgets import Button, CheckBox  # noqa: E402

WIDE, NARROW = (140, 36), (64, 22)
METALINK = "https://mirrors.example/metalink"
SYSTEM = "/usr/share/dnf5/repos.d/fedora.repo"
HOUR = 3600

FAKE_HELPER = r'''
import json, sys
for line in sys.stdin:
    req = json.loads(line)
    if req["op"] == "quit":
        break
    with open(sys.argv[1], "a") as f:
        f.write(json.dumps(req) + "\n")
    print(json.dumps({"event": "done", "ok": True}), flush=True)
'''


@pytest.fixture
def helper(tmp_path, monkeypatch):
    """The window's own client (kram.tui.root) over a fake helper; returns the requests it got."""
    script, seen = tmp_path / "helper.py", tmp_path / "requests"
    script.write_text(FAKE_HELPER)
    monkeypatch.setenv("KRAM_HELPER_NO_PKEXEC", "1")
    monkeypatch.setattr(root.TuiHelperClient, "_command", lambda self: [sys.executable, "-I", str(script), str(seen)])
    monkeypatch.setattr(window_module, "is_root", lambda: False)
    return lambda: [json.loads(line) for line in seen.read_text().splitlines()] if seen.exists() else []


def repos(updates_file: str, *, pinned: str = "", without: tuple[str, ...] = ()) -> list[RepoInfo]:
    """`updates` takes its mirrors from its metalink, or is pinned to `pinned` (the helper empties the metalink and
    sets the address; its file still names the metalink)."""
    updates = RepoInfo("updates", "Fedora 45 - Updates", True, Origin.FEDORA, 2 * HOUR, 99, updates_file,
                       metalink="" if pinned else METALINK, baseurls=(pinned,) if pinned else ())
    found = [RepoInfo("fedora", "Fedora 45 - x86_64", True, Origin.FEDORA, 3 * 86400, 99, SYSTEM, metalink=METALINK),
             RepoInfo("fedora-debuginfo", "Fedora 45 - x86_64 - Debug", False, Origin.FEDORA, None, 99, SYSTEM,
                      metalink=METALINK),
             updates,
             RepoInfo("updates-testing", "Fedora 45 - Test Updates", False, Origin.FEDORA, None, 99, SYSTEM,
                      metalink=METALINK),
             RepoInfo("code", "Visual Studio Code", True, Origin.THIRD_PARTY, 20 * 60, 99,
                      "/etc/yum.repos.d/vscode.repo", baseurls=("https://packages.example/vscode",)),
             RepoInfo("tools", "Tools", True, Origin.THIRD_PARTY, HOUR, 50, "/etc/yum.repos.d/tools.repo",
                      baseurls=("https://tools.example/",)),
             RepoInfo("tools-extra", "Tools: extras", True, Origin.THIRD_PARTY, HOUR, 50, "/etc/yum.repos.d/tools.repo",
                      baseurls=("https://tools.example/extra/",))]
    return [r for r in found if r.id not in without]


def catalog_rows() -> list[PkgRow]:
    found = [PkgRow(f"pkg{i}", "x86_64", f"Summary {i}", "", "1.0-1", "fedora", 1000, Origin.FEDORA,
                    Status.NOT_INSTALLED) for i in range(5)]
    return found + [
        PkgRow("code", "x86_64", "Code editing", "1.9-1", "1.9-1", "code", 1000, Origin.THIRD_PARTY, Status.INSTALLED,
               from_repo_id="code"),
        PkgRow("tool", "x86_64", "A tool", "2.0-1", "2.0-1", "tools", 1000, Origin.THIRD_PARTY, Status.INSTALLED,
               from_repo_id="tools")]


def snap(found: list[RepoInfo], fastest: bool = False) -> CatalogSnapshot:
    rows = catalog_rows()
    return CatalogSnapshot(rows, 2, 0, 0.1, descriptions=[""] * len(rows), repos=found, releasever="45",
                           fastestmirror=fastest)


@pytest.fixture
def updates_file(tmp_path):
    f = tmp_path / "fedora-updates.repo"
    f.write_text(f"[updates]\nmetalink={METALINK}\n")
    return str(f)


def run(monkeypatch, test, snaps: list[CatalogSnapshot], size=WIDE, net: Net | None = None):
    """`test(app, pilot)` in the window; every load gives the next of `snaps` (the last one again at the end)."""
    loads = []

    def load(*_a, **_k):
        loads.append(1)
        return snaps[min(len(loads), len(snaps)) - 1]
    settings.set(AUTO_CLOSE_KEY, False)  # the progress dialog stays until Close
    use_catalog(monkeypatch, snaps[0], load=load,
                repo_package_counts=lambda: Counter({"fedora": 70000, "updates": 9000, "code": 1, "tools": 1}))
    monkeypatch.setattr(browser_module, "file_owners", lambda paths: {})
    if net is not None:
        monkeypatch.setattr(window_module, "MirrorsDialog", lambda *a, **kw: MirrorsDialog(
            *a, **kw, fetch=net.fetch, speed_test=net.speed_test))
    app = KramApp()

    async def go():
        async with app.run_test(size=size) as pilot:
            await until(pilot, lambda: app.main.browser.snapshot is not None and app.main.browser.filter is not None)
            await pilot.pause()
            await test(app, pilot)
            app.main.browser.helper.stop()
    asyncio.run(go())
    return app


async def until(pilot, condition, seconds: float = 5) -> None:
    for _ in range(int(seconds / 0.02)):
        if condition():
            return
        await pilot.pause(0.02)
    assert condition()


async def open_repos(app, pilot) -> ReposDialog:
    app.main.run_action("repos")
    await until(pilot, lambda: isinstance(app.screen, ReposDialog))
    await pilot.pause()
    return app.screen


async def finish(app, pilot, under) -> ProgressDialog:
    """The progress dialog of a request run over `under` (a dialog class), to its end and closed."""
    await until(pilot, lambda: isinstance(app.screen, ProgressDialog) and app.screen.finished is not None)
    dialog = app.screen
    assert isinstance(app.screen_stack[-2], under)  # over the dialog it was run from
    await pilot.press("enter")
    await until(pilot, lambda: isinstance(app.screen, under))
    return dialog


def table_lines(dialog) -> list[str]:
    table = dialog.table
    return [table.render_line(y).text.rstrip() for y in range(len(table.keys) + 1)]


def line_of(dialog, key) -> str:
    return table_lines(dialog)[dialog.table.keys.index(key) + 1]


def bold_texts(dialog, key) -> list[str]:
    strip = dialog.table.render_line(dialog.table.keys.index(key) + 1 - dialog.table.scroll_offset.y)
    return [s.text.strip() for s in strip if s.style is not None and s.style.bold and s.text.strip()]


def text(dialog, name: str) -> str:
    widget = dialog.query_one(f"#{name}", Lines)
    return widget.render().plain if widget.display else ""


async def press(pilot, dialog, name: str) -> None:
    button = dialog.query_one(f"#{name}", Button)
    assert button.enabled, name
    button.action_press()
    await pilot.pause()


# ---------------------------------------------------------------- Repositories (§10.4)

@pytest.mark.feature(Feature.DIALOG_REPOSITORIES, front="tui")
@pytest.mark.feature(Feature.DIALOG_REPOSITORIES_MIRROR_COLUMN, front="tui")
def test_the_table_turns_repositories_on_and_off_and_lists_what_is_not_applied(monkeypatch, updates_file):
    pinned = repos(updates_file, pinned=B.url)

    async def test(app, pilot):
        dialog = await open_repos(app, pilot)
        assert dialog.query_one("#repos-box").border_title == "Repositories"
        # the enabled ones first; no debuginfo repository unless asked for
        assert dialog.shown_ids() == ["code", "fedora", "tools", "tools-extra", "updates", "updates-testing"]
        header = table_lines(dialog)[0].split()
        assert header == ["On", "Repository", "Name", "Packages", "Prio", "Origin", "Mirror", "Metadata"]
        assert line_of(dialog, "fedora").split() == ["[x]", "fedora", "Fedora", "45", "-", "x86_64", "70000", "99",
                                                     "Fedora", "Automatic", "3", "d"]
        assert "b.example" in line_of(dialog, "updates")  # pinned: the host of its mirror
        code = line_of(dialog, "code")  # the origin cut with "…", or "..." where the terminal is not UTF-8
        assert code.endswith(" 20 min") and "Third-par" in code and "Automatic" not in code  # one address: no mirror
        assert line_of(dialog, "updates-testing").startswith(" [ ] updates-testing ")
        assert dialog.table.has_focus and dialog.selected_id() == "code"
        assert not dialog.query_one("#apply", Button).enabled and not text(dialog, "pending")
        # space turns the one under the cursor on or off; the change is bold, with *, and said in words
        dialog.table.select_key("updates-testing")
        await pilot.press("space")
        assert dialog.repos.changes() == {"updates-testing": True}
        assert line_of(dialog, "updates-testing").startswith(" [x] updates-testing * ")
        assert "updates-testing *" in bold_texts(dialog, "updates-testing")
        dialog.table.select_key("code")
        await pilot.press("space")
        assert text(dialog, "pending") == "Not applied yet: turn on updates-testing; turn off code"
        assert dialog.query_one("#apply", Button).enabled
        # with changes pending, the buttons wait, and say so once
        assert not dialog.query_one("#packages", Button).enabled and not dialog.query_one("#remove", Button).enabled
        assert text(dialog, "why") == "Apply or undo the changes first."
        await pilot.press("space")  # back as it was: no longer a change
        assert dialog.repos.changes() == {"updates-testing": True} and "*" not in line_of(dialog, "code")
        assert text(dialog, "pending") == "Not applied yet: turn on updates-testing"
        # a click on the box turns it too
        dialog.table.select_key("updates-testing")
        await pilot.pause()
        y = dialog.table.keys.index("updates-testing") + 1
        await pilot.click(dialog.table, offset=(2, y))
        await pilot.pause()
        assert not dialog.repos.changes() and not text(dialog, "pending")
    run(monkeypatch, test, [snap(pinned)])


def test_a_narrow_table_drops_the_name_and_the_age(monkeypatch, updates_file):
    async def test(app, pilot):
        dialog = await open_repos(app, pilot)
        assert table_lines(dialog)[0].split() == ["On", "Repository", "Packages", "Prio", "Origin", "Mirror"]
        assert line_of(dialog, "updates-testing").startswith(" [ ] updates-testing ")  # the id is not cut
        assert dialog.query_one("#apply", Button).region.bottom <= dialog.query_one("#repos-box").region.bottom
    run(monkeypatch, test, [snap(repos(updates_file))], size=NARROW)


def test_the_age_of_the_metadata_is_short():
    assert [age_text(s) for s in (None, 20 * 60, 5 * HOUR, 9 * 86400)] == ["—", "20 min", "5 h", "9 d"]


@pytest.mark.feature(Feature.DIALOG_REPOSITORIES_FILTER, front="tui")
@pytest.mark.feature(Feature.DIALOG_REPOSITORIES_SHOW_AUX, front="tui")
def test_the_filter_and_the_debuginfo_and_source_repositories(monkeypatch, updates_file):
    async def test(app, pilot):
        dialog = await open_repos(app, pilot)
        await pilot.press("shift+tab")
        assert dialog.focused is dialog.query_one("#repos-filter")
        dialog.focused.value = "visual"
        await pilot.pause()
        assert dialog.shown_ids() == ["code"]  # by name
        dialog.focused.value = "tools-"
        await pilot.pause()
        assert dialog.shown_ids() == ["tools-extra"]  # by id
        dialog.focused.value = "x86_64"
        await pilot.pause()
        assert dialog.shown_ids() == ["fedora"]  # the debuginfo one is hidden
        await pilot.press("ctrl+d")
        await pilot.pause()
        assert dialog.query_one("#aux", CheckBox).value
        assert dialog.shown_ids() == ["fedora", "fedora-debuginfo"]
        await pilot.press("space")  # typed into the filter, not a repository turned on
        assert not dialog.repos.changes()
        await pilot.press("ctrl+d")
        await pilot.pause()
        assert dialog.shown_ids() == ["fedora"]
    run(monkeypatch, test, [snap(repos(updates_file))])


def test_apply_runs_the_changes_through_the_progress_dialog_and_reloads(monkeypatch, helper, updates_file):
    before = repos(updates_file)
    after = [dataclasses.replace(r, enabled=True) if r.id == "updates-testing" else r for r in before]

    async def test(app, pilot):
        dialog = await open_repos(app, pilot)
        dialog.table.select_key("updates-testing")
        await pilot.press("space")
        await pilot.press("ctrl+a")
        await until(pilot, lambda: isinstance(app.screen, ProgressDialog) and app.screen.finished is not None)
        progress = app.screen
        assert progress.title_text == "Changing repositories" and len(app.screen_stack) == 2  # the dialog is gone
        assert helper() == [{"op": "repo_set_enabled", "repos": {"updates-testing": True}}]
        await pilot.press("enter")
        await until(pilot, lambda: len(app.screen_stack) == 1)
        await until(pilot, lambda: any(r.id == "updates-testing" and r.enabled for r in app.main.browser.snapshot.repos))
    run(monkeypatch, test, [snap(before), snap(after)])


def test_closing_with_changes_not_applied_asks_first(monkeypatch, helper, updates_file):
    async def test(app, pilot):
        dialog = await open_repos(app, pilot)
        await pilot.press("escape")  # nothing changed: it closes
        await until(pilot, lambda: len(app.screen_stack) == 1)
        dialog = await open_repos(app, pilot)
        await pilot.press("space")
        await pilot.press("escape")
        await pilot.pause()
        question = app.screen
        assert isinstance(question, QuestionDialog) and app.screen_stack[-2] is dialog
        assert question.question.text == "The changes to the repositories are not applied yet."
        assert question.question.informative == "Not applied yet: turn off code"
        await pilot.press("escape")  # Cancel: back, the change still there
        await pilot.pause()
        assert app.screen is dialog and dialog.repos.changes() == {"code": False}
        await pilot.press("escape")
        await pilot.pause()
        answers = {b.label: b.id for b in app.screen.question.buttons if b.label}
        assert answers == {"Apply": "apply", "Close without applying": "discard"}
        button = next(b for b, answer in app.screen._answers.items() if answer == "discard")
        button.action_press()
        await until(pilot, lambda: len(app.screen_stack) == 1)
        await pilot.pause(0.2)
        assert helper() == []
        # Apply from the question runs them
        dialog = await open_repos(app, pilot)
        await pilot.press("space", "escape")
        await pilot.pause()
        button = next(b for b, answer in app.screen._answers.items() if answer == "apply")
        button.action_press()
        await until(pilot, lambda: isinstance(app.screen, ProgressDialog) and app.screen.finished is not None)
        assert helper() == [{"op": "repo_set_enabled", "repos": {"code": False}}]
        await pilot.press("enter")
        await until(pilot, lambda: len(app.screen_stack) == 1)
    run(monkeypatch, test, [snap(repos(updates_file))])


@pytest.mark.feature(Feature.DIALOG_REPOSITORIES_REMOVE, front="tui")
@pytest.mark.feature(Feature.DIALOG_REPOSITORIES_REMOVE_IN_PLACE, front="tui")
@pytest.mark.feature(Feature.DIALOG_REPOSITORIES_UPDATES_IN_PLACE, front="tui")
def test_remove_names_the_repositories_and_packages_and_the_table_updates_in_place(monkeypatch, helper,
                                                                                    updates_file):
    async def test(app, pilot):
        dialog = await open_repos(app, pilot)
        dialog.table.select_key("fedora")
        await pilot.pause()
        assert not dialog.query_one("#remove", Button).enabled and text(dialog, "why") == \
            "Remove file: Configured by the system."
        dialog.table.select_key("tools")
        await pilot.pause()
        await press(pilot, dialog, "remove")
        question = app.screen
        assert isinstance(question, QuestionDialog)
        q = question.question
        assert q.text == "The file /etc/yum.repos.d/tools.repo configures 2 repositories. Remove them all from " \
                         "the system?"
        assert "• tools — Tools\n• tools-extra — Tools: extras" in q.informative
        assert "1 installed package comes from them." in q.informative
        assert [b.label for b in q.buttons] == ["Remove", "Show packages", ""]
        button = next(b for b, answer in question._answers.items() if answer == "remove")
        button.action_press()
        await finish(app, pilot, ReposDialog)
        assert helper() == [{"op": "repo_remove", "repos": ["tools", "tools-extra"]}]
        # the reload: the dialog, still open, shows the list without them
        await until(pilot, lambda: "tools" not in dialog.shown_ids())
        assert app.screen is dialog and dialog.shown_ids() == ["code", "fedora", "updates", "updates-testing"]
    run(monkeypatch, test, [snap(repos(updates_file)), snap(repos(updates_file, without=("tools", "tools-extra")))])


def test_packages_shows_the_repository_s_packages_and_closes(monkeypatch, updates_file):
    async def test(app, pilot):
        dialog = await open_repos(app, pilot)
        dialog.table.select_key("updates")  # none of its packages are listed
        await pilot.pause()
        assert not dialog.query_one("#packages", Button).enabled
        assert text(dialog, "why") == "Packages: None of its packages are in the list.\n" \
                                      "Remove file: Configured by the system."
        dialog.table.select_key("code")
        await pilot.pause()
        await press(pilot, dialog, "packages")
        await until(pilot, lambda: len(app.screen_stack) == 1)
        b = app.main.browser
        assert b.filter.id == "repo:code" and [b.packages.row(i).name for i in range(len(b.packages))] == ["code"]
    run(monkeypatch, test, [snap(repos(updates_file))])


@pytest.mark.feature(Feature.DIALOG_REPOSITORIES_MIRRORS, front="tui")
@pytest.mark.feature(Feature.DIALOG_MIRRORS_OVER_REPOSITORIES, front="tui")
def test_mirrors_is_off_with_its_reason_and_opens_over_the_repositories(monkeypatch, updates_file):
    net = Net()

    async def test(app, pilot):
        dialog = await open_repos(app, pilot)
        assert dialog.selected_id() == "code"
        assert not dialog.query_one("#mirrors", Button).enabled
        assert "Mirrors: This repository has a single address: there are no mirrors to choose from." in \
            text(dialog, "why")
        dialog.table.select_key("updates")
        await pilot.pause()
        assert dialog.query_one("#mirrors", Button).enabled and "Mirrors" not in text(dialog, "why")
        await press(pilot, dialog, "mirrors")
        await until(pilot, lambda: isinstance(app.screen, MirrorsDialog))
        mirrors = app.screen
        assert app.screen_stack[-2] is dialog  # over the Repositories, which stays open
        assert mirrors.query_one("#mirrors-box").border_title == "Mirrors of Fedora 45 - Updates"
        await pilot.press("escape")
        await until(pilot, lambda: app.screen is dialog)
        assert net.requests[0].cancelled  # the list's loading stopped with it
    run(monkeypatch, test, [snap(repos(updates_file))], net=net)


# ---------------------------------------------------------------- Mirrors (§10.5)

async def open_mirrors(app, pilot, net: Net, mirrors=(A, B, C)) -> MirrorsDialog:
    dialog = await open_repos(app, pilot)
    dialog.table.select_key("updates")
    await pilot.pause()
    await press(pilot, dialog, "mirrors")
    await until(pilot, lambda: isinstance(app.screen, MirrorsDialog))
    net.requests[-1].done(list(mirrors))
    await pilot.pause()
    return app.screen


@pytest.mark.feature(Feature.DIALOG_MIRRORS, front="tui")
@pytest.mark.feature(Feature.DIALOG_MIRRORS_SPEED_TEST, front="tui")
def test_the_speed_test_ranks_the_mirrors_and_stops_when_the_dialog_closes(monkeypatch, updates_file):
    net = Net()

    async def test(app, pilot):
        dialog = await open_mirrors(app, pilot, net)
        assert dialog.table.keys == [A.url, B.url, C.url]
        assert table_lines(dialog)[0].split() == ["Mirror", "Country", "Protocol", "Response", "Speed", "Note"]
        assert line_of(dialog, C.url).split() == ["c.example/f", "CZ", "HTTP", "—", "—"]
        assert text(dialog, "status") == "3 mirrors. Test the speed to see which is the quickest."
        assert dialog.selected_url() == A.url and dialog.query_one("#use", Button).enabled
        await press(pilot, dialog, "test")
        [test_run] = net.tests
        assert test_run.started and dialog.query_one("#test", Button).label == "Stop"
        test_run.probe(A, probe(0.3, 1_000_000))
        test_run.probe(B, probe(0.1, 8_000_000))
        await pilot.pause()
        assert dialog.table.keys == [A.url, B.url, C.url]  # rows do not move under the cursor while it runs
        assert text(dialog, "status") == "Testing the mirrors… 2 of 3 answered"
        test_run.probe(C, probe(None, error="Connection refused"))
        test_run.done()
        await pilot.pause()
        assert dialog.table.keys == [B.url, A.url, C.url]  # the quickest first
        assert line_of(dialog, B.url).endswith("100 ms   7.6 MB/s Fastest")
        assert "Connection refused" in line_of(dialog, C.url)
        assert dialog.selected_url() == A.url  # the cursor stays with its mirror
        assert dialog.query_one("#test", Button).label == "Test speed"
        # a test that is still running stops with the dialog
        await press(pilot, dialog, "test")
        assert len(net.tests) == 2 and not net.tests[1].cancelled
        await pilot.press("escape")
        await until(pilot, lambda: isinstance(app.screen, ReposDialog))
        assert net.tests[1].cancelled
    run(monkeypatch, test, [snap(repos(updates_file))], net=net)


@pytest.mark.feature(Feature.DIALOG_MIRRORS_PIN, front="tui")
@pytest.mark.feature(Feature.DIALOG_MIRRORS_APPLY_IN_PLACE, front="tui")
@pytest.mark.feature(Feature.DIALOG_MIRRORS_IN_USE, front="tui")
def test_use_selected_mirror_asks_about_plain_http_and_shows_the_new_state_in_place(monkeypatch, helper,
                                                                                     updates_file):
    net = Net()

    async def test(app, pilot):
        dialog = await open_mirrors(app, pilot, net)
        repos_dialog = app.screen_stack[-2]
        assert not dialog.query_one("#automatic", Button).enabled
        assert text(dialog, "why") == "Automatic: The repository takes its mirrors from the list already."
        dialog.table.select_key(C.url)
        await pilot.pause()
        await pilot.press("enter")  # Enter on a row: Use selected mirror
        await pilot.pause()
        question = app.screen
        assert isinstance(question, QuestionDialog) and question.question.title == "Use this mirror?"
        assert question.question.informative == "It is not reached over https."
        await pilot.press("escape")  # Cancel: nothing applied
        await pilot.pause()
        assert app.screen is dialog and helper() == []
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("enter")  # Use This Mirror is focused
        await finish(app, pilot, MirrorsDialog)
        assert helper() == [{"op": "mirrors", "pin": {"repo": "updates", "baseurl": C.url}}]
        # the reload: the dialog, still open, shows the mirror in use, bold, and says what happened
        await until(pilot, lambda: dialog.lines[C.url].current)
        assert app.screen is dialog
        assert text(dialog, "status") == "The repository now downloads from c.example/f."
        assert "In use" in line_of(dialog, C.url) and "c.example/f" in bold_texts(dialog, C.url)
        assert dialog.query_one("#automatic", Button).enabled
        # the Repositories under it shows the new state too
        await until(pilot, lambda: "c.example" in line_of(repos_dialog, "updates"))
    run(monkeypatch, test, [snap(repos(updates_file)), snap(repos(updates_file, pinned=C.url))], net=net)


@pytest.mark.feature(Feature.DIALOG_MIRRORS_AUTOMATIC, front="tui")
def test_automatic_lets_dnf_choose_again(monkeypatch, helper, updates_file):
    net = Net()

    async def test(app, pilot):
        dialog = await open_mirrors(app, pilot, net)
        assert dialog.lines[B.url].note == "In use" and "b.example/f" in bold_texts(dialog, B.url)
        await press(pilot, dialog, "automatic")
        await finish(app, pilot, MirrorsDialog)
        assert helper() == [{"op": "mirrors", "pin": {"repo": "updates", "baseurl": None}}]
        await until(pilot, lambda: not dialog.lines[B.url].current)
        assert text(dialog, "status") == "The repository takes its mirrors from the list again."
        assert not dialog.query_one("#automatic", Button).enabled
    run(monkeypatch, test, [snap(repos(updates_file, pinned=B.url)), snap(repos(updates_file))], net=net)


@pytest.mark.feature(Feature.DIALOG_MIRRORS_FASTEST, front="tui")
def test_the_fastest_mirror_switch_is_dnf_s_option(monkeypatch, helper, updates_file):
    net = Net()

    async def test(app, pilot):
        dialog = await open_mirrors(app, pilot, net)
        box = dialog.query_one("#fastest", CheckBox)
        assert not box.value and box.label == "Fastest mirror for every repository"
        assert text(dialog, "fastest-text") == "dnf uses the first mirrors of a list that answer, for every " \
                                               "repository."
        box.focus()
        await pilot.press("space")
        await finish(app, pilot, MirrorsDialog)
        assert helper() == [{"op": "mirrors", "fastestmirror": True}]
        await until(pilot, lambda: dialog.mirrors.fastestmirror)
        assert box.value and text(dialog, "fastest-text").startswith("dnf tests the mirrors of a list itself")
    found = repos(updates_file)
    run(monkeypatch, test, [snap(found), snap(found, fastest=True)], net=net)
