"""The terminal front end's foundation (docs/TUI_SPEC.md §4–§6, §8, §9, §10.21, §12, §13): its layout and who gets a
key, the colours, its own controls, the question dialog, the Ui port, the main loop's port and its settings.

Run with Textual's headless driver (`App.run_test`, `Pilot`): no terminal needed. Skipped without Textual.
"""
import asyncio
import threading

import pytest

pytest.importorskip("textual")

from rich.style import Style  # noqa: E402
from textual.app import App, ComposeResult  # noqa: E402
from textual.containers import Vertical  # noqa: E402
from textual.screen import ModalScreen  # noqa: E402
from textual.widgets import Input  # noqa: E402

from kram.app import preferences  # noqa: E402
from kram.app.ports import CANCEL, NO, OK, YES, Question  # noqa: E402
from kram.app.ports import Button as QuestionButton
from kram.core.marks import Action  # noqa: E402
from kram.core.model import Status  # noqa: E402
from kram.tui import glyphs, loop  # noqa: E402
from kram.tui.__main__ import main, parse_args  # noqa: E402
from kram.tui.app import KramApp, TooSmall  # noqa: E402
from kram.tui.dialogs.path import PathDialog, complete  # noqa: E402
from kram.tui.dialogs.question import QuestionDialog  # noqa: E402
from kram.tui.palette import ROLES, role  # noqa: E402
from kram.tui.widgets import Button, CheckBox, ChoiceList, hint  # noqa: E402

WIDE, NARROW = (120, 40), (80, 24)


@pytest.fixture(autouse=True)
def _made_up_catalog(monkeypatch):
    """The window loads the catalog as it starts: a made-up one here, never the system's (tests/test_tui_window.py
    tests the window itself)."""
    from types import SimpleNamespace

    from kram.app.browser import Browser
    from kram.core.model import CatalogSnapshot
    from kram.tui import window
    catalog = SimpleNamespace(load=lambda *a, **k: CatalogSnapshot([], 0, 0, 0.1), blocked_upgrades=lambda: {})
    monkeypatch.setattr(window, "Browser", lambda view, ui, scheduler, details, post, **kw: Browser(
        view, ui, scheduler, details, post, catalog=catalog, **kw))


def run(test, size=WIDE, app=None):
    """Run `test(app, pilot)` in a headless app of the given terminal size."""
    app = app or KramApp()

    async def go():
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            await test(app, pilot)
    asyncio.run(go())
    return app


def focused_panel(app) -> str | None:
    return next((name for name in ("sidebar", "details") if app.has_focus_in(name)), None) or (
        "list" if app.window.focused is app.list_widget else None)


# ---------------------------------------------------------------- start and keys

def test_starts_wide_with_both_panels_and_the_list_focused():
    async def test(app, pilot):
        assert app.shown_panels() == ["sidebar", "details"]
        assert focused_panel(app) == "list"
        assert app.window.query_one("#body").has_class("tall")
        assert app.window.query_one("#packages").border_title == "Packages"
    run(test)


def test_window_keys_are_off_under_a_modal_screen_and_in_a_text_field():
    async def test(app, pilot):
        assert app.check_action("toggle_panel", ("sidebar",))
        app.push_screen(ChoiceList("Views", [("a", "A"), ("b", "B")], "a"))
        await pilot.pause()
        assert app.check_action("toggle_panel", ("sidebar",)) is False
        assert app.check_action("quit", ()) is False
        await pilot.press("g")  # nothing moves under the modal screen
        assert app.shown_panels() == ["sidebar", "details"] and len(app.screen_stack) == 2
        await pilot.press("escape")
        await pilot.pause()
        assert len(app.screen_stack) == 1 and app.check_action("toggle_panel", ("sidebar",))
        # a text field in the window takes "g" as a letter
        field = Input(id="probe")
        await app.window.query_one("#main").mount(field)
        field.focus()
        await pilot.pause()
        assert app.check_action("toggle_panel", ("sidebar",)) is False
        await pilot.press("g")
        assert field.value == "g" and app.shown_panels() == ["sidebar", "details"]
        app.list_widget.focus()
        await pilot.pause()
        assert app.check_action("toggle_panel", ("sidebar",))
    run(test)


# ---------------------------------------------------------------- panels (§5.2, §6.4)

def test_wide_g_and_d_focus_a_pinned_panel_and_unpin_it_when_pressed_again():
    async def test(app, pilot):
        await pilot.press("g")
        assert focused_panel(app) == "sidebar" and app.shown_panels() == ["sidebar", "details"]
        await pilot.press("g")
        assert focused_panel(app) == "list" and app.shown_panels() == ["details"]
        assert preferences.value(preferences.TUI_PINNED) == "details"
        await pilot.press("g")  # shown and pinned again
        assert focused_panel(app) == "sidebar" and preferences.value(preferences.TUI_PINNED) == "both"
        await pilot.press("escape")  # a pinned panel stays
        assert focused_panel(app) == "list" and app.shown_panels() == ["sidebar", "details"]
        await pilot.press("d", "d")
        assert focused_panel(app) == "list" and app.shown_panels() == ["sidebar"]
        await pilot.press("tab")
        assert focused_panel(app) in ("sidebar", "list")
    run(test)


def test_narrow_panels_slide_over_one_at_a_time():
    async def test(app, pilot):
        assert app.narrow and app.shown_panels() == []
        await pilot.press("g")
        assert app.shown_panels() == ["sidebar"] and focused_panel(app) == "sidebar"
        await pilot.press("d")  # the sidebar makes room for the details
        assert app.shown_panels() == ["details"] and focused_panel(app) == "details"
        assert app.panel("details").styles.height.value == 11
        await pilot.press("escape")  # a slide-over closes
        assert app.shown_panels() == [] and focused_panel(app) == "list"
        await pilot.press("d", "d")
        assert app.shown_panels() == [] and focused_panel(app) == "list"
        assert preferences.value(preferences.TUI_PINNED) == "both"  # a slide-over is not a pin
    run(test, NARROW)


def test_narrow_to_wide_keeps_the_open_slide_over_as_a_pinned_panel():
    async def test(app, pilot):
        await pilot.press("d", "d")  # wide: the details unpinned
        assert app.shown_panels() == ["sidebar"]
        await pilot.resize_terminal(*NARROW)
        await pilot.pause()
        await pilot.press("d")
        assert app.shown_panels() == ["details"]
        await pilot.resize_terminal(*WIDE)
        await pilot.pause()
        assert app.shown_panels() == ["sidebar", "details"] and focused_panel(app) == "details"
        assert preferences.value(preferences.TUI_PINNED) == "both"
    run(test)


def test_wide_to_narrow_hides_every_panel_but_the_focused_one():
    async def test(app, pilot):
        await pilot.press("g")
        await pilot.resize_terminal(*NARROW)
        await pilot.pause()
        assert app.shown_panels() == ["sidebar"] and focused_panel(app) == "sidebar"
        await pilot.resize_terminal(*WIDE)
        await pilot.pause()
        app.list_widget.focus()
        await pilot.resize_terminal(*NARROW)
        await pilot.pause()
        assert app.shown_panels() == [] and focused_panel(app) == "list"
    run(test)


def test_the_details_slide_over_leaves_rows_of_the_list_in_a_tiny_terminal():
    async def test(app, pilot):
        await pilot.press("d")
        assert app.panel("details").styles.height.value == 6  # 3/5 of the 10 lines of the body
    run(test, (40, 12))


def test_a_small_terminal_shows_only_how_large_it_must_be():
    async def test(app, pilot):
        await pilot.press("g")
        await pilot.resize_terminal(39, 11)
        await pilot.pause()
        assert isinstance(app.screen, TooSmall)
        await pilot.press("d")  # nothing else reacts
        assert isinstance(app.screen, TooSmall) and app.check_action("command_palette", ()) is False
        await pilot.resize_terminal(*NARROW)
        await pilot.pause()
        assert not isinstance(app.screen, TooSmall) and len(app.screen_stack) == 1
        assert focused_panel(app) == "sidebar"  # as it was
    run(test)


def test_the_small_terminal_screen_quits_with_q():
    async def test(app, pilot):
        await pilot.press("q")
        await pilot.pause()
    app = run(test, (30, 10))
    assert app.return_code == 0


# ---------------------------------------------------------------- colours (§9)

def test_set_scheme_turns_ansi_colours_on_for_16_colour_schemes_only():
    async def test(app, pilot):
        assert app.theme == "textual-ansi" and app.ansi_color
        for scheme, ansi in (("kram-midnight", True), ("textual-dark", False), ("kram-console", True),
                             ("nord", False), ("textual-ansi", True)):
            app.set_scheme(scheme)
            await pilot.pause()
            assert (app.theme, app.ansi_color) == (scheme, ansi)
            assert preferences.value(preferences.TUI_SCHEME) == scheme
        app.set_scheme("textual-light", save=False)  # a preview
        assert preferences.value(preferences.TUI_SCHEME) == "textual-ansi"
    run(test)


def test_a_theme_changed_elsewhere_is_followed_and_saved():
    async def test(app, pilot):
        app.theme = "kram-midnight"  # as Textual's command palette does
        await pilot.pause()
        await pilot.pause()
        assert app.ansi_color and preferences.value(preferences.TUI_SCHEME) == "kram-midnight"
    run(test)


def test_the_saved_scheme_is_used_at_start():
    preferences.set_value(preferences.TUI_SCHEME, "gruvbox")

    async def test(app, pilot):
        assert app.theme == "gruvbox" and not app.ansi_color
    run(test)


def test_roles_have_styles_once_mounted():
    async def test(app, pilot):
        assert all(isinstance(role(name), Style) for name in ROLES)
        assert role("key").bold and role("key").color is not None
        assert role("muted") != Style() and role("current").reverse
        with pytest.raises(KeyError):
            role("purple")
        text = hint(("g", "hide"), ("esc", "list"))
        assert text.plain == "g hide  esc list" and text.spans[0].style == role("key")
    run(test)


def test_no_color_drops_the_colours_of_the_roles(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    preferences.set_value(preferences.TUI_SCHEME, "nord")

    async def test(app, pilot):
        assert app.theme == "textual-ansi"  # the Terminal scheme, whatever was saved
        assert role("key").bold and role("key").color is None
    run(test)


# ---------------------------------------------------------------- glyphs (§4.4, §7.3.4, §9.6)

def test_utf8_is_read_from_the_locale_variables():
    assert glyphs.is_utf8({"LANG": "uk_UA.UTF-8"})
    assert glyphs.is_utf8({"LC_ALL": "en_US.utf8", "LANG": "C"})
    assert not glyphs.is_utf8({"LANG": "C"})
    assert not glyphs.is_utf8({})
    assert not glyphs.is_utf8({"LANG": "de_DE.ISO-8859-1"})
    assert not glyphs.is_utf8({"LANG": "C", "LC_CTYPE": "C.UTF-8"})  # Python's own coercion of the C locale
    assert glyphs.is_utf8({"LC_ALL": "C.UTF-8"})


def test_glyph_sets_for_utf8_and_not():
    assert glyphs.glyphs(True).panel_border == "solid" and glyphs.glyphs(True).modal_border == "double"
    assert (glyphs.glyphs(True).left, glyphs.glyphs(True).ellipsis) == ("←", "…")
    assert glyphs.glyphs(False).panel_border == "ascii" and glyphs.glyphs(False).modal_border == "ascii"
    assert (glyphs.glyphs(False).left, glyphs.glyphs(False).right, glyphs.glyphs(False).ellipsis) == ("<-", "->",
                                                                                                    "...")
    symbols = glyphs.status_glyphs(utf8=True, setting="auto")
    assert symbols.status[Status.UPGRADABLE] == "▲" and symbols.marks[Action.UPGRADE] == "↑"
    assert glyphs.status_glyphs(utf8=True, setting="letters").status[Status.UPGRADABLE] == "u"
    letters = glyphs.status_glyphs(utf8=False, setting="auto")
    assert letters.status[Status.INSTALLED] == "i" and letters.marks[Action.DOWNGRADE] == "v"
    for glyph_set in (symbols, letters):
        assert set(glyph_set.status) == set(Status) and set(glyph_set.marks) == set(Action)
    assert all(c.isascii() for c in [*letters.status.values(), *letters.marks.values()])


def test_ascii_borders_on_a_terminal_that_is_not_utf8(monkeypatch):
    monkeypatch.setenv("LANG", "C")
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LC_CTYPE", raising=False)

    async def test(app, pilot):
        assert app.panel("sidebar").styles.border_top[0] == "ascii"
    run(test)


def test_box_borders_on_a_utf8_terminal(monkeypatch):
    monkeypatch.setenv("LC_ALL", "en_US.UTF-8")

    async def test(app, pilot):
        assert app.panel("sidebar").styles.border_top[0] == "solid"
        app.push_screen(ChoiceList("Views", [("a", "A")]))
        await pilot.pause()
        assert app.screen.query_one(".window").styles.border_top[0] == "double"
    run(test)


# ---------------------------------------------------------------- controls (§8)

class Controls(App):
    def __init__(self):
        super().__init__()
        self.events: list[tuple] = []

    def compose(self) -> ComposeResult:
        yield Button("Apply", id="apply", variant="primary")
        yield Button("Off", id="off", disabled=True)
        yield CheckBox("Download only", id="box")
        yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.events.append(("pressed", event.button.id))

    def on_check_box_changed(self, event: CheckBox.Changed) -> None:
        self.events.append(("changed", event.value))


def test_button_and_checkbox_keys_and_a_disabled_button_skipped_by_tab():
    async def test(app, pilot):
        apply = app.query_one("#apply", Button)
        apply.focus()
        await pilot.press("enter", "space")
        await pilot.press("tab")
        assert app.focused.id == "box"  # past the disabled one
        await pilot.press("space", "enter")
        box = app.query_one("#box", CheckBox)
        assert box.render().plain == "[ ] Download only" and not box.value
        await pilot.press("space")
        assert box.render().plain == "[x] Download only"
        await pilot.press("tab")
        assert app.focused.id == "cancel"
        off = app.query_one("#off", Button)
        off.action_press()
        await pilot.pause()
        assert app.events == [("pressed", "apply"), ("pressed", "apply"), ("changed", True), ("changed", False),
                              ("changed", True)]
        assert off.render().plain == "< Off >" and off.has_class("-off") and not off.can_focus
        app.query_one("#cancel", Button).set_enabled(False)  # a focused button that goes off gives up the focus
        await pilot.pause()
        assert app.focused is not None and app.focused.id != "cancel"
        off.set_enabled(True)
        assert off.can_focus and not off.has_class("-off")
    run(test, app=Controls())


def test_choice_list_returns_the_chosen_value():
    chosen = []

    async def test(app, pilot):
        app.push_screen(ChoiceList("Colours", [("a", "A"), ("b", "B"), ("c", "C")], "b"), chosen.append)
        await pilot.pause()
        await pilot.press("down", "enter")
        await pilot.pause()
        app.push_screen(ChoiceList("Colours", [("a", "A")]), chosen.append)
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
    run(test)
    assert chosen == ["c", None]


# ---------------------------------------------------------------- the question dialog (§10.21) and the Ui port

def ask(question: Question, keys: list[str]) -> list:
    answers = []

    async def test(app, pilot):
        app.ui.ask(question, answers.append)
        await pilot.pause()
        assert isinstance(app.screen, QuestionDialog) and app.ui.is_modal_open()
        assert app.check_action("toggle_panel", ("sidebar",)) is False
        await pilot.press(*keys)
        await pilot.pause()
        assert not app.ui.is_modal_open()
    run(test)
    return answers


def test_the_question_dialog_returns_the_button_pressed():
    assert ask(Question("Remove", "Remove vim?"), ["enter"]) == ["yes"]  # the accepting button is focused
    assert ask(Question("Remove", "Remove vim?"), ["right", "enter"]) == ["no"]
    assert ask(Question("Remove", "Remove vim?", default="no"), ["enter"]) == ["no"]
    custom = Question("Keys", "Import the key?", buttons=(QuestionButton("import", "Import", "destructive"), CANCEL))
    assert ask(custom, ["tab", "enter"]) == ["cancel"]


def test_escape_is_the_cancel_answer_or_none():
    assert ask(Question("Remove", "Remove vim?", buttons=(YES, NO)), ["escape"]) == ["no"]
    assert ask(Question("Show", "Show them?", buttons=(OK, QuestionButton("show", "Show"))), ["escape"]) == [None]


def test_messages_and_status():
    async def test(app, pilot):
        app.ui.error("Failed", "It did not work.", informative="Try again.", details="a long log")
        await pilot.pause()
        dialog = app.screen
        assert isinstance(dialog, QuestionDialog) and [b.render().plain for b in dialog.query(Button)] == ["< OK >"]
        await pilot.press("enter")
        await pilot.pause()
        app.ui.status("Loading", 0)
        assert app.window.query_one("#top").render().plain.startswith("Kram  Loading")
        app.ui.copy_text("vim-enhanced")
        assert app.clipboard == "vim-enhanced"
        assert app.window.query_one("#top").render().plain.startswith("Kram  Copied")
    run(test)


def test_links_without_a_desktop_are_copied(monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

    async def test(app, pilot):
        assert app.ui.open_web_link("file:///etc/passwd") is False and app.clipboard == ""
        assert app.ui.open_web_link("https://example.org/") is True and app.clipboard == "https://example.org/"
        app.ui.show_in_file_manager("/usr/bin/vim")
        assert app.clipboard == "/usr/bin/vim"
        assert "copied" in app.window.query_one("#top").render().plain
    run(test)


def test_path_completion(tmp_path):
    (tmp_path / "marks.txt").write_text("")
    (tmp_path / "markings").mkdir()
    (tmp_path / "other.rpm").write_text("")
    (tmp_path / ".hidden").write_text("")
    base = f"{tmp_path}/"
    assert complete(base + "mark") == (base + "mark", ["markings/", "marks.txt"])
    assert complete(base + "markin") == (base + "markings/", [])
    assert complete(base + "o") == (base + "other.rpm", [])
    assert complete(base, ["*.rpm"]) == (base, ["markings/", "other.rpm"])
    assert complete(base + ".") == (base + ".hidden", [])
    assert complete(base + "nothing") == (base + "nothing", [])
    assert complete("~") == ("~/", [])


def test_choosing_files(tmp_path):
    existing = tmp_path / "kram-markings.txt"
    existing.write_text("")
    chosen = []

    async def test(app, pilot):
        app.ui.choose_open_file("Read Markings", str(tmp_path), "Text files (*.txt)", chosen.append)
        await pilot.pause()
        field = app.screen.query_one(Input)
        assert isinstance(app.screen, PathDialog) and field.value == f"{tmp_path}/"
        await pilot.press("tab")  # the only matching file
        assert field.value == str(existing)
        await pilot.press("enter")
        await pilot.pause()
        app.ui.choose_save_file("Save Markings", str(existing), "", chosen.append)
        await pilot.pause()
        await pilot.press("enter")  # it exists: asked first, Cancel focused
        await pilot.pause()
        assert isinstance(app.screen, QuestionDialog)
        await pilot.press("left", "enter")  # Replace
        await pilot.pause()
        await pilot.pause()
        app.ui.choose_save_file("Save Markings", str(tmp_path / "missing" / "x.txt"), "", chosen.append)
        await pilot.pause()
        await pilot.press("enter")  # no such folder: it stays open
        await pilot.pause()
        assert isinstance(app.screen, PathDialog)
        await pilot.press("escape")
        await pilot.pause()
    run(test)
    assert chosen == [str(existing), str(existing), None]


# ---------------------------------------------------------------- the main loop's port

def test_post_from_another_thread_runs_on_the_apps_thread():
    seen = []

    async def test(app, pilot):
        me = threading.get_ident()
        worker = threading.Thread(target=lambda: loop.post(lambda: seen.append(threading.get_ident())))
        worker.start()
        worker.join()
        loop.post(lambda: seen.append("same thread"))
        for _ in range(20):
            if len(seen) == 2:
                break
            await pilot.pause(0.01)
        assert seen == [me, "same thread"]
    run(test)


def test_scheduler_timers():
    fired = []

    async def test(app, pilot):
        scheduler = loop.TuiScheduler()
        timer = scheduler.timer(20, lambda: fired.append("timer"))
        assert not timer.active
        timer.start()
        assert timer.active
        await pilot.pause(0.1)
        assert fired == ["timer"] and not timer.active
        timer.start()
        timer.stop()
        assert not timer.active
        await pilot.pause(0.1)
        assert fired == ["timer"]
        scheduler.later(lambda: fired.append("later"))
        await pilot.pause()
        assert fired == ["timer", "later"]
    run(test)


# ---------------------------------------------------------------- settings (§13)

def test_tui_settings_are_the_terminals_own_and_saved():
    tui = {p.key for p in preferences.prefs_for("tui")} | {p.key for p in preferences.prefs_for("tui", "layout")}
    own = {preferences.TUI_SCHEME, preferences.TUI_CENTRE_SCROLLING, preferences.TUI_STATUS_GLYPHS,
           preferences.TUI_CONFIRM_QUIT, preferences.TUI_SIDEBAR_WIDTH, preferences.TUI_DETAILS_HEIGHT,
           preferences.TUI_PINNED}
    # and the shared ones that mean something in a terminal (§13.1)
    assert tui == own | {preferences.STATUS_CLICK, preferences.WATCH_RELEASES}
    for gui in ("qt", "gtk"):
        assert not {p.key for p in preferences.PREFS if gui in p.toolkits} & own
    assert preferences.value(preferences.TUI_CENTRE_SCROLLING) is True
    preferences.set_value(preferences.TUI_CENTRE_SCROLLING, False)
    preferences.set_value(preferences.TUI_SIDEBAR_WIDTH, 500)
    preferences.store.sync()
    assert preferences.value(preferences.TUI_CENTRE_SCROLLING) is False
    assert preferences.value(preferences.TUI_SIDEBAR_WIDTH) == 60  # its largest
    assert "[tui]\ncentre_scrolling=false" in preferences.store.path.read_text()


def test_saved_panel_sizes_are_used():
    preferences.set_value(preferences.TUI_SIDEBAR_WIDTH, 34)
    preferences.set_value(preferences.TUI_PINNED, "sidebar")

    async def test(app, pilot):
        assert app.panel("sidebar").styles.width.value == 34 and app.shown_panels() == ["sidebar"]
    run(test)


# ---------------------------------------------------------------- the command line (§15.2)

def test_command_line(capsys):
    assert parse_args(["--upgradable"]).upgradable and parse_args(["x.rpm"]).file == "x.rpm"
    with pytest.raises(SystemExit) as stop:
        parse_args(["--version"])
    assert stop.value.code == 0 and "kram-tui" in capsys.readouterr().out
    assert main(["vim.rpm"]) == 2 and "later version" in capsys.readouterr().err
    app = KramApp(upgradable=True, file=None)
    assert app.upgradable and app.file is None


def test_a_modal_window_is_transparent_in_16_colours():
    async def test(app, pilot):
        class Probe(ModalScreen):
            def compose(self) -> ComposeResult:
                yield Vertical()
        app.push_screen(Probe())
        await pilot.pause()
        assert app.screen.styles.background.a == 0
        app.set_scheme("textual-dark")
        await pilot.pause()
        await pilot.pause()
        assert app.screen.styles.background.a > 0
    run(test)
