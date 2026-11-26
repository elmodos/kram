"""The terminal front end's sidebar (docs/TUI_SPEC.md §7.2): an entry's line drawn without an app (level 1), the
entries as the widget draws them (a snapshot, level 2), and over a made-up catalog through the API (level 3): views,
filtering, folding, the empty views, the counts, the slide-over, the context menu and the group keys. The keys are
checked once, as bindings to those actions.

Skipped without Textual.
"""
import asyncio
import json

import pytest

pytest.importorskip("textual")

from rich.style import Style  # noqa: E402
from test_tui_window import loaded, rows, use_catalog  # noqa: E402
from tui_kit import assert_snapshot, grid, plain, roles_of  # noqa: E402

from kram.app import preferences  # noqa: E402
from kram.app.actions import DynamicItem  # noqa: E402
from kram.app.parity import Feature  # noqa: E402
from kram.core.custom_filters import Condition, CustomFilter, Field, Op  # noqa: E402
from kram.core.filters import FilterEntry  # noqa: E402
from kram.core.marks import Action  # noqa: E402
from kram.core.model import CatalogSnapshot, GroupInfo, Status  # noqa: E402
from kram.core.settings import store as settings  # noqa: E402
from kram.tui.dialogs.filters import FiltersDialog  # noqa: E402
from kram.tui.dialogs.question import QuestionDialog  # noqa: E402
from kram.tui.glyphs import ASCII, UNICODE, status_glyphs  # noqa: E402
from kram.tui.keymap import CONTEXT_KEYS  # noqa: E402
from kram.tui.palette import role  # noqa: E402
from kram.tui.sidebar import PLACEHOLDERS, VIEWS, EntryList, Sidebar, entry_line, status_entry_glyph  # noqa: E402
from kram.tui.widgets import ChoiceList, PopupMenu  # noqa: E402

WIDE, NARROW = (120, 40), (64, 22)


def names(*numbers: int) -> frozenset[str]:
    return frozenset(f"pkg{i:04d}" for i in numbers)


def catalog() -> CatalogSnapshot:
    """30 packages (every third installed), three groups and two environments."""
    found = rows(30)
    tools = GroupInfo("tools", "Tools", "", True, names(0, 1, 2))  # installed: bold
    games = GroupInfo("games", "Games", "", False, names(4, 5), optional=names(5))
    extra = GroupInfo("extra", "Extra", "", False, names(7))
    work = GroupInfo("work-environment", "Work", "", False, names(0, 1, 2, 7), environment=True, groups=("tools",),
                     optional_groups=("extra",))
    play = GroupInfo("play-environment", "Play", "", False, frozenset(), environment=True)
    return CatalogSnapshot(found, 10, 0, 0.1, descriptions=[""] * 30, groups=[games, tools, extra],
                           environments=[play, work])


def run(test, size=WIDE):
    from kram.tui.app import KramApp
    app = KramApp()

    async def go():
        async with app.run_test(size=size) as pilot:
            await loaded(app, pilot)
            await test(app, pilot)
    asyncio.run(go())
    return app


def bar(app):
    return app.main.sidebar


def entry_lines(app) -> list[str]:
    entries = bar(app).entries
    return [entries.render_line(y).text for y in range(entries.scrollable_content_region.height)]


def shown(app) -> list[str]:
    """The entries' lines, without the blank ones under them."""
    return [line.rstrip() for line in entry_lines(app) if line.strip()]


async def focus_sidebar(app, pilot) -> None:
    app.action_toggle_panel("sidebar")
    await pilot.pause()


def go_to(app, entry_id: str) -> None:
    """The sidebar's cursor on the shown entry `entry_id`."""
    entries = bar(app).entries
    ids = [entries.listing.entries[i].id for i in entries.lines]
    entries.go(ids.index(entry_id))


async def choose(app, pilot, entry_id: str) -> None:
    """Enter on the entry: the list filtered by it."""
    go_to(app, entry_id)
    bar(app).entries.action_choose()
    await pilot.pause()


async def popup(app, pilot, opener) -> None:
    opener()
    await pilot.pause()


async def answer(app, pilot, value) -> None:
    app.screen.dismiss(value)
    await pilot.pause()


# ---------------------------------------------------------------- an entry's line, without an app (level 1)

def test_an_entry_is_its_label_and_its_count_between_margins():
    line = entry_line(FilterEntry("status:installed", "Installed", None, count=10), 20, "", "…", Style(), Style())
    assert plain(line) == " Installed       10 "


def test_long_labels_are_cut_and_counts_never():
    e = FilterEntry("group:x", "A group whose name is far longer than the sidebar is wide", None, count=1234)
    line = plain(entry_line(e, 24, "  ", "…", Style(), Style()))
    assert line == "   A group whose … 1234 " and len(line) == 24
    assert plain(entry_line(e, 24, "", "...", Style(), Style())).rstrip().endswith("... 1234")


def test_an_entry_s_glyph_comes_after_its_indent_and_the_label_makes_room_for_it():
    e = FilterEntry("status:installed", "Installed", None, count=10)
    line = entry_line(e, 20, "", "…", Style(), Style(), ("●", Style(color="green")))
    assert plain(line) == " ● Installed     10 "
    assert next(s for s in line if s.text == "●").style == Style(color="green")


def test_all_entries_and_installed_groups_are_bold_and_an_environment_s_optional_groups_italic():
    def font(e):
        label = next(s for s in entry_line(e, 30, "", "…", Style(), Style()) if s.text == e.label)
        return bool(label.style.bold), bool(label.style.italic)
    assert font(FilterEntry("status:all", "All", None)) == (True, False)
    assert font(FilterEntry("group:tools", "Tools", None, bold=True)) == (True, False)
    assert font(FilterEntry("envgroup:w:extra", "Extra", None, dim=True)) == (False, True)
    assert font(FilterEntry("group:games", "Games", None)) == (False, False)


def test_the_status_view_s_glyphs_are_the_status_column_s():
    symbols = status_glyphs(True)
    assert status_entry_glyph("status:installed", symbols, UNICODE) == (symbols.status[Status.INSTALLED],
                                                                        "installed")
    assert status_entry_glyph("status:marked", symbols, UNICODE) == (UNICODE.yes, "marked")
    assert status_entry_glyph("status:security", symbols, UNICODE)[1] == "danger"
    assert status_entry_glyph("group:tools", symbols, UNICODE) is None


def test_the_keys_of_the_sidebar():
    """The keys (§4.4, §7.2): bound to the actions the tests below call."""
    def keys(widget):
        return {key: b.action for b in widget.BINDINGS for key in b.key.split(",")}
    entries, sidebar = keys(EntryList), keys(Sidebar)
    assert entries["up"] == entries["k"] == "move(-1)" and entries["down"] == entries["j"] == "move(1)"
    assert entries["home"] == "jump(0)" and entries["end"] == "jump(-1)" and entries["pagedown"] == "page(1)"
    assert entries["left"] == entries["h"] == "fold(False)" and entries["right"] == entries["l"] == "fold(True)"
    assert entries["enter"] == "choose"
    assert sidebar["left_square_bracket"] == "view(-1)" and sidebar["right_square_bracket"] == "view(1)"
    assert sidebar["v"] == "views" and sidebar["e"] == "edit"
    assert sidebar["plus"] == "group(True)" and sidebar["minus"] == "group(False)"
    assert all(sidebar[key] == "menu" for key in CONTEXT_KEYS) and {"f16", "f22", "shift+f10"} <= set(CONTEXT_KEYS)


# ---------------------------------------------------------------- the entries as drawn (level 2)

@pytest.mark.parametrize("scheme", ("textual-ansi", "kram-turbo"))
def test_the_entries_as_drawn(monkeypatch, scheme):
    """The Status view with the focus (the cursor on All), then Environments with Work unfolded and an optional group
    in it, without the focus (the cursor back on the view's first entry): every cell's text and role."""
    use_catalog(monkeypatch, catalog())
    monkeypatch.setenv("LC_ALL", "C.UTF-8")
    roles = roles_of(scheme)
    preferences.set_value(preferences.TUI_SCHEME, scheme)
    lines = []

    async def test(app, pilot):
        entries = bar(app).entries
        await focus_sidebar(app, pilot)
        lines.extend(entries.render_line(y) for y in range(len(entries.lines)))
        bar(app).browse("environments")
        go_to(app, "env:work-environment")
        entries.action_fold(True)
        go_to(app, "envgroup:work-environment:extra")
        app.list_widget.focus()
        await pilot.pause()
        lines.extend(entries.render_line(y) for y in range(len(entries.lines)))
    run(test)
    assert_snapshot(f"sidebar-{scheme}", grid(lines, roles))


# ---------------------------------------------------------------- the entries (§7.2.2)

@pytest.mark.feature(Feature.SIDEBAR_COUNTS, front="tui")
def test_the_status_view_lists_its_entries_with_counts(monkeypatch):
    use_catalog(monkeypatch, catalog())

    async def test(app, pilot):
        sidebar = bar(app)
        assert sidebar.border_title == "Status"
        lines = shown(app)
        installed = sidebar.entries.symbols.status[Status.INSTALLED]
        assert lines[0].split() == ["All", "30"] and lines[1].split() == [installed, "Installed", "10"]
        glyph = next(s for s in sidebar.entries.render_line(1) if s.text == installed)
        assert glyph.style.color == role("installed").color
        width = sidebar.entries.scrollable_content_region.width
        assert all(len(line) == width for line in entry_lines(app))
    run(test)


def test_a_long_group_name_is_cut_to_the_sidebar(monkeypatch):
    snap = catalog()
    snap.groups[0].name = "A group whose name is far longer than the sidebar is wide"
    use_catalog(monkeypatch, snap)

    async def test(app, pilot):
        bar(app).browse("groups")
        line = next(line for line in shown(app) if line.lstrip().startswith("A group"))
        assert app.glyphs.ellipsis in line and line.endswith(" 2")
        assert len(line) == bar(app).entries.scrollable_content_region.width - 1
    run(test)


# ---------------------------------------------------------------- filtering and views (§7.2.1, §7.2.3)

def test_choosing_an_entry_filters_the_list_and_moving_does_not(monkeypatch):
    use_catalog(monkeypatch, catalog())

    async def test(app, pilot):
        b = app.main.browser
        await focus_sidebar(app, pilot)
        go_to(app, "status:installed")
        assert b.filter.id == "status:all"
        bar(app).entries.action_choose()
        assert b.filter.id == "status:installed" and len(b.packages) == 10
        await pilot.pause()
        assert app.has_focus_in("sidebar")  # a pinned sidebar keeps the focus
    run(test)


def test_the_cursor_goes_back_to_the_filter_s_entry_when_the_focus_leaves(monkeypatch):
    use_catalog(monkeypatch, catalog())

    async def test(app, pilot):
        await focus_sidebar(app, pilot)
        go_to(app, "status:upgradable")
        app.list_widget.focus()
        await pilot.pause()
        assert app.main.browser.filter.id == "status:all"
        assert bar(app).entries.current_entry().id == "status:all"
        await choose(app, pilot, "status:installed")  # chosen: the highlight stays on it
        app.list_widget.focus()
        await pilot.pause()
        assert bar(app).entries.current_entry().id == "status:installed"
    run(test)


@pytest.mark.feature(Feature.SIDEBAR_VIEWS, front="tui")
def test_changing_the_view_does_not_filter(monkeypatch):
    use_catalog(monkeypatch, catalog())

    async def test(app, pilot):
        b, sidebar = app.main.browser, bar(app)
        sidebar.action_view(1)
        assert sidebar.border_title == "Origin" and b.sidebar.current_view == "origin"
        assert b.filter.id == "status:all" and len(b.packages) == 30
        assert b.sidebar.filter_view == "status" and b.sidebar.current_entry_id == "status:all"
        sidebar.action_view(-1)
        sidebar.action_view(-1)  # round to the last view
        assert sidebar.border_title == "Custom filters" and b.filter.id == "status:all"
        await popup(app, pilot, sidebar.action_views)
        assert isinstance(app.screen, ChoiceList) and app.screen.current == "custom"
        assert app.screen.labels == ["Status", "Origin", "Groups", "Environments", "Search results",
                                     "Custom filters"]
        await answer(app, pilot, "groups")
        assert sidebar.border_title == "Groups" and b.filter.id == "status:all"
        await choose(app, pilot, "group:games")
        assert b.filter.id == "group:games" and len(b.packages) == 2 and b.sidebar.filter_view == "groups"
        # the filter is saved with its own view, whatever is shown
        sidebar.action_view(1)
        b.save_settings()
        assert settings.get("sidebar/view") == "groups" and settings.get("sidebar/entry") == "group:games"
        b.reload()  # a reload keeps the filter
        await pilot.pause()
        assert b.filter.id == "group:games"
    run(test)


def test_the_list_of_views_shows_when_wide_and_tall_and_follows_the_view(monkeypatch):
    use_catalog(monkeypatch, catalog())

    async def test(app, pilot):
        views = bar(app).views
        assert views.display and views.region.height == 7  # a rule over the six views
        dot = app.glyphs.bullet
        text = str(views.render()).splitlines()
        assert text[0] == f"{dot} Status" and text[1] == "  Origin"
        bar(app).action_view(1)
        text = str(views.render()).splitlines()
        assert text[0] == "  Status" and text[1] == f"{dot} Origin"
        await pilot.resize_terminal(140, 30)  # not tall
        await pilot.pause()
        assert not views.region.height
        await pilot.resize_terminal(80, 40)  # tall, but narrow
        await pilot.pause()
        assert not views.region.height
    run(test, (140, 36))


def test_a_click_on_a_view_shows_that_view(monkeypatch):
    use_catalog(monkeypatch, catalog())

    async def test(app, pilot):
        views = bar(app).views
        await pilot.click(views, offset=(4, 0))  # the rule over the views: nothing
        assert app.main.browser.sidebar.current_view == "status"
        for line in (3, 6):
            await pilot.click(views, offset=(4, line))
            assert app.main.browser.sidebar.current_view == VIEWS[line - 1][0]
    run(test, (140, 36))


def test_a_click_on_an_entry_filters_by_it(monkeypatch):
    use_catalog(monkeypatch, catalog())

    async def test(app, pilot):
        await pilot.click(bar(app).entries, offset=(4, 1))
        assert app.main.browser.filter.id == "status:installed"
    run(test)


# ---------------------------------------------------------------- folding (§7.2.4)

@pytest.mark.feature(Feature.SIDEBAR_ENVIRONMENTS_TREE, front="tui")
def test_environments_fold(monkeypatch):
    use_catalog(monkeypatch, catalog())

    async def test(app, pilot):
        b = app.main.browser
        g = app.glyphs
        entries = bar(app).entries
        bar(app).browse("environments")
        assert [line.split()[:2] for line in shown(app)] == [["Play", "0"], [g.folded, "Work"]]
        go_to(app, "env:work-environment")
        entries.action_fold(True)
        assert [line.split()[:2] for line in shown(app)] == [["Play", "0"], [g.unfolded, "Work"], ["Tools", "3"],
                                                            ["Extra", "1"]]
        assert shown(app)[2].startswith("     Tools")  # under the label of its parent, one level in
        assert "env:work-environment" in b.sidebar._expanded
        go_to(app, "envgroup:work-environment:extra")
        entries.action_fold(False)  # on a group: to its environment
        assert entries.current_entry().id == "env:work-environment"
        entries.action_fold(False)
        assert len(shown(app)) == 2 and "env:work-environment" not in b.sidebar._expanded
        entries.action_fold(True)
        await choose(app, pilot, "envgroup:work-environment:tools")  # a group of the environment filters
        assert b.filter.id == "envgroup:work-environment:tools" and len(b.packages) == 3
        bar(app).browse("status")
        bar(app).browse("environments")  # comes back unfolded
        assert len(shown(app)) == 4
    run(test)


def test_folding_glyphs_on_a_terminal_that_is_not_utf8(monkeypatch):
    monkeypatch.setenv("LANG", "C")
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LC_CTYPE", raising=False)
    use_catalog(monkeypatch, catalog())

    async def test(app, pilot):
        assert app.glyphs is ASCII
        bar(app).browse("environments")
        assert shown(app)[1].split()[:2] == ["+", "Work"]
        go_to(app, "env:work-environment")
        bar(app).entries.action_fold(True)
        assert shown(app)[1].split()[:2] == ["-", "Work"]
        assert str(bar(app).views.render()).splitlines()[3] == "* Environments"
    run(test)


# ---------------------------------------------------------------- empty views, counts (§7.2.5, §7.2.2)

def test_empty_views_say_how_to_fill_them(monkeypatch):
    use_catalog(monkeypatch, catalog())

    async def test(app, pilot):
        sidebar = bar(app)
        for view in ("search", "custom"):
            sidebar.browse(view)
            text = " ".join(line.strip() for line in shown(app))
            assert text == PLACEHOLDERS[view]()
            line = next(y for y, text in enumerate(entry_lines(app)) if text.strip())
            words = [s for s in sidebar.entries.render_line(line) if s.text.strip()]
            assert all(s.style.italic for s in words)
        assert app.main.browser.filter.id == "status:all"
        assert "Press / to search" in PLACEHOLDERS["search"]()
    run(test)


def test_counts_follow_the_marks(monkeypatch):
    use_catalog(monkeypatch, catalog())

    async def test(app, pilot):
        b = app.main.browser
        marked = next(i for i, e in enumerate(b.sidebar.entries) if e.id == "status:marked")
        assert shown(app)[marked].split()[-1] == "0"
        drawn = []
        monkeypatch.setattr(bar(app).entries, "refresh", lambda *a, **k: drawn.append(a))
        b.packages.marks.set(b.packages.row(1), Action.INSTALL)
        b.marker.changed.emit([b.packages.row(1).key])
        assert shown(app)[marked].split()[-1] == "1"
        assert drawn and all(a and a[0].height == 1 for a in drawn)  # its line alone
    run(test)


# ---------------------------------------------------------------- the slide-over (§5.2, §7.2.3)

def test_in_a_narrow_terminal_choosing_closes_the_slide_over(monkeypatch):
    use_catalog(monkeypatch, catalog())

    async def test(app, pilot):
        b = app.main.browser
        await focus_sidebar(app, pilot)
        assert app.shown_panels() == ["sidebar"] and app.panel("sidebar").outer_size.width == 30
        bar(app).action_view(1)
        bar(app).action_view(-1)  # views change, the slide-over stays
        assert app.shown_panels() == ["sidebar"]
        await choose(app, pilot, "status:installed")
        assert b.filter.id == "status:installed"
        assert app.shown_panels() == [] and app.window.focused is app.list_widget
    run(test, NARROW)


def test_the_hints_fit_the_bottom_border(monkeypatch):
    use_catalog(monkeypatch, catalog())

    async def test(app, pilot):
        assert bar(app)._border_subtitle.plain == "[ prev  ] next  v all"
        app.panel("sidebar").styles.width = 20
        await pilot.pause()
        assert bar(app)._border_subtitle.plain == "[ prev  ] next"
    run(test)


# ---------------------------------------------------------------- the context menu (§7.2.6)

def menu_labels(app) -> list[str]:
    from textual.widgets import OptionList
    return [str(o.prompt) for o in app.screen.query_one(OptionList).options]


def disabled_labels(app) -> list[str]:
    from textual.widgets import OptionList
    return [str(o.prompt) for o in app.screen.query_one(OptionList).options if o.disabled]


@pytest.mark.feature(Feature.MENU_SIDEBAR, front="tui")
@pytest.mark.feature(Feature.SIDEBAR_GROUP_CHANGE, front="tui")
def test_the_context_menu_lists_the_entry_s_actions(monkeypatch):
    use_catalog(monkeypatch, catalog())

    async def test(app, pilot):
        b, sidebar = app.main.browser, bar(app)
        changes = []
        monkeypatch.setattr(b, "change_group", lambda group, action, optional=False: changes.append(
            (group.id, action, optional)))
        sidebar.browse("groups")
        await focus_sidebar(app, pilot)
        go_to(app, "group:games")  # not installed
        await popup(app, pilot, sidebar.action_menu)
        assert isinstance(app.screen, PopupMenu)
        wanted = b.sidebar_menu(b.sidebar.entries[1])
        assert isinstance(wanted[0], DynamicItem) and None in wanted
        labels = [app.main.menu_item(item)[0] for item in wanted if item is not None]
        assert menu_labels(app) == labels
        assert labels[:2] == ["Install Group…", "Install Group with Optional Packages…"]
        assert not disabled_labels(app)
        await answer(app, pilot, 1)  # with optional packages
        assert changes == [("games", Action.INSTALL, True)] and not isinstance(app.screen, PopupMenu)
        sidebar.action_group(True)
        assert changes[-1] == ("games", Action.INSTALL, False)
        sidebar.action_group(False)  # not installed: nothing to remove
        assert len(changes) == 2
        go_to(app, "group:tools")  # installed: + upgrades it once there is something to upgrade
        sidebar.action_group(False)
        assert changes[-1] == ("tools", Action.REMOVE, False)
        sidebar.action_group(True)
        assert len(changes) == 3 and "upgrade" in app.top_line.render().plain.lower()
        assert "Edit Filter…" not in labels and "Delete Filter" not in labels
        assert sidebar.check_action("edit", ()) is False and sidebar.check_action("group", ()) is True
    run(test)


def test_the_status_view_s_menu_and_the_search_view_s(monkeypatch):
    use_catalog(monkeypatch, catalog())

    async def test(app, pilot):
        sidebar = bar(app)
        await popup(app, pilot, sidebar.action_menu)
        assert "Clear Search History" not in menu_labels(app)  # only in Search results
        assert menu_labels(app)[-2:] == ["New Filter from Current View…", "Custom Filters…"]
        assert not disabled_labels(app)
        await answer(app, pilot, None)
        assert len(app.screen_stack) == 1
        sidebar.browse("search")
        await popup(app, pilot, sidebar.action_menu)
        assert disabled_labels(app) == ["Clear Search History"]
    run(test)


@pytest.mark.feature(Feature.SIDEBAR_CUSTOM_FILTER_MENU, front="tui")
def test_a_custom_filter_s_menu_edits_and_deletes_it(monkeypatch):
    use_catalog(monkeypatch, catalog())
    big = CustomFilter("Big", [Condition(Field.NAME, Op.CONTAINS, "pkg001")])
    settings.set("filters/custom", json.dumps([big.to_dict()]))

    async def test(app, pilot):
        b, sidebar = app.main.browser, bar(app)
        sidebar.browse("custom")
        assert shown(app)[0].split() == ["Big", "10"]
        await focus_sidebar(app, pilot)
        await popup(app, pilot, sidebar.action_menu)
        assert menu_labels(app) == ["Edit Filter…", "Delete Filter", "New Filter from Current View…",
                                    "Custom Filters…"]
        await answer(app, pilot, None)
        assert sidebar.check_action("edit", ()) is True
        await popup(app, pilot, sidebar.action_edit)  # the Custom Filters dialog at it (tests/test_tui_dialogs.py)
        assert isinstance(app.screen, FiltersDialog) and app.screen.edit.current_name() == "Big"
        await answer(app, pilot, None)
        await popup(app, pilot, sidebar.action_menu)
        await answer(app, pilot, 1)  # Delete Filter
        assert isinstance(app.screen, QuestionDialog)
        await answer(app, pilot, "yes")
        assert b.sidebar.custom == [] and " ".join(line.strip() for line in shown(app)) == PLACEHOLDERS["custom"]()
    run(test)
