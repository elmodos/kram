"""Snapshots of the whole screen (docs/TUI_SPEC.md §14.2, level 2): the window and its popups and dialogs as the
terminal gets them, set up through the API, compared cell by cell (text and role) with the files under
tests/snapshots/tui/, one set for each major version of Textual, which draws its own widgets a little differently.
A change in the layout, a border, a colour shows up as a diff of those files (`KRAM_UPDATE_SNAPSHOTS=1
scripts/tui_check.sh quick` rewrites both sets, to be read in the diff).
"""
import asyncio

import pytest

pytest.importorskip("textual")

from test_tui_apply import preview  # noqa: E402
from test_tui_window import loaded, snapshot, use_catalog  # noqa: E402
from tui_kit import assert_snapshot, grid, roles_of, screen_lines  # noqa: E402

from kram.app import preferences  # noqa: E402
from kram.core.marks import Action  # noqa: E402
from kram.tui.app import KramApp  # noqa: E402
from kram.tui.dialogs.apply import ApplyDialog  # noqa: E402
from kram.tui.search import open_search  # noqa: E402

SCHEMES = ("textual-ansi", "kram-turbo")


def shot(monkeypatch, name: str, size: tuple[int, int], scheme: str, setup=None) -> None:
    """The screen after `setup(app)` (an async function, or None for the window as it starts), in `scheme`,
    compared with tests/snapshots/tui/<name>-<scheme>.txt."""
    monkeypatch.setenv("LC_ALL", "C.UTF-8")
    monkeypatch.setattr("kram.tui.window.is_root", lambda: False)  # the test container runs as root
    roles = roles_of(scheme)  # before the app's loop: it runs one of its own, once
    preferences.set_value(preferences.TUI_SCHEME, scheme)  # started in it: no switch half drawn
    app = KramApp()

    async def go():
        async with app.run_test(size=size) as pilot:
            await loaded(app, pilot)
            if setup is not None:
                await setup(app, pilot)
            await pilot.pause()
            app.main.scheduler.fire()  # every timer that is due, the details' delay among them: no race with it
            await pilot.pause()
            content = grid(screen_lines(app), roles)
        assert_snapshot(f"{name}-{scheme}", content, per_textual=True)
    asyncio.run(go())


@pytest.mark.parametrize("scheme", SCHEMES)
def test_the_window(monkeypatch, scheme):
    use_catalog(monkeypatch, snapshot(60), clock=True)
    shot(monkeypatch, "window", (100, 30), scheme)


@pytest.mark.parametrize("scheme", SCHEMES)
def test_the_narrow_window_with_marks(monkeypatch, scheme):
    use_catalog(monkeypatch, snapshot(60), clock=True)

    async def setup(app, pilot):
        b = app.main.browser
        b.packages.marks.set(b.packages.row(1), Action.INSTALL)
        b.packages.marks.set(b.packages.row(3), Action.REMOVE)
        b.marker.changed.emit(None)
        app.main.list.select(2)
    shot(monkeypatch, "window-narrow", (64, 22), scheme, setup)


@pytest.mark.parametrize("scheme", SCHEMES)
def test_the_menu(monkeypatch, scheme):
    use_catalog(monkeypatch, snapshot(60), clock=True)

    async def setup(app, pilot):
        app.action_menu()
        await pilot.pause()
        app.screen.show_menu(2)  # Package
    shot(monkeypatch, "menu", (100, 30), scheme, setup)


@pytest.mark.parametrize("scheme", SCHEMES)
def test_the_search(monkeypatch, scheme):
    use_catalog(monkeypatch, snapshot(60), clock=True)

    async def setup(app, pilot):
        app.main.browser.sidebar.add_search("pkg01", 0, 10)
        open_search(app.main)
    shot(monkeypatch, "search", (100, 30), scheme, setup)


@pytest.mark.parametrize("scheme", SCHEMES)
def test_the_apply_dialog(monkeypatch, scheme):
    use_catalog(monkeypatch, snapshot(60), clock=True)

    async def setup(app, pilot):
        app.push_screen(ApplyDialog(preview(), {"op": "transaction", "install": ["virt-manager"]}, "x86_64", None))
    shot(monkeypatch, "apply", (100, 30), scheme, setup)
