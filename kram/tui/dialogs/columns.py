"""Settings → Columns… (docs/TUI_SPEC.md §10.18): which columns the package list shows, in which order, how wide.
The GUIs do this in the list's header (its context menu, dragging and resizing); a terminal has a dialog for it.

A row per column after S: Package first, which is always shown and always first (it names the row), then the
hideable ones (kram.app.columns.HIDEABLE) in their order. `space` shows or hides one, `alt+↑ ↓` moves it, `<` `>`
narrow and widen it; the Summary takes the room the others leave, and Package is as wide as most names until it is
given a width. Every change goes to the list at once and into the setting (kram.app.preferences.TUI_COLUMNS): the
dialog only closes.
"""
import copy
from collections.abc import Callable

from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen

from ...app.columns import COL_NAME, COL_SUMMARY
from ...i18n import _, pgettext
from ..package_list import RESIZABLE, WIDTH_RANGE, WIDTHS, Columns, column_label
from ..palette import role
from ..table import Column, Table
from ..widgets import Button, hint

STEP = 1  # cells per `<` / `>`


def columns_label() -> str:
    return _("Columns…")


class ColumnsDialog(ModalScreen):
    """`columns`: the list's; `apply(columns)` shows and saves a change; `shown_width(col)` is the width the list
    gives a column now (Package's, before the user gives it one)."""

    BINDINGS = [
        Binding("escape", "close", show=False),
        Binding("space", "toggle", show=False),
        Binding("alt+up", "move(-1)", show=False),
        Binding("alt+down", "move(1)", show=False),
        Binding("less_than_sign", "width(-1)", show=False),
        Binding("greater_than_sign", "width(1)", show=False),
    ]
    DEFAULT_CSS = """
    ColumnsDialog { align: center middle; }
    ColumnsDialog #column-list { height: auto; }
    """

    def __init__(self, columns: Columns, apply: Callable[[Columns], None], shown_width: Callable[[int], int]):
        super().__init__()
        self.columns = copy.deepcopy(columns)
        self.apply = apply
        self.shown_width = shown_width

    def compose(self) -> ComposeResult:
        g = self.app.glyphs
        box = Vertical(classes="window dialog columns")
        box.border_title = _("Columns")
        box.border_subtitle = hint(("space", _("show")), (f"alt+{g.up} {g.down}", _("move")),
                                   ("< >", _("width")), ("esc", _("close")))
        with box:
            yield Table([Column("on", pgettext("short column header", "On"), 3, 3),
                         Column("column", pgettext("column of the list", "Column"), 12),
                         Column("width", pgettext("column width", "Width"), 6, 6, right=True)],
                        self._cell, g.ellipsis, id="column-list")
            with Horizontal(classes="buttons"):
                yield Button(_("Close"), id="close", variant="primary")

    def on_mount(self) -> None:
        table = self.query_one(Table)
        table.set_rows(self.rows())
        table.styles.height = len(self.rows()) + 1
        table.focus()

    def rows(self) -> list[int]:
        return [COL_NAME, *self.columns.order]

    def _cell(self, col: int, column: str) -> Text:
        c = self.columns
        match column:
            case "on":
                if col == COL_NAME:  # always shown
                    return Text("[x]", Style(dim=True))
                shown = col not in c.hidden
                return Text("[x]" if shown else "[ ]", role("marked") if shown else Style())
            case "column":
                return Text(column_label(col), Style(dim=True) if col in c.hidden else Style())
            case "width":
                if col in c.widths:
                    return Text(str(c.widths[col]))
                # the summary takes what is left, Package fits the names, until given a width
                return Text(pgettext("column width", "auto") if col in (COL_NAME, COL_SUMMARY) else
                            str(WIDTHS[col]), role("muted"))
        return Text()

    @property
    def current(self) -> int | None:
        return self.query_one(Table).current

    def _changed(self) -> None:
        table = self.query_one(Table)
        table.set_rows(self.rows())
        table.redraw()
        self.apply(copy.deepcopy(self.columns))

    def action_toggle(self) -> None:
        col = self.current
        if col is None or col == COL_NAME:
            return
        self.columns.hidden ^= {col}
        self._changed()

    def action_move(self, d: int) -> None:
        col, order = self.current, self.columns.order
        if col not in order:
            return
        i = order.index(col)
        j = i + d
        if 0 <= j < len(order):
            order[i], order[j] = order[j], order[i]
            self._changed()  # the cursor stays on its column (Table.set_rows)

    def action_width(self, d: int) -> None:
        col = self.current
        if col not in RESIZABLE:
            return
        low, high = WIDTH_RANGE
        width = self.columns.widths.get(col) or (self.shown_width(col) if col == COL_NAME else WIDTHS[col])
        self.columns.widths[col] = max(low, min(high, width + d * STEP))
        self._changed()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.action_close()

    def action_close(self) -> None:
        self.dismiss(None)
