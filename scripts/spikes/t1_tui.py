"""TUI spike T1 (Textual): a package list over 70k rows that draws only the lines on screen, the sidebar and the
details panels pinned in a wide terminal and sliding over the list in a narrow one, and how the sidebar's views and
the details' tabs are switched.

Run it:   python3 scripts/spikes/t1_tui.py            (the app)
Measure:  python3 scripts/spikes/t1_tui.py bench      (headless; prints timings for a narrow and a wide terminal)
Shots:    python3 scripts/spikes/t1_tui.py shots DIR  (headless; SVG screenshots of the layouts and edge cases)

Keys: g and d show a panel and focus it, or hide it when it has the focus; Esc goes back to the list. In the sidebar
[ and ] switch the view, v opens the list of views; in the details [ and ] (or 1-7) switch the tab, t opens the list
of tabs. In the list ←/→ (h/l) scroll sideways; the status and name columns stay in place when there is room. / opens
the search, m (or F9) the menu.

Which key goes where (the "first responder"): Textual hands a key to the focused widget first, then to its parents,
the screen and the app; a text field takes the printable keys itself. A modal screen (the search, a menu) sits on
top of the window, but the app's own bindings would still answer under it, so `KramTui.check_action` turns the
window's keys (WINDOW_ACTIONS) off while a modal screen is up or a text field has the focus. This is the scope
kram.app.actions already gives its actions ("window" / "table"), applied to the terminal.

The rows come from a pickled CatalogSnapshot when KRAM_SPIKE_SNAPSHOT names one, else from a real
`Catalog().load()` (read-only), else from made-up rows. Needs python3-textual (Fedora 43/44: 4.0.0, 45: 8.1.x).
"""
import asyncio
import os
import pickle
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rich.segment import Segment  # noqa: E402
from rich.style import Style  # noqa: E402
from rich.text import Text  # noqa: E402
from textual import __version__ as TEXTUAL_VERSION  # noqa: E402
from textual.app import App, ComposeResult  # noqa: E402
from textual.binding import Binding  # noqa: E402
from textual.containers import Horizontal, Vertical, VerticalScroll  # noqa: E402
from textual.geometry import Size  # noqa: E402
from textual.message import Message  # noqa: E402
from textual.screen import ModalScreen  # noqa: E402
from textual.scroll_view import ScrollView  # noqa: E402
from textual.strip import Strip  # noqa: E402
from textual.theme import Theme  # noqa: E402
from textual.widget import Widget  # noqa: E402
from textual.widgets import Footer, Input, OptionList, Static  # noqa: E402
from textual.widgets.option_list import Option  # noqa: E402

from kram.app.actions import MenuItem, action_defs, menu_bar  # noqa: E402
from kram.app.columns import (  # noqa: E402
    COL_CANDIDATE,
    COL_INSTALLED,
    COL_NAME,
    COL_REPO,
    COL_SIZE,
    COL_SUMMARY,
    HEADERS,
    cell_text,
)
from kram.app.details import TABS, TabChoice, tab_titles  # noqa: E402
from kram.app.package_list import PackageList  # noqa: E402
from kram.app.sidebar import VIEWS, history_id  # noqa: E402
from kram.core.filters import (  # noqa: E402
    FilterEntry,
    custom_filter_entries,
    environment_filters,
    group_filters,
    origin_filters,
    status_filters,
    visible_entries,
)
from kram.core.model import Status  # noqa: E402
from kram.core.search import MODE_LABELS, Mode, SearchIndex  # noqa: E402

WIDE = 100  # columns: from here on the panels are pinned beside and under the list, below it they slide over it
TALL = 34   # rows: from here on (in a wide terminal) the sidebar lists every view at its bottom, as the GUIs do

STATUS_CHAR = {Status.INSTALLED: "■", Status.UPGRADABLE: "▲", Status.NOT_INSTALLED: "□", Status.ORPHAN: "◆",
               Status.UNNEEDED: "◇", Status.NEWER: "▼"}
PANELS = ("side", "details")
# the GUIs' headers are longer than these columns; a terminal has no room to spare
SHORT_HEADERS = {COL_INSTALLED: "Installed", COL_CANDIDATE: "Latest", COL_SIZE: "Size"}
# the window's own keys: off while a modal screen is up or a text field has the focus (see the module's docstring)
WINDOW_ACTIONS = {"toggle_panel", "search", "menu", "quit", "back_to_list"}


# ---------------------------------------------------------------- colours

class Palette(Widget):
    """Every colour of the TUI, by role. No colour is written anywhere else: widgets' CSS uses theme variables, and
    text drawn in Python asks `role(name)`. Two sets of rules: high-colour themes take Textual's theme variables;
    16-colour schemes (Textual's `App:ansi`) use only what a 16-colour terminal has: its 16 colours, its
    own foreground and background, bold, dim, reverse. With the "Terminal" scheme those are the terminal's own
    colours, so the terminal's light or dark mode shows at once, with no restart."""

    ROLES = ("muted", "rule", "key", "current", "header", "cursor", "cursor-blurred", "upgradable", "installed",
             "marked", "info", "danger", "ok", "badge")
    COMPONENT_CLASSES = {f"role--{r}" for r in ROLES}
    DEFAULT_CSS = """
    Palette { display: none; }
    Palette > .role--muted { color: $text-muted; }
    Palette > .role--rule { color: $border-blurred; }
    Palette > .role--key { color: $accent; text-style: bold; }
    Palette > .role--current { text-style: reverse bold; }
    Palette > .role--header { color: $text-muted; text-style: bold; }
    Palette > .role--cursor { background: $block-cursor-background; color: $block-cursor-foreground;
                              text-style: $block-cursor-text-style; }
    Palette > .role--cursor-blurred { background: $block-cursor-blurred-background;
                                      color: $block-cursor-blurred-foreground; }
    Palette > .role--upgradable { color: $warning; }
    Palette > .role--installed { color: $success; }
    Palette > .role--marked { color: $accent; text-style: bold; }
    Palette > .role--info { color: $primary; text-style: bold; }
    Palette > .role--danger { color: $error; text-style: bold; }
    Palette > .role--ok { color: $success; }
    Palette > .role--badge { color: $error; text-style: reverse bold; }


    App:ansi Palette > .role--muted { color: $foreground; text-style: dim; }
    App:ansi Palette > .role--header { color: $foreground; text-style: bold dim; }
    App:ansi Palette > .role--key { color: $warning; text-style: bold; }
    App:ansi Palette > .role--cursor { background: $background; color: $foreground; text-style: reverse bold; }
    App:ansi Palette > .role--cursor-blurred { background: $background; color: $foreground; text-style: underline; }
    """


_palette: Palette | None = None


def role(name: str) -> Style:
    """The text style of a colour role (Palette), from the current scheme; plain until the palette has its styles
    (the window draws its texts again then: KramTui.refresh_colours)."""
    try:
        return _palette.get_component_rich_style(f"role--{name}", partial=True)
    except (AttributeError, KeyError):  # no palette yet, or not styled yet
        return Style()


# 16-colour schemes of our own: only the terminal's 16 colours, by their ANSI names
ANSI_THEMES = [
    Theme(name="kram-midnight", primary="ansi_bright_cyan", secondary="ansi_bright_cyan", accent="ansi_bright_yellow",
          warning="ansi_bright_yellow", error="ansi_bright_red", success="ansi_bright_green",
          foreground="ansi_bright_white", background="ansi_blue", surface="ansi_blue", panel="ansi_blue",
          boost="ansi_blue", dark=True,
          variables={"border": "ansi_bright_cyan", "border-blurred": "ansi_white", "scrollbar": "ansi_cyan",
                     "footer-background": "ansi_cyan", "footer-foreground": "ansi_black",
                     "footer-key-foreground": "ansi_bright_white", "input-cursor-text-style": "reverse"}),
    Theme(name="kram-console", primary="ansi_green", secondary="ansi_cyan", accent="ansi_bright_green",
          warning="ansi_yellow", error="ansi_red", success="ansi_green", foreground="ansi_white",
          background="ansi_black", surface="ansi_black", panel="ansi_black", boost="ansi_black", dark=True,
          variables={"border": "ansi_bright_green", "border-blurred": "ansi_bright_black", "scrollbar": "ansi_green",
                     "input-cursor-text-style": "reverse"}),
]
# (theme, label): what Settings → Colours offers, in its order
SCHEMES = [
    ("textual-ansi", "Terminal: 16 colours, follows the terminal"),
    ("kram-midnight", "Midnight: 16 colours, blue"),
    ("kram-console", "Console: 16 colours, black"),
    ("textual-dark", "Textual dark: high colour"),
    ("textual-light", "Textual light: high colour"),
    ("nord", "Nord: high colour"),
    ("gruvbox", "Gruvbox: high colour"),
    ("solarized-light", "Solarized light: high colour"),
    ("tokyo-night", "Tokyo Night: high colour"),
]
ANSI_SCHEMES = {"textual-ansi", *(t.name for t in ANSI_THEMES)}


def hint(*pairs: tuple[str, str]) -> Text:
    """Key hints for a panel's bottom border: each key in the "key" role, then what it does; lower case, as the
    keys are typed (the footer shows them so too). A Text, not markup: Textual's markup has no working escape for
    "["."""
    t = Text()
    for i, (key, label) in enumerate(pairs):
        if i:
            t.append("  ")
        t.append(key, role("key"))
        t.append(f" {label}")
    return t


# ---------------------------------------------------------------- data

def snapshot():
    path = os.environ.get("KRAM_SPIKE_SNAPSHOT")
    if path and Path(path).exists():
        with open(path, "rb") as f:
            return pickle.load(f)
    try:
        from kram.core.catalog import Catalog
        return Catalog().load()
    except Exception as e:  # noqa: BLE001 - no libdnf5 or no cache: made-up rows still answer the speed questions
        print(f"no catalog ({e}); using made-up rows", file=sys.stderr)
        return fake_snapshot()


def fake_snapshot(n: int = 70000):
    from kram.core.model import CatalogSnapshot, Origin, PkgRow
    rnd = random.Random(1)
    rows = []
    for i in range(n):
        installed = rnd.random() < 0.05
        rows.append(PkgRow(name=f"package-{i:05d}", arch="x86_64", summary="A made-up package to fill the list",
                           installed_evr="1.2.3-4.fc44" if installed else "", candidate_evr="1.2.4-1.fc44",
                           repo_id="fedora", size=rnd.randint(1000, 10**9), origin=Origin.FEDORA,
                           status=Status.INSTALLED if installed else Status.NOT_INSTALLED))
    return CatalogSnapshot(rows=rows, n_installed=0, n_upgradable=0, load_seconds=0)


def view_entries(snap, view: str, marked) -> list[FilterEntry]:
    """The sidebar's entries of a view, as kram.app.sidebar builds them (without its scheduler)."""
    if view == "status":
        return visible_entries(status_filters(snap, marked, set()))
    if view == "origin":
        return origin_filters(snap)
    if view == "groups":
        return group_filters(snap)
    if view == "environments":
        return environment_filters(snap)
    if view == "custom":
        return custom_filter_entries(snap, [])
    return []  # search results: built by the app from its history


PLACEHOLDER = {"search": "No searches yet.\nPress / to search.",
               "custom": "No custom filters.\nPress F to make one."}


# ---------------------------------------------------------------- the package list

class CursorMoved(Message):
    pass


class PackageTable(ScrollView, can_focus=True):
    """Draws only the lines on screen: `render_line` reads `PackageList` for the row at that line, so 70k rows cost
    nothing until they scroll into view. Line 0 is the header. The columns have their natural widths; when they do
    not fit, the list scrolls sideways, and the status and name columns stay in place if they leave room for the
    rest. `bottom_inset`: lines covered by the details slide-over, which the cursor keeps out of."""

    BINDINGS = [
        Binding("up,k", "move(-1)", "Up", show=False),
        Binding("down,j", "move(1)", "Down", show=False),
        Binding("pageup", "page(-1)", "Page up", show=False),
        Binding("pagedown", "page(1)", "Page down", show=False),
        Binding("home", "jump(0)", show=False),
        Binding("end", "jump(-1)", show=False),
        Binding("left,h", "side(-8)", show=False),
        Binding("right,l", "side(8)", show=False),
        Binding("space", "toggle_mark", "Mark"),
    ]
    DEFAULT_CSS = "PackageTable { height: 1fr; scrollbar-size: 1 1; }"

    def __init__(self, plist: PackageList, **kw):
        super().__init__(**kw)
        self.plist = plist
        self.cursor = 0
        self.marked: set[tuple[str, str]] = set()
        self._inset = 0
        self.centre = True  # mc's "centre scrolling": the list moves under a cursor that stays mid-screen
        self.columns: list[tuple[int, int, bool]] = []
        self.lines_drawn = 0  # render_line calls and their time, for the bench
        self.render_seconds = 0.0
        self.set_columns()

    def set_columns(self) -> None:
        # wide enough for 95% of the shown names: one 81-character name should not push every other column away
        lengths = sorted(len(self.plist.rows[i].name) for i in self.plist.visible)
        name_w = max(12, min(48, lengths[int(len(lengths) * 0.95)] if lengths else 12))
        self.columns = [(-1, 1, False), (COL_NAME, name_w, False), (COL_INSTALLED, 16, False),
                        (COL_CANDIDATE, 16, False), (COL_REPO, 12, False), (COL_SIZE, 9, True), (COL_SUMMARY, 60, False)]

    @property
    def total_width(self) -> int:
        return sum(w + 1 for _c, w, _r in self.columns)

    @property
    def frozen(self) -> int:
        """Width of the columns that do not scroll sideways: status and name, if they take at most half the view."""
        w = sum(w + 1 for _c, w, _r in self.columns[:2])
        return w if self.total_width > self.size.width and 2 * w <= self.size.width else 0

    @property
    def bottom_inset(self) -> int:
        return self._inset

    @bottom_inset.setter
    def bottom_inset(self, lines: int) -> None:
        """A short list gets room to scroll its last rows out from under the slide-over."""
        self._inset = lines
        self._sync_size()

    def _sync_size(self) -> None:
        self.virtual_size = Size(self.total_width, len(self.plist) + 1 + self._inset)

    def on_resize(self) -> None:
        self._sync_size()

    def reset(self) -> None:
        self.cursor = 0
        self.set_columns()
        self._sync_size()
        self.scroll_to(x=0, y=0, animate=False, force=True)
        self.refresh()
        self.post_message(CursorMoved())

    def render_line(self, y: int) -> Strip:
        t = time.perf_counter()
        try:
            return self._render_line(y)
        finally:
            self.lines_drawn += 1
            self.render_seconds += time.perf_counter() - t

    def _cells(self, pos: int | None) -> tuple[list[Segment], Style]:
        if pos is None:  # the header
            base = role("header")
            return [s for col, w, right in self.columns for s in (
                Segment(_fit(SHORT_HEADERS.get(col, HEADERS[col] if col >= 0 else "S"), w, right), base),
                Segment(" ", base))], base
        r = self.plist.row(pos)
        marked = r.key in self.marked
        base = role("cursor") if pos == self.cursor and self.has_focus else (
            role("cursor-blurred") if pos == self.cursor else Style())
        segs = []
        for col, w, right in self.columns:
            if col == -1:
                text = "✓" if marked else STATUS_CHAR.get(r.status, " ")
                style = base + role("marked" if marked else "upgradable" if r.status is Status.UPGRADABLE
                                    else "installed" if r.installed_evr else "muted")
            else:
                text = cell_text(r, col, self.plist.ctx) or ""
                style = base + Style(bold=col == COL_CANDIDATE and r.status is Status.UPGRADABLE)
            segs += [Segment(_fit(text, w, right), style), Segment(" ", base)]
        return segs, base

    def _render_line(self, y: int) -> Strip:
        width = self.size.width
        sx, sy = self.scroll_offset
        pos = None if y == 0 else sy + y - 1
        if pos is not None and pos >= len(self.plist):
            return Strip.blank(width)
        segs, base = self._cells(pos)
        line = Strip(segs)
        frozen = self.frozen
        if frozen:
            line = Strip.join([line.crop(0, frozen), line.crop(frozen + sx, sx + width)])
        else:
            line = line.crop(sx, sx + width)
        return line.adjust_cell_length(width, base)

    @property
    def rows_shown(self) -> int:
        return max(1, self.size.height - 1 - self.bottom_inset)

    def ensure_visible(self) -> None:
        top = self.scroll_offset.y
        if self.cursor < top:
            self.scroll_to(y=self.cursor, animate=False, force=True)
        elif self.cursor >= top + self.rows_shown:
            self.scroll_to(y=self.cursor - self.rows_shown + 1, animate=False, force=True)

    def centre_cursor(self) -> None:
        """Scroll so that the cursor is mid-list; near either end the list stops and the cursor moves on."""
        top = max(0, min(self.cursor - self.rows_shown // 2, len(self.plist) - self.rows_shown))
        self.scroll_to(y=top, animate=False, force=True)

    def follow_cursor(self) -> None:
        self.centre_cursor() if self.centre else self.ensure_visible()

    def _go(self, pos: int) -> None:
        n = len(self.plist)
        if not n:
            return
        self.cursor = max(0, min(n - 1, pos))
        self.follow_cursor()
        self.refresh()
        self.post_message(CursorMoved())

    def action_move(self, d: int) -> None:
        self._go(self.cursor + d)

    def action_page(self, d: int) -> None:
        self._go(self.cursor + d * max(1, self.rows_shown - 1))

    def action_jump(self, pos: int) -> None:
        self._go(pos if pos >= 0 else len(self.plist) - 1)

    def action_side(self, d: int) -> None:
        self.scroll_to(x=max(0, self.scroll_offset.x + d), animate=False, force=True)

    def action_toggle_mark(self) -> None:
        if len(self.plist):
            self.marked.symmetric_difference_update({self.plist.row(self.cursor).key})
            self.app.update_status()
            self._go(self.cursor + 1)

    def on_focus(self) -> None:
        self.refresh()
        self.app.list_focused()

    def on_blur(self) -> None:
        self.refresh()


def _fit(text: str, w: int, right: bool) -> str:
    text = text[:w - 1] + "…" if len(text) > w else text
    return text.rjust(w) if right else text.ljust(w)


# ---------------------------------------------------------------- the sidebar

class Sidebar(Vertical):
    """One list whose content the view chooses, as in the GUIs. The view's name is the panel's title; [ and ] go to
    the previous and next view, v lists them all. A wide and tall terminal also lists the views at the bottom."""

    BINDINGS = [
        Binding("left_square_bracket", "view(-1)", "Prev view", show=False),
        Binding("right_square_bracket", "view(1)", "Next view", show=False),
        Binding("v", "view_menu", "Views"),
    ]

    def compose(self) -> ComposeResult:
        yield OptionList(id="entries")
        yield Static("", id="views")

    def action_view(self, d: int) -> None:
        ids = [v for v, _l, _b in VIEWS]
        self.app.set_view(ids[(ids.index(self.app.view) + d) % len(ids)])

    def action_view_menu(self) -> None:
        ids = [v for v, _l, _b in VIEWS]
        self.app.push_screen(ChoiceMenu("Views", [label for _v, label, _b in VIEWS], ids.index(self.app.view)),
                             lambda i: i is not None and self.app.set_view(ids[i]))


# ---------------------------------------------------------------- the details

class TabStrip(Static):
    """The details' tabs on one line: all of them when they fit, else only the current one between arrows, with its
    number, and t for the list."""

    def show(self, tabs: list[str], current: str, width: int) -> None:
        titles = tab_titles()
        full = Text()
        for i, name in enumerate(tabs, 1):
            style = role("current") if name == current else (role("upgradable") + Style(bold=True)
                                                              if name == "advisories" else Style())
            if i > 1:
                full.append(" │ ", role("rule"))
            full.append(f" {i} {titles[name]} ", style)
        if full.cell_len <= width:
            self.update(full)
            return
        i = tabs.index(current)
        compact = Text()
        compact.append("← ", role("muted"))
        compact.append(f" {titles[current]} ", role("current"))
        compact.append(" →", role("muted"))
        compact.append(f"  {i + 1}/{len(tabs)}", role("muted"))
        if "advisories" in tabs and current != "advisories":
            compact.append("  ! advisories", role("upgradable") + Style(bold=True))
        self.update(compact)


class Details(Vertical):
    BINDINGS = [
        Binding("left_square_bracket", "tab(-1)", "Prev tab", show=False),
        Binding("right_square_bracket", "tab(1)", "Next tab", show=False),
        Binding("t", "tab_menu", "Tabs"),
        *[Binding(str(i), f"tab_no({i})", show=False) for i in range(1, 8)],
    ]

    def compose(self) -> ComposeResult:
        yield TabStrip(id="tabs")
        with VerticalScroll(id="doc-box"):
            yield Static("", id="doc")

    def on_resize(self) -> None:
        self.app.show_details()

    def action_tab(self, d: int) -> None:
        tabs = self.app.tabs
        self.app.choose_tab(tabs[(tabs.index(self.app.tab) + d) % len(tabs)])

    def action_tab_no(self, i: int) -> None:
        if i <= len(self.app.tabs):
            self.app.choose_tab(self.app.tabs[i - 1])

    def action_tab_menu(self) -> None:
        titles = tab_titles()
        tabs = self.app.tabs
        self.app.push_screen(ChoiceMenu("Tabs", [f"{i}  {titles[t]}" for i, t in enumerate(tabs, 1)],
                                        tabs.index(self.app.tab)),
                             lambda i: i is not None and self.app.choose_tab(tabs[i]))


class ChoiceMenu(ModalScreen):
    """A short list over everything else: Enter picks, Esc closes."""

    BINDINGS = [Binding("escape", "close", "Close")]
    DEFAULT_CSS = """
    ChoiceMenu { align: center middle; background: $background 50%; }
    ChoiceMenu OptionList { width: auto; min-width: 30; max-width: 90%; height: auto; max-height: 80%;
                            border: round $accent;
                            border-title-color: $accent; background: $surface; }
    """

    def __init__(self, title: str, labels: list[str], current: int):
        super().__init__()
        self.title_text, self.labels, self.current = title, labels, current

    def compose(self) -> ComposeResult:
        menu = OptionList(*self.labels)
        menu.border_title = self.title_text
        yield menu

    def on_mount(self) -> None:
        menu = self.query_one(OptionList)
        menu.highlighted = self.current
        menu.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option_index)

    def action_close(self) -> None:
        self.dismiss(None)


# ---------------------------------------------------------------- the search

class SearchPopup(ModalScreen):
    """The search at the top of the screen, over the window, as a command palette: type, Tab changes what is
    searched, ↓ goes to the earlier searches, Enter searches, Esc closes. The name modes count matches as you type
    (kram.core.search, the GUIs' own index); Provides and File ask dnf, so only on Enter."""

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("tab", "mode(1)", "Mode", priority=True),
        Binding("shift+tab", "mode(-1)", show=False, priority=True),
        Binding("down", "history", show=False),
    ]
    DEFAULT_CSS = """
    SearchPopup { align: center top; background: $background 40%; }
    #search-box { width: 90%; max-width: 84; height: auto; margin-top: 1; padding: 0 1; background: $surface;
                  border: round $accent; border-title-color: $accent; border-subtitle-color: $accent; }
    #search-input { border: none; height: 1; padding: 0; background: $surface; }
    #search-modes, #search-count { height: 1; }
    #search-count { color: $text-muted; }
    #search-history { height: auto; max-height: 8; border: none; padding: 0; background: $surface;
                      border-top: solid $border-blurred; }
    """

    def __init__(self, app_: "KramTui", mode: int):
        super().__init__()
        self.kram, self.mode = app_, mode

    def compose(self) -> ComposeResult:
        box = Vertical(id="search-box")
        box.border_title = "Search"
        box.border_subtitle = hint(("tab", "what"), ("↓", "earlier"), ("enter", "search"), ("esc", "close"))
        with box:
            yield Input(placeholder="Package name, or words of its summary", id="search-input")
            yield Static("", id="search-modes")
            yield Static("", id="search-count")
            yield OptionList(*[f"“{t}” — {MODE_LABELS[Mode(m)].lower()}   {c:,}" for t, m, c in self.kram.history],
                             id="search-history")

    def on_mount(self) -> None:
        self.query_one("#search-history").display = bool(self.kram.history)
        self.show_modes()
        self.query_one(Input).focus()

    def show_modes(self) -> None:
        """Every mode when they fit, else the current one between arrows, as the details' tabs."""
        t = Text()
        for m in Mode:
            if m:
                t.append("  ")
            t.append(f" {MODE_LABELS[m]} ", role("current") if m == self.mode else role("muted"))
        modes = self.query_one("#search-modes", Static)
        if t.cell_len > modes.size.width > 0:
            t = Text()
            t.append("← ", role("muted"))
            t.append(f" {MODE_LABELS[Mode(self.mode)]} ", role("current"))
            t.append(f" →  {self.mode + 1}/{len(Mode)}", role("muted"))
        modes.update(t)
        self.count()

    def on_resize(self) -> None:
        self.call_after_refresh(self.show_modes)

    def count(self) -> None:
        text = self.query_one(Input).value
        if not text.strip():
            msg = ""
        elif Mode(self.mode).local:
            msg = f"{len(self.kram.index.search(text, Mode(self.mode))):,} packages"
        else:
            msg = "dnf looks this up when you press Enter"
        self.query_one("#search-count", Static).update(msg)

    def on_input_changed(self, _event) -> None:
        self.count()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.value.strip():
            self.dismiss((event.value.strip(), self.mode))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        text, mode, _c = self.kram.history[event.option_index]
        self.dismiss((text, mode))

    def action_mode(self, d: int) -> None:
        self.mode = (self.mode + d) % len(Mode)
        self.show_modes()

    def action_history(self) -> None:
        if self.kram.history:
            self.query_one("#search-history").focus()

    def action_close(self) -> None:
        self.dismiss(None)


# ---------------------------------------------------------------- the menu

class MenuPopup(ModalScreen):
    """The menu bar of the GUIs (kram.app.actions.menu_bar) in the middle of the screen: its menus on the left,
    the chosen one's entries on the right. ↑↓ move, → or Enter opens, ← goes back, Esc closes."""

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("left", "column(0)", show=False),
        Binding("right", "column(1)", show=False),
    ]
    DEFAULT_CSS = """
    MenuPopup { align: center middle; background: $background 50%; }
    #menu-box { width: auto; height: auto; max-height: 90%; background: $surface;
                border: round $accent; border-title-color: $accent; border-subtitle-color: $accent; }
    #menu-titles { width: 14; height: auto; border: none; border-right: solid $border-blurred; padding: 0;
                   background: $surface; }
    #menu-items { width: 46; height: auto; border: none; padding: 0; background: $surface; }
    """

    def __init__(self, app_: "KramTui"):
        super().__init__()
        self.kram = app_
        self.menus = menu_bar()
        self.labels = {d.id: d for d in action_defs()}
        self.items: list = []  # the MenuItems shown on the right, None for the "back" line
        self.stack: list = []  # submenus opened on the right

    def compose(self) -> ComposeResult:
        box = Horizontal(id="menu-box")
        box.border_title = "Menu"
        box.border_subtitle = hint(("enter", "open"), ("←", "back"), ("esc", "close"))
        with box:
            yield OptionList(*[m.title.replace("&", "") for m in self.menus], id="menu-titles")
            yield OptionList(id="menu-items")

    def on_mount(self) -> None:
        self.show_menu(self.menus[0])
        self.query_one("#menu-titles").focus()

    def show_menu(self, menu, sub: bool = False) -> None:
        items = self.query_one("#menu-items", OptionList)
        items.clear_options()
        self.items = []
        if sub:
            items.add_option(Option(Text("← " + menu.title.replace("&", ""), style="bold")))
            self.items.append(None)
        for it in menu.items:
            self.items.append(it)
            if it.separator:
                items.add_option(Option(Text("─" * 44, style=role("rule")), disabled=True))
            elif it.submenu is not None:
                items.add_option(Option(_menu_line(it.submenu.title.replace("&", ""), "→")))
            elif it.prefs is not None:
                mark = "[x]" if self.kram.table.centre else "[ ]"  # a real checkbox here
                items.add_option(Option(_menu_line(f"{mark} Centre the cursor when scrolling", "")))
                self.items.append(COLOURS_ITEM)  # the TUI's own preference
                items.add_option(Option(_menu_line("Colours…", "")))
            elif it is COLOURS_ITEM:
                pass
            else:
                d = self.labels.get(it.action)
                items.add_option(Option(_menu_line(d.label if d else it.action, d.shortcuts[0] if d and d.shortcuts
                                                   else "")))
        items.highlighted = 0

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option_list.id == "menu-titles":
            self.stack = []
            self.show_menu(self.menus[event.option_index])

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id == "menu-titles":
            self.action_column(1)
            return
        it = self.items[event.option_index]
        if it is None:  # back out of a submenu
            self.stack.pop()
            self.show_menu(self.stack[-1], sub=True) if self.stack else self.show_menu(
                self.menus[self.query_one("#menu-titles", OptionList).highlighted])
        elif it.submenu is not None:
            self.stack.append(it.submenu)
            self.show_menu(it.submenu, sub=True)
        else:
            self.dismiss("pref:centre" if it.prefs is not None else it.action)

    def action_column(self, i: int) -> None:
        self.query_one("#menu-items" if i else "#menu-titles").focus()

    def action_close(self) -> None:
        self.dismiss(None)


COLOURS_ITEM = MenuItem(action="colours")


def _menu_line(label: str, right: str, width: int = 44) -> Text:
    t = Text(label[:width - len(right) - 1].ljust(width - len(right)))
    t.append(right, role("muted"))
    return t


# ---------------------------------------------------------------- the app

class Body(Horizontal):
    """The panels' room. Its resize switches the layout: Textual 8 does not send the app its own Resize when the
    terminal changes size (4.0 does)."""

    def on_resize(self) -> None:
        self.app.apply_layout()


class KramTui(App):
    CSS = """
    /* 16 colours: Textual draws some widgets in colours blended with transparency, which a 16-colour terminal
       cannot show (the footer's words and a checkbox's label vanished). Plain colours instead. Here in the app's CSS:
       a widget's DEFAULT_CSS is scoped to that widget. */
    App:ansi Screen { background: $background; color: $foreground; }
    App:ansi Footer, App:ansi FooterKey { background: $background; color: $text; }
    App:ansi FooterKey .footer-key--key { background: $background; color: $warning; text-style: bold; }
    App:ansi FooterKey .footer-key--description { background: $background; color: $text; }
    App:ansi Checkbox { border: none; padding: 0; background: $background; color: $foreground; }
    App:ansi Checkbox > .toggle--button { background: $background; color: $foreground; }
    App:ansi Checkbox.-on > .toggle--button { color: $success; text-style: bold; }
    App:ansi Input { background: $background; color: $foreground; }
    #top { height: 1; background: $panel; color: $text; padding: 0 1; }
    #body { height: 1fr; layers: base overlay; }
    .panel { border: round $border-blurred; border-title-color: $text-muted; border-subtitle-color: $text-muted; }
    .panel:focus-within { border: round $accent; border-title-color: $accent; border-subtitle-color: $accent; }
    #side { width: 28; height: 1fr; }
    #entries { height: 1fr; border: none; padding: 0; background: transparent; }
    #views { height: auto; border-top: solid $border-blurred; color: $text-muted; display: none; }
    #body.tall #views { display: block; }
    #main { width: 1fr; }
    #table-box { height: 1fr; }
    #details { height: 12; }
    #tabs { height: 1; }
    #doc-box { height: 1fr; padding: 0 1; }
    .hidden { display: none; }
    /* narrow terminal: the panels slide over the list instead of taking room from it */
    #body.narrow #side { layer: overlay; position: absolute; width: 30; max-width: 85%; background: $surface; }
    #body.narrow #details { layer: overlay; dock: bottom; width: 100%; background: $surface; }
    """
    BINDINGS = [
        Binding("g", "toggle_panel('side')", "Groups"),
        Binding("d", "toggle_panel('details')", "Details"),
        Binding("slash", "search", "Search"),
        Binding("m,f9", "menu", "Menu"),
        Binding("escape", "back_to_list", "List", show=False),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, snap):
        super().__init__()
        self.snap = snap
        self.plist = PackageList()
        self.plist.set_rows(snap.rows, getattr(snap, "basearch", "x86_64") or "x86_64")
        self.index_of = {id(r): i for i, r in enumerate(snap.rows)}
        self.view = "status"
        self.entries: list[FilterEntry] = []
        self.selected: dict[str, str] = {"status": "status:all"}  # view -> its selected entry, kept per view
        self.entry: FilterEntry | None = None
        self.pinned = {"side": True, "details": True}  # wide terminal: the panels the user keeps shown
        self.narrow = False
        self.choice = TabChoice()
        self.tab = "description"
        self.tabs: list[str] = list(TABS)
        self.history: list[tuple[str, int, int]] = []  # (text, mode, count), newest first, as SidebarModel keeps it
        self._index: SearchIndex | None = None

    def compose(self) -> ComposeResult:
        global _palette
        _palette = Palette()
        yield _palette
        yield Static("", id="top")
        with Body(id="body"):
            yield Sidebar(id="side", classes="panel")
            with Vertical(id="main"):
                box = Vertical(id="table-box", classes="panel")
                box.border_title = "Packages"
                box.border_subtitle = hint(("space", "mark"), ("← →", "scroll"))
                with box:
                    yield PackageTable(self.plist, id="table")
                details = Details(id="details", classes="panel")
                details.border_title = "Details"
                details.border_subtitle = hint(("[", "prev"), ("]", "next"), ("t", "tabs"))
                yield details
        yield Footer()

    def on_mount(self) -> None:
        for theme in ANSI_THEMES:
            self.register_theme(theme)
        signal = getattr(self, "theme_changed_signal", None)
        if signal is not None:  # the command palette's "Change theme" too
            signal.subscribe(self, lambda _theme: self.scheme_changed())
        self.set_scheme(os.environ.get("KRAM_SCHEME", "textual-ansi"))
        self.set_view("status")
        self.apply_layout()
        self.table.focus()
        self.update_status()
        self.call_after_refresh(self.show_details)

    # ---------------------------------------------------------------- colours

    def set_scheme(self, name: str) -> None:
        """A colour scheme (SCHEMES), at once: no restart."""
        self.theme = name
        self.scheme_changed()

    def scheme_changed(self) -> None:
        # Textual turns ANSI colours on only for its own "textual-ansi"; ours are 16-colour schemes as well
        self.ansi_color = self.theme in ANSI_SCHEMES
        self.call_after_refresh(self.refresh_colours)

    def refresh_colours(self) -> None:
        """Draw again everything whose colours were taken from `role` in Python."""
        self.query_one("#table-box").border_subtitle = hint(("space", "mark"), ("← →", "scroll"))
        self.query_one("#details").border_subtitle = hint(("[", "prev"), ("]", "next"), ("t", "tabs"))
        self.set_view(self.view)
        self.update_status()
        self.show_details()
        self.table.refresh()

    def choose_scheme(self) -> None:
        names = [n for n, _l in SCHEMES]
        current = names.index(self.theme) if self.theme in names else 0
        self.push_screen(ChoiceMenu("Colours", [label for _n, label in SCHEMES], current),
                         lambda i: i is not None and self.set_scheme(names[i]))

    @property
    def table(self) -> PackageTable:
        return self.query_one(PackageTable)

    def on_resize(self) -> None:
        self.apply_layout()

    # ---------------------------------------------------------------- the panels

    def panel(self, name: str):
        return self.query_one(f"#{name}")

    def focus_target(self, name: str):
        return self.query_one("#entries") if name == "side" else self.query_one("#doc-box")

    def has_focus_in(self, name: str) -> bool:
        node = self.focused
        while node is not None:
            if node is self.panel(name):
                return True
            node = node.parent
        return False

    def apply_layout(self) -> None:
        """Wide: the pinned panels are shown. Narrow: none, except the one that has the focus, as a slide-over.
        From narrow to wide, an open slide-over stays as a pinned panel."""
        width, height = self.size
        narrow = width < WIDE
        body = self.query_one("#body")
        body.set_class(not narrow and height >= TALL, "tall")
        self.panel("details").styles.height = self.overlay_height() if narrow else 12  # follows the terminal
        if narrow == self.narrow and self.is_mounted and body.has_class("narrow") == narrow:
            return
        self.narrow = narrow
        body.set_class(narrow, "narrow")
        for name in PANELS:
            focused = self.has_focus_in(name)
            if not narrow and focused:
                self.pinned[name] = True
            self.panel(name).set_class(not focused if narrow else not self.pinned[name], "hidden")
        self.table.bottom_inset = self.overlay_inset()

    def overlay_height(self) -> int:
        """The details slide-over: 11 lines, but at most 3/5 of the panels' room, so that a few rows of the list
        stay in sight above it (on a 40×12 terminal it would cover the list whole)."""
        return max(5, min(11, self.query_one("#body").size.height * 3 // 5))

    def overlay_inset(self) -> int:
        details = self.panel("details")
        return self.overlay_height() if self.narrow and not details.has_class("hidden") else 0

    def action_toggle_panel(self, name: str) -> None:
        """Not focused: show the panel (pinned, or as the one slide-over) and focus it. Focused: hide it and go back
        to the list."""
        panel = self.panel(name)
        if self.has_focus_in(name):
            if not self.narrow:
                self.pinned[name] = False
            panel.add_class("hidden")
            self.table.bottom_inset = 0
            self.table.focus()
            return
        if self.narrow:
            for other in PANELS:
                self.panel(other).add_class("hidden")
        else:
            self.pinned[name] = True
        panel.remove_class("hidden")
        self.focus_target(name).focus()
        if name == "details":
            self.table.bottom_inset = self.overlay_inset()
            self.table.call_after_refresh(self.table.follow_cursor)  # once the list has its new size
            self.show_details()

    def action_back_to_list(self) -> None:
        self.table.focus()

    # ---------------------------------------------------------------- who gets a key

    def check_action(self, action: str, parameters) -> bool | None:
        """The window's keys (WINDOW_ACTIONS) belong to the window: not while a modal screen is up (Textual would
        still give them to the app under it) and not while a text field has the focus (there "g" and "/" are
        text). False also takes them out of the footer."""
        if action in WINDOW_ACTIONS:
            if len(self.screen_stack) > 1 or isinstance(self.focused, Input):
                return False
        return True

    # ---------------------------------------------------------------- search and menu

    @property
    def index(self) -> SearchIndex:
        if self._index is None:
            self._index = SearchIndex(self.plist.rows, getattr(self.snap, "descriptions", None))
        return self._index

    def action_search(self) -> None:
        mode = self.history[0][1] if self.history else int(Mode.NAME_SUMMARY)
        self.push_screen(SearchPopup(self, mode), lambda found: found and self.run_search(*found))

    def run_search(self, text: str, mode: int) -> None:
        if Mode(mode).local:
            found = self.index.search(text, Mode(mode))
        else:
            found = []
            self.notify(f"{MODE_LABELS[Mode(mode)]}: dnf answers this in the real app", timeout=4)
        self.history = [(text, mode, len(found))] + [h for h in self.history if h[:2] != (text, mode)]
        self.selected["search"] = history_id(text, mode)
        self.entry = FilterEntry(history_id(text, mode), f"“{text}”", lambda _r: True, len(found))
        self.plist.set_visible(found, ranked=True)  # best match first, as the GUIs show a search
        self.table.reset()
        self.update_status()
        self.set_view("search")

    def action_menu(self) -> None:
        self.push_screen(MenuPopup(self), lambda action: action and self.run_menu_action(action))

    def run_menu_action(self, action: str) -> None:
        if action == "quit":
            self.exit()
        elif action == "find":
            self.action_search()
        elif action == "colours":
            self.choose_scheme()
        elif action == "pref:centre":
            self.table.centre = not self.table.centre
            self.table.follow_cursor()
            self.notify("Centre scrolling " + ("on" if self.table.centre else "off"), timeout=3)
        elif action == "mark_upgrades":
            self.table.marked |= {r.key for r in self.plist.rows if r.status is Status.UPGRADABLE}
            self.table.refresh()
            self.update_status()
        elif action == "unmark_all":
            self.table.marked.clear()
            self.table.refresh()
            self.update_status()
        else:
            label = next((d.label for d in action_defs() if d.id == action), action)
            self.notify(f"{label}: not in the spike", timeout=3)

    def list_focused(self) -> None:
        """Focus moved to the list (Esc, Tab, a click): a slide-over closes, a pinned panel stays."""
        if self.narrow:
            for name in PANELS:
                self.panel(name).add_class("hidden")
            self.table.bottom_inset = 0

    # ---------------------------------------------------------------- the sidebar

    def set_view(self, view: str) -> None:
        self.view = view
        side = self.panel("side")
        label = dict((v, lbl) for v, lbl, _b in VIEWS)[view]
        side.border_title = label
        side.border_subtitle = hint(("[", "prev"), ("]", "next"), ("v", "all"))  # fits the 28 columns
        self.entries = view_entries(self.snap, view, self.table.marked) if view != "search" else [
            FilterEntry(history_id(text, mode), f"“{text}” — {MODE_LABELS[Mode(mode)].lower()}", lambda _r: True,
                        count, query=(text, mode)) for text, mode, count in self.history]
        entries = self.query_one("#entries", OptionList)
        entries.clear_options()
        if not self.entries:
            entries.add_option(Option(Text(PLACEHOLDER.get(view, "Nothing here"), style=role("muted") + Style(
                italic=True)),
                                      disabled=True))
        else:
            entries.add_options([Option(_entry_text(e, 26)) for e in self.entries])
            ids = [e.id for e in self.entries]
            current = self.selected.get(view)
            entries.highlighted = ids.index(current) if current in ids else 0
        views = Text()
        for v, lbl, _b in VIEWS:
            views.append(("● " if v == view else "  ") + lbl + "\n", "bold" if v == view else "")
        views.rstrip()
        self.query_one("#views", Static).update(views)
        # switching the view does not filter the list: picking an entry does, as in the GUIs

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id != "entries" or not self.entries:
            return
        self.set_entry(self.entries[event.option_index])
        if self.narrow:
            self.table.focus()  # the slide-over has done its job

    def set_entry(self, entry: FilterEntry) -> None:
        if entry.query:  # a search of the history: run it again
            self.run_search(*entry.query)
            return
        self.selected[self.view] = entry.id
        self.entry = entry
        rows = self.plist.rows
        self.plist.set_visible([i for i, r in enumerate(rows) if entry.predicate(r)])
        self.table.reset()
        self.update_status()

    def select_entry(self, entry_id: str) -> None:
        """For the shots and the bench: pick an entry of the current view as Enter would."""
        entry = next(e for e in self.entries if e.id == entry_id)
        self.query_one("#entries", OptionList).highlighted = self.entries.index(entry)
        self.set_entry(entry)

    # ---------------------------------------------------------------- the details

    def choose_tab(self, name: str) -> None:
        self.choice.user_selected(name)
        self.tab = name
        self.show_details()

    def on_cursor_moved(self, _event) -> None:
        self.show_details()

    def show_details(self) -> None:
        details = self.panel("details")
        if details.has_class("hidden"):
            return
        doc = self.query_one("#doc", Static)
        strip = self.query_one(TabStrip)
        if not len(self.plist):
            self.tabs = [t for t in TABS if t != "advisories"]
            strip.show(self.tabs, self.tab if self.tab in self.tabs else "description", details.size.width - 2)
            doc.update(Text("No package is selected.", style=role("muted") + Style(italic=True)))
            return
        r = self.plist.row(self.table.cursor)
        self.tabs = [t for t in TABS if t != "advisories" or r.advisories]
        # the advisories tab comes and goes with the package: TabChoice brings it back when the user had picked it
        if self.choice.wants_advisories and r.advisories:
            self.tab = "advisories"
        elif self.tab == "advisories" and not r.advisories:
            self.tab = self.choice.instead_of_advisories()
        strip.show(self.tabs, self.tab, details.size.width - 2)
        doc.update(self.tab_text(r))

    def tab_text(self, r) -> Text:
        t = Text()
        t.append(f"{r.name} ", "bold")
        t.append(f"{r.candidate_evr or r.installed_evr}\n", role("muted"))
        if self.tab == "description":
            descriptions = getattr(self.snap, "descriptions", None) or []
            i = self.index_of.get(id(r))
            t.append(r.summary + "\n\n", "italic")
            t.append(descriptions[i] if i is not None and i < len(descriptions) else "")
        elif self.tab == "general":
            for label, value in (("Installed", r.installed_evr or "—"), ("Latest", r.candidate_evr or "—"),
                                 ("Repository", r.repo_id), ("Size", cell_text(r, COL_SIZE, self.plist.ctx)),
                                 ("Origin", r.origin.name.lower())):
                t.append(f"{label:<12}", role("muted"))
                t.append(f"{value}\n")
        elif self.tab == "advisories":
            for a in r.advisories:
                t.append(f"{a.id}  ", role("upgradable") + Style(bold=True))
                t.append(f"{a.level}  {a.title}\n")
        else:
            t.append(f"({tab_titles()[self.tab]}: read from dnf when the cursor rests, as in the GUIs)",
                     role("muted") + Style(italic=True))
        return t

    def update_status(self) -> None:
        label = self.entry.label if self.entry else "All"
        self.query_one("#top", Static).update(
            f"[b]Kram[/b]  {label} ({len(self.plist):,})  ·  {len(self.table.marked)} marked")


def _entry_text(e: FilterEntry, width: int) -> Text:
    """An entry on one line: indented label, cut with an ellipsis, and its count on the right."""
    count = f" {e.count:,}" if e.count is not None else ""
    label = "  " * e.indent + e.label
    room = width - len(count)
    label = label[:room - 1] + "…" if len(label) > room else label
    t = Text(label.ljust(room), style="bold" if e.bold or e.id.endswith(":all") else "italic" if e.dim else "")
    t.append(count, role("muted"))
    return t


# ---------------------------------------------------------------- measuring

def rss_mb() -> float:
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) / 1024
    return 0.0


async def bench(snap) -> None:
    print(f"Textual {TEXTUAL_VERSION}, Python {sys.version.split()[0]}, {len(snap.rows):,} rows, RSS {rss_mb():.0f} MB")
    for size in ((52, 18), (160, 50)):
        app = KramTui(snap)
        t0 = time.perf_counter()
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            print(f"\n{size[0]}×{size[1]}: first frame {1000 * (time.perf_counter() - t0):.0f} ms")
            table = app.table

            async def timed(label, keys, n, table=table, pilot=pilot):
                table.lines_drawn = 0
                table.render_seconds = 0.0
                t, c = time.perf_counter(), time.process_time()
                for _ in range(n):
                    await pilot.press(*keys)
                    await pilot.pause()
                dt, dc = (time.perf_counter() - t) / n, (time.process_time() - c) / n
                print(f"  {label:<28} {1000 * dt:6.1f} ms wall, {1000 * dc:5.1f} ms CPU per step; "
                      f"{table.lines_drawn / n:4.0f} lines in {1000 * table.render_seconds / n:4.1f} ms")

            await timed("cursor down", ["down"], 200)
            await timed("page down", ["pagedown"], 100)
            await timed("end / home", ["end", "home"], 20)
            await timed("right / left", ["right", "left"], 20)
            await timed("space (mark)", ["space"], 50)
            for entry in ("status:installed", "status:upgradable", "status:all"):
                t = time.perf_counter()
                app.select_entry(entry)
                await pilot.pause()
                print(f"  filter {entry:<21} {1000 * (time.perf_counter() - t):6.1f} ms ({len(app.plist):,} rows)")
            t = time.perf_counter()
            app.plist.sort(COL_SIZE, True)
            table.refresh()
            await pilot.pause()
            print(f"  sort by size (70k)           {1000 * (time.perf_counter() - t):6.1f} ms")
            for view in ("groups", "environments", "origin"):
                t = time.perf_counter()
                app.set_view(view)
                await pilot.pause()
                print(f"  view {view:<23} {1000 * (time.perf_counter() - t):6.1f} ms ({len(app.entries)} entries)")
            await timed("open/close sidebar (g, g)", ["g", "g"], 20)
        print(f"  RSS after: {rss_mb():.0f} MB")


async def shots(snap, out: Path) -> None:
    """The layouts and their edge cases; each prints where the focus is and which panels are shown."""
    out.mkdir(parents=True, exist_ok=True)
    upgradable = [lambda a: a.select_entry("status:upgradable")]
    W, M, N = (150, 40), (110, 26), (60, 20)
    cases = [
        ("01-wide-list-focused", W, upgradable),
        ("02-wide-g-focuses-sidebar", W, [*upgradable, "g"]),
        ("03-wide-g-again-hides-it", W, [*upgradable, "g", "g"]),
        ("04-wide-v-view-menu", W, [*upgradable, "g", "v"]),
        ("05-wide-environments", W, [*upgradable, "g", "right_square_bracket", "right_square_bracket",
                                     "right_square_bracket"]),
        ("06-wide-search-view-empty", W, [*upgradable, "g", "v", "down", "down", "down", "down", "enter"]),
        ("07-wide-d-focuses-details", W, [*upgradable, "d"]),
        ("08-wide-details-tab-2", W, [*upgradable, "d", "2"]),
        ("09-wide-all-scrolled-right", W, ["right", "right", "right", "right", "right", "right"]),
        ("10-medium-short-no-view-list", M, [*upgradable, "d"]),
        ("11-medium-advisories-gone", M, [*upgradable, "d", "3", lambda a: a.select_entry("status:all")]),
        ("12-medium-advisories-back", M, [*upgradable, "d", "3", lambda a: a.select_entry("status:all"),
                                          lambda a: a.select_entry("status:upgradable")]),
        ("13-narrow-list", N, upgradable),
        ("14-narrow-scrolled-right", N, [*upgradable, "right", "right"]),
        ("15-narrow-g-slide-over", N, [*upgradable, "g"]),
        ("16-narrow-g-again-closes", N, [*upgradable, "g", "g"]),
        ("17-narrow-d-cursor-stays-visible", N, [*upgradable, "end", "d"]),
        ("18-narrow-t-tab-menu", N, [*upgradable, "d", "t"]),
        ("19-narrow-g-while-d-open", N, [*upgradable, "d", "g"]),
        ("20-narrow-to-wide-keeps-panel", N, [*upgradable, "g", W]),
        ("21-wide-to-narrow-hides-panels", W, [*upgradable, N]),
        ("22-tiny-40x12", (40, 12), [*upgradable, "d"]),
        ("23-centre-scrolling", W, ["down"] * 30),
        ("24-centre-scrolling-near-end", W, ["end", "up", "up"]),
        ("25-search-popup", W, ["slash", *"vim"]),
        ("26-search-g-is-text", W, ["slash", *"vim", "space", "g"]),
        ("27-search-tab-mode", W, ["slash", *"vim", "tab"]),
        ("28-search-results", W, ["slash", *"vim", "enter"]),
        ("29-search-history", W, ["slash", *"vim", "enter", "slash", "down"]),
        ("30-menu", W, ["m"]),
        ("31-menu-edit-items", W, ["m", "down", "right"]),
        ("32-menu-submenu", W, ["m", "down", "right", "enter"]),
        ("33-menu-g-does-nothing", W, ["m", "g", "d", "slash"]),
        ("34-menu-settings-centre", W, ["m", "down", "down", "down", "right", "end"]),
        ("35-narrow-search", N, ["slash", *"kern"]),
        ("36-narrow-menu", N, ["m", "down", "down", "right"]),
        ("37-scheme-menu", W, ["m", "down", "down", "down", "right", "end", "enter"]),
        ("38-scheme-midnight", W, [*upgradable, lambda a: a.set_scheme("kram-midnight"), "g"]),
        ("39-scheme-console", W, [*upgradable, lambda a: a.set_scheme("kram-console")]),
        ("40-scheme-textual-dark", W, [*upgradable, lambda a: a.set_scheme("textual-dark")]),
        ("41-scheme-textual-light", W, [*upgradable, lambda a: a.set_scheme("textual-light"), "slash", *"vim"]),
        ("42-scheme-nord-narrow", N, [*upgradable, lambda a: a.set_scheme("nord"), "d"]),
    ]
    for name, size, steps in cases:
        app = KramTui(snap)
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            for step in steps:
                if callable(step):
                    step(app)
                elif isinstance(step, tuple):
                    await pilot.resize_terminal(*step)
                else:
                    await pilot.press(step)
                await pilot.pause()
            await pilot.pause()
            app.save_screenshot(filename=f"{name}.svg", path=str(out))
            focused = app.focused.id if app.focused else None
            shown = [n for n in PANELS if not app.panel(n).has_class("hidden")]
            print(f"{name}: screens={len(app.screen_stack)} focus={focused} shown={shown} tab={app.tab} "
                  f"tabs={len(app.tabs)} rows={len(app.plist)} cursor={app.table.cursor} "
                  f"top={app.table.scroll_offset.y} x={app.table.scroll_offset.x}")


def main() -> None:
    snap = snapshot()
    if sys.argv[1:2] == ["bench"]:
        asyncio.run(bench(snap))
    elif sys.argv[1:2] == ["shots"]:
        asyncio.run(shots(snap, Path(sys.argv[2])))
    else:
        KramTui(snap).run()


if __name__ == "__main__":
    main()
