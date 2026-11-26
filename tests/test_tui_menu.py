"""The terminal front end's menus and the dialogs they lead to (docs/TUI_SPEC.md §7.7, §10.13, §10.17, §10.19,
§10.20, §13): the menu popup over `tui_menu_bar()`, the package list's context menu, the settings of the registry,
Colours, Keys, About and quitting; and the keys of kram.tui.keymap.

The entries are built and drawn by functions of kram.tui.menu, tested here against the real window's state; the
popup is opened and worked through its API. Keys are pressed only where the key is what is tested (§14.2).
"""
import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("textual")

import textual  # noqa: E402
from rich.style import Style  # noqa: E402
from test_tui_window import WIDE, loaded, snapshot, use_catalog  # noqa: E402
from textual.widgets import OptionList  # noqa: E402
from tui_kit import cells, plain, scheme_fixture, styles_at  # noqa: E402, F401 - a fixture

from kram.app import preferences  # noqa: E402
from kram.app.actions import table_menu, walk  # noqa: E402
from kram.app.parity import Feature  # noqa: E402
from kram.core import releases  # noqa: E402
from kram.core.marks import Action  # noqa: E402
from kram.core.model import CatalogSnapshot, Origin, PkgRow, Status  # noqa: E402
from kram.tui.app import KramApp  # noqa: E402
from kram.tui.dialogs.about import AboutDialog, WhatsNewDialog  # noqa: E402
from kram.tui.dialogs.colours import ColoursDialog  # noqa: E402
from kram.tui.dialogs.keys import KeysDialog  # noqa: E402
from kram.tui.dialogs.question import QuestionDialog  # noqa: E402
from kram.tui.glyphs import UNICODE  # noqa: E402
from kram.tui.menu import Entry, MenuPopup, entry_line, menu_entries, menu_title, tui_menu_bar  # noqa: E402
from kram.tui.palette import role  # noqa: E402
from kram.tui.search import SearchDialog  # noqa: E402
from kram.tui.widgets import Button, PopupMenu  # noqa: E402

NARROW = (64, 22)
MENUS = [menu_title(m) for m in tui_menu_bar()]


def run(test, size=WIDE):
    app = KramApp()

    async def go():
        async with app.run_test(size=size) as pilot:
            await loaded(app, pilot)
            await test(app, pilot)
    asyncio.run(go())
    return app


def entries(app, title: str) -> list[Entry]:
    """The menu `title`'s entries as the window's state makes them, without the separators."""
    menu = tui_menu_bar()[MENUS.index(title)]
    return [e for e in menu_entries(app.main, menu.items, app.glyphs, app.scheme) if e is not None]


def entry(app, title: str, label: str) -> Entry:
    return next(e for e in entries(app, title) if e.label.startswith(label))


async def open_menu(app, pilot, title: str) -> MenuPopup:
    """The menu popup on the menu `title`."""
    app.action_menu()
    await pilot.pause()
    popup = app.screen
    assert isinstance(popup, MenuPopup)
    popup.show_menu(MENUS.index(title))
    return popup


def shown(popup: MenuPopup) -> list[str]:
    """The entries' column as shown, without the padding at the right."""
    return [o.prompt.plain.rstrip() for o in popup.query_one("#menu-entries", OptionList).options]


def status(popup: MenuPopup) -> str:
    return str(popup.query_one("#menu-status").render())


def highlighted(popup: MenuPopup) -> str:
    column = popup.query_one("#menu-entries", OptionList)
    return column.get_option_at_index(column.highlighted).prompt.plain


# ---------------------------------------------------------------- the entries (§7.7.1)

@pytest.mark.feature(Feature.MENU_PACKAGE, front="tui")
def test_the_menus_are_the_menu_bar_s_and_package_has_every_package_action(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        assert MENUS == ["File", "Edit", "Package", "Settings", "Help"]
        labels = [e.label for e in entries(app, "Package")]
        package = [app.main.defs[i.action].label for i in tui_menu_bar()[2].items if i.action and i.action != "why_blocked"]
        assert all(label in labels for label in package)
        assert "Downgrade to Version" in labels
        assert "Why It Cannot Be Upgraded" not in labels  # only for a blocked one
        assert entries(app, "File")[0].label.startswith("Open Package File…")
    run(test)


@pytest.mark.feature(Feature.MENU_ACCELERATORS, front="tui")
def test_the_entries_show_the_terminal_s_keys(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        keys = {e.label: e.key for e in entries(app, "File") + entries(app, "Edit")}
        assert keys["Reload"] == "f5" and keys["Reload from cache"] == "R" and keys["Read Markings…"] == "ctrl+o"
        find = next(key for label, key in keys.items() if label.startswith("Find"))
        assert keys["Quit"] == "q" and find == "/" and keys["Unmark All"] == "Z"
        assert keys["Apply"] == "a"  # not the GUIs' Ctrl+P
    run(test)


def test_an_entry_that_is_off_is_dim_and_says_why(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        save = entry(app, "File", "Save Markings As…")
        assert not save.enabled and save.note == "Nothing is marked"
        assert {s.dim for s in styles_at(entry_line(save, 40, app.glyphs), "Save")} == {True}
        opened = entry(app, "File", "Open Package File…")
        assert opened.enabled and opened.note.startswith("Install a downloaded .rpm file")
        # the same action by its key: the top line says why
        app.main.run_action("save_marks")
        await pilot.pause()
        assert "Nothing is marked" in app.top_line.render().plain
    run(test)


def test_an_entry_line_fits_its_width(scheme):
    e = Entry("action", "Mark Upgrades of Every Kind, Security and Bug Fixes", "U")
    line = entry_line(e, 30, UNICODE)
    assert line.cell_len == 30 and plain(line).rstrip().endswith(f"{UNICODE.ellipsis}  U")
    assert cells(line)[-1] == ("U", role("muted"))
    sub = entry_line(Entry("submenu", "Status glyphs", UNICODE.right), 30, UNICODE)
    assert plain(sub).rstrip().endswith(UNICODE.right)


def test_a_ticked_setting_shows_its_tick_in_the_marked_role(scheme):
    pref = preferences.pref(preferences.TUI_CENTRE_SCROLLING)
    line = entry_line(Entry("bool", pref.label, pref=pref), 50, UNICODE)
    assert plain(line).startswith("[x] Centre") and styles_at(line, "[x]") == {role("marked")}
    preferences.set_value(pref, False)
    line = entry_line(Entry("bool", pref.label, pref=pref), 50, UNICODE)
    assert plain(line).startswith("[ ] Centre") and styles_at(line, "[ ]") == {Style()}


# ---------------------------------------------------------------- the popup (§7.7.1)

@pytest.mark.feature(Feature.WINDOW_KEYBOARD_ONLY, front="tui")
def test_m_and_f9_open_the_menu_and_the_arrows_reach_an_entry(monkeypatch):
    """Every action is in the menu (§6.6), reached and run by keys alone; the window's keys are off meanwhile."""
    use_catalog(monkeypatch)

    async def test(app, pilot):
        b = app.main.browser
        reloads = []
        monkeypatch.setattr(b, "reload", lambda: reloads.append(True))
        for key in ("m", "f9"):
            await pilot.press(key)
            await pilot.pause()
            assert isinstance(app.screen, MenuPopup)
            for action, params in (("find", ()), ("toggle_panel", ("sidebar",)), ("menu", ()), ("quit", ()),
                                   ("run", ("reload_cache",))):
                assert app.check_action(action, params) is False
            await pilot.press("escape")
            await pilot.pause()
            assert len(app.screen_stack) == 1
        await pilot.press("m", "right")  # File's entries
        while not highlighted(app.screen).startswith("Reload from cache"):
            await pilot.press("down")
        await pilot.press("enter")
        await pilot.pause()
        assert reloads == [True] and len(app.screen_stack) == 1
    run(test)


def test_an_entry_runs_its_action_once_the_popup_is_gone(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        popup = await open_menu(app, pilot, "Edit")
        popup.choose(popup.entry("Find"))
        await pilot.pause()
        assert isinstance(app.screen, SearchDialog) and app.screen_stack[-2] is not popup
        app.pop_screen()
        popup = await open_menu(app, pilot, "Help")
        popup.choose(popup.entry("About Kram"))
        await pilot.pause()
        assert isinstance(app.screen, AboutDialog)
        app.pop_screen()
        popup = await open_menu(app, pilot, "File")
        popup.choose(popup.entry("Save Markings As…"))  # off: nothing runs, the popup stays
        await pilot.pause()
        assert app.screen is popup
    run(test)


@pytest.mark.feature(Feature.MENU_DOWNGRADE_SUBMENU, front="tui")
def test_submenus_open_in_place_and_downgrade_is_filled_when_it_opens(monkeypatch):
    use_catalog(monkeypatch)
    versions = [SimpleNamespace(evr="1.0-1", installed=True, locked_out=False, repo_id="@System"),
                SimpleNamespace(evr="0.9-1", installed=False, locked_out=False, repo_id="fedora"),
                SimpleNamespace(evr="0.8-1", installed=False, locked_out=False, repo_id="fedora")]

    async def test(app, pilot):
        b = app.main.browser
        marked, asked = [], []
        monkeypatch.setattr(b, "mark_selected", lambda action, evr="": marked.append((action, evr)))

        def details_of(key):
            asked.append(key)
            return SimpleNamespace(versions=versions)
        monkeypatch.setattr(b.details_loader, "details_of", details_of)
        popup = await open_menu(app, pilot, "Package")
        assert not asked  # not before it opens
        popup.choose(popup.entry("Downgrade to Version"))
        assert asked == [("pkg0000", "x86_64")]
        g = app.glyphs
        assert shown(popup) == [f"{g.left} Downgrade to Version", "0.9-1  (fedora)", "0.8-1  (fedora)"]
        popup.back()  # onto the entry it was opened from
        assert highlighted(popup).startswith("Downgrade to Version") and "Mark for Removal" in " ".join(shown(popup))
        popup.choose(popup.entry("Downgrade to Version"))
        popup.choose(popup.entries[0])  # the back line works as ← does
        assert highlighted(popup).startswith("Downgrade to Version")
        popup.choose(popup.entry("Downgrade to Version"))
        popup.choose(popup.entry("0.8-1"))
        await pilot.pause()
        assert marked == [(Action.DOWNGRADE, "0.8-1")] and len(app.screen_stack) == 1
        app.main.list.select(1)  # not installed: the submenu is off and says why
        assert entry(app, "Package", "Downgrade to Version").note == "Not for this package"
    run(test)


def test_left_and_right_move_between_the_menus_and_into_a_submenu(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        popup = await open_menu(app, pilot, "Package")
        await pilot.press("right")  # into the entries
        while not highlighted(popup).startswith("Downgrade to Version"):
            await pilot.press("down")
        await pilot.press("right")  # into the submenu
        assert popup.stack and shown(popup)[0].endswith("Downgrade to Version")
        await pilot.press("left")  # out of it
        assert not popup.stack and highlighted(popup).startswith("Downgrade to Version")
        await pilot.press("left")  # to the menus
        assert popup.query_one("#menu-titles").has_focus
    run(test)


def test_the_menu_fits_a_narrow_terminal(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        popup = await open_menu(app, pilot, "Edit")
        assert popup.query_one("#menu-box").region.width <= NARROW[0]
        assert next(line for line in shown(popup) if line.startswith("Mark Upgrades")).endswith(app.glyphs.right)
    run(test, NARROW)


def test_the_menu_opens_at_the_top_left_under_the_top_line(monkeypatch):
    """§7.7.1: where a GUI's menu bar drops its menus; on a short terminal too, whole."""
    use_catalog(monkeypatch)

    for size in (WIDE, NARROW, (64, 12)):
        async def test(app, pilot):
            box = (await open_menu(app, pilot, "File")).query_one("#menu-box").region
            assert (box.x, box.y) == (0, 1) and box.bottom <= app.size.height
        run(test, size)


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
        popup = await open_menu(app, pilot, "Settings")
        lines = [" ".join(line.split()) for line in shown(popup)]
        assert lines[lines.index("New Filter from Current View…") + 1:] == [
            "[ ] Clicking the status icon marks the likely action", "[x] Watch Fedora Releases",
            "[x] Centre the cursor when scrolling", f"Status glyphs {app.glyphs.right}",
            "[x] Ask before quitting with changes not applied", "Colours…", "Columns…"]
        centre = popup.entry("Centre")
        assert centre.note == ""  # it has no tooltip
        popup.choose(centre)  # ticked in place; the menu stays
        assert preferences.value(preferences.TUI_CENTRE_SCROLLING) is False and not app.main.list.centre
        assert "[ ] Centre the cursor when scrolling" in [" ".join(line.split()) for line in shown(popup)]
        glyph_choice = popup.entry("Status glyphs")
        assert glyph_choice.note == "Symbols, or letters when the terminal is not UTF-8"  # the choice made
        popup.choose(glyph_choice)
        g = app.glyphs
        assert shown(popup) == [f"{g.left} Status glyphs",
                                f"({g.item}) Symbols, or letters when the terminal is not UTF-8", "( ) Letters"]
        popup.choose(popup.entry("Letters"))
        await pilot.pause()
        assert preferences.value(preferences.TUI_STATUS_GLYPHS) == "letters"
        assert highlighted(popup).startswith("Status glyphs")
        assert app.main.list.symbols.status[next(iter(app.main.list.symbols.status))].isalpha()
    run(test)


def test_colours_previews_the_scheme_and_esc_puts_it_back(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        assert app.theme == "textual-ansi"
        popup = await open_menu(app, pilot, "Settings")
        popup.choose(popup.entry("Colours…"))
        await pilot.pause()
        dialog = app.screen
        assert isinstance(dialog, ColoursDialog)
        listing = dialog.query_one(OptionList)
        listing.highlighted = dialog.values.index("kram-turbo")
        await pilot.pause()
        assert app.theme == "kram-turbo" and preferences.value(preferences.TUI_SCHEME) == "textual-ansi"
        listing.highlighted = dialog.values.index("textual-dark")
        await pilot.pause()
        assert app.theme == "textual-dark" and not app.ansi_color
        dialog.action_close()
        await pilot.pause()
        assert len(app.screen_stack) == 1 and app.theme == "textual-ansi" and app.ansi_color
        assert preferences.value(preferences.TUI_SCHEME) == "textual-ansi"
        app.open_colours()
        await pilot.pause()
        listing = app.screen.query_one(OptionList)
        listing.highlighted = app.screen.values.index("kram-turbo")
        listing.action_select()
        await pilot.pause()
        assert len(app.screen_stack) == 1 and app.theme == "kram-turbo"
        assert preferences.value(preferences.TUI_SCHEME) == "kram-turbo"
    run(test)


@pytest.mark.parametrize("start", ["textual-dark", "kram-console"])
def test_colours_opens_and_walks_from_any_scheme(monkeypatch, start):
    """Opening Colours… in a true-colour scheme stopped the app: the window under the dialog was drawn with a
    16-colour scheme's styles under the true-colour filter. A late theme signal put the stale scheme back."""
    use_catalog(monkeypatch)

    async def test(app, pilot):
        app.set_scheme(start)
        await pilot.pause()
        app.open_colours()
        await pilot.pause()
        dialog = app.screen
        assert isinstance(dialog, ColoursDialog) and app.theme == app.scheme == start
        listing = dialog.query_one(OptionList)
        for index in range(len(dialog.values)):
            listing.highlighted = index
            await pilot.pause()
            assert app.theme == dialog.values[index]
        dialog.action_close()
        await pilot.pause()
        assert app.theme == app.scheme == start and app.ansi_color == (start == "kram-console")
        assert preferences.value(preferences.TUI_SCHEME) == start
    run(test)


# ---------------------------------------------------------------- the context menu (§7.7.2)

@pytest.mark.feature(Feature.LIST_CONTEXT_MENU, front="tui")
def test_the_row_s_context_menu(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        b = app.main.browser
        marked = []
        monkeypatch.setattr(b, "mark_selected", lambda action, evr="": marked.append(action))
        for key in ("full_stop", "shift+f10", "f22", "f16", "menu"):  # its keys
            await pilot.press(key)
            await pilot.pause()
            assert isinstance(app.screen, PopupMenu) and app.screen.title_text == "pkg0000"
            app.pop_screen()
        app.main.list.select(1)  # pkg0001, not installed
        app.main.list.action_context_menu()
        await pilot.pause()
        menu = app.screen.query_one(OptionList)
        lines = [o.prompt.plain.rstrip() for o in menu.options]
        labels = [app.main.defs[i.action].label for i in table_menu().items if i.action and i.action != "why_blocked"]
        assert [line.split("  ")[0].rstrip() for line in lines if not line.startswith("Downgrade")] == labels
        assert lines[0].endswith(" +") and lines[-1].endswith(" Y")  # with the keys
        on = [o.prompt.plain.split("  ")[0] for o in menu.options if not o.disabled]
        assert on[0] == "Mark for Installation" and "Mark for Removal" not in on
        assert menu.region.y == app.main.list.content_region.y + 3  # next to the cursor's row
        menu.highlighted = 0
        menu.action_select()
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


def test_plus_marks_the_upgrade_of_an_upgradable_package(monkeypatch):
    # `+` runs the first of its two actions that is on: Textual passed `run_either` only the first (install)
    found = [PkgRow("pkg0000", "x86_64", "Summary", "1.0-1", "2.0-1", "fedora", 1000, Origin.FEDORA,
                    Status.UPGRADABLE)]
    use_catalog(monkeypatch, snap=CatalogSnapshot(found, 1, 0, 0.1, descriptions=[""]))

    async def test(app, pilot):
        ran = []
        monkeypatch.setattr(app.main.browser, "mark_selected", lambda action, evr="": ran.append(action))
        await pilot.press("plus")
        assert ran == [Action.UPGRADE]
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
        app.pop_screen()
        app.main.sidebar.entries.focus()
        await pilot.press("f1")
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
        await pilot.pause()
        assert isinstance(app.screen, ApplyDialog)
    run(test)


# ---------------------------------------------------------------- About (§10.13)

@pytest.mark.feature(Feature.DIALOG_ABOUT_TOOLKIT, front="tui")
@pytest.mark.feature(Feature.DIALOG_WHATS_NEW, front="tui")
@pytest.mark.feature(Feature.DIALOG_WHATS_NEW_OVER_ABOUT, front="tui")
def test_about_names_textual_and_its_version(monkeypatch):
    """…and What's New opens over it (§10.14): the release notes, newest first, scrolling."""
    use_catalog(monkeypatch)
    from kram import HOMEPAGE, __version__

    async def test(app, pilot):
        app.main.run_action("about")
        await pilot.pause()
        about = app.screen
        assert isinstance(about, AboutDialog)
        assert str(about.query_one("#about-version").render()) == f"Kram {__version__}"
        assert str(about.query_one("#about-toolkit").render()) == \
            f"Terminal front end, Textual {textual.__version__}"
        assert about.query_one("#about-homepage").url == HOMEPAGE
        assert about.focused.id == "close"
        about.query_one("#whats-new", Button).action_press()
        await pilot.pause()
        whats_new = app.screen
        assert isinstance(whats_new, WhatsNewDialog) and app.screen_stack[-2] is about  # over About, which stays
        notes = releases.load()
        text = str(whats_new.query_one("#whats-new").render())
        assert text.startswith(f"{notes[0].version} — {notes[0].date}")  # the newest first
        assert text.index(f"{notes[1].version} — ") > text.index(notes[0].items[0][:20])
        scroll = whats_new.query_one("#whats-new-scroll")
        assert whats_new.focused is scroll and scroll.max_scroll_y > 0
        await pilot.press("pagedown")  # it scrolls by the keys
        await pilot.pause()
        assert scroll.scroll_y > 0
        await pilot.press("escape")
        await pilot.pause()
        assert app.screen is about
    run(test)


# ---------------------------------------------------------------- quitting (§10.19)

@pytest.mark.feature(Feature.WINDOW_CLOSE_PENDING, front="tui")
def test_quitting_with_marks_asks_and_cancel_keeps_running(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        b = app.main.browser
        b.packages.marks.set(b.snapshot.rows[1], Action.INSTALL)
        app.request_quit()
        await pilot.pause()
        question = app.screen
        assert isinstance(question, QuestionDialog)
        assert question.question.text == "1 marked change has not been applied. Quit anyway?"
        assert [str(button.render()) for button in question.query(Button)] == ["< Quit >", "< Cancel >"]
        assert str(question.focused.render()) == "< Cancel >"
        app.request_quit()  # asked once
        await pilot.pause()
        assert app.screen is question
        await pilot.press("escape")  # Esc is Cancel
        await pilot.pause()
        assert len(app.screen_stack) == 1 and app.return_code is None
        # a transaction running: no quitting
        monkeypatch.setattr(b, "busy", lambda: True)
        app.request_quit()
        await pilot.pause()
        assert len(app.screen_stack) == 1 and "Another operation is still running" in app.top_line.render().plain
        monkeypatch.setattr(b, "busy", lambda: False)
        app.request_quit()
        await pilot.pause()
        next(w for w in app.screen.query(Button) if str(w.render()) == "< Quit >").action_press()
        await pilot.pause()
    app = run(test)
    assert app.return_code == 0


def test_quitting_without_marks_or_without_the_question_is_at_once(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        await pilot.press("q")  # its key
        await pilot.pause()
    assert run(test).return_code == 0
    preferences.set_value(preferences.TUI_CONFIRM_QUIT, False)

    async def with_marks(app, pilot):
        b = app.main.browser
        b.packages.marks.set(b.snapshot.rows[1], Action.INSTALL)
        app.request_quit()
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
        entries.action_move(1)
        b.sidebar.refresh_counts()
        await pilot.pause()
        assert entries.current_entry().id == "status:not-installed"
    run(test)


def test_every_menu_action_has_a_way_to_run(monkeypatch):
    """Every action the menus hold runs something of its own in the terminal."""
    use_catalog(monkeypatch)

    async def test(app, pilot):
        ids = {i.action for m in (*tui_menu_bar(), table_menu()) for i in walk(m.items) if i.action}
        assert ids <= set(app.main.action_runs())
    run(test)


def test_there_are_no_update_notifications_in_the_terminal(monkeypatch):
    """A tray icon and the desktop's notifiers mean nothing over SSH or without a desktop: the GUIs' entry is not
    in the Settings menu, and nothing runs it."""
    use_catalog(monkeypatch)

    async def test(app, pilot):
        assert "Update Notifications…" not in [e.label for e in entries(app, "Settings")]
        assert "notifications" not in app.main.action_runs()
    run(test)
