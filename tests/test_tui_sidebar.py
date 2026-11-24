"""The terminal front end's sidebar over a made-up catalog (docs/TUI_SPEC.md §7.2): its views and entries, filtering,
folding, the empty views, the counts, the slide-over, the context menu and the group keys.

Run with Textual's headless driver (`App.run_test`, `Pilot`), as tests/test_tui_window.py. Skipped without Textual.
"""
import asyncio

import pytest

pytest.importorskip("textual")

from test_tui_window import loaded, rows, use_catalog  # noqa: E402

from kram.app.actions import DynamicItem  # noqa: E402
from kram.app.parity import Feature  # noqa: E402
from kram.core.custom_filters import Condition, CustomFilter, Field, Op  # noqa: E402
from kram.core.marks import Action  # noqa: E402
from kram.core.model import CatalogSnapshot, GroupInfo  # noqa: E402
from kram.core.settings import store as settings  # noqa: E402
from kram.tui.dialogs.filters import FiltersDialog  # noqa: E402
from kram.tui.dialogs.question import QuestionDialog  # noqa: E402
from kram.tui.palette import role  # noqa: E402
from kram.tui.sidebar import PLACEHOLDERS  # noqa: E402
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
            await pilot.pause()
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


# ---------------------------------------------------------------- the entries (§7.2.2)

@pytest.mark.feature(Feature.SIDEBAR_COUNTS, front="tui")
def test_the_status_view_lists_its_entries_with_counts(monkeypatch):
    use_catalog(monkeypatch, catalog())

    async def test(app, pilot):
        sidebar = bar(app)
        assert sidebar.border_title == "Status"
        lines = shown(app)
        assert lines[0].split() == ["All", "30"] and lines[1].split() == ["Installed", "10"]
        width = sidebar.entries.scrollable_content_region.width
        assert all(len(line) <= width for line in entry_lines(app))
        assert entry_lines(app)[0].rstrip().endswith("30") and len(entry_lines(app)[0].rstrip()) == width - 1
        first = sidebar.entries.render_line(0)
        label = next(s for s in first if s.text == "All")
        count = next(s for s in first if s.text == "30")
        assert label.style.bold  # an "All" entry
        assert count.style.dim is None or count.style.dim  # the cursor row of a list without the focus
        second = sidebar.entries.render_line(1)
        assert next(s for s in second if s.text == "10").style == role("muted")
    run(test)


def test_long_labels_are_cut_and_counts_never(monkeypatch):
    snap = catalog()
    snap.groups[0].name = "A group whose name is far longer than the sidebar is wide"
    use_catalog(monkeypatch, snap)

    async def test(app, pilot):
        bar(app).browse("groups")
        await pilot.pause()
        line = next(line for line in shown(app) if line.lstrip().startswith("A group"))
        assert app.glyphs.ellipsis in line and line.endswith(" 2")
        width = bar(app).entries.scrollable_content_region.width
        assert len(line) == width - 1  # the margin on the right
    run(test)


def test_installed_groups_are_bold_and_optional_groups_italic(monkeypatch):
    use_catalog(monkeypatch, catalog())

    async def test(app, pilot):
        entries = bar(app).entries
        bar(app).browse("groups")
        await pilot.pause()
        assert shown(app)[0].split()[:2] == ["All", "groups"]
        tools = next(s for s in entries.render_line(2) if s.text == "Tools")
        games = next(s for s in entries.render_line(1) if s.text == "Games")
        assert tools.style.bold and not games.style.bold
        bar(app).browse("environments")
        await pilot.pause()
        await pilot.press("g", "down", "right")  # Work unfolded: Tools, then Extra (optional)
        extra = next(s for s in entries.render_line(3) if s.text == "Extra")
        assert extra.style.italic and shown(app)[3].lstrip().startswith("Extra")
    run(test)


# ---------------------------------------------------------------- filtering and views (§7.2.1, §7.2.3)

def test_enter_filters_the_list(monkeypatch):
    use_catalog(monkeypatch, catalog())

    async def test(app, pilot):
        b = app.main.browser
        await pilot.press("g", "down")
        assert b.filter.id == "status:all"  # moving does not filter
        await pilot.press("enter")
        await pilot.pause()
        assert b.filter.id == "status:installed" and len(b.packages) == 10
        assert app.has_focus_in("sidebar")  # a pinned sidebar keeps the focus
        await pilot.press("escape")  # the list has the focus: the highlight stays on the filter's entry
        assert bar(app).entries.current_entry().id == "status:installed"
    run(test)


def test_the_cursor_goes_back_to_the_filter_s_entry_when_the_focus_leaves(monkeypatch):
    use_catalog(monkeypatch, catalog())

    async def test(app, pilot):
        await pilot.press("g", "down", "down", "escape")
        assert app.main.browser.filter.id == "status:all"
        assert bar(app).entries.current_entry().id == "status:all"
    run(test)


@pytest.mark.feature(Feature.SIDEBAR_VIEWS, front="tui")
def test_brackets_and_v_change_the_view_without_filtering(monkeypatch):
    use_catalog(monkeypatch, catalog())

    async def test(app, pilot):
        b, sidebar = app.main.browser, bar(app)
        await pilot.press("g", "right_square_bracket")
        assert sidebar.border_title == "Origin" and b.sidebar.current_view == "origin"
        assert b.filter.id == "status:all" and len(b.packages) == 30
        assert b.sidebar.filter_view == "status" and b.sidebar.current_entry_id == "status:all"
        await pilot.press("left_square_bracket", "left_square_bracket")  # round to the last view
        assert sidebar.border_title == "Custom filters" and b.filter.id == "status:all"
        await pilot.press("v")
        await pilot.pause()
        assert isinstance(app.screen, ChoiceList) and app.screen.current == "custom"
        assert app.screen.labels == ["Status", "Origin", "Groups", "Environments", "Search results",
                                     "Custom filters"]
        await pilot.press("up", "up", "up", "enter")  # Groups
        await pilot.pause()
        assert sidebar.border_title == "Groups" and b.filter.id == "status:all"
        await pilot.press("down", "enter")
        await pilot.pause()
        assert b.filter.id == "group:games" and len(b.packages) == 2
        assert b.sidebar.filter_view == "groups"
        # the filter is saved with its own view, whatever is shown
        await pilot.press("right_square_bracket")
        b.save_settings()
        assert settings.get("sidebar/view") == "groups" and settings.get("sidebar/entry") == "group:games"
        b.reload()  # a reload keeps the filter
        await pilot.pause(0.2)
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
        await pilot.press("g", "right_square_bracket")
        text = str(views.render()).splitlines()
        assert text[0] == "  Status" and text[1] == f"{dot} Origin"
        await pilot.resize_terminal(140, 30)  # not tall
        await pilot.pause()
        assert not views.region.height
        await pilot.resize_terminal(80, 40)  # tall, but narrow
        await pilot.pause()
        assert not views.region.height
    run(test, (140, 36))


# ---------------------------------------------------------------- folding (§7.2.4)

@pytest.mark.feature(Feature.SIDEBAR_ENVIRONMENTS_TREE, front="tui")
def test_environments_fold(monkeypatch):
    use_catalog(monkeypatch, catalog())

    async def test(app, pilot):
        b = app.main.browser
        g = app.glyphs
        bar(app).browse("environments")
        await pilot.pause()
        assert [line.split()[:2] for line in shown(app)] == [["Play", "0"], [g.folded, "Work"]]
        await pilot.press("g", "down", "right")
        assert [line.split()[:2] for line in shown(app)] == [["Play", "0"], [g.unfolded, "Work"], ["Tools", "3"],
                                                            ["Extra", "1"]]
        assert shown(app)[2].startswith("     Tools")  # under the label of its parent, one level in
        assert "env:work-environment" in b.sidebar._expanded
        await pilot.press("down", "down", "left")  # on a group: to its environment
        assert bar(app).entries.current_entry().id == "env:work-environment"
        await pilot.press("left")
        assert len(shown(app)) == 2 and "env:work-environment" not in b.sidebar._expanded
        await pilot.press("right", "down", "enter")  # a group of the environment filters
        await pilot.pause()
        assert b.filter.id == "envgroup:work-environment:tools" and len(b.packages) == 3
        bar(app).browse("status")
        await pilot.pause()
        bar(app).browse("environments")  # comes back unfolded
        await pilot.pause()
        assert len(shown(app)) == 4
    run(test)


def test_folding_glyphs_on_a_terminal_that_is_not_utf8(monkeypatch):
    monkeypatch.setenv("LANG", "C")
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LC_CTYPE", raising=False)
    use_catalog(monkeypatch, catalog())

    async def test(app, pilot):
        bar(app).browse("environments")
        await pilot.pause()
        assert shown(app)[1].split()[:2] == ["+", "Work"]
        await pilot.press("g", "down", "right")
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
            await pilot.pause()
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

def test_in_a_narrow_terminal_enter_closes_the_slide_over(monkeypatch):
    use_catalog(monkeypatch, catalog())

    async def test(app, pilot):
        b = app.main.browser
        await pilot.press("g")
        assert app.shown_panels() == ["sidebar"] and app.panel("sidebar").outer_size.width == 30
        await pilot.press("right_square_bracket", "left_square_bracket")  # views change, the slide-over stays
        assert app.shown_panels() == ["sidebar"]
        await pilot.press("down", "enter")
        await pilot.pause()
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


@pytest.mark.feature(Feature.MENU_SIDEBAR, front="tui")
@pytest.mark.feature(Feature.SIDEBAR_GROUP_CHANGE, front="tui")
def test_the_context_menu_lists_the_entry_s_actions(monkeypatch):
    use_catalog(monkeypatch, catalog())

    async def test(app, pilot):
        b = app.main.browser
        changes = []
        monkeypatch.setattr(b, "change_group", lambda group, action, optional=False: changes.append(
            (group.id, action, optional)))
        bar(app).browse("groups")
        await pilot.pause()
        await pilot.press("g", "down")  # Games, not installed
        await pilot.press("full_stop")
        await pilot.pause()
        assert isinstance(app.screen, PopupMenu)
        wanted = b.sidebar_menu(b.sidebar.entries[1])
        assert isinstance(wanted[0], DynamicItem) and None in wanted
        labels = [app.main.menu_item(item)[0] for item in wanted if item is not None]
        assert menu_labels(app) == labels
        assert labels[:2] == ["Install Group…", "Install Group with Optional Packages…"]
        await pilot.press("down", "enter")  # with optional packages
        await pilot.pause()
        assert changes == [("games", Action.INSTALL, True)] and not isinstance(app.screen, PopupMenu)
        await pilot.press("plus")
        assert changes[-1] == ("games", Action.INSTALL, False)
        await pilot.press("minus")  # not installed: nothing to remove
        assert len(changes) == 2
        await pilot.press("down")  # Tools, installed: + upgrades it once there is something to upgrade
        await pilot.press("minus")
        assert changes[-1] == ("tools", Action.REMOVE, False)
        await pilot.press("plus")
        assert len(changes) == 3 and "upgrade" in app.top_line.render().plain.lower()
        await pilot.press("full_stop")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert len(app.screen_stack) == 1
    run(test)


def test_the_menu_key_and_shift_f10_open_the_menu_and_disabled_items_are_dim(monkeypatch):
    use_catalog(monkeypatch, catalog())

    async def test(app, pilot):
        from textual.widgets import OptionList
        await pilot.press("g")
        for key in ("f16", "f22", "shift+f10"):
            await pilot.press(key)
            await pilot.pause()
            assert isinstance(app.screen, PopupMenu)
            await pilot.press("escape")
            await pilot.pause()
        await pilot.press("full_stop")
        await pilot.pause()
        options = app.screen.query_one(OptionList).options
        disabled = [str(o.prompt) for o in options if o.disabled]
        assert "Clear Search History" not in menu_labels(app)  # only in Search results
        assert menu_labels(app)[-2:] == ["New Filter from Current View…", "Custom Filters…"]
        assert not disabled
        await pilot.press("escape")
        await pilot.pause()
        bar(app).browse("search")
        await pilot.pause()
        await pilot.press("full_stop")
        await pilot.pause()
        options = app.screen.query_one(OptionList).options
        assert [str(o.prompt) for o in options if o.disabled] == ["Clear Search History"]
    run(test)


@pytest.mark.feature(Feature.SIDEBAR_CUSTOM_FILTER_MENU, front="tui")
def test_a_custom_filter_s_menu_edits_and_deletes_it(monkeypatch):
    import json
    use_catalog(monkeypatch, catalog())
    big = CustomFilter("Big", [Condition(Field.NAME, Op.CONTAINS, "pkg001")])
    settings.set("filters/custom", json.dumps([big.to_dict()]))

    async def test(app, pilot):
        b = app.main.browser
        bar(app).browse("custom")
        await pilot.pause()
        assert shown(app)[0].split() == ["Big", "10"]
        await pilot.press("g", "full_stop")
        await pilot.pause()
        assert menu_labels(app) == ["Edit Filter…", "Delete Filter", "New Filter from Current View…",
                                    "Custom Filters…"]
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("e")  # Edit Filter…: the Custom Filters dialog at it (tests/test_tui_dialogs.py)
        await pilot.pause()
        assert isinstance(app.screen, FiltersDialog) and app.screen.edit.current_name() == "Big"
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("full_stop", "down", "enter")  # Delete Filter
        await pilot.pause()
        assert isinstance(app.screen, QuestionDialog)
        app.screen.dismiss("yes")
        await pilot.pause()
        assert b.sidebar.custom == [] and " ".join(line.strip() for line in shown(app)) == PLACEHOLDERS["custom"]()
    run(test)


def test_a_group_s_menu_has_no_custom_filter_items(monkeypatch):
    use_catalog(monkeypatch, catalog())

    async def test(app, pilot):
        bar(app).browse("groups")
        await pilot.pause()
        await pilot.press("g", "down", "full_stop")
        await pilot.pause()
        assert "Edit Filter…" not in menu_labels(app) and "Delete Filter" not in menu_labels(app)
    run(test)
