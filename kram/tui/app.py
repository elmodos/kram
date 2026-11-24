"""The terminal front end's application: the window's layout, who gets a key, the colours (docs/TUI_SPEC.md §5, §6,
§9). It is a view over kram.app, as kram.gtk's window is; the panels' contents come from their own modules.

Who gets a key (§6, T13): Textual hands a key to the focused widget, then to its parents, the screen and the app; a
text field takes printable keys itself, and a modal screen keeps the window under it from its keys. What is left is
one rule, in `check_action`: the window's keys (WINDOW_ACTIONS) work only while no other screen is up and no text
field has the focus. Returning False there also takes them out of the footer.

The layout follows the terminal (§5.2): from WIDE columns the sidebar and the details are pinned beside and under
the list; below that they slide over it, one at a time. Textual 8 sends the app no Resize when the terminal changes
size (4.0 does), so the switch is made on the resize of the panels' container, `Body`.
"""
import os

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.theme import Theme
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Footer, Input, Static

from ..app import preferences
from ..i18n import _
from . import loop
from .glyphs import glyphs, is_utf8
from .palette import ANSI_THEMES, DEFAULT_SCHEME, PALETTE_CSS, Palette, is_ansi, schemes
from .ui_port import TuiUi
from .widgets import hint

WIDE = 100        # columns: from here on the panels are pinned beside and under the list, below it they slide over it
TALL = 34         # lines: from here on (in a wide terminal) the sidebar also lists every view at its bottom
MIN_SIZE = (40, 12)  # below it only "Make the terminal larger" is shown (§5.3)
SLIDE_WIDTH = 30  # the sidebar slide-over; at most 85% of the width (CSS)
SLIDE_HEIGHT = 11  # the details slide-over; at most 3/5 of the body, so that rows of the list stay in sight
PANELS = ("sidebar", "details")
PINNED = {"both": {"sidebar", "details"}, "sidebar": {"sidebar"}, "details": {"details"}, "none": set()}
# the window's own keys: off while another screen is up or a text field has the focus (the module's docstring)
WINDOW_ACTIONS = frozenset({"toggle_panel", "find", "back_to_list", "quit", "back"})

CSS = PALETTE_CSS + """
/* 16 colours: Textual draws some widgets in colours blended with transparency, which a 16-colour terminal cannot
   show (the footer's words, a checkbox's label vanish): plain theme colours there (T19) */
App:ansi Screen { background: $background; color: $foreground; }
App:ansi Footer, App:ansi FooterKey { background: $background; color: $text; }
App:ansi FooterKey .footer-key--key { background: $background; color: $warning; text-style: bold; }
App:ansi FooterKey .footer-key--description { background: $background; color: $text; }
ModalScreen { background: $background 50%; }
/* popups' lists (ChoiceList, PopupMenu): in 16 colours a blended separator or disabled item would vanish */
App:ansi OptionList > .option-list--separator { color: $border-blurred; }
App:ansi OptionList > .option-list--option-disabled { color: $foreground; text-style: dim; }
/* in 16 colours a modal screen does not dim (it could only be a solid fill): the window stays in sight under it.
   "$background 0%" stays opaque in ANSI mode */
App:ansi ModalScreen { background: transparent; }
App:ansi Input { background: $background; color: $foreground; }

/* quiet scrollbars: a thin track in the panel's colour, the thumb as an inactive border */
* { scrollbar-background: $surface; scrollbar-background-hover: $surface; scrollbar-background-active: $surface;
    scrollbar-color: $border-blurred; scrollbar-color-hover: $border; scrollbar-color-active: $accent;
    scrollbar-corner-color: $surface; scrollbar-size: 1 1; }

#top { height: 1; background: $panel; color: $text; padding: 0 1; }
App:ansi #top { background: $background; color: $foreground; }
#body { height: 1fr; layers: base overlay; }

/* a panel has a single line, a modal window a double one, both square (§4.1); the focused panel is in the accent
   colour, the others faint: the text's colour at 30%, as the theme's own border colour vanishes on dark themes */
.panel { border: $panel-border $foreground 30%; border-title-color: $text-muted; border-subtitle-color: $text-muted;
         background: $background; }
.panel:focus-within { border: $panel-border $accent; border-title-color: $accent; border-subtitle-color: $accent; }
App:ansi .panel { border: $panel-border $border-blurred; border-title-color: $foreground;
                  border-subtitle-color: $foreground; border-title-style: dim; border-subtitle-style: dim; }
App:ansi .panel:focus-within { border: $panel-border $accent; border-title-color: $accent;
                               border-subtitle-color: $accent; border-title-style: none;
                               border-subtitle-style: none; }
.window { border: $window-border $accent; border-title-color: $accent; border-subtitle-color: $accent;
          background: $surface; }
App:ansi .window { background: $background; }

.dialog { width: 90%; max-width: 110; height: auto; max-height: 90%; padding: 0 1; }
.dialog.question, .dialog.path { max-width: 76; }
.dialog .note { color: $text-muted; }
App:ansi .dialog .note { color: $foreground; text-style: dim; }
.dialog .details { height: auto; max-height: 10; margin-top: 1; }
.dialog .buttons { height: 1; align-horizontal: right; margin-top: 1; }
.dialog Button { margin-left: 2; }
/* a text field: one line, no border, the window's background (§4.3) */
.dialog Input { border: none; height: 1; padding: 0; background: $surface; }
App:ansi .dialog Input { background: $background; }

#sidebar { height: 1fr; }
#main { width: 1fr; }
#packages { height: 1fr; }
#views { height: auto; border-top: $panel-border $border-blurred; color: $text-muted; display: none; }
App:ansi #views { color: $foreground; }
#body.tall #views { display: block; }
.hidden { display: none; }
/* a narrow terminal: the panels slide over the list instead of taking room from it */
#body.narrow #sidebar { layer: overlay; position: absolute; max-width: 85%; }
#body.narrow #details { layer: overlay; dock: bottom; width: 100%; }

/* the search (§7.6): at the top, under the top line, which keeps showing the list's filter and count */
.dialog.search { max-width: 84; margin-top: 1; }
.search #search-status { height: 1; color: $text-muted; }
App:ansi .search #search-status { color: $foreground; text-style: dim; }
.search History, .search History:focus { height: auto; max-height: 8; border: none; padding: 0;
                                         border-top: $panel-border $border-blurred; background: $surface; }
App:ansi .search History, App:ansi .search History:focus { background: $background; }

TooSmall { align: center middle; }
TooSmall > Static { width: 100%; height: auto; }
"""


class Body(Horizontal):
    """The panels' room. Its resize switches the layout (the module's docstring)."""

    def on_resize(self) -> None:
        self.app.apply_layout()


class TopLine(Static):
    """The top line (§5.4): "Kram", the window's status (the filter, its rows, the marks; or what Kram is doing)
    or a transient message over it (the Ui port's `status`), and on the right what is wrong with the catalog and its
    age. What does not fit is dropped from the right."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.message = ""
        self.status = Text()
        self.right: list[Text] = []
        self._timer: Timer | None = None

    def set_status(self, status: str | Text) -> None:
        self.status = Text(status) if isinstance(status, str) else status
        self.refresh()

    def set_right(self, parts: list[Text]) -> None:
        self.right = parts
        self.refresh()

    def show_message(self, text: str, timeout_ms: int = 0) -> None:
        """`text` until the next one, or for `timeout_ms`."""
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        self.message = text
        if timeout_ms > 0 and text:
            self._timer = self.set_timer(timeout_ms / 1000, lambda: self.show_message(""))
        self.refresh()

    def render(self) -> Text:
        line = Text()
        line.append("Kram", "bold")
        left = Text(self.message) if self.message else self.status
        if left:
            line.append("  ")
            line.append_text(left)
        width = self.size.width
        right = list(self.right)
        while right and line.cell_len + sum(p.cell_len + 2 for p in right) > width:
            right.pop()
        if right:
            gap = width - line.cell_len - sum(p.cell_len for p in right) - 2 * (len(right) - 1)
            line.append(" " * gap)
            for i, part in enumerate(right):
                line.append("  " if i else "")
                line.append_text(part)
        else:
            line.truncate(width, overflow="ellipsis")
        return line


class TooSmall(Screen):
    """Only "Make the terminal larger" and the quit key (§5.3). The window under it stays as it was."""

    BINDINGS = [Binding("q,ctrl+q", "quit_kram", show=False)]

    def compose(self) -> ComposeResult:
        size = f"{MIN_SIZE[0]}{self.app.glyphs.times}{MIN_SIZE[1]}"
        text = Text(_("Make the terminal larger: Kram needs {size}").format(size=size) + "\n\n", justify="center")
        text.append_text(hint(("q", _("quit"))))
        yield Static(text)

    def on_resize(self) -> None:
        self.app.apply_layout()

    def action_quit_kram(self) -> None:
        self.app.request_quit()


class KramApp(App):
    CSS = CSS
    BINDINGS = [
        Binding("g", "toggle_panel('sidebar')", _("Sidebar")),
        Binding("d", "toggle_panel('details')", _("Details")),
        Binding("slash,ctrl+f", "find", _("Search")),
        Binding("escape", "back_to_list", show=False),
        Binding("alt+left", "back", show=False),
        Binding("q", "quit", _("Quit")),
    ]

    def __init__(self, upgradable: bool = False, file: str | None = None):
        self.utf8 = is_utf8()
        self.glyphs = glyphs(self.utf8)  # before Textual's own init, which reads the CSS variables
        # NO_COLOR: the Terminal scheme, whatever was saved; `role` drops the colours of the roles (§9.6)
        no_colour = os.environ.get("NO_COLOR") is not None
        scheme = DEFAULT_SCHEME if no_colour else preferences.value(preferences.TUI_SCHEME)
        # with NO_COLOR Textual picks its colour filter by `ansi_color` here, once: the 16-colour one drops colours
        # and keeps the rest, the other one would turn everything grey
        super().__init__(ansi_color=is_ansi(scheme))
        self.upgradable, self.file = upgradable, file  # `kram-tui --upgradable` / `kram-tui FILE.rpm` (§15.2)
        self._scheme = scheme
        self.narrow: bool | None = None  # None until the first layout
        self.pinned = {name: name in PINNED[preferences.value(preferences.TUI_PINNED)] for name in PANELS}
        self.ui = TuiUi(self, self.show_status)
        for theme in ANSI_THEMES:
            self.register_theme(theme)
        from .window import MainWindow  # it needs the Ui port and the glyphs set above
        self.main = MainWindow(self)

    def get_css_variables(self) -> dict[str, str]:
        # the border types: box drawing, or plain ASCII where the terminal is not UTF-8 (§9.6)
        return {**super().get_css_variables(), "panel-border": self.glyphs.panel_border,
                "window-border": self.glyphs.modal_border}

    def compose(self) -> ComposeResult:
        yield Palette()
        yield TopLine(id="top")
        with Body(id="body"):
            yield self.main.sidebar
            with Vertical(id="main"):
                with Vertical(id="packages", classes="panel"):
                    yield self.main.list
                yield self.main.details
        yield Footer()

    def on_mount(self) -> None:
        loop.attach(self)
        self.theme_changed_signal.subscribe(self, self._theme_changed)
        self.set_scheme(self._scheme, save=False)
        self.window.query_one("#packages").border_title = _("Packages")
        self.window.query_one("#details").border_title = _("Details")
        self.refresh_colours()
        self.window.query_one("#list").focus()
        self.apply_layout()
        self.main.start()

    @property
    def window(self) -> Screen:
        """The window's screen, under whatever is up: `App.query_one` would search only the screen on top."""
        return self.screen_stack[0]

    # ---------------------------------------------------------------- colours

    def set_scheme(self, name: str, save: bool = True) -> None:
        """A colour scheme (palette.schemes), at once: no restart. `save` False for a preview."""
        if name not in self.available_themes:
            name = DEFAULT_SCHEME
        self._scheme = name
        self.theme = name
        # Textual turns ANSI colours on only for its own "textual-ansi"; ours are 16-colour schemes as well
        self.ansi_color = is_ansi(name)
        if save:
            preferences.set_value(preferences.TUI_SCHEME, name)

    def watch_theme(self, theme_name: str) -> None:
        """Right after Textual's own watcher, which turns ANSI colours off for every theme but "textual-ansi": ours
        need them on before the next frame. A frame drawn in between, with ANSI colours in the theme and Textual's
        filters for true colour, stopped the app (a scheme picked in Textual's command palette)."""
        self.ansi_color = is_ansi(theme_name)

    def _theme_changed(self, theme: Theme) -> None:
        if theme.name != self._scheme:  # changed elsewhere: Textual's command palette
            self._scheme = theme.name
            if theme.name in {value for value, _label in schemes()}:
                preferences.set_value(preferences.TUI_SCHEME, theme.name)
        if self.ansi_color != is_ansi(theme.name):
            self.ansi_color = is_ansi(theme.name)
            self.refresh_css()
        self.call_after_refresh(self.refresh_colours)

    def refresh_colours(self) -> None:
        """Draw again what took its colours from `role` in Python: the hints, every widget's text."""
        self.window.query_one("#packages").border_subtitle = hint(("s", _("sort")), ("y", _("copy")))
        for screen in self.screen_stack:
            for widget in screen.query("*"):
                refresh = getattr(widget, "refresh_colours", None)
                if callable(refresh):
                    refresh()
                widget.refresh()

    # ---------------------------------------------------------------- the top line

    @property
    def top_line(self) -> TopLine:
        return self.window.query_one(TopLine)

    def show_status(self, text: str, timeout_ms: int = 0) -> None:
        self.top_line.show_message(text, timeout_ms)

    # ---------------------------------------------------------------- the panels

    def panel(self, name: str) -> Widget:
        return self.window.query_one(f"#{name}")

    @property
    def list_widget(self) -> Widget:
        return self.window.query_one("#list")

    def focus_target(self, name: str) -> Widget:
        return self.window.query_one(f"#{name}-body")

    def has_focus_in(self, name: str) -> bool:
        node = self.window.focused
        panel = self.panel(name)
        while node is not None:
            if node is panel:
                return True
            node = node.parent
        return False

    def shown_panels(self) -> list[str]:
        return [name for name in PANELS if not self.panel(name).has_class("hidden")]

    def is_too_small(self) -> bool:
        width, height = self.size
        return width < MIN_SIZE[0] or height < MIN_SIZE[1]

    def apply_layout(self) -> None:
        """Wide: the pinned panels are shown. Narrow: none, except the one that has the focus, as the slide-over.
        From narrow to wide an open slide-over stays as a pinned panel."""
        too_small = self.is_too_small()
        if isinstance(self.screen, TooSmall):
            if not too_small:
                self.pop_screen()
            return
        if too_small:
            self.push_screen(TooSmall())
            return
        width, height = self.size
        narrow = width < WIDE
        body = self.window.query_one(Body)
        body.set_class(not narrow and height >= TALL, "tall")
        sidebar, details = self.panel("sidebar"), self.panel("details")
        sidebar.styles.width = SLIDE_WIDTH if narrow else preferences.value(preferences.TUI_SIDEBAR_WIDTH)
        details.styles.height = self.slide_height() if narrow else preferences.value(preferences.TUI_DETAILS_HEIGHT)
        if narrow == self.narrow:
            self.update_list_inset()
            return
        self.narrow = narrow
        body.set_class(narrow, "narrow")
        pinned = dict(self.pinned)
        for name in PANELS:
            focused = self.has_focus_in(name)
            if not narrow and focused:
                pinned[name] = True
            self.panel(name).set_class(not focused if narrow else not pinned[name], "hidden")
        self.set_pinned(pinned)
        self.update_list_inset()

    def update_list_inset(self) -> None:
        """The details slide-over covers the bottom of the list: the cursor keeps out from under it (§7.3.9). The
        list's bottom border is under it too, so it covers one line fewer of the rows."""
        open_ = self.narrow and not self.panel("details").has_class("hidden")
        self.main.list.bottom_inset = self.slide_height() - 1 if open_ else 0

    def slide_height(self) -> int:
        return max(3, min(SLIDE_HEIGHT, self.window.query_one(Body).size.height * 3 // 5))

    def set_pinned(self, pinned: dict[str, bool]) -> None:
        if pinned == self.pinned:
            return
        self.pinned = pinned
        shown = {name for name, on in pinned.items() if on}
        preferences.set_value(preferences.TUI_PINNED, next(k for k, v in PINNED.items() if v == shown))

    def action_toggle_panel(self, name: str) -> None:
        """Not focused: show the panel (pinned, or as the one slide-over) and focus it. Focused: hide it and go back
        to the list; in a wide terminal that unpins it (§6.4, T6)."""
        panel = self.panel(name)
        if self.has_focus_in(name):
            self.list_widget.focus()
            panel.add_class("hidden")
            if not self.narrow:
                self.set_pinned({**self.pinned, name: False})
            self.update_list_inset()
            return
        if self.narrow:
            for other in PANELS:
                self.panel(other).add_class("hidden")
        else:
            self.set_pinned({**self.pinned, name: True})
        panel.remove_class("hidden")
        self.focus_target(name).focus()
        self.update_list_inset()

    def action_find(self) -> None:
        """`/`, ctrl+f: the search dialog (§7.6)."""
        self.main.find()

    def action_back_to_list(self) -> None:
        self.list_widget.focus()

    def action_back(self) -> None:
        """alt+←: the package before the last link followed (§6.5)."""
        self.main.browser.go_back()

    def list_focused(self) -> None:
        """Focus moved to the list (Esc, Tab, a click): a slide-over closes, a pinned panel stays."""
        if self.narrow:
            for name in PANELS:
                self.panel(name).add_class("hidden")
            self.update_list_inset()

    # ---------------------------------------------------------------- who gets a key

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """The window's keys belong to the window (the module's docstring). Under the small-terminal screen nothing
        else reacts either, Textual's command palette included."""
        if action in WINDOW_ACTIONS and (len(self.screen_stack) > 1 or isinstance(self.focused, Input)):
            return False
        if action == "command_palette" and isinstance(self.screen, TooSmall):
            return False
        return True

    # ---------------------------------------------------------------- quitting

    async def action_quit(self) -> None:
        self.request_quit()

    def request_quit(self) -> None:
        """Quit (§10.19). With nothing pending Kram quits at once; asking first comes with the marks."""
        self.main.shutdown()
        self.exit()
