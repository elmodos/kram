"""The terminal front end's search dialog over a made-up catalog (docs/TUI_SPEC.md §7.6): opening it, filtering
while typing, the modes and their compact strip, keeping a search with Enter, putting the list back with Esc, the
earlier searches, and Provides / File, which dnf answers on Enter.

The dialog is worked through its API (the field's value, `action_mode`, `submit`, `action_close`) and the search's
debounce and history timers through the test's clock (tests/tui_kit.py, ManualClock): nothing waits for time. Keys
only where they are the point: the dialog's own (Tab, ↓ ↑), and the window's keys typed as text (§14.2).
"""
import asyncio

import pytest

pytest.importorskip("textual")

from test_tui_window import WIDE, loaded, snapshot, top  # noqa: E402
from test_tui_window import use_catalog as use_window_catalog  # noqa: E402
from textual.widgets import Input  # noqa: E402

from kram import __version__  # noqa: E402
from kram.app.parity import Feature  # noqa: E402
from kram.app.search import DEBOUNCE_MS  # noqa: E402
from kram.core.search import Mode, SearchIndex  # noqa: E402
from kram.tui.app import KramApp  # noqa: E402
from kram.tui.search import History, ModeStrip, SearchDialog, open_search  # noqa: E402

NARROW = (64, 22)


def use_catalog(monkeypatch, lookups: list | None = None):
    """The made-up catalog of test_tui_window, with Provides and File lookups that note what they were asked and
    answer two packages, as tests/test_browser.py fakes the catalog; the Browser's timers on the test's clock."""
    snap = snapshot()

    def lookup(kind):
        def run(text):
            if lookups is not None:
                lookups.append((kind, text))
            return [("pkg0005", "x86_64"), ("pkg0007", "x86_64")]
        return run
    made = use_window_catalog(monkeypatch, snap, clock=True, search_provides=lookup("provides"),
                              search_files=lookup("file"), capabilities_ready=True)
    return snap, made


def run(test, size=WIDE):
    app = KramApp()

    async def go():
        async with app.run_test(size=size) as pilot:
            await loaded(app, pilot)
            await test(app, pilot)
    asyncio.run(go())
    return app


async def opened(app, pilot) -> SearchDialog:
    open_search(app.main)
    await pilot.pause()
    return dialog(app)


def dialog(app) -> SearchDialog:
    assert isinstance(app.screen, SearchDialog)
    return app.screen


def field(app) -> Input:
    return dialog(app).query_one("#search-text", Input)


async def typed(app, pilot, text: str, clock=None) -> None:
    """`text` in the field, as typing leaves it; with `clock`: the pause in typing that lets the debounce search."""
    field(app).value = text
    await pilot.pause()
    if clock is not None:
        clock.fire(DEBOUNCE_MS)
        await pilot.pause()


def status(app) -> str:
    return str(dialog(app).query_one("#search-status").render())


def strip(app) -> str:
    return dialog(app).query_one(ModeStrip).render().plain


def names(app) -> list[str]:
    packages = app.main.browser.packages
    return [packages.row(p).name for p in range(len(packages))]


# ---------------------------------------------------------------- opening and typing (§7.6.1, §7.6.2)

@pytest.mark.feature(Feature.SEARCH_FILTER_WHILE_TYPING, front="tui")
def test_the_list_filters_once_typing_pauses_and_says_how_many(monkeypatch):
    _snap, made = use_catalog(monkeypatch)

    async def test(app, pilot):
        b, clock = app.main.browser, made.clock
        await opened(app, pilot)
        assert app.focused is field(app) and field(app).value == ""
        box = dialog(app).query_one(".search")
        assert box.border_title == "Search"
        assert box._border_subtitle.plain == "tab what  enter search  esc close"  # no earlier searches yet
        assert status(app) == ""
        await typed(app, pilot, "pkg01")
        assert len(b.packages) == 300  # typing goes on: not yet
        clock.fire(DEBOUNCE_MS)
        await pilot.pause()
        assert len(b.packages) == 100 and status(app) == "Filtering as you type: 100 packages"
        assert top(app).startswith(f"Kram TUI v{__version__}  “pkg01” in All  100")  # the top line says so too
        await typed(app, pilot, "pkg01gqd", clock)
        assert len(b.packages) == 0 and status(app) == "Filtering as you type: 0 packages"
        await typed(app, pilot, "")
        assert status(app) == ""  # at once: nothing typed, nothing to count
        clock.fire(DEBOUNCE_MS)
        await pilot.pause()
        assert len(b.packages) == 300
    run(test)


def test_slash_opens_the_search_and_the_window_s_keys_are_text_in_it(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        await pilot.press("slash")
        await pilot.pause()
        assert app.focused is field(app)
        for action, params in (("find", ()), ("toggle_panel", ("sidebar",)), ("quit", ())):
            assert app.check_action(action, params) is False
        await pilot.press("g", "slash", "q", "d")
        assert field(app).value == "g/qd" and isinstance(app.screen, SearchDialog)
        assert "sidebar" in app.shown_panels() and app.return_code is None
    run(test)


def test_ctrl_f_opens_the_search_with_the_shown_search_in_it(monkeypatch):
    _snap, made = use_catalog(monkeypatch)

    async def test(app, pilot):
        b = app.main.browser
        b.search.set_query("pkg02", Mode.NAME_SUMMARY)
        b.apply_filter()
        app.main.select_key(("pkg0250", "x86_64"))
        await pilot.press("ctrl+f")  # its other key
        await pilot.pause()
        assert field(app).value == "pkg02" and dialog(app).mode is Mode.NAME_SUMMARY
        assert status(app) == "Filtering as you type: 100 packages"
        made.clock.fire(DEBOUNCE_MS)  # opening it searches nothing again
        await pilot.pause()
        assert app.main.current_key() == ("pkg0250", "x86_64")
    run(test)


# ---------------------------------------------------------------- the modes (§4.3, §7.6.1)

@pytest.mark.feature(Feature.SEARCH_MODES, front="tui")
def test_tab_changes_the_mode_and_the_filter_follows(monkeypatch):
    snap, made = use_catalog(monkeypatch)
    index = SearchIndex(snap.rows, snap.descriptions)

    async def test(app, pilot):
        b = app.main.browser
        await opened(app, pilot)
        assert strip(app) == " Name    Name + summary    Description    Provides    File "
        assert field(app).placeholder == "A part of the package name"
        await typed(app, pilot, "description 7", made.clock)
        assert len(b.packages) == 0  # no name has these words
        await pilot.press("tab")
        assert dialog(app).mode is Mode.NAME_SUMMARY and b.search.mode() is Mode.NAME_SUMMARY
        assert len(b.packages) == 0 and field(app).placeholder == "Words of the name or the summary"
        await pilot.press("tab")  # the descriptions have them: the list follows at once
        found = index.search("description 7", Mode.DESCRIPTION)
        assert len(found) > 0 and names(app) == [snap.rows[i].name for i in found]
        assert status(app) == f"Filtering as you type: {len(found)} packages"
        assert app.focused is field(app)  # Tab changed the mode, not the focus
        await pilot.press("shift+tab", "shift+tab")
        assert dialog(app).mode is Mode.NAME and len(b.packages) == 0
        # the current mode is reversed among muted ones
        line = dialog(app).query_one(ModeStrip).render()
        assert [line.plain[s.start:s.end] for s in line.spans if s.style.reverse] == [" Name "]
        dialog(app).action_mode(-1)  # round to the last one
        assert dialog(app).mode is Mode.FILE and field(app).placeholder == "A file: /usr/bin/7z or just 7z"
    run(test)


def test_the_modes_take_the_compact_form_in_a_narrow_terminal(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        await opened(app, pilot)
        g = app.glyphs
        assert strip(app) == f"{g.left}  Name  {g.right}  1/5"
        dialog(app).action_mode(1)
        await pilot.pause()
        assert strip(app) == f"{g.left}  Name + summary  {g.right}  2/5"
        box = dialog(app).query_one(".search")
        assert box.size.width < 64 and box._border_subtitle.cell_length <= box.size.width - 4
        # a click on an arrow steps through the modes
        await pilot.click(ModeStrip, offset=(strip(app).index(g.right), 0))
        assert dialog(app).mode is Mode.DESCRIPTION
        await pilot.click(ModeStrip, offset=(0, 0))
        assert dialog(app).mode is Mode.NAME_SUMMARY
    run(test, size=NARROW)


# ---------------------------------------------------------------- Enter and Esc (§7.6.3)

def test_enter_keeps_the_search_within_the_sidebar_entry(monkeypatch):
    """As Enter in the GUIs' search field (Browser._on_search_enter): within Installed it stays within Installed,
    goes into the history, and the sidebar stays on its entry."""
    snap, made = use_catalog(monkeypatch)
    index = SearchIndex(snap.rows, snap.descriptions)

    async def test(app, pilot):
        b = app.main.browser
        b.sidebar.select("status", "status:installed")
        await opened(app, pilot)
        await typed(app, pilot, "pkg01", made.clock)
        assert len(b.packages) == 33  # in Installed while typing
        dialog(app).submit()
        await pilot.pause()
        assert not isinstance(app.screen, SearchDialog)
        assert b.sidebar.current_view == "status" and b.sidebar.current_entry_id == "status:installed"
        assert app.main.sidebar.border_title == "Status"
        assert app.main.sidebar.entries.current_id == "status:installed"
        # only installed rows, ranked (no sorted column), the search and its count in the history
        installed = [i for i, r in enumerate(snap.rows) if r.installed_evr]
        assert names(app) == [snap.rows[i].name for i in index.search("pkg01", Mode.NAME, installed)]
        assert len(b.packages) == 33 and all(row.installed_evr for row in app.main.selected_rows())
        assert app.main.list.sort_shown is None
        assert b.sidebar.history == [("pkg01", 0, 33)]
        assert app.focused is app.main.list and app.main.current_key() == ("pkg0102", "x86_64")
        assert top(app).startswith(f"Kram TUI v{__version__}  “pkg01” in Installed  33")
        made.clock.fire()  # remembered once, not moved again by the idle timer
        assert b.sidebar.history == [("pkg01", 0, 33)]
    run(test)


def test_enter_on_an_empty_field_drops_the_search(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        b = app.main.browser
        b.search.set_query("pkg02", Mode.NAME)
        b.apply_filter()
        await opened(app, pilot)
        await pilot.press("ctrl+u")  # the field's key that empties it
        await pilot.pause()
        dialog(app).submit()
        await pilot.pause()
        assert not isinstance(app.screen, SearchDialog)
        assert b.search.text() == "" and len(b.packages) == 300 and b.sidebar.history == []
        assert b.sidebar.current_view == "status"
    run(test)


def test_esc_puts_back_the_filter_the_search_and_the_cursor(monkeypatch):
    _snap, made = use_catalog(monkeypatch)

    async def test(app, pilot):
        b, main = app.main.browser, app.main
        b.sidebar.select("status", "status:installed")
        b.search.set_query("pkg0", Mode.NAME_SUMMARY)
        b.apply_filter()
        b.search.stop_history()
        main.sort(1, True)  # the ranked results sorted by a column
        main.select_key(("pkg0045", "x86_64"))
        before = (names(app), main.list.scroll_offset.y, main.list.sort_shown)
        await opened(app, pilot)
        await typed(app, pilot, "pkg01")
        dialog(app).action_mode(1)
        made.clock.fire(DEBOUNCE_MS)
        await pilot.pause()
        assert len(b.packages) == 33 and b.search.mode() is Mode.DESCRIPTION
        made.clock.fire()  # left alone: still not in the history
        assert b.sidebar.history == []
        await pilot.press("escape")  # its key
        await pilot.pause()
        assert not isinstance(app.screen, SearchDialog) and app.focused is main.list
        assert (b.search.text(), b.search.mode()) == ("pkg0", Mode.NAME_SUMMARY)
        assert b.filter.id == "status:installed" and b.sidebar.current_view == "status"
        assert (names(app), main.list.scroll_offset.y, main.list.sort_shown) == before
        assert main.current_key() == ("pkg0045", "x86_64") and b.sidebar.history == []
        made.clock.fire()
        assert b.sidebar.history == []
    run(test)


def test_esc_right_after_typing_searches_nothing_later(monkeypatch):
    _snap, made = use_catalog(monkeypatch)

    async def test(app, pilot):
        b = app.main.browser
        app.main.select_key(("pkg0123", "x86_64"))
        await opened(app, pilot)
        await typed(app, pilot, "x")
        dialog(app).action_close()  # before the debounce searched
        await pilot.pause()
        made.clock.fire()
        await pilot.pause()
        assert b.search.text() == "" and len(b.packages) == 300
        assert app.main.current_key() == ("pkg0123", "x86_64")
    run(test)


# ---------------------------------------------------------------- the earlier searches (§7.6.1, §7.6.4)

def test_down_goes_to_the_earlier_searches_and_enter_repeats_one(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        b = app.main.browser
        b.sidebar.add_search("pkg01", int(Mode.NAME_SUMMARY), 100)
        b.sidebar.add_search("pkg02", int(Mode.NAME), 100)
        await opened(app, pilot)
        history = dialog(app).query_one(History)
        assert history.display and history.option_count == 2 and history.highlighted is None
        assert str(history.get_option_at_index(0).prompt) == "“pkg02” — name   100"
        assert dialog(app).query_one(".search")._border_subtitle.plain == \
            f"tab what  {app.glyphs.down} earlier  enter search  esc close"
        await pilot.press("down")  # the dialog's keys
        assert app.focused is history and history.highlighted == 0
        await pilot.press("up")  # from the first one back to the field
        assert app.focused is field(app) and history.highlighted is None
        await pilot.press("down", "down")
        assert history.highlighted == 1
        history.action_select()
        await pilot.pause()
        assert not isinstance(app.screen, SearchDialog)
        assert (b.search.text(), b.search.mode()) == ("pkg01", Mode.NAME_SUMMARY)
        assert b.sidebar.current_entry_id == "status:all" and len(b.packages) == 100
        assert [h[:2] for h in b.sidebar.history] == [("pkg01", 1), ("pkg02", 0)]
        assert app.focused is app.main.list
    run(test)


def test_the_search_mode_and_history_are_the_guis_settings(monkeypatch):
    """No settings of its own: Browser.save_settings keeps what the dialog left, as for the GUIs (§7.6.4)."""
    _snap, made = use_catalog(monkeypatch)
    from kram.core.settings import store as settings

    async def test(app, pilot):
        await opened(app, pilot)
        dialog(app).action_mode(1)
        await typed(app, pilot, "pkg01", made.clock)
        dialog(app).submit()
        await pilot.pause()
        app.main.browser.save_settings()
        assert settings.get("search/mode", 0) == int(Mode.NAME_SUMMARY)
        assert '"pkg01", 1, 100' in settings.get("search/history", "")
    run(test)


# ---------------------------------------------------------------- Provides and File (§7.6.2)

@pytest.mark.parametrize("mode, kind", [(Mode.PROVIDES, "provides"), (Mode.FILE, "file")])
def test_provides_and_file_ask_dnf_only_on_enter(monkeypatch, mode, kind):
    lookups = []
    _snap, made = use_catalog(monkeypatch, lookups)

    async def test(app, pilot):
        b = app.main.browser
        await opened(app, pilot)
        dialog(app).choose_mode(mode)
        assert status(app) == ""
        await typed(app, pilot, "libfoo", made.clock)
        assert status(app) == "dnf looks this up when you press Enter"
        assert lookups == [] and len(b.packages) == 300  # nothing asked, nothing filtered while typing
        dialog(app).submit()
        await pilot.pause()
        assert lookups == [(kind, "libfoo")] and len(b.packages) == 2
        assert names(app) == ["pkg0005", "pkg0007"] and app.focused is app.main.list
        assert b.sidebar.current_view == "status" and b.sidebar.current_entry_id == "status:all"
        made.clock.fire()  # kept once it has been left alone a while
        assert b.sidebar.history == [("libfoo", int(mode), 2)]
    run(test)


def test_a_name_mode_after_provides_filters_again(monkeypatch):
    lookups = []
    _snap, made = use_catalog(monkeypatch, lookups)

    async def test(app, pilot):
        b = app.main.browser
        await opened(app, pilot)
        await typed(app, pilot, "pkg01")
        dialog(app).choose_mode(Mode.PROVIDES)  # before the debounce: it must not ask dnf
        made.clock.fire(DEBOUNCE_MS)
        await pilot.pause()
        assert lookups == [] and status(app) == "dnf looks this up when you press Enter"
        dialog(app).choose_mode(Mode.DESCRIPTION)
        await pilot.pause()
        assert len(b.packages) == 100 and status(app) == "Filtering as you type: 100 packages"
    run(test)


# ---------------------------------------------------------------- colours

def test_the_window_stays_in_sight_under_the_search_in_16_colours(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        assert app.ansi_color
        await opened(app, pilot)
        assert app.screen.styles.background.a == 0
    run(test)
