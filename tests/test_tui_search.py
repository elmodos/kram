"""The terminal front end's search dialog over a made-up catalog (docs/TUI_SPEC.md §7.6): opening it, filtering
while typing, the modes and their compact strip, keeping a search with Enter, putting the list back with Esc, the
earlier searches, and Provides / File, which dnf answers on Enter.

Run with Textual's headless driver (`App.run_test`, `Pilot`), as tests/test_tui_window.py. Skipped without Textual.
"""
import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("textual")

from test_tui_window import WIDE, loaded, snapshot, top  # noqa: E402
from textual.widgets import Input  # noqa: E402

from kram.app.browser import Browser  # noqa: E402
from kram.app.parity import Feature  # noqa: E402
from kram.app.search import DEBOUNCE_MS, HISTORY_IDLE_MS  # noqa: E402
from kram.core.search import Mode, SearchIndex  # noqa: E402
from kram.tui import window as window_module  # noqa: E402
from kram.tui.app import KramApp  # noqa: E402
from kram.tui.search import History, ModeStrip, SearchDialog  # noqa: E402

NARROW = (64, 22)
TYPED = DEBOUNCE_MS / 1000 + 0.15  # long enough for the controller's debounce to search


def use_catalog(monkeypatch, lookups: list | None = None):
    """The window's Browser over the made-up catalog of test_tui_window, with Provides and File lookups that note
    what they were asked and answer two packages, as tests/test_browser.py fakes the catalog."""
    snap = snapshot()

    def lookup(kind):
        def run(text):
            if lookups is not None:
                lookups.append((kind, text))
            return [("pkg0005", "x86_64"), ("pkg0007", "x86_64")]
        return run
    catalog = SimpleNamespace(load=lambda *a, **k: snap, blocked_upgrades=lambda: {},
                              details=lambda key: (_ for _ in ()).throw(LookupError(key)),
                              search_provides=lookup("provides"), search_files=lookup("file"),
                              capabilities_ready=True)
    monkeypatch.setattr(window_module, "Browser",
                        lambda view, ui, scheduler, details, post, **kw: Browser(view, ui, scheduler, details, post,
                                                                                 catalog=catalog, **kw))
    return snap


def run(test, size=WIDE):
    app = KramApp()

    async def go():
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            await loaded(app, pilot)
            await test(app, pilot)
    asyncio.run(go())
    return app


def dialog(app) -> SearchDialog:
    assert isinstance(app.screen, SearchDialog)
    return app.screen


def field(app) -> Input:
    return dialog(app).query_one("#search-text", Input)


def status(app) -> str:
    return str(dialog(app).query_one("#search-status").render())


def strip(app) -> str:
    return dialog(app).query_one(ModeStrip).render().plain


def names(app) -> list[str]:
    packages = app.main.browser.packages
    return [packages.row(p).name for p in range(len(packages))]


async def until(pilot, ready, seconds: float = 3.0) -> None:
    for _ in range(int(seconds / 0.02)):
        if ready():
            return
        await pilot.pause(0.02)
    assert ready()


# ---------------------------------------------------------------- opening and typing (§7.6.1, §7.6.2)

@pytest.mark.feature(Feature.SEARCH_FILTER_WHILE_TYPING, front="tui")
def test_slash_opens_the_search_and_the_list_filters_while_typing(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        b = app.main.browser
        await pilot.press("slash")
        assert app.focused is field(app) and field(app).value == ""
        box = dialog(app).query_one(".search")
        assert box.border_title == "Search"
        assert box._border_subtitle.plain == "tab what  enter search  esc close"  # no earlier searches yet
        assert status(app) == ""
        await pilot.press(*"pkg01")
        await pilot.pause(TYPED)
        assert len(b.packages) == 100 and status(app) == "Filtering as you type: 100 packages"
        assert top(app).startswith("Kram  “pkg01” in All  100")  # the top line above the dialog says so too
        # the window's keys are text in the field and off under the dialog
        for action, params in (("find", ()), ("toggle_panel", ("sidebar",)), ("quit", ())):
            assert app.check_action(action, params) is False
        await pilot.press("g", "slash", "q", "d")
        assert field(app).value == "pkg01g/qd" and isinstance(app.screen, SearchDialog)
        assert "sidebar" in app.shown_panels() and app.return_code is None
        await pilot.pause(TYPED)
        assert len(b.packages) == 0 and status(app) == "Filtering as you type: 0 packages"
        await pilot.press(*["backspace"] * 9)
        assert status(app) == ""  # at once: nothing typed, nothing to count
        await pilot.pause(TYPED)
        assert len(b.packages) == 300
    run(test)


def test_ctrl_f_opens_the_search_with_the_shown_search_in_it(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        b = app.main.browser
        b.search.set_query("pkg02", Mode.NAME_SUMMARY)
        b.apply_filter()
        app.main.select_key(("pkg0250", "x86_64"))
        await pilot.press("ctrl+f")
        assert field(app).value == "pkg02" and dialog(app).mode is Mode.NAME_SUMMARY
        assert status(app) == "Filtering as you type: 100 packages"
        await pilot.pause(TYPED)
        assert app.main.current_key() == ("pkg0250", "x86_64")  # opening it searches nothing again
    run(test)


# ---------------------------------------------------------------- the modes (§4.3, §7.6.1)

@pytest.mark.feature(Feature.SEARCH_MODES, front="tui")
def test_tab_changes_the_mode_and_the_filter_follows(monkeypatch):
    snap = use_catalog(monkeypatch)
    index = SearchIndex(snap.rows, snap.descriptions)

    async def test(app, pilot):
        b = app.main.browser
        await pilot.press("slash")
        assert strip(app) == " Name    Name + summary    Description    Provides    File "
        assert field(app).placeholder == "A part of the package name"
        await pilot.press(*"description 7")
        await pilot.pause(TYPED)
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
        current = [line.plain[s.start:s.end] for s in line.spans if s.style.reverse]
        assert current == [" Name "]
        await pilot.press("shift+tab")  # round to the last one
        assert dialog(app).mode is Mode.FILE and field(app).placeholder == "A file: /usr/bin/7z or just 7z"
    run(test)


def test_the_modes_take_the_compact_form_in_a_narrow_terminal(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        await pilot.press("slash")
        await pilot.pause()
        g = app.glyphs
        assert strip(app) == f"{g.left}  Name  {g.right}  1/5"
        await pilot.press("tab")
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
    snap = use_catalog(monkeypatch)
    index = SearchIndex(snap.rows, snap.descriptions)

    async def test(app, pilot):
        b = app.main.browser
        b.sidebar.select("status", "status:installed")
        await pilot.press("slash", *"pkg01")
        await pilot.pause(TYPED)
        assert len(b.packages) == 33  # in Installed while typing
        await pilot.press("enter")
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
        assert top(app).startswith("Kram  “pkg01” in Installed  33")
        await pilot.pause(HISTORY_IDLE_MS / 1000 + 0.2)  # remembered once, not moved again by the idle timer
        assert b.sidebar.history == [("pkg01", 0, 33)]
    run(test)


def test_enter_on_an_empty_field_drops_the_search(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        b = app.main.browser
        b.search.set_query("pkg02", Mode.NAME)
        b.apply_filter()
        await pilot.press("slash", "ctrl+u", "enter")  # ctrl+u empties the field
        await pilot.pause()
        assert not isinstance(app.screen, SearchDialog)
        assert b.search.text() == "" and len(b.packages) == 300 and b.sidebar.history == []
        assert b.sidebar.current_view == "status"
    run(test)


def test_esc_puts_back_the_filter_the_search_and_the_cursor(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        b, main = app.main.browser, app.main
        b.sidebar.select("status", "status:installed")
        b.search.set_query("pkg0", Mode.NAME_SUMMARY)
        b.apply_filter()
        b.search.stop_history()
        main.sort(1, True)  # the ranked results sorted by a column
        main.select_key(("pkg0045", "x86_64"))
        before = (names(app), main.list.scroll_offset.y, main.list.sort_shown)
        await pilot.press("slash", "ctrl+u", *"pkg01", "tab")
        await pilot.pause(TYPED)
        assert len(b.packages) == 33 and b.search.mode() is Mode.DESCRIPTION
        await pilot.pause(HISTORY_IDLE_MS / 1000 + 0.2)  # left alone: still not in the history
        assert b.sidebar.history == []
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, SearchDialog) and app.focused is main.list
        assert (b.search.text(), b.search.mode()) == ("pkg0", Mode.NAME_SUMMARY)
        assert b.filter.id == "status:installed" and b.sidebar.current_view == "status"
        assert (names(app), main.list.scroll_offset.y, main.list.sort_shown) == before
        assert main.current_key() == ("pkg0045", "x86_64") and b.sidebar.history == []
        await pilot.pause(HISTORY_IDLE_MS / 1000 + 0.2)
        assert b.sidebar.history == []
    run(test)


def test_esc_right_after_typing_searches_nothing_later(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        b = app.main.browser
        app.main.select_key(("pkg0123", "x86_64"))
        await pilot.press("slash", "x", "escape")  # before the debounce searched
        await pilot.pause(TYPED)
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
        await pilot.press("slash")
        history = dialog(app).query_one(History)
        assert history.display and history.option_count == 2 and history.highlighted is None
        assert str(history.get_option_at_index(0).prompt) == "“pkg02” — name   100"
        assert dialog(app).query_one(".search")._border_subtitle.plain == \
            f"tab what  {app.glyphs.down} earlier  enter search  esc close"
        await pilot.press("down")
        assert app.focused is history and history.highlighted == 0
        await pilot.press("up")  # from the first one back to the field
        assert app.focused is field(app) and history.highlighted is None
        await pilot.press("down", "down")
        assert history.highlighted == 1
        await pilot.press("enter")
        await pilot.pause()
        assert not isinstance(app.screen, SearchDialog)
        assert (b.search.text(), b.search.mode()) == ("pkg01", Mode.NAME_SUMMARY)
        assert b.sidebar.current_entry_id == "status:all" and len(b.packages) == 100
        assert [h[:2] for h in b.sidebar.history] == [("pkg01", 1), ("pkg02", 0)]
        assert app.focused is app.main.list
    run(test)


def test_the_search_mode_and_history_are_the_guis_settings(monkeypatch):
    """No settings of its own: Browser.save_settings keeps what the dialog left, as for the GUIs (§7.6.4)."""
    use_catalog(monkeypatch)
    from kram.core.settings import store as settings

    async def test(app, pilot):
        await pilot.press("slash", "tab", *"pkg01", "enter")
        await pilot.pause()
        app.main.browser.save_settings()
        assert settings.get("search/mode", 0) == int(Mode.NAME_SUMMARY)
        assert '"pkg01", 1, 100' in settings.get("search/history", "")
    run(test)


# ---------------------------------------------------------------- Provides and File (§7.6.2)

@pytest.mark.parametrize("tabs, mode, kind", [(3, Mode.PROVIDES, "provides"), (4, Mode.FILE, "file")])
def test_provides_and_file_ask_dnf_only_on_enter(monkeypatch, tabs, mode, kind):
    lookups = []
    use_catalog(monkeypatch, lookups)

    async def test(app, pilot):
        b = app.main.browser
        await pilot.press("slash", *["tab"] * tabs)
        assert dialog(app).mode is mode and status(app) == ""
        await pilot.press(*"libfoo")
        await pilot.pause(TYPED)
        assert status(app) == "dnf looks this up when you press Enter"
        assert lookups == [] and len(b.packages) == 300  # nothing asked, nothing filtered while typing
        await pilot.press("enter")
        await until(pilot, lambda: len(b.packages) == 2)
        assert lookups == [(kind, "libfoo")]
        assert names(app) == ["pkg0005", "pkg0007"] and app.focused is app.main.list
        assert b.sidebar.current_view == "status" and b.sidebar.current_entry_id == "status:all"
        await until(pilot, lambda: b.sidebar.history == [("libfoo", int(mode), 2)])
    run(test)


def test_a_name_mode_after_provides_filters_again(monkeypatch):
    lookups = []
    use_catalog(monkeypatch, lookups)

    async def test(app, pilot):
        b = app.main.browser
        await pilot.press("slash", *"pkg01")
        await pilot.press("tab", "tab", "tab")  # to Provides before the debounce: it must not ask dnf
        await pilot.pause(TYPED)
        assert lookups == [] and status(app) == "dnf looks this up when you press Enter"
        await pilot.press("shift+tab")
        await pilot.pause()
        assert dialog(app).mode is Mode.DESCRIPTION and len(b.packages) == 100
        assert status(app) == "Filtering as you type: 100 packages"
    run(test)


# ---------------------------------------------------------------- colours

def test_the_window_stays_in_sight_under_the_search_in_16_colours(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        assert app.ansi_color
        await pilot.press("slash")
        await pilot.pause()
        assert app.screen.styles.background.a == 0
    run(test)
