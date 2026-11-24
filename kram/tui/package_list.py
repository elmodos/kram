"""The package list of the terminal front end (docs/TUI_SPEC.md §7.3): a view over kram.app.package_list.PackageList.

It draws only the lines on screen (§3.3, §14.1, T4): `render_line(y)` reads the row at that line from the
PackageList, so 70,000 rows cost nothing until they scroll into view. Line 0 is the header; it does not scroll.
Textual's DataTable keeps a copy of every cell and needs seconds to fill with the whole catalog.

The columns (§7.3.2) are kept in `Columns`, one object the Columns dialog (§10.18) can change; the list lays them
out for its width: the name column as wide as 95% of the shown names, the summary taking the room that is left.
When they do not fit, the list scrolls sideways and the status and name columns stay in place, if they take at most
half of the width (§7.3.3).

Every `scroll_to` passes `force=True`: Textual refuses to scroll a widget that has no scrollbar, which is the case
for a short list that a slide-over has just covered (TUI_FRONTEND.md §4).
"""
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from rich.cells import cell_len, set_cell_size
from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual.actions import SkipAction
from textual.binding import Binding
from textual.events import Click
from textual.geometry import Size
from textual.scroll_view import ScrollView
from textual.strip import Strip

from ..app import preferences
from ..app.columns import (
    ALIGN_RIGHT,
    COL_ADVISORY,
    COL_CANDIDATE,
    COL_DOWNLOAD,
    COL_INSTALLED,
    COL_NAME,
    COL_REASON,
    COL_REPO,
    COL_SIZE,
    COL_STATUS,
    COL_SUMMARY,
    HEADER_TIPS,
    HEADERS,
    HIDEABLE,
    cell_style,
    cell_text,
)
from ..app.doc import Bold, Break, Doc, Heading, Inline, Italic, Link, Para, Small
from ..app.package_list import PackageList, Sort
from ..core.marks import Action
from ..core.model import SECURITY_LEVELS, PkgRow, Status
from ..i18n import _, pgettext
from .glyphs import UNICODE, Glyphs, StatusGlyphs, status_glyphs
from .palette import role
from .widgets import hint

# ---------------------------------------------------------------- the columns (§7.3.2)

STATUS_WIDTH = 2   # the status glyph and the flag
NAME_WIDTHS = (12, 48)  # the name column's narrowest and widest
NAME_SHARE = 0.95  # the name column fits this share of the shown names: one very long name pushes nothing away
SUMMARY_MIN = 20
SIDE_STEP = 8      # cells per ← →
# the columns after S and Package in their order, hidden ones where they belong: the reason after the installed
# version, the update type after the latest, the download size after the installed size (as the GUIs show them)
ORDER = (COL_INSTALLED, COL_REASON, COL_CANDIDATE, COL_ADVISORY, COL_REPO, COL_SIZE, COL_DOWNLOAD, COL_SUMMARY)
HIDDEN = frozenset({COL_REASON, COL_ADVISORY, COL_DOWNLOAD})
WIDTHS = {COL_INSTALLED: 16, COL_CANDIDATE: 16, COL_REPO: 12, COL_SIZE: 9, COL_DOWNLOAD: 9, COL_REASON: 12,
          COL_ADVISORY: 14}
# a terminal has no room for the GUIs' long headers
SHORT_HEADERS = {
    COL_INSTALLED: pgettext("short column header", "Installed"),
    COL_CANDIDATE: pgettext("short column header", "Latest"),
    COL_SIZE: pgettext("short column header", "Size"),
    COL_DOWNLOAD: pgettext("short column header", "Download"),
}


def header_text(col: int) -> str:
    return SHORT_HEADERS.get(col) or HEADERS[col]


def column_label(col: int) -> str:
    """The column's full name, for the sort list: the GUIs' header, or its tooltip where it has no title."""
    return HEADER_TIPS.get(col, HEADERS[col]) if col == COL_STATUS else HEADERS[col]


@dataclass
class Columns:
    """Which columns the list shows, in which order, and the widths the user gave them (none yet): the one place the
    Columns dialog changes. S and Package always come first; `order` holds the others (HIDEABLE)."""
    order: list[int] = field(default_factory=lambda: list(ORDER))
    hidden: set[int] = field(default_factory=lambda: set(HIDDEN))
    widths: dict[int, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        assert set(self.order) == set(HIDEABLE)

    def shown(self) -> list[int]:
        return [COL_STATUS, COL_NAME, *(c for c in self.order if c not in self.hidden)]

    def layout(self, width: int, name_width: int) -> list[tuple[int, int]]:
        """(column, width) of each shown column for a list `width` cells wide, the margin not counted.

        The name column gives way first: it shrinks (down to its narrowest) so that the other columns and the
        summary's narrowest fit, as a wide list should not scroll sideways for long names. Where they cannot fit
        anyway, it keeps what it can of its width but S and Package take at most half of the list, so that they stay
        in place while the rest scrolls (§7.3.3)."""
        shown = self.shown()
        summary = SUMMARY_MIN + 1 if COL_SUMMARY in shown else 0
        fixed = []
        for col in shown:
            if col == COL_STATUS:
                fixed.append((col, STATUS_WIDTH))
            elif col == COL_NAME:
                fixed.append((col, 0))  # worked out below
            elif col != COL_SUMMARY:
                fixed.append((col, self.widths.get(col, WIDTHS[col])))
        others = sum(w + 1 for c, w in fixed if c != COL_NAME)
        low = NAME_WIDTHS[0]
        name = self.widths.get(COL_NAME, name_width)
        room = width - others - 1 - summary  # for the name, with everything else at its width
        if room >= low:
            name = min(name, room)
        else:
            # the margin, S and Package within half of the list's width (the margin and its 1 cell back in)
            name = min(name, max(low, (width + 1) // 2 - 1 - (STATUS_WIDTH + 1) - 1))
        fixed = [(c, name if c == COL_NAME else w) for c, w in fixed]
        if COL_SUMMARY in shown:
            # the summary takes the room left (cut with "…"): no sideways scrolling just for it
            room = width - sum(w + 1 for _c, w in fixed) - 1
            fixed.append((COL_SUMMARY, max(SUMMARY_MIN, room)))
        return fixed


def name_lengths(rows: list[PkgRow], basearch: str) -> list[int]:
    """The length of every row's name as cell_text shows it (with the arch of another architecture)."""
    return [len(r.name) if r.arch in ("noarch", basearch) else len(r.name) + len(r.arch) + 1 for r in rows]


def name_width(lengths: list[int], visible: list[int]) -> int:
    """Wide enough for 95% of the shown names (`lengths` of name_lengths), within NAME_WIDTHS."""
    low, high = NAME_WIDTHS
    if not visible:
        return low
    # map and sort run in C: a loop in Python over 70,000 rows took a filter change 15 ms
    shown = sorted(map(lengths.__getitem__, visible))
    return max(low, min(high, shown[min(len(shown) - 1, int(len(shown) * NAME_SHARE))]))


def fit(text: str, width: int, right: bool, ellipsis: str) -> str:
    """`text` in exactly `width` cells: cut with the ellipsis, padded on the side away from its alignment."""
    n = cell_len(text)
    if n > width:
        cut = width - cell_len(ellipsis)
        return set_cell_size(text, cut) + ellipsis if cut > 0 else set_cell_size(text, width)
    return " " * (width - n) + text if right else text + " " * (width - n)


# ---------------------------------------------------------------- the status cells (§7.3.4)

STATUS_ROLES = {Status.INSTALLED: "installed", Status.NOT_INSTALLED: "muted", Status.UPGRADABLE: "upgradable",
                Status.NEWER: "info", Status.ORPHAN: "danger", Status.UNNEEDED: "muted"}


def mark_role(action: Action) -> str:
    return "danger" if action is Action.REMOVE else "marked"


def status_cells(r: PkgRow, mark: Action | None, blocked: bool, symbols: StatusGlyphs) -> tuple[str, str, str, str]:
    """(glyph, its role, flag, its role): a mark shows over the state; the flag says what matters most of a blocked
    upgrade, a version lock and a security advisory, in that order (" " for none)."""
    if mark is not None:
        glyph, glyph_role = symbols.marks[mark], mark_role(mark)
    else:
        glyph, glyph_role = symbols.status[r.status], STATUS_ROLES[r.status]
    if blocked:
        flag, flag_role = symbols.blocked, "danger"
    elif r.locked:
        flag, flag_role = symbols.locked, "upgradable"
    elif any(a.level in SECURITY_LEVELS for a in r.advisories):
        flag, flag_role = symbols.security, "danger"
    else:
        flag, flag_role = " ", "muted"
    return glyph, glyph_role, flag, flag_role


# ---------------------------------------------------------------- what the empty list says (§7.3.8)

LINK_KEYS = tuple("123456789")


def doc_paragraphs(doc: Doc, extra: Iterable[tuple[str, str]] = ()) -> tuple[list[Text], list[str]]:
    """The paragraphs of `doc` as Texts, its links as key hints (the n-th link's key is LINK_KEYS[n]), and the links'
    targets in that order; `extra` hints (key, word) make a paragraph of their own at the end."""
    links: list[str] = []

    def add(spans, text: Text, style: Style) -> None:
        for s in spans:
            if isinstance(s, str):
                text.append(s, style)
            elif isinstance(s, Break):
                text.append("\n")
            elif isinstance(s, Link):
                if len(links) < len(LINK_KEYS):
                    text.append(LINK_KEYS[len(links)], role("key"))
                    text.append(" ")
                    links.append(s.target)
                add(s.children, text, style + role("info"))
            elif isinstance(s, Bold):
                add(s.children, text, style + Style(bold=True))
            elif isinstance(s, Italic):
                add(s.children, text, style + Style(italic=True))
            elif isinstance(s, Small):
                add(s.children, text, style)
            else:  # Colored: no colour of its own in a terminal (§9.1)
                add(s.children, text, style)

    paragraphs = []
    for block in doc.blocks:
        if isinstance(block, (Para, Heading, Inline)):
            text = Text()
            add(block.spans, text, Style(bold=True) if isinstance(block, Heading) else Style())
            paragraphs.append(text)
    extra = tuple(extra)
    if extra:
        paragraphs.append(hint(*extra))
    return paragraphs, links


# ---------------------------------------------------------------- the list

class PackageTable(ScrollView, can_focus=True):
    """The view. The cursor is a position; a selection of several rows (Shift with the arrows and pages) is a set of
    positions around it, kept through a sort and dropped when the list changes. What the user does reaches its
    owner through the callbacks it sets: `on_current(pos | None)`, `on_selection()`, and `commands`, which runs
    the keys that act on the rows (sorting, copying, following a link of the empty list)."""

    BINDINGS = [
        Binding("up,k", "move(-1)", show=False),
        Binding("down,j", "move(1)", show=False),
        Binding("pageup", "page(-1)", show=False),
        Binding("pagedown", "page(1)", show=False),
        Binding("home", "jump(0)", show=False),
        Binding("end", "jump(-1)", show=False),
        Binding("shift+up", "extend(-1)", show=False),
        Binding("shift+down", "extend(1)", show=False),
        Binding("shift+pageup", "extend_page(-1)", show=False),
        Binding("shift+pagedown", "extend_page(1)", show=False),
        Binding("left,h", f"side(-{SIDE_STEP})", show=False),
        Binding("right,l", f"side({SIDE_STEP})", show=False),
        Binding("s", "sort", _("Sort")),
        Binding("S", "reverse_sort", show=False),
        Binding("y", "copy_names", show=False),
        Binding("Y", "copy_nevras", show=False),
        Binding("enter", "details", show=False),
        Binding("escape", "escape", show=False),
        *[Binding(key, f"link({i})", show=False) for i, key in enumerate(LINK_KEYS)],
    ]
    DEFAULT_CSS = "PackageTable { height: 1fr; background: $background; }"

    def __init__(self, packages: PackageList, commands, glyphs: Glyphs = UNICODE, utf8: bool = True, **kw):
        super().__init__(**kw)
        self.packages = packages
        self.commands = commands
        self.glyphs = glyphs
        self.utf8 = utf8
        self.symbols = status_glyphs(utf8)
        self.columns_state = Columns()
        self.columns: list[tuple[int, int]] = []
        self.cursor = 0
        self.anchor: int | None = None    # where a Shift selection started
        self.selection: set[int] = set()  # the selected positions when more than the cursor's row is selected
        self.sort_shown: Sort | None = None
        self.centre = bool(preferences.value(preferences.TUI_CENTRE_SCROLLING))
        self._inset = 0
        self._name_width = NAME_WIDTHS[0]
        self._lengths: tuple[list[PkgRow] | None, list[int]] = (None, [])  # (the rows, name_lengths of them)
        self.empty_doc = Doc()
        self.empty_extra: tuple[tuple[str, str], ...] = ()
        self.links: list[str] = []
        self._empty_cache: tuple[int, int, list[Strip]] | None = None  # (width, generation, lines)
        self._colours = 0  # bumped when the scheme changes: cached lines carry its colours
        self.on_current: Callable[[int | None], None] = lambda pos: None
        self.on_selection: Callable[[], None] = lambda: None
        self.lines_drawn = 0  # for measuring (§14.1): render_line calls since the owner last reset it
        packages.about_to_reset.connect(self._about_to_reset)
        packages.reset.connect(self._reset)
        packages.sorted.connect(self._sorted)
        packages.rows_changed.connect(lambda _positions=None: self.refresh())
        preferences.changed.connect(self._pref_changed)
        self._layout_columns()

    def on_unmount(self) -> None:
        preferences.changed.disconnect(self._pref_changed)

    def _pref_changed(self, key: str) -> None:
        if key == preferences.TUI_CENTRE_SCROLLING:
            self.centre = bool(preferences.value(key))
            self.follow_cursor()
        elif key == preferences.TUI_STATUS_GLYPHS:
            self.symbols = status_glyphs(self.utf8)
            self.refresh()

    def refresh_colours(self) -> None:
        """The scheme changed (KramApp.refresh_colours): the cached lines of the empty list carry the old one."""
        self._colours += 1

    # ---------------------------------------------------------------- sizes

    @property
    def view_width(self) -> int:
        """The width the lines are drawn in: without the vertical scrollbar, which shows when the rows do not fit.
        Worked out before the layout has it, so that the summary never pushes the list into sideways scrolling."""
        height = self.size.height
        bar = self.styles.scrollbar_size_vertical if self.virtual_lines > height > 0 else 0
        return max(1, self.size.width - bar)

    @property
    def virtual_lines(self) -> int:
        return len(self.packages) + 1 + self._inset

    @property
    def rows_shown(self) -> int:
        """Rows in sight: the lines under the header, less those a slide-over covers."""
        return max(1, self.scrollable_content_region.height - 1 - self._inset)

    @property
    def total_width(self) -> int:
        return 1 + sum(w + 1 for _c, w in self.columns)  # 1: the margin

    @property
    def frozen(self) -> int:
        """The width that does not scroll sideways: the margin, S and Package, if they take at most half the view."""
        w = 1 + sum(w + 1 for _c, w in self.columns[:2])
        width = self.view_width
        return w if self.total_width > width and 2 * w <= width else 0

    @property
    def bottom_inset(self) -> int:
        return self._inset

    @bottom_inset.setter
    def bottom_inset(self, lines: int) -> None:
        """Lines at the bottom a slide-over covers (§7.3.9): a short list gets room to scroll its last rows out from
        under it, and the cursor keeps out of them."""
        if lines == self._inset:
            return
        self._inset = lines
        self._sync_size()
        self.call_after_refresh(self.follow_cursor)

    def _layout_columns(self) -> None:
        self.columns = self.columns_state.layout(self.view_width - 1, self._name_width)

    def _sync_size(self) -> None:
        self._layout_columns()
        self.virtual_size = Size(self.total_width, self.virtual_lines)

    def set_columns(self, columns: Columns) -> None:
        """For the Columns dialog."""
        self.columns_state = columns
        self._sync_size()
        self.refresh()

    def on_resize(self) -> None:
        self._sync_size()
        self.call_after_refresh(self.follow_cursor)

    # ---------------------------------------------------------------- the model's signals

    def _about_to_reset(self) -> None:
        self.anchor = None
        self.selection = set()

    def _reset(self) -> None:
        p = self.packages
        if self._lengths[0] is not p.rows:  # a new catalog
            self._lengths = (p.rows, name_lengths(p.rows, p.basearch))
        self._name_width = name_width(self._lengths[1], p.visible)
        self.cursor = 0
        self._sync_size()
        self.scroll_to(x=0, y=0, animate=False, force=True)
        self.refresh()

    def _sorted(self, moved: list[int]) -> None:
        """The rows were sorted again: the cursor and the selection stay on their rows."""
        if not moved:
            return
        self.cursor = moved[self.cursor] if self.cursor < len(moved) else 0
        self.anchor = moved[self.anchor] if self.anchor is not None and self.anchor < len(moved) else None
        self.selection = {moved[p] for p in self.selection if p < len(moved)}
        self.follow_cursor()
        self.refresh()

    # ---------------------------------------------------------------- drawing

    def render_line(self, y: int) -> Strip:
        self.lines_drawn += 1
        width = self.scrollable_content_region.width
        if not len(self.packages) and y > 0:
            return self._empty_line(y - 1, width)
        sx, sy = self.scroll_offset
        pos = None if y == 0 else sy + y - 1
        if pos is not None and pos >= len(self.packages):
            return Strip.blank(width)
        segments, base = self._header() if pos is None else self._row(pos)
        line = Strip(segments)
        frozen = self.frozen
        if frozen:
            line = Strip.join([line.crop(0, frozen), line.crop(frozen + sx, sx + width)])
        else:
            line = line.crop(sx, sx + width)
        return line.adjust_cell_length(width, base)

    def _header(self) -> tuple[list[Segment], Style]:
        base = role("header")
        segments = [Segment(" ", base)]
        sort = self.sort_shown
        for col, w in self.columns:
            text = header_text(col)
            if sort is not None and sort[0] == col:
                arrow = self.glyphs.down if sort[1] else self.glyphs.up
                text = fit(text, max(1, w - cell_len(arrow) - 1), False, self.glyphs.ellipsis).rstrip() + " " + arrow
            segments += [Segment(fit(text, w, col in ALIGN_RIGHT, self.glyphs.ellipsis), base), Segment(" ", base)]
        return segments, base

    def _row(self, pos: int) -> tuple[list[Segment], Style]:
        p = self.packages
        r, ctx = p.row(pos), p.ctx
        mark = ctx.marks.get(r.key)
        action = mark.action if mark else None
        ansi = self.app.ansi_color
        # a marked row: tinted in high colour; in 16 colours its glyph and name take the mark's colour (§7.3.5)
        base = role("tint-danger" if action is Action.REMOVE else "tint-marked") if action and not ansi else Style()
        if pos == self.cursor:
            base += role("cursor") if self.has_focus else role("cursor-blurred")
        selected = len(self.selection) > 1 and pos in self.selection
        segments = [Segment(self.glyphs.selected if selected else " ", base + role("marked") if selected else base)]
        ellipsis = self.glyphs.ellipsis
        for col, w in self.columns:
            if col == COL_STATUS:
                glyph, glyph_role, flag, flag_role = status_cells(r, action, r.key in ctx.blocked, self.symbols)
                segments += [Segment(glyph, base + role(glyph_role)), Segment(flag, base + role(flag_role))]
            else:
                style = cell_style(r, col, ctx)
                cell = base + Style(bold=style.bold or None, italic=style.italic or None, dim=style.dimmed or None)
                if col == COL_NAME and action and ansi:
                    cell += role(mark_role(action))
                segments.append(Segment(fit(cell_text(r, col, ctx) or "", w, col in ALIGN_RIGHT, ellipsis), cell))
            segments.append(Segment(" ", base))
        return segments, base

    def _empty_line(self, line: int, width: int) -> Strip:
        """A line of the empty list's explanation, centred in the rows in sight."""
        cached = self._empty_cache
        if cached is None or cached[:2] != (width, self._colours):
            paragraphs, self.links = doc_paragraphs(self.empty_doc, self.empty_extra)
            console = self.app.console
            lines: list[Strip] = []
            for i, text in enumerate(paragraphs):
                if i:
                    lines.append(Strip.blank(width))
                for wrapped in text.wrap(console, max(1, width - 4), justify="center"):
                    lines.append(Strip(list(wrapped.render(console)), wrapped.cell_len))
            cached = self._empty_cache = (width, self._colours, lines)
        lines = cached[2]
        top = max(0, (self.rows_shown - len(lines)) // 2)
        if top <= line < top + len(lines):
            strip = lines[line - top]
            pad = max(0, (width - strip.cell_length) // 2)
            return Strip.join([Strip.blank(pad), strip]).adjust_cell_length(width)
        return Strip.blank(width)

    def set_empty(self, doc: Doc, extra: Iterable[tuple[str, str]] = ()) -> None:
        """What the list says while it is empty; `extra`: key hints after it (key, word)."""
        self.empty_doc, self.empty_extra = doc, tuple(extra)
        self._empty_cache = None
        self.links = doc_paragraphs(doc)[1]
        self.refresh()

    def show_sort(self, sort: Sort | None) -> None:
        self.sort_shown = sort
        self.refresh()

    # ---------------------------------------------------------------- the cursor and the selection

    def current_row(self) -> PkgRow | None:
        return self.packages.row(self.cursor) if self.cursor < len(self.packages) else None

    def selected_positions(self) -> list[int]:
        if not len(self.packages):
            return []
        return sorted(self.selection) if len(self.selection) > 1 else [self.cursor]

    def ensure_visible(self) -> None:
        top, shown = self.scroll_offset.y, self.rows_shown
        if self.cursor < top:
            self.scroll_to(y=self.cursor, animate=False, force=True)
        elif self.cursor >= top + shown:
            self.scroll_to(y=self.cursor - shown + 1, animate=False, force=True)

    def centre_cursor(self) -> None:
        """The cursor mid-list (T11); near either end the list stops and the cursor moves on."""
        shown = self.rows_shown
        top = max(0, min(self.cursor - shown // 2, len(self.packages) - shown))
        self.scroll_to(y=top, animate=False, force=True)

    def follow_cursor(self) -> None:
        if self.centre:
            self.centre_cursor()
        else:
            self.ensure_visible()

    def select(self, pos: int, scroll: bool = True) -> None:
        """Only `pos` selected, the cursor on it; `scroll`: brought into view. Its owner hears of it even when the
        cursor stays where it was: after a change of the list another row is there."""
        self._go(pos, extend=False, scroll=scroll, tell=True)

    def scroll_to_top(self) -> None:
        self.scroll_to(y=0, animate=False, force=True)

    def _go(self, pos: int, extend: bool = False, scroll: bool = True, tell: bool = False) -> None:
        n = len(self.packages)
        if not n:
            return
        old = self.cursor
        pos = max(0, min(n - 1, pos))
        had = len(self.selection) > 1
        if extend:
            if self.anchor is None:
                self.anchor = old
            low, high = sorted((self.anchor, pos))
            self.selection = set(range(low, high + 1))
        else:
            self.anchor = None
            self.selection = set()
        self.cursor = pos
        if scroll:
            self.follow_cursor()
        self.refresh()
        if pos != old or tell:
            self.on_current(pos)
        if pos != old or extend or had or tell:
            self.on_selection()

    def clear_selection(self) -> bool:
        if len(self.selection) <= 1:
            return False
        self.anchor = None
        self.selection = set()
        self.refresh()
        self.on_selection()
        return True

    # ---------------------------------------------------------------- keys and clicks

    def action_move(self, d: int) -> None:
        self._go(self.cursor + d)

    def action_page(self, d: int) -> None:
        self._go(self.cursor + d * max(1, self.rows_shown - 1))

    def action_jump(self, pos: int) -> None:
        self._go(pos if pos >= 0 else len(self.packages) - 1)

    def action_extend(self, d: int) -> None:
        self._go(self.cursor + d, extend=True)

    def action_extend_page(self, d: int) -> None:
        self._go(self.cursor + d * max(1, self.rows_shown - 1), extend=True)

    def action_side(self, d: int) -> None:
        self.scroll_to(x=max(0, self.scroll_offset.x + d), animate=False, force=True)

    def action_sort(self) -> None:
        self.commands.choose_sort()

    def action_reverse_sort(self) -> None:
        self.commands.reverse_sort()

    def action_copy_names(self) -> None:
        if len(self.packages):
            self.commands.copy_names()

    def action_copy_nevras(self) -> None:
        if len(self.packages):
            self.commands.copy_nevras()

    def action_details(self) -> None:
        self.commands.open_details()

    def action_escape(self) -> None:
        """Esc clears a selection of several rows; else it is the window's (it focuses the list, or quits while
        Kram waits for another package manager)."""
        if not self.clear_selection() and not self.commands.escape():
            raise SkipAction()

    def action_link(self, i: int) -> None:
        self.commands.follow_empty_link(self.links[i])

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "link":
            return not len(self.packages) and parameters[0] < len(self.links)
        return True

    def on_click(self, event: Click) -> None:
        line = event.y
        if line >= 1 and len(self.packages):
            pos = self.scroll_offset.y + line - 1
            if pos < len(self.packages):
                self._go(pos, scroll=False)

    def on_focus(self) -> None:
        self.refresh()
        self.app.list_focused()

    def on_blur(self) -> None:
        self.refresh()
