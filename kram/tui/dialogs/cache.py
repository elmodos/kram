"""The Cleanup dialog (docs/TUI_SPEC.md §10.9): the `CleanupView` of kram.app.cache.Cleanup, as
kram.gtk.dialogs.cache is.

At the top the package caches in a small table (kram.tui.table): the cache, its size, its files and, in a wide
table, where its files are. Under it the cache under the cursor in words, and its button: `< Clean >`, or for the
repository metadata `< Download again… >`, which asks first and reads the catalog again after it (the presenter's
question). While the sizes are counted they show "…" and the button is off. A warning of the presenter (PackageKit's
cache cannot be cleaned while an offline update is prepared) stands under the table in the danger role.

Below, rpm's leftover configuration files: what they are, the search's status line, and a table of the files found
(path, date, size; a narrow table drops the date). The file under the cursor is described under the table, with why
it cannot be compared when it cannot. The buttons under it are the GUIs': `< Compare >` (also `Enter`) shows the diff
in a dialog of its own, its `+` and `-` lines in the ok and danger roles; `< Delete… >` deletes it after the
presenter's question; `< Delete unused… >` deletes every copy of a file that no longer exists, after a question;
`< Search all folders… >`, shown while folders only root can read were left out, searches again as root. What needs
root runs through the helper with its progress dialog, over this one, which then shows the result. Everything but
`< Close >` is in one area that scrolls, so that a short terminal reaches all of it.
"""
from collections.abc import Callable

from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen

from ...app.cache import CACHES, METADATA, CacheLine, Cleanup, LeftoverLine, RunHelper
from ...core.leftovers import Leftover
from ...i18n import _
from ..palette import role
from ..table import Column, Table
from ..widgets import Button, ButtonBar, hint
from .apply import Lines

LEFTOVER_ROWS = 10  # rows of the leftovers' table before it scrolls by itself
TITLES = {target: title for target, _icons, title, _description, _button in CACHES}
DESCRIPTIONS = {target: description for target, _icons, _title, description, _button in CACHES}


def cache_columns() -> list[Column]:
    return [
        Column("cache", _("Cache"), 16, 30, grow=0),
        Column("size", _("Size"), 9, 9, right=True),
        Column("files", _("Files"), 10, 12, right=True),
        Column("path", _("Location"), 10, wide=True),
    ]


def leftover_columns() -> list[Column]:
    return [
        Column("path", _("File"), 16),
        Column("date", _("Date"), 10, 12, wide=True),
        Column("size", _("Size"), 9, 9, right=True),
    ]


def clean_label(target: str | None) -> str:
    # the GUIs' "Download Again…" in the sentence case of the terminal (§4.6)
    return _("Download again…") if target == METADATA else _("Clean")


def diff_text(text: str) -> Text:
    """A unified diff with its `+` lines in the ok role, its `-` lines in the danger role, the hunks' `@@` lines in
    the info role and the file names in bold; the signs say it without the colours."""
    out = Text()
    for n, line in enumerate(text.splitlines()):
        if n:
            out.append("\n")
        if line.startswith(("+++", "---")):
            style = Style(bold=True)
        else:
            style = {"+": role("ok"), "-": role("danger"), "@": role("info")}.get(line[:1], Style())
        out.append(line, style)
    return out


class DiffDialog(ModalScreen):
    """Compare: the diff of a leftover against the current file, scrolling, over the Cleanup dialog."""

    BINDINGS = [Binding("escape", "close", show=False)]
    DEFAULT_CSS = """
    DiffDialog { align: center middle; }
    DiffDialog #diff-box { height: 90%; }
    DiffDialog #diff-scroll { height: 1fr; margin-top: 1; background: $surface; }
    App:ansi DiffDialog #diff-scroll { background: $background; }
    """

    def __init__(self, leftover: Leftover, text: str):
        super().__init__()
        self.leftover, self.text = leftover, text

    def compose(self) -> ComposeResult:
        box = Vertical(classes="window dialog diff", id="diff-box")
        box.border_title = _("Compare")
        g = self.app.glyphs
        box.border_subtitle = hint((f"{g.up} {g.down}", _("scroll")), ("esc", _("close")))
        leftover = self.leftover
        with box:
            yield Lines(lambda: Text(_("Lines with “-” are in the current file {current}; lines with “+” only in "
                                       "{path}.").format(current=leftover.current, path=leftover.path),
                                     role("muted")), id="diff-note")
            with VerticalScroll(id="diff-scroll"):
                yield Lines(lambda: diff_text(self.text), id="diff")
            with Horizontal(classes="buttons"):
                yield Button(_("Close"), id="close", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#diff-scroll").focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.action_close()

    def action_close(self) -> None:
        self.dismiss(None)


class CacheDialog(ModalScreen):
    """`clean_system(target, done)` runs the helper's clean_cache; `run_helper(request, title, done)` any other
    request, None when there is no helper (kram.app.cache.Cleanup)."""

    BINDINGS = [
        Binding("escape", "close", show=False),
        Binding("enter", "activate", show=False),
    ]
    DEFAULT_CSS = """
    CacheDialog { align: center middle; }
    CacheDialog #cleanup-box { height: 90%; }
    CacheDialog #caches { height: 5; }
    CacheDialog #cache-buttons { height: 1; align-horizontal: right; }
    CacheDialog #cleanup-scroll { height: 1fr; }
    CacheDialog #leftovers { height: 2; }
    CacheDialog #cache-about, CacheDialog #cleanup-note, CacheDialog #leftover-about { margin-top: 1; }
    """

    def __init__(self, dnf, clean_system: Callable[[str, Callable[[], None]], None], ui, *,
                 run_helper: RunHelper | None = None):
        super().__init__()
        self.ui = ui
        self.cleanup = Cleanup(dnf, self, ui, clean_system, run_helper)
        self.caches: dict[str, CacheLine] = {}
        self.clean_off: set[str] = set()  # cleaning now, or the sizes are counted
        self.measuring = True
        self.leftover_lines: list[LeftoverLine] = []
        self.status = ""
        self.can_delete_unused = False
        self._dismissing = self._close_pending = False  # not `_closing`: that is Textual's own
        self._stopped = False

    @property
    def leftovers(self):
        return self.cleanup.leftovers

    # ---------------------------------------------------------------- the widgets

    def compose(self) -> ComposeResult:
        box = Vertical(classes="window dialog cleanup", id="cleanup-box")
        box.border_title = _("Cleanup")
        with box:
            with VerticalScroll(id="cleanup-scroll"):
                yield Table(cache_columns(), self._cache_cell, self.app.glyphs.ellipsis, id="caches")
                yield Lines(id="cache-about")
                with Horizontal(id="cache-buttons"):
                    yield Button(_("Clean"), id="clean", disabled=True)
                yield Lines(id="cleanup-note")
                yield Lines(lambda: Text(_("Leftover configuration files"), role("header")), classes="gap")
                yield Lines(lambda: Text(_(
                    "Copies rpm keeps when you had changed a package's configuration file: your earlier version "
                    "(.rpmsave) or the package's new default it did not apply (.rpmnew)."), role("muted")))
                yield Lines(lambda: Text(self.status), id="leftovers-status", classes="gap")
                yield Table(leftover_columns(), self._leftover_cell, self.app.glyphs.ellipsis, id="leftovers")
                yield Lines(id="leftover-about")
                # under the leftovers, in the area that scrolls: a narrow terminal stacks them a line each
                with ButtonBar(classes="buttons", id="leftover-buttons"):
                    with Horizontal():  # the file under the cursor
                        yield Button(_("Compare"), id="compare", disabled=True)
                        yield Button(_("Delete…"), id="delete", variant="error", disabled=True)
                    with Horizontal():  # all of them
                        yield Button(_("Delete unused…"), id="delete-unused", variant="error", disabled=True)
                    with Horizontal():
                        yield Button(_("Search all folders…"), id="search-root")
            with Horizontal(classes="buttons"):
                yield Button(_("Close"), id="close", variant="primary")

    def on_mount(self) -> None:
        self._button("search-root").display = False
        self.cache_table.focus()
        self.cleanup.start()
        self._hint()

    def _hint(self) -> None:
        """What `Enter` does where the focus is: the cache's button in the caches, Compare in the leftovers."""
        pairs = [("tab", _("next"))]
        if self.focused is self.cache_table and self._button("clean").enabled:
            pairs.append(("enter", clean_label(self.selected_cache()).rstrip("…").lower()))
        elif self.focused is self.leftover_table and self._button("compare").enabled:
            pairs.append(("enter", _("compare")))
        pairs.append(("esc", _("close")))
        self.query_one("#cleanup-box").border_subtitle = hint(*pairs)

    def on_descendant_focus(self, _event) -> None:
        self._hint()

    @property
    def cache_table(self) -> Table:
        return self.query_one("#caches", Table)

    @property
    def leftover_table(self) -> Table:
        return self.query_one("#leftovers", Table)

    def _button(self, name: str) -> Button:
        return self.query_one(f"#{name}", Button)

    def _cache_cell(self, target: str, column: str) -> Text:
        line = self.caches.get(target)
        match column:
            case "cache":
                return Text(_(TITLES[target]))
            case "size":
                return Text("…" if self.measuring or line is None else line.size, Style(bold=True))
            case "files":
                return Text("" if self.measuring or line is None else line.files, role("muted"))
            case "path":
                return Text(line.path if line is not None else "", role("muted"))
        return Text()

    def _leftover_cell(self, index: int, column: str) -> Text:
        line = self.leftover_lines[index]
        date, _sep, size = line.when.partition("\n")
        match column:
            case "path":
                return Text(line.leftover.path)
            case "date":
                return Text(date, role("muted"))
            case "size":
                return Text(size)
        return Text()

    def selected_cache(self) -> str | None:
        return self.cache_table.current

    def selected_leftover(self) -> LeftoverLine | None:
        index = self.leftover_table.current
        return self.leftover_lines[index] if index is not None and index < len(self.leftover_lines) else None

    def _update_cache(self) -> None:
        """The cache under the cursor: its words, where it is, and its button."""
        target = self.selected_cache()
        line = self.caches.get(target)
        clean = self._button("clean")
        clean.set_label(clean_label(target))
        clean.set_enabled(line is not None and line.can_clean and not self.measuring and target not in self.clean_off)
        about = _(DESCRIPTIONS[target]) if target else ""
        if line is not None and line.path:
            about += "\n" + line.path
        self.query_one("#cache-about", Lines).show(lambda: Text(about, role("muted")))
        self._hint()

    def _update_leftover(self) -> None:
        line = self.selected_leftover()
        self._button("compare").set_enabled(line is not None and line.can_compare)
        self._button("delete").set_enabled(line is not None and line.can_delete)
        self._button("delete-unused").set_enabled(self.can_delete_unused)
        about = ""
        if line is not None:
            about = line.description + ("\n" + line.compare_tip if line.compare_tip else "")
        self.query_one("#leftover-about", Lines).show(lambda: Text(about, role("muted")))
        self.query_one("#leftover-buttons", ButtonBar).fit()
        self._hint()

    # ---------------------------------------------------------------- the user

    def on_table_highlighted(self, event: Table.Highlighted) -> None:
        event.stop()
        if event.table.id == "caches":
            self._update_cache()
        else:
            self._update_leftover()

    def on_table_clicked(self, event: Table.Clicked) -> None:
        event.stop()
        if event.table.id == "leftovers" and event.chain == 2:
            self.compare()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        match event.button.id:
            case "clean":
                if (target := self.selected_cache()) is not None:
                    self.cleanup.clean(target)
            case "compare":
                self.compare()
            case "delete":
                if (line := self.selected_leftover()) is not None and line.can_delete:
                    self.cleanup.delete([line.leftover])
            case "delete-unused":
                self.cleanup.delete_unused()
            case "search-root":
                self.cleanup.search_as_root()
            case "close":
                self.action_close()

    def compare(self) -> None:
        line = self.selected_leftover()
        if line is not None and line.can_compare:
            self.cleanup.compare(line.leftover)

    def action_activate(self) -> None:
        """Enter: Compare in the table of leftovers (a button takes its own Enter first)."""
        if self.focused is self.leftover_table:
            self.compare()
        elif self.focused is self.cache_table:
            self._button("clean").action_press()

    def action_close(self) -> None:
        self._close()

    # ---------------------------------------------------------------- closing

    def _close(self) -> None:
        """Only from the top of the screens (kram.tui.dialogs.repos.ReposDialog._close)."""
        if self._dismissing:
            return
        if self.app.screen is not self:
            self._close_pending = True
            return
        self._dismissing = True
        self.stop()
        self.dismiss(None)

    def on_screen_resume(self) -> None:
        if self._close_pending:
            self._close_pending = False
            self._close()

    def stop(self) -> None:
        """Results that arrive later are for a dialog that is gone (Cleanup.close)."""
        if not self._stopped:
            self._stopped = True
            self.cleanup.close()

    def on_unmount(self) -> None:
        self.stop()

    # ---------------------------------------------------------------- CleanupView

    def show_measuring(self) -> None:
        self.measuring = True
        if not self.caches:  # the first count: every cache Kram knows, until it says which this system has
            self.cache_table.set_rows([target for target, *_rest in CACHES])
        self.cache_table.redraw()
        self._update_cache()

    def show_caches(self, lines: list[CacheLine]) -> None:
        self.measuring = False
        self.clean_off.clear()
        self.caches = {line.target: line for line in lines if line.shown}
        table = self.cache_table
        table.set_rows([line.target for line in lines if line.shown])
        table.styles.height = len(table.keys) + 1
        table.redraw()
        self._update_cache()

    def set_clean_enabled(self, target: str, on: bool) -> None:
        if on:
            self.clean_off.discard(target)
        else:
            self.clean_off.add(target)
        self._update_cache()

    def show_note(self, text: str | None) -> None:
        note = f"{self.app.glyphs.warning} {text}" if text else ""
        self.query_one("#cleanup-note", Lines).show(lambda: Text(note, role("danger")))

    def show_leftovers_status(self, text: str) -> None:
        """Searching, or the search failed: nothing to act on meanwhile."""
        self.status = text
        self.query_one("#leftovers-status", Lines).show(lambda: Text(self.status))
        self._button("search-root").display = False
        self.can_delete_unused = False
        self._update_leftover()

    def show_leftovers(self, lines: list[LeftoverLine], status: str, can_search_root: bool,
                       can_delete_unused: bool) -> None:
        self.leftover_lines = lines
        self.status = status
        self.query_one("#leftovers-status", Lines).show(lambda: Text(self.status))
        table = self.leftover_table
        table.set_rows(list(range(len(lines))))
        # all of them, up to a screenful: the dialog's own area scrolls, not a table of 1fr inside it
        table.styles.height = 1 + max(1, min(len(lines), LEFTOVER_ROWS))
        table.redraw()
        self._button("search-root").display = can_search_root
        self.query_one("#leftover-buttons", ButtonBar).fit()
        self.can_delete_unused = can_delete_unused
        self._update_leftover()

    def show_diff(self, leftover: Leftover, text: str) -> None:
        self.app.push_screen(DiffDialog(leftover, text))
