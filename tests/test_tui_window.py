"""The terminal front end's window over a made-up catalog (docs/TUI_SPEC.md §5.4, §7.1, §7.3): the package list,
its columns, scrolling, selection, sorting and empty list, and the top line.

Run with Textual's headless driver (`App.run_test`, `Pilot`): no terminal needed. Skipped without Textual.
"""
import asyncio
import threading
from types import SimpleNamespace

import pytest

pytest.importorskip("textual")

from textual.widgets import OptionList  # noqa: E402
from tui_kit import InlineWorker, ManualClock  # noqa: E402

from kram import __version__  # noqa: E402
from kram.app import preferences, release_watch  # noqa: E402
from kram.app.browser import Browser  # noqa: E402
from kram.app.columns import COL_ADVISORY, COL_DOWNLOAD, COL_NAME, COL_REASON, COL_SIZE, COL_SUMMARY  # noqa: E402
from kram.app.parity import Feature  # noqa: E402
from kram.core.marks import Action  # noqa: E402
from kram.core.model import (  # noqa: E402
    Advisory,
    CatalogSnapshot,
    Origin,
    PkgRow,
    RepoInfo,
    Status,
    VersionLock,
)
from kram.core.search import Mode  # noqa: E402
from kram.tui import window as window_module  # noqa: E402
from kram.tui.app import KramApp  # noqa: E402
from kram.tui.package_list import Columns, name_lengths, name_width  # noqa: E402
from kram.tui.palette import role  # noqa: E402
from kram.tui.widgets import ChoiceList  # noqa: E402

WIDE, NARROW = (120, 40), (80, 24)
DAY = 86400


def rows(n: int = 300) -> list[PkgRow]:
    return [PkgRow(f"pkg{i:04d}", "x86_64", f"Summary {i}", "1.0-1" if i % 3 == 0 else "", "1.0-1", "fedora",
                   1000 * i, Origin.FEDORA, Status.INSTALLED if i % 3 == 0 else Status.NOT_INSTALLED)
            for i in range(n)]


def snapshot(n: int = 300, **kw) -> CatalogSnapshot:
    found = rows(n)
    return CatalogSnapshot(found, sum(1 for r in found if r.installed_evr), 0, 0.1,
                           descriptions=[f"Description {i}" for i in range(n)], **kw)


def use_catalog(monkeypatch, snap: CatalogSnapshot | None = None, load=None, blocked=None, threaded: bool = False,
                clock: bool = False, **more) -> SimpleNamespace:
    """The window's Browser over a made-up catalog, as tests/test_gtk.py does it; `more`: what else the catalog
    answers (`resolve` for the Apply dialog, …). Its libdnf5 jobs run on the app's thread (tests/tui_kit.py,
    InlineWorker), unless `threaded`: a job that waits for the test (a held lock, a slow load) needs the real
    worker. `clock`: the Browser's timers (the search's debounce and history) go off when the test says so
    (tests/tui_kit.py, ManualClock). The returned namespace has the inline worker and the clock once the window has
    made them."""
    snap = snap or snapshot()
    # a Reload does not ask Bodhi whether a new release is out (tests/test_tui_dialogs.py puts the check back)
    monkeypatch.setattr(release_watch.ReleaseWatcher, "check", lambda self: None)
    catalog = SimpleNamespace(load=load or (lambda *a, **k: snap), blocked_upgrades=lambda: blocked or {},
                              details=lambda key: (_ for _ in ()).throw(LookupError(key)), **more)
    made = SimpleNamespace(worker=None, clock=None)

    def browser(view, ui, scheduler, details, post, **kw):
        if clock:
            made.clock = scheduler = ManualClock(post)
        if not threaded:
            made.worker = kw["dnf"] = InlineWorker(post)
        return Browser(view, ui, scheduler, details, post, catalog=catalog, **kw)
    monkeypatch.setattr(window_module, "Browser", browser)
    return made


async def loaded(app, pilot) -> None:
    for _ in range(100):
        if app.main.browser.snapshot is not None and app.main.browser.filter is not None:
            break
        await pilot.pause(0.01)
    await pilot.pause()


def run(test, size=WIDE, load=True):
    app = KramApp()

    async def go():
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            if load:
                await loaded(app, pilot)
            await test(app, pilot)
    asyncio.run(go())
    return app


def lines(app, n: int | None = None) -> list[str]:
    table = app.main.list
    return [table.render_line(y).text for y in range(n or table.scrollable_content_region.height)]


def top(app) -> str:
    return app.top_line.render().plain


# ---------------------------------------------------------------- the catalog (§7.1)

def test_the_catalog_shows_with_the_first_row_selected(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        b = app.main.browser
        assert len(b.packages) == 300 and app.main.current_key() == ("pkg0000", "x86_64")
        assert [r.name for r in app.main.selected_rows()] == ["pkg0000"]
        assert top(app).startswith(f"Kram TUI v{__version__}  All  300")
        header, first = lines(app, 2)
        assert header.split() == ["S", "Package", app.glyphs.up, "Installed", "Latest", "Repository", "Size",
                                  "Summary"]
        assert "pkg0000" in first and "Summary 0" in first
        assert b.front_package == "kram-tui"
    run(test)


def test_loading_the_catalog_says_so_in_the_list(monkeypatch):
    go_on = threading.Event()
    snap = snapshot()

    def load(*_a, **_k):
        go_on.wait(5)
        return snap
    use_catalog(monkeypatch, load=load, threaded=True)  # the load waits for the test

    async def test(app, pilot):
        try:
            text = [line.strip() for line in lines(app)]
            assert "Loading the package catalog…" in text
            row = text.index("Loading the package catalog…")
            assert 0 < row and abs(row - len(text) // 2) <= 2  # centred
        finally:
            go_on.set()
        await loaded(app, pilot)
        assert len(app.main.browser.packages) == 300
    run(test, load=False)


def test_a_held_lock_is_waited_for_and_esc_quits(monkeypatch):
    go_on = threading.Event()

    def load(_queries, on_wait, _cancel):
        on_wait()
        go_on.wait(5)
        return snapshot()
    use_catalog(monkeypatch, load=load, threaded=True)  # the load waits for the test

    async def test(app, pilot):
        try:
            for _ in range(50):
                if app.main.waiting_for_lock:
                    break
                await pilot.pause(0.01)
            await pilot.pause()
            text = "\n".join(lines(app))
            assert "Another package manager is running: waiting" in text and "esc quit" in text
            await pilot.press("escape")
            await pilot.pause()
        finally:
            go_on.set()
    app = run(test, load=False)
    assert app.return_code == 0


# ---------------------------------------------------------------- selection (§7.3.6)

@pytest.mark.feature(Feature.LIST_MULTI_SELECT, front="tui")
def test_select_key_and_a_selection_of_several_rows(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        main = app.main
        assert main.select_key(("pkg0010", "x86_64")) and main.current_key() == ("pkg0010", "x86_64")
        assert not main.select_key(("nothing", "x86_64"))
        await pilot.press("shift+down", "shift+down")
        assert [r.name for r in main.selected_rows()] == ["pkg0010", "pkg0011", "pkg0012"]
        table = main.list
        y = 10 - table.scroll_offset.y + 1
        margins = [table.render_line(y + i).text[0] for i in range(-1, 4)]
        assert margins == [" ", "▌", "▌", "▌", " "] or margins == [" ", "|", "|", "|", " "]
        await pilot.press("y")  # copies every selected row
        assert app.clipboard == "pkg0010 pkg0011 pkg0012"
        await pilot.press("Y")
        assert app.clipboard == "pkg0010-1.0-1.x86_64 pkg0011-1.0-1.x86_64 pkg0012-1.0-1.x86_64"
        await pilot.press("shift+up", "shift+up", "shift+up")  # past the start: the other way
        assert [r.name for r in main.selected_rows()] == ["pkg0009", "pkg0010"]
        await pilot.press("escape")
        assert [r.name for r in main.selected_rows()] == ["pkg0009"] and app.focused is table
        await pilot.press("shift+pagedown")
        assert len(main.selected_rows()) == table.rows_shown
        await pilot.press("down")  # a plain move drops the selection
        assert len(main.selected_rows()) == 1
    run(test)


def test_enter_focuses_the_details_and_alt_left_goes_back(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        b = app.main.browser
        b.navigate(("pkg0042", "x86_64"))
        assert app.main.current_key() == ("pkg0042", "x86_64")
        await pilot.press("alt+left")
        assert app.main.current_key() == ("pkg0000", "x86_64")
        await pilot.press("d", "d")  # the details unpinned
        await pilot.press("enter")
        assert app.has_focus_in("details") and "details" in app.shown_panels()
    run(test)


# ---------------------------------------------------------------- columns and scrolling (§7.3.2, §7.3.3)

def test_the_summary_takes_the_room_left(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        table = app.main.list
        summary = dict(table.columns)[COL_SUMMARY]
        assert table.total_width == table.scrollable_content_region.width  # no sideways scrolling for it
        assert table.virtual_size.width <= table.scrollable_content_region.width and not table.frozen
        await pilot.resize_terminal(180, 40)
        await pilot.pause()
        assert dict(table.columns)[COL_SUMMARY] == summary + 30
    run(test, (150, 40))


def test_columns_that_do_not_fit_scroll_sideways_with_status_and_name_in_place(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        table = app.main.list
        table.set_columns(Columns(hidden=set()))  # every column: they do not fit 80 columns
        await pilot.pause()
        assert table.total_width > table.scrollable_content_region.width and table.frozen == 1 + 3 + 13
        before = lines(app, 3)
        await pilot.press("right")
        await pilot.pause()
        after = lines(app, 3)
        assert table.scroll_offset.x == 8
        frozen = table.frozen
        for old, new in zip(before, after, strict=True):
            assert new[:frozen] == old[:frozen] and new[frozen:-8] == old[frozen + 8:]
        await pilot.press("end")
        await pilot.press("left", "left")
        assert table.scroll_offset.x == 0
        assert table.show_horizontal_scrollbar
        table.set_columns(Columns())
        await pilot.resize_terminal(150, 40)  # the default columns fit
        await pilot.pause()
        assert not table.show_horizontal_scrollbar and not table.frozen
    run(test, NARROW)


def long_names() -> CatalogSnapshot:
    snap = snapshot()
    for r in snap.rows:
        r.name = f"{r.name}-with-a-name-far-longer-than-the-list-has-room-for"  # 63 characters
    return snap


def test_long_names_give_way_to_the_other_columns_in_a_wide_list(monkeypatch):
    use_catalog(monkeypatch, long_names())

    async def test(app, pilot):
        table = app.main.list
        widths = dict(table.columns)
        assert widths[COL_NAME] < 48 and widths[COL_SUMMARY] >= 20
        assert table.total_width == table.scrollable_content_region.width and not table.show_horizontal_scrollbar
        assert "Summary 0" in lines(app, 2)[1]
        app.action_toggle_panel("sidebar")  # g, g: focused, then hidden and unpinned
        await pilot.pause()
        app.action_toggle_panel("sidebar")
        await pilot.pause()  # the list is wider, the name gets the room
        assert dict(table.columns)[COL_NAME] == min(48, widths[COL_NAME] + 28 + 2)
        assert not table.show_horizontal_scrollbar
        app.action_toggle_panel("sidebar")
        await pilot.pause()
        assert dict(table.columns)[COL_NAME] == widths[COL_NAME]
        app.main.browser.sidebar.select("status", "status:installed")  # a filter change lays them out again
        await pilot.pause()
        assert dict(table.columns)[COL_NAME] == widths[COL_NAME] and not table.show_horizontal_scrollbar
    run(test, (140, 36))


def test_long_names_leave_status_and_name_in_place_in_a_narrow_list(monkeypatch):
    use_catalog(monkeypatch, long_names())

    async def test(app, pilot):
        table = app.main.list
        width = table.scrollable_content_region.width
        assert table.total_width > width and table.frozen and 2 * table.frozen <= width
        assert dict(table.columns)[COL_NAME] > 12  # what room half the list leaves it
        before = lines(app, 2)
        await pilot.press("right")
        await pilot.pause()
        frozen = table.frozen
        after = lines(app, 2)
        assert [line[:frozen] for line in after] == [line[:frozen] for line in before]
        assert "Installed" not in before[0][:frozen] and after[0][frozen:] != before[0][frozen:]
    run(test, (64, 22))


def test_the_name_column_fits_most_names():
    found = rows(100)
    for i in range(3):
        found[i].name = "x" * 80  # a few very long names push nothing away
    assert name_width(name_lengths(found, "x86_64"), list(range(100))) == 12
    found[5].arch = "i686"  # cell_text adds the arch: pkg0005.i686
    for r in found[10:]:
        r.name = "n" * 20
    assert name_lengths(found, "x86_64")[5] == 12
    assert name_width(name_lengths(found, "x86_64"), list(range(100))) == 20
    assert name_width(name_lengths(found, "x86_64"), list(range(5))) == 48  # never wider
    assert name_width([], []) == 12
    assert Columns().shown()[:2] == [0, COL_NAME]
    hidden = Columns().hidden
    assert hidden == {COL_REASON, COL_ADVISORY, COL_DOWNLOAD}


# ---------------------------------------------------------------- centre scrolling (§7.3.6, T11)

def test_centre_scrolling_on_and_off(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        table = app.main.list
        for _ in range(30):  # step by step, as ↓ does
            table.action_move(1)
        half = table.rows_shown // 2
        assert table.cursor == 30 and table.scroll_offset.y == 30 - half
        await pilot.press("home")  # the keys to the ends
        assert table.scroll_offset.y == 0
        await pilot.press("end")
        assert table.cursor == 299 and table.scroll_offset.y == 300 - table.rows_shown
        preferences.set_value(preferences.TUI_CENTRE_SCROLLING, False)
        table.action_jump(0)
        for _ in range(30):
            table.action_move(1)
        assert table.scroll_offset.y == 30 - table.rows_shown + 1  # the cursor at the bottom
        table.action_move(-1)
        assert table.scroll_offset.y == 30 - table.rows_shown + 1  # the list stays
    run(test)


def test_the_cursor_stays_above_the_details_slide_over(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        table = app.main.list
        await pilot.press("end")
        await pilot.press("d")
        await pilot.pause()
        await pilot.pause()
        inset = table.bottom_inset
        assert inset == app.slide_height() - 1 > 0
        line = table.cursor - table.scroll_offset.y + 1  # the header is line 0
        details_top = app.panel("details").region.y
        assert table.region.y + line < details_top
        await pilot.press("escape")  # the slide-over closes: the list has its lines back
        assert table.bottom_inset == 0
        preferences.set_value(preferences.TUI_CENTRE_SCROLLING, False)
        await pilot.press("d")
        await pilot.pause()
        await pilot.pause()
        line = table.cursor - table.scroll_offset.y + 1
        assert table.region.y + line < app.panel("details").region.y
    run(test, NARROW)


# ---------------------------------------------------------------- sorting (§7.3.7)

@pytest.mark.feature(Feature.LIST_SORT, front="tui")
def test_s_sorts_by_a_column_and_S_reverses(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        b, table, g = app.main.browser, app.main.list, app.glyphs
        assert lines(app, 1)[0].split()[:3] == ["S", "Package", g.up]
        await pilot.press("s")
        await pilot.pause()
        assert isinstance(app.screen, ChoiceList) and app.screen.current == COL_NAME
        choices = app.screen.query_one(OptionList)
        choices.highlighted = app.screen.values.index(COL_SIZE)
        choices.action_select()
        await pilot.pause()
        assert b.user_sort == (COL_SIZE, False)
        assert f"Size {g.up}" in lines(app, 1)[0]
        await pilot.press("S")
        assert b.user_sort == (COL_SIZE, True) and f"Size {g.down}" in lines(app, 1)[0]
        assert app.main.current_key() == ("pkg0000", "x86_64")  # the cursor stays on its row
        await pilot.press("home")
        assert app.main.current_key() == ("pkg0299", "x86_64")
        # a search keeps its ranked order until a sort is chosen
        b.search.set_query("pkg01", Mode.NAME)
        b.apply_filter()
        await pilot.pause()
        assert table.sort_shown is None and g.down not in lines(app, 1)[0]
        assert app.main.current_key() == ("pkg0102", "x86_64")  # the best match: installed ones first
        await pilot.press("S")  # the last column sort, the other way round
        assert table.sort_shown == (COL_SIZE, False) and b.user_sort == (COL_SIZE, False)
        await pilot.press("s")
        await pilot.pause()
        app.screen.action_close()
        await pilot.pause()
        assert table.sort_shown == (COL_SIZE, False)
    run(test)


# ---------------------------------------------------------------- the empty list (§7.3.8)

@pytest.mark.feature(Feature.LIST_EMPTY_EXPLANATION, front="tui")
def test_the_empty_list_explains_and_its_links_are_keys(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        b = app.main.browser
        b.sidebar.select("status", "status:installed")
        b.search.set_query("pkg0001", Mode.NAME)  # not installed
        b.apply_filter()
        await pilot.pause()
        assert len(b.packages) == 0
        text = [line.strip() for line in lines(app)]
        assert "Nothing found for “pkg0001” in “Installed”." in text
        assert "1 Show 1 result in “All”" in text
        assert app.main.list.check_action("link", (0,)) and not app.main.list.check_action("link", (1,))
        assert top(app).startswith(f"Kram TUI v{__version__}  “pkg0001” in Installed  0")
        await pilot.press("2")  # no second link: nothing happens
        assert b.filter.id == "status:installed"
        await pilot.press("1")
        await pilot.pause()
        assert b.filter.id == "status:all" and app.main.current_key() == ("pkg0001", "x86_64")
        assert not app.main.list.check_action("link", (0,))  # the list is not empty any more
    run(test)


# ---------------------------------------------------------------- glyphs and tints (§7.3.4, §7.3.5)

def special_snapshot() -> CatalogSnapshot:
    snap = snapshot(6)
    r = snap.rows
    r[1].status, r[1].installed_evr, r[1].candidate_evr = Status.UPGRADABLE, "1.0-1", "2.0-1"
    r[1].advisories = (Advisory("FEDORA-1", "security", "important", "Fix", 0),)
    r[2].locks = (VersionLock("evr = 1.0-1"),)
    r[2].held_evr = "3.0-1"
    r[4].status, r[4].installed_evr, r[4].candidate_evr = Status.UPGRADABLE, "1.0-1", "2.0-1"
    return snap


def status_cells(app) -> list[str]:
    table = app.main.list
    return [table.render_line(y).text[1:3] for y in range(1, 7)]


@pytest.mark.feature(Feature.LIST_LOCK_PADLOCK, front="tui")
def test_status_glyphs_on_utf8_and_letters(monkeypatch):
    monkeypatch.setenv("LC_ALL", "en_US.UTF-8")
    use_catalog(monkeypatch, special_snapshot(), blocked={("pkg0004", "x86_64"): "nothing provides libfoo"})

    async def test(app, pilot):
        await pilot.pause()
        # installed, upgradable with a security advisory, locked (its held-back upgrade dim and italic), blocked
        assert status_cells(app) == ["■ ", "▲s", "□L", "■ ", "▲!", "□ "]
        table = app.main.list
        latest = [s for s in table.render_line(3) if s.text.startswith("3.0-1")][0]
        assert latest.style.italic and latest.style.dim
        preferences.set_value(preferences.TUI_STATUS_GLYPHS, "letters")
        assert status_cells(app) == ["i ", "us", "pL", "i ", "u!", "p "]
        b = app.main.browser
        b.packages.marks.set(b.packages.row(5), Action.INSTALL)
        b.packages.marks.set(b.packages.row(0), Action.REMOVE)
        b.marker.changed.emit([b.packages.row(5).key, b.packages.row(0).key])
        assert status_cells(app)[5] == "+ " and status_cells(app)[0] == "- "
        assert top(app).split("  ")[3] == "2 changes marked"
    run(test)


def test_letters_on_a_terminal_that_is_not_utf8(monkeypatch):
    monkeypatch.setenv("LANG", "C")
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LC_CTYPE", raising=False)
    use_catalog(monkeypatch, special_snapshot())

    async def test(app, pilot):
        assert status_cells(app)[:3] == ["i ", "us", "pL"]
        app.main.sort(COL_NAME, True)
        assert f"Package {app.glyphs.down}" in lines(app, 1)[0] and app.glyphs.down == "v"
    run(test)


def test_marked_rows_are_tinted_in_high_colour_and_coloured_in_16(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        b, table = app.main.browser, app.main.list
        b.packages.marks.set(b.packages.row(2), Action.INSTALL)
        b.packages.marks.set(b.packages.row(3), Action.REMOVE)
        b.marker.changed.emit(None)
        app.set_scheme("textual-dark")
        await pilot.pause()
        await pilot.pause()
        row = table.render_line(3)  # position 2
        assert all(s.style.bgcolor == role("tint-marked").bgcolor for s in row if s.text.strip())
        assert role("tint-marked").bgcolor is not None and role("tint-marked") != role("tint-danger")
        assert all(s.style.bgcolor == role("tint-danger").bgcolor for s in table.render_line(4) if s.text.strip())
        app.set_scheme("textual-ansi")
        await pilot.pause()
        await pilot.pause()
        name = [s for s in table.render_line(3) if s.text.startswith("pkg0002")][0]
        # the terminal's colour numbers: the drawn colour and the role's may differ in Rich's bookkeeping only
        assert name.style.color.number == role("marked").color.number
        assert name.style.bgcolor is None or name.style.bgcolor.is_default  # no tint: the colour of the name
        removal = [s for s in table.render_line(4) if s.text.startswith("pkg0003")][0]
        assert removal.style.color.number == role("danger").color.number
    run(test)


def test_the_cursor_is_reversed_with_the_focus_and_marked_without(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        table = app.main.list
        cursor = table.render_line(1)
        assert all(s.style.reverse for s in cursor if s.text.strip())  # 16 colours: reverse, bold
        app.main.sidebar.entries.focus()  # another panel has the focus
        await pilot.pause()
        assert all(s.style.underline for s in table.render_line(1) if s.text.strip())
    run(test)


# ---------------------------------------------------------------- filters and the top line (§5.4)

def test_a_filter_change_updates_the_list_and_the_top_line(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        b = app.main.browser
        b.sidebar.select("status", "status:installed")
        await pilot.pause()
        assert len(b.packages) == 100 and app.main.current_key() == ("pkg0000", "x86_64")
        assert top(app).startswith(f"Kram TUI v{__version__}  Installed  100")
        assert "pkg0003" in lines(app, 3)[2]
        b.sidebar.select("status", "status:all")
        await pilot.pause()
        assert len(b.packages) == 300
    run(test)


@pytest.mark.feature(Feature.WINDOW_STATUS_BAR, front="tui")
def test_the_top_line_drops_what_does_not_fit_from_the_right(monkeypatch):
    repos = [RepoInfo("fedora", "Fedora", True, Origin.FEDORA, 9 * DAY + 60),
             RepoInfo("broken", "Broken", True, Origin.THIRD_PARTY, None)]
    use_catalog(monkeypatch, snapshot(repos=repos))
    monkeypatch.setattr(window_module, "is_root", lambda: False)  # the test container runs as root: no badge

    title = f"Kram TUI v{__version__}"
    extra = len(title) - len("Kram")  # the widths below were picked for a bare "Kram"

    async def test(app, pilot):
        line = top(app)
        assert line.startswith(f"{title}  All  300")
        assert line.endswith("! The package information is 9 days old  ! 1 repository has no metadata  "
                             "Metadata: 9 d ago")
        await pilot.resize_terminal(90 + extra, 24)
        await pilot.pause()
        assert top(app).endswith("! 1 repository has no metadata") and "Metadata" not in top(app)
        await pilot.resize_terminal(50 + extra, 24)
        await pilot.pause()
        assert top(app).rstrip() == f"{title}  All  300"
        app.ui.status("Copied", 0)  # a message stands in for the counts
        assert top(app).startswith(f"Kram TUI v{__version__}  Copied")
    run(test)



def _drawn(widget) -> list:
    """The segments a widget draws, as the terminal gets them (not as an SVG screenshot paints them)."""
    from textual.geometry import Region
    return [s for strip in widget.render_lines(Region(0, 0, widget.size.width, widget.size.height))
            for s in strip if s.text.strip()]


def test_nothing_is_drawn_black_on_the_terminals_own_colours(monkeypatch):
    """With 16 colours every word follows the terminal's own colours: Textual's Footer drew its words #000000 on
    #000000, and a dim text in an explicit default colour became #000000 too (both seen on a real dark terminal).
    The footer and the top line draw no truecolor black."""
    use_catalog(monkeypatch)

    async def test(app, pilot):
        app.set_scheme("textual-ansi", save=False)
        await pilot.pause()
        app.main.browser.sidebar.select("status", "status:installed")
        await pilot.pause(0.2)
        from kram.tui.widgets import KeyFooter
        for widget in (app.query_one(KeyFooter), app.query_one("#top")):
            segments = _drawn(widget)
            assert segments
            for s in segments:
                for colour in (s.style.color, s.style.bgcolor):
                    assert colour is None or colour.is_default or colour.number is not None, (widget, s)
        words = "".join(s.text for s in _drawn(app.query_one(KeyFooter)))
        assert "Sidebar" in words or "Groups" in words or "Search" in words

    run(test)
