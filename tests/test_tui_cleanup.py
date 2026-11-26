"""The terminal front end's Cleanup dialog (docs/TUI_SPEC.md §10.9, kram.tui.dialogs.cache) over a made-up cache
report and leftovers, as tests/test_cache.py tests the Qt one: the caches and cleaning them, the leftover
configuration files, Compare, Delete unused and Search all folders; and from the window, cleaning through the fake
helper.
"""
import asyncio

import pytest

pytest.importorskip("textual")
pytest.importorskip("libdnf5")  # kram.core.cache

from test_install_flow import Sync  # noqa: E402
from test_tui_progress import finish, helper, until  # noqa: E402, F401 - helper is a fixture
from test_tui_window import WIDE, loaded, use_catalog  # noqa: E402

from kram.app import cache as app_cache  # noqa: E402
from kram.app.parity import Feature  # noqa: E402
from kram.core import cache, leftovers  # noqa: E402
from kram.core.settings import store as settings  # noqa: E402
from kram.tui.app import KramApp  # noqa: E402
from kram.tui.dialogs.apply import Lines  # noqa: E402
from kram.tui.dialogs.cache import CacheDialog, DiffDialog, diff_text  # noqa: E402
from kram.tui.dialogs.progress import AUTO_CLOSE_KEY  # noqa: E402
from kram.tui.dialogs.question import QuestionDialog  # noqa: E402
from kram.tui.palette import role  # noqa: E402
from kram.tui.widgets import Button  # noqa: E402

K = leftovers.Kind
REPORT = cache.CacheReport(cache.Usage(12_000_000, 3), cache.Usage(5000, 2), None, cache.Usage(2048, 2), "offline",
                           "/var/cache/libdnf5", "/home/u/.cache/libdnf5")


@pytest.fixture
def files(tmp_path):
    """A leftover that can be compared, and two copies of files that are gone."""
    (tmp_path / "app.conf").write_text("a\nb\n")
    (tmp_path / "app.conf.rpmsave").write_text("a\nc\n")
    return leftovers.LeftoverReport([
        leftovers.Leftover(str(tmp_path / "app.conf.rpmsave"), 4, 0, K.SAVED, "app"),
        leftovers.Leftover("/etc/yum.repos.d/fedora.repo.rpmsave", 10, 0, K.ORPHAN),
        leftovers.Leftover("/etc/yum.repos.d/chrome.repo.rpmsave", 10, 0, K.ORPHAN),
    ], 3)


def run_alone(monkeypatch, test, size=WIDE):
    """`test(app, pilot)` over the window with a made-up catalog, loaded: the dialog is pushed by the test."""
    use_catalog(monkeypatch)
    app = KramApp()

    async def go():
        async with app.run_test(size=size) as pilot:
            await loaded(app, pilot)
            await test(app, pilot)
    asyncio.run(go())


async def show(app, pilot, monkeypatch, report, run_helper=None, clean=None) -> CacheDialog:
    monkeypatch.setattr(app_cache, "measure", lambda: REPORT)
    monkeypatch.setattr(app_cache, "scan_leftovers", lambda: report)
    dialog = CacheDialog(Sync(), clean or (lambda target, done: None), app.ui, run_helper=run_helper)
    app.push_screen(dialog)
    await until(pilot, lambda: dialog.is_mounted and bool(dialog.query("#delete-unused")))
    await pilot.pause()
    return dialog


def text(dialog, name: str) -> str:
    widget = dialog.query_one(f"#{name}", Lines)
    return widget.render().plain if widget.display else ""


def table_lines(table) -> list[str]:
    return [table.render_line(y).text.rstrip() for y in range(len(table.keys) + 1)]


@pytest.mark.feature(Feature.DIALOG_CLEANUP, front="tui")
@pytest.mark.feature(Feature.DIALOG_CLEANUP_CACHES, front="tui")
def test_the_caches_with_their_sizes_and_their_buttons(monkeypatch, files):
    cleaned = []

    async def test(app, pilot):
        dialog = await show(app, pilot, monkeypatch, files, run_helper=lambda *a: None,
                            clean=lambda target, done: cleaned.append(target))
        assert dialog.query_one("#cleanup-box").border_title == "Cleanup"
        lines = table_lines(dialog.cache_table)
        assert lines[0].split()[:3] == ["Cache", "Size", "Files"]
        assert "DNF: downloaded packages" in lines[1] and "11.4 MB" in lines[1] and "3 files" in lines[1]
        assert "/var/cache/libdnf5/*/packages" in lines[1]  # where, in a wide table
        assert dialog.cache_table.keys == ["dnf_packages", "dnf_metadata", "packagekit"]  # no user cache here
        assert "Left by interrupted transactions" in text(dialog, "cache-about")
        assert text(dialog, "cleanup-note").startswith(f"{app.glyphs.warning} ")  # an offline update is prepared
        clean = dialog.query_one("#clean", Button)
        assert clean.label == "Clean" and clean.enabled
        assert dialog.focused is dialog.cache_table
        dialog.action_activate()  # Enter: Clean
        await pilot.pause()
        assert cleaned == ["dnf_packages"]
        dialog.cache_table.action_move(1)  # down
        await pilot.pause()
        assert clean.label == "Download again…" and clean.enabled
        dialog.action_activate()  # asks first
        await pilot.pause()
        assert isinstance(app.screen, QuestionDialog) and app.screen.question.title == "Download metadata again"
        app.screen.action_cancel()  # Esc
        await pilot.pause()
        assert cleaned == ["dnf_packages"] and app.screen is dialog
        dialog.cache_table.action_move(1)
        await pilot.pause()
        assert not clean.enabled  # PackageKit's, while an offline update is prepared
        dialog.show_measuring()
        await pilot.pause()
        assert "…" in table_lines(dialog.cache_table)[1] and not clean.enabled
        dialog.action_close()
        await pilot.pause()
        assert len(app.screen_stack) == 1
    run_alone(monkeypatch, test)


def test_a_narrow_dialog_drops_the_location_and_the_date(monkeypatch, files):
    async def test(app, pilot):
        dialog = await show(app, pilot, monkeypatch, files, run_helper=lambda *a: None)
        assert "/var/cache" not in "".join(table_lines(dialog.cache_table))
        assert [c.id for c, _w in dialog.leftover_table.shown_columns()] == ["path", "size"]
        assert all(b.region.right <= app.size.width for b in dialog.query(Button) if b.display)
    run_alone(monkeypatch, test, size=(64, 22))


@pytest.mark.feature(Feature.DIALOG_CLEANUP_LEFTOVERS, front="tui")
@pytest.mark.feature(Feature.DIALOG_CLEANUP_COMPARE, front="tui")
def test_the_leftovers_and_compare(monkeypatch, files):
    async def test(app, pilot):
        dialog = await show(app, pilot, monkeypatch, files, run_helper=lambda *a: None)
        assert text(dialog, "leftovers-status") == \
            "3 files found. 3 folders only root can read were not searched."
        lines = table_lines(dialog.leftover_table)
        assert len(lines) == 4 and "fedora.repo.rpmsave" in lines[2] and "10 B" in lines[2]
        assert "Your earlier version, put aside by app." in text(dialog, "leftover-about")
        assert dialog.query_one("#compare", Button).enabled and dialog.query_one("#search-root").display
        dialog.leftover_table.focus()
        await pilot.pause()
        dialog.action_activate()  # Enter: Compare
        await pilot.pause()
        diff = app.screen
        assert isinstance(diff, DiffDialog)
        shown = diff.query_one("#diff", Lines).render()
        assert "-b" in shown.plain.splitlines() and "+c" in shown.plain.splitlines()
        assert "lines with “+” only in" in diff.query_one("#diff-note", Lines).render().plain
        diff.action_close()  # Esc
        await pilot.pause()
        assert app.screen is dialog
        dialog.leftover_table.action_move(1)  # a copy of a file that is gone: nothing to compare it with
        await pilot.pause()
        assert not dialog.query_one("#compare", Button).enabled
        assert "There is no current file to compare it with." in text(dialog, "leftover-about")
    run_alone(monkeypatch, test)


def test_the_diff_s_lines_in_their_roles(monkeypatch):
    async def test(app, pilot):
        shown = diff_text("--- a\n+++ b\n@@ -1 +1 @@\n-old\n+new\n same")
        styles = {shown.plain[s.start:s.end]: s.style for s in shown.spans}
        assert styles["-old"] == role("danger") and styles["+new"] == role("ok") and styles["--- a"].bold
        assert role("danger") != role("ok") and not styles.get(" same")
    run_alone(monkeypatch, test)


@pytest.mark.feature(Feature.DIALOG_CLEANUP_DELETE_UNUSED, front="tui")
def test_delete_unused_asks_then_runs_the_helper(monkeypatch, files):
    requests = []

    async def test(app, pilot):
        dialog = await show(app, pilot, monkeypatch, files,
                            run_helper=lambda r, t, done: (requests.append(r), done({"ok": True})))
        button = dialog.query_one("#delete-unused", Button)
        assert button.enabled
        button.action_press()
        await until(pilot, lambda: isinstance(app.screen, QuestionDialog))
        assert app.screen.question.text == "Delete 2 files?"
        app.screen.action_cancel()  # Esc: Cancel
        await until(pilot, lambda: app.screen is dialog)
        assert requests == []
        button.action_press()
        await until(pilot, lambda: isinstance(app.screen, QuestionDialog))
        question = app.screen
        next(b for b, answer in question._answers.items() if answer == "delete").action_press()
        await pilot.pause()
        await pilot.pause()
        assert requests == [{"op": "remove_leftovers", "paths": ["/etc/yum.repos.d/fedora.repo.rpmsave",
                                                                 "/etc/yum.repos.d/chrome.repo.rpmsave"]}]
        assert len(dialog.leftover_table.keys) == 1 and not button.enabled
        assert text(dialog, "leftovers-status").startswith("1 file found.")
    run_alone(monkeypatch, test)


@pytest.mark.feature(Feature.DIALOG_CLEANUP_SEARCH_ALL, front="tui")
def test_search_all_folders_runs_as_root_and_replaces_the_list(monkeypatch, files):
    found = [{"path": "/etc/firewalld/firewalld.conf.rpmnew", "size": 1, "mtime": 0, "current": True}]
    requests = []

    async def test(app, pilot):
        monkeypatch.setattr(leftovers, "file_owners", lambda paths: {p: "firewalld" for p in paths})
        dialog = await show(app, pilot, monkeypatch, files, run_helper=lambda r, t, done: (
            requests.append((r, t)), done({"ok": True, "files": found, "unreadable": 0})))
        dialog.query_one("#search-root", Button).action_press()
        await pilot.pause()
        assert requests == [({"op": "find_leftovers"}, "Searching for leftover files")]
        assert [f.path for f in dialog.leftovers.files] == ["/etc/firewalld/firewalld.conf.rpmnew"]
        assert "/etc/firewalld/firewalld.conf.rpmnew" in table_lines(dialog.leftover_table)[1]
        assert not dialog.query_one("#search-root").display and text(dialog, "leftovers-status") == "1 file found."
    run_alone(monkeypatch, test)


def test_without_a_helper_nothing_needs_root(monkeypatch, files):
    async def test(app, pilot):
        dialog = await show(app, pilot, monkeypatch, leftovers.LeftoverReport([], 0))
        assert text(dialog, "leftovers-status") == "Nothing found."
        assert not dialog.query_one("#search-root").display
        assert not dialog.query_one("#delete-unused", Button).enabled
        assert not dialog.query_one("#compare", Button).enabled and not text(dialog, "leftover-about")
    run_alone(monkeypatch, test)


def test_cleanup_from_the_menu_cleans_through_the_helper(monkeypatch, helper, files):  # noqa: F811
    settings.set(AUTO_CLOSE_KEY, False)
    monkeypatch.setattr(app_cache, "measure", lambda: REPORT)
    monkeypatch.setattr(app_cache, "scan_leftovers", lambda: files)
    use_catalog(monkeypatch)
    app = KramApp()

    async def go():
        async with app.run_test(size=WIDE) as pilot:
            await loaded(app, pilot)
            app.main.run_action("cache")
            await until(pilot, lambda: isinstance(app.screen, CacheDialog)
                        and any(b.enabled for b in app.screen.query("#clean").results(Button)))
            dialog = app.screen
            dialog.action_activate()  # Enter: Clean
            await finish_over(app, pilot, dialog)
            assert helper() == ["clean_cache"]
            await until(pilot, lambda: dialog.query_one("#clean", Button).enabled)  # counted again
            app.main.browser.helper.stop()
    asyncio.run(go())


async def finish_over(app, pilot, dialog) -> None:
    """The progress dialog of a request run from `dialog`, closed: the dialog stays."""
    from kram.tui.dialogs.progress import ProgressDialog
    await until(pilot, lambda: isinstance(app.screen, ProgressDialog) and app.screen.finished is not None)
    app.screen.close()  # Enter
    await until(pilot, lambda: app.screen is dialog)
