"""The small tables of the dialogs (docs/TUI_SPEC.md §3.3, §4.3): the repositories, the mirrors.

A table of our own rather than Textual's DataTable, for the same reasons as the package list and the sidebar: its
cells are drawn when a line is (`render_line`), from the dialog's `cell(key, column)`, so the colour roles follow a
change of the scheme at once and a row that changes needs no copy updated; the header is quiet (the header role, no
filled bar), the cursor row is the cursor role of every list (§4.2); and the look is the same on both Textual
versions Kram supports.

The columns are laid out for the width and never scroll sideways: each gets its narrowest, then they grow in their
order of `grow` up to their widest, and the columns without a widest share what is left. A narrow table drops the
columns marked `wide` (each dialog says which, §10). What is too long is cut with the ellipsis.
"""
from collections.abc import Callable, Hashable, Sequence
from dataclasses import dataclass

from rich.cells import cell_len
from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual.binding import Binding
from textual.events import Click
from textual.geometry import Size
from textual.message import Message
from textual.scroll_view import ScrollView
from textual.strip import Strip

from .package_list import MOVE
from .palette import role

NARROW = 80  # cells of a table below which it drops its wide columns


@dataclass(frozen=True)
class Column:
    """`max` 0: no widest, the column takes a share of the room left. `wide`: only in a table of NARROW cells or
    more. `grow`: columns with a lower one grow first."""
    id: str
    header: str
    min: int
    max: int = 0
    right: bool = False
    wide: bool = False
    grow: int = 1


def layout(columns: Sequence[Column], width: int, narrow: int = NARROW) -> list[tuple[Column, int]]:
    """The shown columns and their widths for a table `width` cells wide: a cell's margin on the left and one
    between the columns."""
    shown = [c for c in columns if not c.wide or width >= narrow]
    widths = {c.id: c.min for c in shown}
    left = width - len(shown) - sum(widths.values())
    for c in sorted((c for c in shown if c.max), key=lambda c: c.grow):
        add = max(0, min(c.max - c.min, left))
        widths[c.id] += add
        left -= add
    flex = [c for c in shown if not c.max]
    for i, c in enumerate(flex):
        share = max(0, left) // (len(flex) - i)
        widths[c.id] += share
        left -= share
    return [(c, widths[c.id]) for c in shown]


class Table(ScrollView, can_focus=True):
    """Rows by their keys; `cell(key, column id)` gives a cell's text, with its style. The cursor is a row; the
    dialog hears of it moving (`Highlighted`) and of clicks (`Clicked`, with the column clicked and the click's
    `chain`: 2 for a double click)."""

    class Highlighted(Message):
        def __init__(self, table: "Table", key: Hashable | None):
            super().__init__()
            self.table, self.key = table, key

        @property
        def control(self) -> "Table":
            return self.table

    class Clicked(Message):
        def __init__(self, table: "Table", key: Hashable, column: str | None, chain: int):
            super().__init__()
            self.table, self.key, self.column, self.chain = table, key, column, chain

        @property
        def control(self) -> "Table":
            return self.table

    BINDINGS = [
        Binding("up", "move(-1)", MOVE, show=False),
        Binding("down", "move(1)", MOVE, show=False),
        Binding("pageup", "page(-1)", MOVE, show=False),
        Binding("pagedown", "page(1)", MOVE, show=False),
        Binding("home", "jump(0)", MOVE, show=False),
        Binding("end", "jump(-1)", MOVE, show=False),
    ]
    # the cells are cut to the width: nothing to scroll sideways to
    DEFAULT_CSS = "Table { height: 1fr; background: transparent; overflow-x: hidden; }"

    def __init__(self, columns: Sequence[Column], cell: Callable[[Hashable, str], Text], ellipsis: str = "…",
                 narrow: int = NARROW, **kw):
        super().__init__(**kw)
        self.columns = list(columns)
        self.cell = cell
        self.ellipsis = ellipsis
        self.narrow = narrow
        self.keys: list[Hashable] = []
        self.cursor = 0

    # ---------------------------------------------------------------- the rows

    @property
    def current(self) -> Hashable | None:
        return self.keys[self.cursor] if self.keys else None

    def set_rows(self, keys: Sequence[Hashable]) -> None:
        """The rows to show; the cursor stays on its row when that is still there, else at its place."""
        before = self.current
        self.keys = list(keys)
        if before in self.keys:
            self.cursor = self.keys.index(before)
        else:
            self.cursor = max(0, min(self.cursor, len(self.keys) - 1))
        self.virtual_size = Size(0, len(self.keys) + 1)
        self.ensure_visible()
        self.refresh()
        if self.current != before:
            self.post_message(self.Highlighted(self, self.current))

    def redraw(self) -> None:
        """The cells changed, the rows did not."""
        self.refresh()

    def shown_columns(self) -> list[tuple[Column, int]]:
        return layout(self.columns, self.scrollable_content_region.width, self.narrow)

    # ---------------------------------------------------------------- drawing

    def render_line(self, y: int) -> Strip:
        width = self.scrollable_content_region.width
        # the widget's own colours under everything: segments without a background show the terminal's default
        # one, not the dialog's
        back = self.rich_style
        if y == 0:
            base = back + role("header")
            cells = [(Text(c.header), c, w) for c, w in self.shown_columns()]
        else:
            row = self.scroll_offset.y + y - 1
            if row >= len(self.keys):
                return Strip.blank(width, back)
            key = self.keys[row]
            base = back
            if row == self.cursor:
                base += role("cursor") if self.has_focus else role("cursor-blurred")
            cells = [(self.cell(key, c.id), c, w) for c, w in self.shown_columns()]
        segments = [Segment(" ", base)]
        console = self.app.console
        for i, (text, column, w) in enumerate(cells):
            if i:
                segments.append(Segment(" ", base))
            segments += self._cell(text, column, w, base, console)
        return Strip(segments).adjust_cell_length(width, base)

    def _cell(self, text: Text, column: Column, width: int, base: Style, console) -> list[Segment]:
        if width <= 0:
            return []
        cell = Text(no_wrap=True)
        cell.append_text(text)  # the text's own style as a span: `render` leaves out a Text's base style
        text = cell
        n = text.cell_len
        if n > width:
            cut = width - cell_len(self.ellipsis)
            if cut > 0:
                text.truncate(cut)
                text.append(self.ellipsis)
            else:
                text.truncate(width)
        pad = " " * max(0, width - text.cell_len)
        if pad:
            text = Text(pad) + text if column.right else text + Text(pad)
        return [Segment(s.text, base + s.style if s.style else base)
                for s in text.render(console) if s.text and s.text != "\n"]

    # ---------------------------------------------------------------- the cursor

    @property
    def rows_shown(self) -> int:
        return max(1, self.scrollable_content_region.height - 1)

    def ensure_visible(self) -> None:
        top, shown = self.scroll_offset.y, self.rows_shown
        if self.cursor < top:
            self.scroll_to(y=self.cursor, animate=False, force=True)
        elif self.cursor >= top + shown:
            self.scroll_to(y=self.cursor - shown + 1, animate=False, force=True)

    def go(self, row: int) -> None:
        if not self.keys:
            return
        before = self.cursor
        self.cursor = max(0, min(len(self.keys) - 1, row))
        self.ensure_visible()
        self.refresh()
        if self.cursor != before:
            self.post_message(self.Highlighted(self, self.current))

    def select_key(self, key: Hashable) -> None:
        if key in self.keys:
            self.go(self.keys.index(key))

    def action_move(self, d: int) -> None:
        self.go(self.cursor + d)

    def action_page(self, d: int) -> None:
        self.go(self.cursor + d * max(1, self.rows_shown - 1))

    def action_jump(self, row: int) -> None:
        self.go(row if row >= 0 else len(self.keys) - 1)

    def on_resize(self) -> None:
        self.ensure_visible()

    def on_focus(self) -> None:
        self.refresh()

    def on_blur(self) -> None:
        self.refresh()

    def on_click(self, event: Click) -> None:
        row = self.scroll_offset.y + event.y - 1
        if event.y < 1 or not 0 <= row < len(self.keys):
            return
        self.go(row)
        x, column = 1, None
        for c, w in self.shown_columns():
            if x <= event.x < x + w:
                column = c.id
                break
            x += w + 1
        self.post_message(self.Clicked(self, self.keys[row], column, event.chain))
