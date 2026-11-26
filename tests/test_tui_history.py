"""The terminal front end's Transaction History (docs/TUI_SPEC.md §10.7, kram.tui.dialogs.history), from the window
over a made-up catalog and history, as tests/test_gtk.py tests the GTK window: the transactions and their packages
as they load, the filter, Mark Changes to Undo, Enter on a package, and Package → Show in History.
"""
import asyncio

import pytest

pytest.importorskip("textual")

from test_tui_repos import until  # noqa: E402
from test_tui_window import use_catalog  # noqa: E402

from kram.app import history as history_module  # noqa: E402
from kram.app.parity import Feature  # noqa: E402
from kram.core.history import HistoryItem, HistoryTransaction, PackageState  # noqa: E402
from kram.core.marks import Action  # noqa: E402
from kram.core.model import CatalogSnapshot, Origin, PkgRow, Reason, Status  # noqa: E402
from kram.tui.dialogs.history import HistoryDialog  # noqa: E402
from kram.tui.widgets import Button  # noqa: E402

WIDE, NARROW = (140, 36), (64, 22)
TRANSACTIONS = [HistoryTransaction(3, 1795000000, 0, "dnf5 remove fish", "", True),
                HistoryTransaction(2, 1794000000, 1000, "kram", "", False),
                HistoryTransaction(1, 1793000000, 1000, "dnf5 install fish", "a comment", True)]
ITEMS = {3: (HistoryItem("fish", "x86_64", "3.9-1", "remove", Reason.USER, "@System"),),
         2: (HistoryItem("vim", "x86_64", "9.1-2", "upgrade", Reason.USER, "updates"),
             HistoryItem("vim", "x86_64", "9.1-1", "replaced", Reason.USER, "@System")),
         1: (HistoryItem("fish", "x86_64", "4.0-1", "install", Reason.USER, "fedora"),
             HistoryItem("ncurses-term", "noarch", "6.5-1", "install", Reason.DEPENDENCY, "fedora"))}


def snapshot() -> CatalogSnapshot:
    rows = [PkgRow(f"pkg{i}", "x86_64", f"Summary {i}", "", "1.0-1", "fedora", 1000, Origin.FEDORA,
                   Status.NOT_INSTALLED) for i in range(20)]
    rows += [PkgRow("fish", "x86_64", "Friendly shell", "4.0-1", "4.0-1", "fedora", 1000, Origin.FEDORA,
                    Status.INSTALLED, from_repo_id="fedora"),
             PkgRow("ncurses-term", "noarch", "Terminfo", "6.5-1", "6.5-1", "fedora", 1000, Origin.FEDORA,
                    Status.INSTALLED, from_repo_id="fedora"),
             PkgRow("vim", "x86_64", "Editor", "9.1-2", "9.1-2", "updates", 1000, Origin.FEDORA, Status.INSTALLED,
                    from_repo_id="updates")]
    return CatalogSnapshot(rows, 3, 0, 0.1, descriptions=[""] * len(rows), releasever="45")


STATES = {("fish", "x86_64"): PackageState(("4.0-1",), frozenset({"4.0-1"}), "4.0-1", Reason.USER),
          ("ncurses-term", "noarch"): PackageState(("6.5-1",), frozenset({"6.5-1"}), "6.5-1", Reason.DEPENDENCY)}


def run(monkeypatch, test, size=WIDE):
    monkeypatch.setattr(history_module, "CHUNK", 2)  # the packages load in two chunks
    run.catalog = use_catalog(monkeypatch, snapshot(), history=lambda: TRANSACTIONS,
                              history_items=lambda ids: {i: ITEMS[i] for i in ids},
                              package_states=lambda keys: {k: STATES[k] for k in keys if k in STATES},
                              removal_dependents=lambda keys: [])
    from kram.tui.app import KramApp
    app = KramApp()

    async def go():
        async with app.run_test(size=size) as pilot:
            await until(pilot, lambda: app.main.browser.snapshot is not None and app.main.browser.filter is not None)
            await pilot.pause()
            await test(app, pilot)
    asyncio.run(go())
    return app


async def open_history(app, pilot, action: str = "history") -> HistoryDialog:
    app.main.run_action(action)
    await until(pilot, lambda: isinstance(app.screen, HistoryDialog) and app.screen._ready)
    dialog = app.screen
    await until(pilot, lambda: dialog.state.endswith(("transactions", "transaction")) and "Reading" not in dialog.state)
    await pilot.pause()
    return dialog


def lines(table) -> list[str]:
    return [table.render_line(y).text.rstrip() for y in range(len(table.keys) + 1)]


def bold(table, row: int) -> list[str]:
    return [s.text.strip() for s in table.render_line(row + 1) if s.style is not None and s.style.bold
            and s.text.strip()]


def about(dialog) -> str:
    widget = dialog.query_one("#about")
    return widget.render().plain if widget.display else ""


@pytest.mark.feature(Feature.DIALOG_HISTORY, front="tui")
def test_the_transactions_load_with_their_packages(monkeypatch):
    async def test(app, pilot):
        dialog = await open_history(app, pilot)
        assert dialog.query_one("#history-box").border_title == "Transaction History"
        assert dialog.state == "3 transactions" and dialog.transaction_table.keys == [3, 2, 1]
        header, three, two, one = lines(dialog.transaction_table)
        assert header.split() == ["ID", "Date", "Changes", "User", "Command"]
        assert three.split()[0] == "3" and "1 removed" in three and "dnf5 remove fish" in three
        assert two.split()[:2] == ["!", "2"] and "1 upgraded" in two  # failed: the glyph, and words below
        assert "2 installed" in one
        # the newest is the current one, its packages under it
        assert dialog.history.current == 3 and dialog.transaction_table.has_focus
        header, fish = lines(dialog.package_table)
        assert header.split() == ["Action", "Package", "Version", "Repository", "Reason"]
        assert fish.split()[:3] == ["Remove", "fish.x86_64", "3.9-1"]
        assert about(dialog) == "dnf5 remove fish"
        dialog.transaction_table.action_move(1)  # down
        await pilot.pause()
        assert dialog.history.current == 2
        assert about(dialog) == "The transaction failed or did not finish\nkram"
        assert lines(dialog.package_table)[1].split()[:5] == ["Upgrade", "vim.x86_64", "9.1-1", "→", "9.1-2"]
        assert not dialog.query_one("#undo", Button).enabled  # a failed transaction is not undone
        dialog.transaction_table.action_move(1)
        await pilot.pause()
        assert about(dialog) == "dnf5 install fish a comment"
        assert [line.split()[:2] for line in lines(dialog.package_table)[1:]] == [["Install", "fish.x86_64"],
                                                                                   ["Install", "ncurses-term.noarch"]]
        assert dialog.query_one("#undo", Button).enabled and dialog.query_one("#undo", Button).label == \
            "Mark Changes to Undo"
    run(monkeypatch, test)


def test_a_narrow_history_drops_the_user_command_repository_and_reason(monkeypatch):
    async def test(app, pilot):
        dialog = await open_history(app, pilot)
        assert lines(dialog.transaction_table)[0].split() == ["ID", "Date", "Changes"]
        assert lines(dialog.package_table)[0].split() == ["Action", "Package", "Version"]
        assert dialog.query_one("#undo", Button).region.bottom <= dialog.query_one("#history-box").region.bottom
    run(monkeypatch, test, size=NARROW)


@pytest.mark.feature(Feature.DIALOG_HISTORY_FILTER, front="tui")
def test_the_filter_leaves_the_transactions_of_a_package(monkeypatch):
    async def test(app, pilot):
        dialog = await open_history(app, pilot)
        dialog.query_one("#history-filter").focus()
        dialog.query_one("#history-filter").value = "FISH"
        await until(pilot, lambda: dialog.state == "2 of 3 transactions")
        assert dialog.transaction_table.keys == [3, 1]
        dialog.transaction_table.select_key(1)
        await pilot.pause()
        assert bold(dialog.package_table, 0) == ["Install", "fish.x86_64", "4.0-1", "fedora", "user"]
        assert bold(dialog.package_table, 1) == []  # ncurses-term does not match
        dialog.query_one("#history-filter").value = "vim"
        await until(pilot, lambda: dialog.transaction_table.keys == [2])
        assert dialog.history.current == 2  # the current one was hidden: the first shown one instead
        dialog.query_one("#history-filter").value = "vimzzz"
        await until(pilot, lambda: dialog.transaction_table.keys == [])
        assert dialog.state == "0 of 3 transactions" and lines(dialog.package_table) == \
            [lines(dialog.package_table)[0]]
        assert not dialog.query_one("#undo", Button).enabled
    run(monkeypatch, test)


@pytest.mark.feature(Feature.DIALOG_HISTORY_UNDO, front="tui")
def test_mark_changes_to_undo_marks_them_and_closes_the_history(monkeypatch):
    async def test(app, pilot):
        dialog = await open_history(app, pilot)
        dialog.transaction_table.select_key(1)
        await pilot.pause()
        dialog.query_one("#undo", Button).action_press()
        await until(pilot, lambda: len(app.screen_stack) == 1)
        await pilot.pause()
        b = app.main.browser
        marks = {key: b.packages.marks.get(key).action for key in (("fish", "x86_64"), ("ncurses-term", "noarch"))}
        assert marks == {("fish", "x86_64"): Action.REMOVE, ("ncurses-term", "noarch"): Action.REMOVE}
        assert b.filter.id == "status:marked"  # the Marked list shows them
        assert "2 changes marked to undo transaction 1." in app.top_line.render().plain
    run(monkeypatch, test)


@pytest.mark.feature(Feature.DIALOG_HISTORY_OPEN_PACKAGE, front="tui")
def test_enter_on_a_package_closes_the_history_and_selects_it(monkeypatch):
    async def test(app, pilot):
        dialog = await open_history(app, pilot)
        dialog.transaction_table.select_key(2)
        dialog.action_activate()  # Enter: down to the packages
        await pilot.pause()
        assert dialog.focused is dialog.package_table
        dialog.action_activate()
        await until(pilot, lambda: len(app.screen_stack) == 1)
        await pilot.pause()
        assert app.main.current_key() == ("vim", "x86_64") and app.main.list.has_focus
    run(monkeypatch, test)


@pytest.mark.feature(Feature.DIALOG_HISTORY_FILTER, front="tui")
def test_show_in_history_opens_it_on_the_package(monkeypatch):
    async def test(app, pilot):
        app.main.browser.navigate(("fish", "x86_64"))
        await until(pilot, lambda: app.main.current_key() == ("fish", "x86_64"))
        await pilot.pause()
        dialog = await open_history(app, pilot, "show_in_history")
        assert dialog.query_one("#history-filter").value == "fish"
        await until(pilot, lambda: dialog.state == "2 of 3 transactions")
        assert dialog.transaction_table.keys == [3, 1]
        dialog.action_close()  # Esc
        await until(pilot, lambda: len(app.screen_stack) == 1)
        # ctrl+h opens it without a filter
        app.action_run("history")
        await until(pilot, lambda: isinstance(app.screen, HistoryDialog) and app.screen._ready)
        await until(pilot, lambda: "Reading" not in app.screen.state)
        assert app.screen.query_one("#history-filter").value == ""
    run(monkeypatch, test)


def test_a_history_closed_while_it_reads_draws_nothing_more(monkeypatch):
    """Esc while the packages still came in chunks: what came after went to the dialog's widgets, gone by then."""
    async def test(app, pilot):
        worker = run.catalog.worker
        app.main.run_action("history")
        await until(pilot, lambda: isinstance(app.screen, HistoryDialog) and app.screen._ready)
        dialog = app.screen
        worker.hold()  # the next chunk of packages waits
        dialog.history.reload()
        dialog.action_close()  # Esc
        await until(pilot, lambda: len(app.screen_stack) == 1)
        worker.release()
        await pilot.pause()
        assert app.is_running and len(app.screen_stack) == 1
    run(monkeypatch, test)
