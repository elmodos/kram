"""The search of the terminal front end (docs/TUI_SPEC.md §7.6, T12): a modal dialog at the top of the screen, over
the window, with a one-line text field, the modes of kram.core.search as a strip, a status line and the earlier
searches. It drives the window's `SearchController` as the GUIs' search fields do, so the list behind the dialog
filters while the text is typed; the dialog's result says what to do with that when it closes.

- Typing in a name mode filters at once (the controller's debounce). Provides and File ask dnf, which takes a while
  and should not run for every keystroke: their text is only shown, and dnf looks it up on Enter.
- `Enter` keeps the search as Enter in the GUIs' search field does (`Browser._on_search_enter`): the list stays
  filtered by the sidebar's entry and the search together, the search goes into the history, the sidebar stays
  on its entry, the list gets the focus.
- `Esc` puts back the list as it was before the dialog opened: the filter, the search text and mode, the cursor.
  So while the dialog is up a search is not put into the history after a pause, as it is in the GUIs: here the
  dialog says when a search is kept.

The keeping and the restoring run in the dialog's dismissal callback (`open_search`), so that whatever they open
starts after the dialog is gone (§11.3.8).
"""
from dataclasses import dataclass

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.events import Click
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from ..app.package_list import Sort
from ..core.search import MODE_LABELS, Mode
from ..i18n import _, ngettext, pgettext
from .glyphs import Glyphs
from .palette import role
from .widgets import hint


def placeholders() -> dict[Mode, str]:
    """What the empty field says it takes, by mode."""
    return {
        Mode.NAME: _("A part of the package name"),
        Mode.NAME_SUMMARY: _("Words of the name or the summary"),
        Mode.DESCRIPTION: _("Words of the name, the summary or the description"),
        Mode.PROVIDES: _("A capability: libvulkan.so.1, python3dist(requests)"),
        Mode.FILE: _("A file: /usr/bin/7z or just 7z"),
    }


def mode_strip(mode: Mode, width: int, glyphs: Glyphs) -> tuple[Text, list[tuple[int, int, int]]]:
    """The modes on one line of `width` cells, the current one reversed among muted ones; when they do not fit, the
    compact form `← Name + summary → 2/5` (§4.3). With where each mode is on it, or each arrow (-1 / +1 as a step,
    as negative values below the modes' own)."""
    full = Text()
    regions: list[tuple[int, int, int]] = []
    for m in Mode:
        if m:
            full.append("  ")
        start = full.cell_len
        full.append(f" {MODE_LABELS[m]} ", role("current") if m is mode else role("muted"))
        regions.append((start, full.cell_len, int(m)))
    if full.cell_len <= width:
        return full, regions
    compact = Text()
    compact.append(glyphs.left, role("muted"))
    regions = [(0, compact.cell_len, -1)]
    compact.append(" ")
    compact.append(f" {MODE_LABELS[mode]} ", role("current"))
    compact.append(" ")
    start = compact.cell_len
    compact.append(glyphs.right, role("muted"))
    regions.append((start, compact.cell_len, -2))
    compact.append(f"  {int(mode) + 1}/{len(Mode)}", role("muted"))
    compact.truncate(width)
    return compact, regions


class ModeStrip(Widget):
    """The modes of the search; a click picks one, or steps with an arrow of the compact form."""

    DEFAULT_CSS = "ModeStrip { height: 1; }"

    def __init__(self, dialog: "SearchDialog", **kw):
        super().__init__(**kw)
        self.dialog = dialog
        self.regions: list[tuple[int, int, int]] = []

    def render(self) -> Text:
        text, self.regions = mode_strip(self.dialog.mode, self.size.width, self.dialog.glyphs)
        return text

    def on_click(self, event: Click) -> None:
        for start, end, value in self.regions:
            if start <= event.x < end:
                if value == -1:
                    self.dialog.action_mode(-1)
                elif value == -2:
                    self.dialog.action_mode(1)
                else:
                    self.dialog.choose_mode(Mode(value))
                return


class History(OptionList):
    """The earlier searches. `↑` on the first one goes back to the text field; the cursor shows only while the list
    has the focus, so that it does not look picked while the user types."""

    def action_cursor_up(self) -> None:
        if not self.highlighted:
            self.screen.query_one("#search-text", Input).focus()
            return
        super().action_cursor_up()

    def on_focus(self) -> None:
        if self.highlighted is None and self.option_count:
            self.highlighted = 0

    def on_blur(self) -> None:
        self.highlighted = None


class SearchBox(Vertical):
    """The dialog's window: its hints follow its width and the colours (§4.5)."""

    def on_resize(self) -> None:
        self.screen.show_hints()

    def refresh_colours(self) -> None:
        self.screen.show_hints()
        self.screen.fill_history()


class SearchDialog(ModalScreen):
    """The screen's result: (text, mode) to keep, None to put back the list as it was."""

    BINDINGS = [
        Binding("escape", "close", show=False),
        # priority: the text field would take Tab to move the focus
        Binding("tab", "mode(1)", show=False, priority=True),
        Binding("shift+tab", "mode(-1)", show=False, priority=True),
        Binding("down", "earlier", show=False),
    ]
    DEFAULT_CSS = "SearchDialog { align: center top; }"

    def __init__(self, main):
        super().__init__()
        self.main = main
        self.browser = main.browser
        self.glyphs: Glyphs = main.app.glyphs
        search = self.browser.search
        self.mode = search.mode()
        self.text = search.text()
        self.searched = False  # the list behind was filtered again while the dialog was up

    def compose(self) -> ComposeResult:
        box = SearchBox(classes="window dialog search")
        box.border_title = _("Search")
        with box:
            yield Input(self.text, placeholder=placeholders()[self.mode], id="search-text")
            yield ModeStrip(self, id="search-modes")
            yield Static("", id="search-status", markup=False)
            yield History(id="search-history")

    def on_mount(self) -> None:
        self.browser.search.changed.connect(self._searched)
        self.fill_history()
        self.show_status()
        self.query_one("#search-text", Input).focus()

    def on_unmount(self) -> None:
        self._disconnect()

    def _disconnect(self) -> None:
        try:
            self.browser.search.changed.disconnect(self._searched)
        except ValueError:  # already: the dialog was closed
            pass

    # ---------------------------------------------------------------- drawing

    def show_hints(self) -> None:
        """`tab what  ↓ earlier  enter search  esc close`, as much of it as the bottom border has room for; `↓` only
        when there are earlier searches."""
        pairs = [("tab", pgettext("search key hint", "what"))]
        if self.browser.sidebar.history:
            pairs.append((self.glyphs.down, pgettext("search key hint", "earlier")))
        pairs += [("enter", pgettext("search key hint", "search")), ("esc", _("close"))]
        box = self.query_one(SearchBox)
        room = box.size.width - 4  # the corners and a space on each side of the hints
        while pairs and hint(*pairs).cell_len > room:
            pairs.pop()
        box.border_subtitle = hint(*pairs)

    def fill_history(self) -> None:
        history = self.query_one(History)
        highlighted = history.highlighted
        history.clear_options()
        for text, mode, count in self.browser.sidebar.history:
            line = Text(_("“{text}” — {mode}").format(text=text, mode=MODE_LABELS[Mode(mode)].lower()))
            if count is not None:
                line.append(f"   {count}", role("muted"))
            history.add_option(Option(line))
        history.display = bool(self.browser.sidebar.history)
        if history.has_focus and highlighted is not None and history.option_count:
            history.highlighted = min(highlighted, history.option_count - 1)

    def show_status(self) -> None:
        """What the typed text does: how many packages it leaves in the list, or that dnf answers on Enter."""
        text = self.text.strip()
        if not text:
            status = ""
        elif self.mode.local:
            n = len(self.browser.packages)
            status = ngettext("Filtering as you type: {n} package", "Filtering as you type: {n} packages",
                              n).format(n=n)
        else:
            status = _("dnf looks this up when you press Enter")
        self.query_one("#search-status", Static).update(status)

    # ---------------------------------------------------------------- the text and the mode

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        if event.value == self.text:  # the field filled with the shown search as it opens: nothing to search again
            return
        self.text = event.value
        search = self.browser.search
        if self.mode.local:
            search.edited(event.value)  # the list follows once typing pauses; the count with it (`_searched`)
            if not event.value.strip():
                self.show_status()
        else:
            search.cancel_pending()
            search.set_query(event.value, self.mode)
            self.show_status()

    def action_mode(self, step: int) -> None:
        self.choose_mode(Mode((int(self.mode) + step) % len(Mode)))

    def choose_mode(self, mode: Mode) -> None:
        if mode is self.mode:
            return
        self.mode = mode
        search = self.browser.search
        if mode.local and search.text():
            search.mode_chosen(mode)  # searches again at once
        else:
            # Provides and File wait for Enter; an empty text has nothing to search again
            search.cancel_pending()
            search.set_query(self.text, mode)
        self.query_one("#search-text", Input).placeholder = placeholders()[mode]
        self.query_one(ModeStrip).refresh()
        self.show_status()

    def _searched(self) -> None:
        """The list behind was filtered again (after `Browser.apply_filter`, which is connected first)."""
        self.searched = True
        self.browser.search.stop_history()  # the dialog says when a search is kept (the module's docstring)
        self.show_status()

    # ---------------------------------------------------------------- the earlier searches

    def action_earlier(self) -> None:
        history = self.query_one(History)
        if history.option_count and not history.has_focus:
            history.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        text, mode, _count = self.browser.sidebar.history[event.option_index]
        self._close((text, Mode(mode)))

    # ---------------------------------------------------------------- closing

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.submit()

    def submit(self) -> None:
        """Enter in the field: keep the search typed."""
        self._close((self.text.strip(), self.mode))

    def action_close(self) -> None:
        self._close(None)

    def _close(self, result: tuple[str, Mode] | None) -> None:
        self._disconnect()
        self.dismiss(result)


@dataclass(frozen=True)
class Before:
    """The list as it was when the dialog opened, for `Esc`."""
    text: str
    mode: Mode
    key: tuple[str, str] | None
    top: int
    sort: Sort | None


def open_search(main) -> None:
    """The search dialog over `main` (the MainWindow); what it leaves behind once it is closed."""
    b = main.browser
    before = Before(b.search.text(), b.search.mode(), main.current_key(), main.list.scroll_offset.y,
                    main.list.sort_shown)
    dialog = SearchDialog(main)

    def closed(result: tuple[str, Mode] | None) -> None:
        if result is None:
            restore(main, before, dialog.searched)
        else:
            keep(main, *result)
    main.app.push_screen(dialog, closed)


def keep(main, text: str, mode: Mode) -> None:
    """Enter, as in the GUIs' search field: the search runs at once within the sidebar's entry and goes into the
    history (Provides and File when dnf has answered); the sidebar stays where it is. An empty text: the list
    without a search, at once, and nothing for the history."""
    search = main.browser.search
    search.set_query(text, mode)
    search.submit()  # Browser._on_search_enter: apply_filter (which drops a pending keystroke's search), remember
    main.focus_list()


def restore(main, before: Before, searched: bool) -> None:
    """Esc: the search text and mode as they were, and the list with them, its cursor where it was."""
    b = main.browser
    search = b.search
    search.cancel_pending()  # a keystroke's search still to come
    search.set_query(before.text, before.mode)
    if not searched:
        return
    b.apply_filter()
    search.stop_history()  # it was there before, or was never kept
    if before.sort is not None and main.list.sort_shown != before.sort:
        main.sort(*before.sort)  # ranked results the user had sorted by a column
    if before.key is not None:
        main.select_key(before.key)
    main.list.scroll_to(y=before.top, animate=False, force=True)
