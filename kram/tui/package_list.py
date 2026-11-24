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
from ..app.actions import action_defs, mark_id
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
from .keymap import CONTEXT_KEYS, bindings_key
from .palette import filled, over, role
from .widgets import hint

# ---------------------------------------------------------------- the columns (§7.3.2)

STATUS_WIDTH = 2   # the status glyph and the flag
NAME_WIDTHS = (12, 48)  # the name column's narrowest and widest
NAME_SHARE = 0.95  # the name column fits this share of the shown names: one very long name pushes nothing away
SUMMARY_MIN = 20
SIDE_STEP = 8      # cells per ← →
# what the keys do, for the Keys dialog (§10.20)
MOVE = _("Move the cursor")
EXTEND = _("Extend the selection")
SIDEWAYS = _("Scroll sideways")
LABELS = {d.id: d.label for d in action_defs()}
# the columns after S and Package in their order, hidden ones where they belong: the reason after the installed
# version, the update type after the latest, the download size after the installed size (as the GUIs show them)
ORDER = (COL_INSTALLED, COL_REASON, COL_CANDIDATE, COL_ADVISORY, COL_REPO, COL_SIZE, COL_DOWNLOAD, COL_SUMMARY)
HIDDEN = frozenset({COL_REASON, COL_ADVISORY, COL_DOWNLOAD})
WIDTHS = {COL_INSTALLED: 16, COL_CANDIDATE: 16, COL_REPO: 12, COL_SIZE: 9, COL_DOWNLOAD: 9, COL_REASON: 12,
          COL_ADVISORY: 14}
# the widths the Columns dialog gives (§10.18): every column but S, which is its two glyphs, and the summary, which
# takes the room left
RESIZABLE = frozenset({COL_NAME, *WIDTHS})
WIDTH_RANGE = (4, 64)
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

    def to_dict(self) -> dict:
        """As the setting keeps it (kram.app.preferences.TUI_COLUMNS)."""
        return {"order": list(self.order), "hidden": sorted(self.hidden),
                "widths": {str(c): w for c, w in sorted(self.widths.items())}}

    @classmethod
    def from_dict(cls, data) -> "Columns":
        """What the setting holds; whatever does not fit the columns of this version (a column added or dropped since,
        a hand-edited file) is left at its default."""
        columns = cls()
        if not isinstance(data, dict):
            return columns
        order = data.get("order")
        if isinstance(order, list) and sorted(order) == sorted(HIDEABLE):
            columns.order = list(order)
        hidden = data.get("hidden")
        if isinstance(hidden, list) and all(c in HIDEABLE for c in hidden):
            columns.hidden = set(hidden)
        widths = data.get("widths")
        if isinstance(widths, dict):
            for key, w in widths.items():
                col = int(key) if str(key).isdigit() else None
                if col in RESIZABLE and isinstance(w, int) and WIDTH_RANGE[0] <= w <= WIDTH_RANGE[1]:
                    columns.widths[col] = w
        return columns

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
        Binding("up,k", "move(-1)", MOVE, show=False),
        Binding("down,j", "move(1)", MOVE, show=False),
        Binding("pageup", "page(-1)", MOVE, show=False),
        Binding("pagedown", "page(1)", MOVE, show=False),
        Binding("home", "jump(0)", MOVE, show=False),
        Binding("end", "jump(-1)", MOVE, show=False),
        Binding("shift+up", "extend(-1)", EXTEND, show=False),
        Binding("shift+down", "extend(1)", EXTEND, show=False),
        Binding("shift+pageup", "extend_page(-1)", EXTEND, show=False),
        Binding("shift+pagedown", "extend_page(1)", EXTEND, show=False),
        Binding("left,h", f"side(-{SIDE_STEP})", SIDEWAYS, show=False),
        Binding("right,l", f"side({SIDE_STEP})", SIDEWAYS, show=False),
        Binding("s", "sort", _("Sort")),
        Binding("S", "reverse_sort", _("Reverse the sort"), show=False),
        # the status cell's click (§6.5, LIST_STATUS_CLICK): the likely mark or the row's menu, as the setting says
        Binding("space", "status_click", _("Mark the likely action"), show=False),
        # the actions of the rows (kram.tui.keymap), as the Package menu runs them
        Binding(bindings_key(mark_id(Action.INSTALL)), "run_either('mark.install', 'mark.upgrade')",
                _("Mark for installation or upgrade"), show=False),
        Binding(bindings_key(mark_id(Action.REMOVE)), "run('mark.remove')", LABELS[mark_id(Action.REMOVE)],
                show=False),
        Binding(bindings_key("unmark"), "run('unmark')", LABELS["unmark"], show=False),
        Binding(bindings_key("lock"), "run_either('lock', 'unlock')", _("Lock or unlock the version"), show=False),
        Binding(bindings_key("copy_name"), "copy_names", LABELS["copy_name"], show=False),
        Binding(bindings_key("copy_nevra"), "copy_nevras", LABELS["copy_nevra"], show=False),
        Binding(",".join(CONTEXT_KEYS), "context_menu", _("Context menu"), show=False),
        Binding("enter", "details", _("Details"), show=False),
        Binding("escape", "escape", _("Clear the selection"), show=False),
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
        return filled(self, self._line(y))

    def _line(self, y: int) -> Strip:
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
        segments = [Segment(self.glyphs.selected if selected else " ", over(base, role("marked")) if selected else base)]
        ellipsis = self.glyphs.ellipsis
        for col, w in self.columns:
            if col == COL_STATUS:
                glyph, glyph_role, flag, flag_role = status_cells(r, action, r.key in ctx.blocked, self.symbols)
                segments += [Segment(glyph, over(base, role(glyph_role))), Segment(flag, over(base, role(flag_role)))]
            else:
                style = cell_style(r, col, ctx)
                cell = base + Style(bold=style.bold or None, italic=style.italic or None, dim=style.dimmed or None)
                if col == COL_NAME and action and ansi:
                    cell = over(cell, role(mark_role(action)))
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

    def action_run(self, action_id: str) -> None:
        if len(self.packages):
            self.commands.run_action(action_id)

    def action_run_either(self, *action_ids: str) -> None:
        if len(self.packages):
            self.commands.run_either(*action_ids)

    def _beside_cursor(self, x: int) -> tuple[int, int]:
        """The screen cell under the cursor's row, `x` cells into the list: where its menus open."""
        region = self.content_region
        line = 1 + self.cursor - self.scroll_offset.y
        return region.x + x, region.y + max(1, min(line, region.height - 1)) + 1

    def action_context_menu(self, at: tuple[int, int] | None = None) -> None:
        """`.`, the Menu key, Shift+F10, a right click: the row's menu (§7.7.2), next to the cursor's row."""
        self.commands.context_menu(at if at is not None else self._beside_cursor(4))

    def action_status_click(self, at: tuple[int, int] | None = None) -> None:
        """`space`, a click on the status cell: what a click on the status icon does in the GUIs."""
        if len(self.packages):
            self.commands.status_click(at if at is not None else self._beside_cursor(1))

    def in_status_cell(self, x: int) -> bool:
        """Whether the list's cell `x` (of the widget, as a click gives it) is in the status column."""
        sx = self.scroll_offset.x
        frozen = self.frozen
        x = x if frozen and x < frozen else x + sx
        return 1 <= x < 1 + STATUS_WIDTH  # 1: the margin

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "link":
            return not len(self.packages) and parameters[0] < len(self.links)
        return True

    def on_click(self, event: Click) -> None:
        """A click picks the row; a right click also opens its menu, keeping a selection the row is in. A click on
        the status cell is the status click (LIST_STATUS_CLICK), a double click elsewhere on the row the likely mark
        (LIST_DOUBLE_CLICK_MARK), as in the GUIs."""
        line = event.y
        if line >= 1 and len(self.packages):
            pos = self.scroll_offset.y + line - 1
            if pos < len(self.packages):
                if event.button != 3 or pos not in self.selected_positions():
                    self._go(pos, scroll=False)
                if event.button == 3:
                    self.action_context_menu((event.screen_x, event.screen_y + 1))
                elif event.button == 1 and self.in_status_cell(event.x):
                    if event.chain == 1:  # the second click of a double one would undo the first
                        self.action_status_click((event.screen_x, event.screen_y + 1))
                elif event.button == 1 and event.chain == 2:
                    self.commands.likely_mark()

    def on_focus(self) -> None:
        self.refresh()
        self.app.list_focused()

    def on_blur(self) -> None:
        self.refresh()
