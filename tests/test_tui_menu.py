"""The terminal front end's menus and the dialogs they lead to (docs/TUI_SPEC.md §7.7, §10.13, §10.17, §10.19,
§10.20, §13): the menu popup over `menu_bar()`, the package list's context menu, the settings of the registry,
Colours, Keys, About and quitting; and the keys of kram.tui.keymap.

Run with Textual's headless driver (`App.run_test`, `Pilot`), over the made-up catalog of test_tui_window. Skipped
without Textual.
"""
import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("textual")

import textual  # noqa: E402
from test_tui_window import WIDE, loaded, snapshot, use_catalog  # noqa: E402
from textual.widgets import OptionList  # noqa: E402

from kram.app import preferences  # noqa: E402
from kram.app.actions import menu_bar, table_menu, walk  # noqa: E402
from kram.app.parity import Feature  # noqa: E402
from kram.core.marks import Action  # noqa: E402
from kram.tui.app import KramApp  # noqa: E402
from kram.tui.dialogs.about import AboutDialog  # noqa: E402
from kram.tui.dialogs.colours import ColoursDialog  # noqa: E402
from kram.tui.dialogs.keys import KeysDialog  # noqa: E402
from kram.tui.dialogs.question import QuestionDialog  # noqa: E402
from kram.tui.menu import MenuPopup, menu_title  # noqa: E402
from kram.tui.search import SearchDialog  # noqa: E402
from kram.tui.widgets import Button, PopupMenu  # noqa: E402

NARROW = (64, 22)


def run(test, size=WIDE):
    app = KramApp()

    async def go():
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            await loaded(app, pilot)
            await test(app, pilot)
    asyncio.run(go())
    return app


def popup(app) -> MenuPopup:
    assert isinstance(app.screen, MenuPopup)
    return app.screen


def titles(app) -> list[str]:
    return [str(o.prompt) for o in popup(app).query_one("#menu-titles", OptionList).options]


def lines(app) -> list[str]:
    """The entries' column as shown, without the padding at the right."""
    return [o.prompt.plain.rstrip() for o in popup(app).query_one("#menu-entries", OptionList).options]


def status(app) -> str:
    return str(popup(app).query_one("#menu-status").render())


def highlighted(app) -> str:
    column = popup(app).query_one("#menu-entries", OptionList)
    return column.get_option_at_index(column.highlighted).prompt.plain


async def open_menu(app, pilot, title: str) -> None:
    """The menu popup on the menu called `title`, the cursor in its entries."""
    await pilot.press("m")
    await pilot.pause()
    for _ in range(titles(app).index(title)):
        await pilot.press("down")
    await pilot.press("right")
    await pilot.pause()


async def go_to(app, pilot, label: str) -> None:
    """The cursor on the entry whose line starts with `label`."""
    for _ in range(40):
        if highlighted(app).startswith(label):
            return
        await pilot.press("down")
    raise AssertionError(f"{label!r} not in {lines(app)}")


def popup_labels(app) -> list[str]:
    return [o.prompt.plain.rstrip() for o in app.screen.query_one(OptionList).options]


# ---------------------------------------------------------------- the menu popup (§7.7.1)

@pytest.mark.feature(Feature.MENU_PACKAGE, front="tui")
def test_m_and_f9_open_the_menus_of_the_menu_bar(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        for key in ("m", "f9"):
            await pilot.press(key)
            await pilot.pause()
            assert titles(app) == ["File", "Edit", "Package", "Settings", "Help"] == [
                menu_title(m) for m in menu_bar()]
            assert lines(app)[0].startswith("Open Package File…")  # File's entries beside the menus
            # the window's keys are off while it is up
            for action, params in (("find", ()), ("toggle_panel", ("sidebar",)), ("menu", ()), ("quit", ()),
                                   ("run", ("reload_cache",))):
                assert app.check_action(action, params) is False
            await pilot.press("g", "q")
            assert isinstance(app.screen, MenuPopup) and app.return_code is None
            assert app.shown_panels() == ["sidebar", "details"]
            await pilot.press("escape")
            await pilot.pause()
            assert len(app.screen_stack) == 1
        await open_menu(app, pilot, "Package")
        package = [app.main.defs[i.action].label for i in menu_bar()[2].items if i.action and i.action != "why_blocked"]
        shown = lines(app)
        assert all(any(line.startswith(label) for line in shown) for label in package)
        assert any(line.startswith("Downgrade to Version") for line in shown)
        assert not any(line.startswith("Why It Cannot Be Upgraded") for line in shown)  # only for a blocked one
    run(test)


def test_an_entry_runs_what_the_gui_s_action_runs(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        b = app.main.browser
        reloads = []
        monkeypatch.setattr(b, "reload", lambda: reloads.append(True))
        await open_menu(app, pilot, "File")
        await go_to(app, pilot, "Reload from cache")
        await pilot.press("enter")
        await pilot.pause()
        assert reloads == [True] and len(app.screen_stack) == 1
        await open_menu(app, pilot, "Edit")
        await go_to(app, pilot, "Find")
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, SearchDialog)  # opened once the menu was gone
        await pilot.press("escape")
        await pilot.pause()
        # an action whose dialog comes later says so
        await open_menu(app, pilot, "Settings")
        await go_to(app, pilot, "Cleanup…")
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, QuestionDialog) and app.screen.question.text == "Not in this version yet"
    run(test)


def test_entries_that_are_off_are_dim_and_say_why(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        await open_menu(app, pilot, "File")
        assert status(app).startswith("Install a downloaded .rpm file")  # what an entry that is on does
        await go_to(app, pilot, "Save Markings As…")
        option = popup(app).query_one("#menu-entries", OptionList)
        prompt = option.get_option_at_index(option.highlighted).prompt
        assert prompt.spans and all(span.style.dim for span in prompt.spans)
        assert status(app) == "Nothing is marked"
        await pilot.press("enter")  # nothing runs
        await pilot.pause()
        assert isinstance(app.screen, MenuPopup)
        await pilot.press("escape")
        await pilot.pause()
        # the same action by its key: the top line says why
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert "Nothing is marked" in app.top_line.render().plain
    run(test)


@pytest.mark.feature(Feature.MENU_ACCELERATORS, front="tui")
def test_the_entries_show_the_terminal_s_keys(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        await open_menu(app, pilot, "File")
        shown = lines(app)
        for label, key in (("Reload", "f5"), ("Reload from cache", "R"), ("Read Markings…", "ctrl+o"),
                           ("Quit", "q")):
            line = next(line for line in shown if line.startswith(label + " "))
            assert line.endswith(" " + key), line
        await pilot.press("left", "down")  # Edit
        await pilot.pause()
        shown = lines(app)
        assert next(line for line in shown if line.startswith("Apply")).endswith(" a")  # not the GUIs' Ctrl+P
        assert next(line for line in shown if line.startswith("Find")).endswith(" /")
        assert next(line for line in shown if line.startswith("Unmark All")).endswith(" Z")
    run(test)


@pytest.mark.feature(Feature.MENU_DOWNGRADE_SUBMENU, front="tui")
def test_submenus_open_in_place_and_downgrade_is_filled_when_it_opens(monkeypatch):
    use_catalog(monkeypatch)
    versions = [SimpleNamespace(evr="1.0-1", installed=True, locked_out=False, repo_id="@System"),
                SimpleNamespace(evr="0.9-1", installed=False, locked_out=False, repo_id="fedora"),
                SimpleNamespace(evr="0.8-1", installed=False, locked_out=False, repo_id="fedora")]

    async def test(app, pilot):
        b = app.main.browser
        marked = []
        monkeypatch.setattr(b, "mark_selected", lambda action, evr="": marked.append((action, evr)))
        asked = []

        def details_of(key):
            asked.append(key)
            return SimpleNamespace(versions=versions)
        monkeypatch.setattr(b.details_loader, "details_of", details_of)
        await open_menu(app, pilot, "Package")
        assert not asked  # not before it opens
        await go_to(app, pilot, "Downgrade to Version")
        await pilot.press("right")
        await pilot.pause()
        assert asked == [("pkg0000", "x86_64")]
        g = app.glyphs  # arrows as the terminal can show them
        assert lines(app) == [f"{g.left} Downgrade to Version", "0.9-1  (fedora)", "0.8-1  (fedora)"]
        await pilot.press("left")  # back, onto the entry it was opened from
        await pilot.pause()
        assert highlighted(app).startswith("Downgrade to Version") and "Mark for Removal" in " ".join(lines(app))
        await pilot.press("enter", "down", "down", "enter")
        await pilot.pause()
        assert marked == [(Action.DOWNGRADE, "0.8-1")] and len(app.screen_stack) == 1
        # the back line works as ← does; a submenu that is off says why
        await open_menu(app, pilot, "Package")
        await go_to(app, pilot, "Downgrade to Version")
        await pilot.press("enter", "enter")  # the cursor starts on the back line
        await pilot.pause()
        assert highlighted(app).startswith("Downgrade to Version")
        await pilot.press("escape")
        await pilot.pause()
        app.main.list.select(1)  # not installed
        await open_menu(app, pilot, "Package")
        await go_to(app, pilot, "Downgrade to Version")
        assert status(app) == "Not for this package"
        await pilot.press("enter")
        assert highlighted(app).startswith("Downgrade to Version")
    run(test)


def test_the_menu_fits_a_narrow_terminal(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        await open_menu(app, pilot, "Edit")
        box = popup(app).query_one("#menu-box")
        assert box.region.width <= NARROW[0]
        long = next(line for line in lines(app) if line.startswith("Mark Upgrades"))
        assert long.endswith(app.glyphs.right)
    run(test, NARROW)


# ---------------------------------------------------------------- settings (§7.7.3, §13)

@pytest.mark.feature(Feature.SETTINGS_REGISTRY, front="tui")
def test_the_settings_menu_holds_the_registry_s_settings_for_the_terminal(monkeypatch):
    use_catalog(monkeypatch)
    # the GUIs' settings menus are unchanged: the shared ones are theirs as before
    assert [p.key for p in preferences.prefs_for("qt")] == [preferences.STATUS_CLICK, preferences.WATCH_RELEASES,
                                                             preferences.TOOLBAR_STYLE]
    assert [p.key for p in preferences.prefs_for("gtk")] == [preferences.STATUS_CLICK, preferences.WATCH_RELEASES,
                                                              preferences.MENU_BAR]
    monkeypatch.setattr(preferences.distro, "running_release", lambda: 44)  # on Fedora: Watch Fedora Releases

    async def test(app, pilot):
        await open_menu(app, pilot, "Settings")
        shown = [" ".join(line.split()) for line in lines(app)]
        settings = shown[shown.index("New Filter from Current View…") + 1:]
        assert settings == ["[ ] Clicking the status icon marks the likely action", "[x] Watch Fedora Releases",
                            "[x] Centre the cursor when scrolling", f"Status glyphs {app.glyphs.right}",
                            "[x] Ask before quitting with changes not applied", "Colours…"]
        await go_to(app, pilot, "[x] Centre")
        assert status(app) == ""  # it has no tooltip
        await pilot.press("enter")  # ticked in place; the menu stays
        await pilot.pause()
        assert preferences.value(preferences.TUI_CENTRE_SCROLLING) is False and not app.main.list.centre
        assert highlighted(app).startswith("[ ] Centre") and isinstance(app.screen, MenuPopup)
        await pilot.press("down")
        assert status(app) == "Symbols, or letters when the terminal is not UTF-8"  # the choice made
        await pilot.press("enter")
        await pilot.pause()
        g = app.glyphs
        assert lines(app) == [f"{g.left} Status glyphs",
                              f"({g.item}) Symbols, or letters when the terminal is not UTF-8", "( ) Letters"]
        await pilot.press("down", "down", "enter")
        await pilot.pause()
        assert preferences.value(preferences.TUI_STATUS_GLYPHS) == "letters"
        assert highlighted(app).startswith("Status glyphs")
        assert app.main.list.symbols.status[next(iter(app.main.list.symbols.status))].isalpha()
    run(test)


def test_colours_previews_the_scheme_and_esc_puts_it_back(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        assert app.theme == "textual-ansi"
        await open_menu(app, pilot, "Settings")
        await go_to(app, pilot, "Colours…")
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, ColoursDialog)
        await pilot.press("down")
        await pilot.pause()
        assert app.theme == "kram-midnight" and preferences.value(preferences.TUI_SCHEME) == "textual-ansi"
        await pilot.press("down", "down")
        await pilot.pause()
        assert app.theme == "textual-dark" and not app.ansi_color
        await pilot.press("escape")
        await pilot.pause()
        assert len(app.screen_stack) == 1 and app.theme == "textual-ansi" and app.ansi_color
        assert preferences.value(preferences.TUI_SCHEME) == "textual-ansi"
        app.open_colours()
        await pilot.pause()
        await pilot.press("down", "enter")
        await pilot.pause()
        assert len(app.screen_stack) == 1 and app.theme == "kram-midnight"
        assert preferences.value(preferences.TUI_SCHEME) == "kram-midnight"
    run(test)


# ---------------------------------------------------------------- the context menu (§7.7.2)

@pytest.mark.feature(Feature.LIST_CONTEXT_MENU, front="tui")
def test_the_row_s_context_menu(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        b = app.main.browser
        marked = []
        monkeypatch.setattr(b, "mark_selected", lambda action, evr="": marked.append(action))
        labels = [app.main.defs[i.action].label for i in table_menu().items if i.action and i.action != "why_blocked"]
        for key in ("full_stop", "shift+f10", "f22", "f16", "menu"):
            await pilot.press(key)
            await pilot.pause()
            assert isinstance(app.screen, PopupMenu) and app.screen.title_text == "pkg0000"
            await pilot.press("escape")
            await pilot.pause()
        await pilot.press("down", "full_stop")  # pkg0001, not installed
        await pilot.pause()
        shown = popup_labels(app)
        assert [line.split("  ")[0].rstrip() for line in shown if not line.startswith("Downgrade")] == labels
        assert shown[0].endswith(" +") and shown[-1].endswith(" Y")  # with the keys
        menu = app.screen.query_one(OptionList)
        on = [o.prompt.plain.split("  ")[0] for o in menu.options if not o.disabled]
        assert on[0] == "Mark for Installation" and "Mark for Removal" not in on
        # next to the cursor's row
        assert menu.region.y == app.main.list.content_region.y + 3
        await pilot.press("enter")
        await pilot.pause()
        assert marked == [Action.INSTALL] and len(app.screen_stack) == 1
        # a right click on a row picks it and opens its menu where it was clicked
        app.main.list.on_click(SimpleNamespace(y=4, button=3, screen_x=30, screen_y=8))
        await pilot.pause()
        assert app.main.list.cursor == 3 and isinstance(app.screen, PopupMenu)
        assert app.screen.query_one(OptionList).region.y == 9 and app.screen.title_text == "pkg0003"
    run(test)


# ---------------------------------------------------------------- the keys (§6.5, §10.20)

def test_the_window_s_and_the_list_s_action_keys(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        b = app.main.browser
        ran = []
        monkeypatch.setattr(b, "reload", lambda: ran.append("reload"))
        monkeypatch.setattr(b, "mark_selected", lambda action, evr="": ran.append(action))
        monkeypatch.setattr(b, "unmark_selected", lambda: ran.append("unmark"))
        monkeypatch.setattr(b, "set_version_lock", lambda lock: ran.append(("lock", lock)))
        await pilot.press("R")
        await pilot.press("minus")  # pkg0000 is installed
        await pilot.press("down", "plus", "insert")  # pkg0001 is not
        assert ran == ["reload", Action.REMOVE, Action.INSTALL, Action.INSTALL]
        await pilot.press("z")  # not marked: the top line says so
        assert ran[-1] == Action.INSTALL and "Not marked" in app.top_line.render().plain
        await pilot.press("equals_sign")  # not installed: neither lock nor unlock
        await pilot.pause()
        assert len(app.screen_stack) == 1
        await pilot.press("up", "equals_sign")  # installed: locked (tests/test_tui_progress.py runs it)
        await pilot.pause()
        assert ran[-1] == ("lock", True)
    run(test)


def test_question_mark_lists_the_keys_of_the_focused_panel_and_the_window(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        await pilot.press("question_mark")
        await pilot.pause()
        assert isinstance(app.screen, KeysDialog)
        sections = dict(app.screen.sections)
        assert list(sections) == ["Packages", "Window"]
        packages, window = dict((w, k) for k, w in sections["Packages"]), dict((w, k) for k, w in sections["Window"])
        g = app.glyphs
        assert packages["Move the cursor"].split() == [g.up, g.down, "home", "end", "pgup", "pgdn", "k", "j"]
        assert packages["Mark for installation or upgrade"] == "+ ins" and packages["Context menu"].startswith(".")
        assert window["Search"] == "/ ctrl+f" and window["Menu"] == "m f9" and window["Apply"] == "a ctrl+p"
        assert window["Quit"] == "q ctrl+q" and window["Keys"] == "? f1"
        assert not {"Page Left", "Focus Next"} & (set(packages) | set(window))  # Textual's own, in its words
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("g", "f1")
        await pilot.pause()
        sections = dict(app.screen.sections)
        assert list(sections) == ["Status", "Window"]
        assert {"Views", "Filter the list by the entry", "Menu"} <= {w for _k, w in sections["Status"]}
        await pilot.press("f1")  # closes it again
        await pilot.pause()
        assert len(app.screen_stack) == 1
    run(test)


def test_ctrl_p_is_apply_and_textual_s_command_palette_is_off(monkeypatch):
    from kram.core.model import TransactionPreview
    from kram.tui.dialogs.apply import ApplyDialog
    use_catalog(monkeypatch, resolve=lambda request, sizes=True: TransactionPreview([], [], 0, 0))

    async def test(app, pilot):
        assert app.ENABLE_COMMAND_PALETTE is False
        await pilot.press("ctrl+p")
        await pilot.pause()
        assert len(app.screen_stack) == 1 and "Nothing is marked" in app.top_line.render().plain
        b = app.main.browser
        b.packages.marks.set(b.snapshot.rows[1], Action.INSTALL)
        b.update_actions()
        await pilot.press("ctrl+p")
        for _ in range(100):
            if isinstance(app.screen, ApplyDialog):
                break
            await pilot.pause(0.02)
        assert isinstance(app.screen, ApplyDialog)
    run(test)


# ---------------------------------------------------------------- About (§10.13)

@pytest.mark.feature(Feature.DIALOG_ABOUT_TOOLKIT, front="tui")
def test_about_names_textual_and_its_version(monkeypatch):
    use_catalog(monkeypatch)
    from kram import HOMEPAGE, __version__

    async def test(app, pilot):
        await open_menu(app, pilot, "Help")
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, AboutDialog)
        about = app.screen
        assert str(about.query_one("#about-version").render()) == f"Kram {__version__}"
        assert str(about.query_one("#about-toolkit").render()) == \
            f"Terminal front end, Textual {textual.__version__}"
        assert about.query_one("#about-homepage").url == HOMEPAGE
        assert about.focused.id == "close"
        about.query_one("#whats-new", Button).action_press()
        await pilot.pause()
        assert isinstance(app.screen, QuestionDialog)  # over About, which stays
        await pilot.press("enter")
        await pilot.pause()
        assert app.screen is about
        await pilot.press("escape")
        await pilot.pause()
        assert len(app.screen_stack) == 1
    run(test)


# ---------------------------------------------------------------- quitting (§10.19)

@pytest.mark.feature(Feature.WINDOW_CLOSE_PENDING, front="tui")
def test_quitting_with_marks_asks_and_cancel_keeps_running(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        b = app.main.browser
        b.packages.marks.set(b.snapshot.rows[1], Action.INSTALL)
        await pilot.press("q")
        await pilot.pause()
        question = app.screen
        assert isinstance(question, QuestionDialog)
        assert question.question.text == "1 marked change has not been applied. Quit anyway?"
        assert [str(button.render()) for button in question.query(Button)] == ["< Quit >", "< Cancel >"]
        assert str(question.focused.render()) == "< Cancel >"
        await pilot.press("ctrl+q")  # asked once
        await pilot.pause()
        assert app.screen is question
        await pilot.press("enter")
        await pilot.pause()
        assert len(app.screen_stack) == 1 and app.return_code is None
        await pilot.press("q")
        await pilot.pause()
        await pilot.press("escape")  # Esc is Cancel
        await pilot.pause()
        assert app.return_code is None
        # a transaction running: no quitting
        monkeypatch.setattr(b, "busy", lambda: True)
        await pilot.press("ctrl+q")
        await pilot.pause()
        assert len(app.screen_stack) == 1 and "Another operation is still running" in app.top_line.render().plain
        monkeypatch.setattr(b, "busy", lambda: False)
        await pilot.press("q")
        await pilot.pause()
        await pilot.press("left", "enter")  # Quit
        await pilot.pause()
    app = run(test)
    assert app.return_code == 0


def test_quitting_without_marks_or_without_the_question_is_at_once(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        await pilot.press("q")
        await pilot.pause()
    assert run(test).return_code == 0
    preferences.set_value(preferences.TUI_CONFIRM_QUIT, False)

    async def with_marks(app, pilot):
        b = app.main.browser
        b.packages.marks.set(b.snapshot.rows[1], Action.INSTALL)
        await open_menu(app, pilot, "File")
        await go_to(app, pilot, "Quit")
        await pilot.press("enter")
        await pilot.pause()
    assert run(with_marks).return_code == 0


# ---------------------------------------------------------------- the sidebar follows the code (§7.6.3)

def test_the_sidebar_s_cursor_follows_a_selection_made_by_code(monkeypatch):
    use_catalog(monkeypatch, snapshot())

    async def test(app, pilot):
        b = app.main.browser
        entries = app.main.sidebar.entries
        assert entries.current_entry().id == "status:all"
        b.sidebar.select("status", "status:installed")  # as Esc in the search and the links do
        await pilot.pause()
        assert entries.current_id == "status:installed" and b.filter.id == "status:installed"
        assert entries.current_entry().id == "status:installed"
        # a redraw of the same entry keeps the cursor where the user moved it
        await pilot.press("g", "down")
        b.sidebar.refresh_counts()
        await pilot.pause()
        assert entries.current_entry().id == "status:not-installed"
    run(test)


def test_every_menu_action_has_a_way_to_run(monkeypatch):
    """Every action the menus hold runs something in the terminal: its own code, or "Not in this version yet"."""
    use_catalog(monkeypatch)

    async def test(app, pilot):
        from kram.tui.window import NOT_YET
        ids = {i.action for m in (*menu_bar(), table_menu()) for i in walk(m.items) if i.action}
        runs = app.main.action_runs()
        assert ids - NOT_YET <= set(runs) and not NOT_YET & set(runs)
    run(test)
