"""TUI spike T1 (Textual): a package list over 70k rows that draws only the lines on screen, the sidebar and the
details panels pinned in a wide terminal and sliding over the list in a narrow one, and how the sidebar's views and
the details' tabs are switched.

Run it:   python3 scripts/spikes/t1_tui.py            (the app)
Measure:  python3 scripts/spikes/t1_tui.py bench      (headless; prints timings for a narrow and a wide terminal)
Shots:    python3 scripts/spikes/t1_tui.py shots DIR  (headless; SVG screenshots of the layouts and edge cases)

Keys: G and D show a panel and focus it, or hide it when it has the focus; Esc goes back to the list. In the sidebar
[ and ] switch the view, V opens the list of views; in the details [ and ] (or 1-7) switch the tab, T opens the list
of tabs. In the list ←/→ (h/l) scroll sideways; the status and name columns stay in place when there is room.

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
from textual.widgets import Footer, OptionList, Static  # noqa: E402
from textual.widgets.option_list import Option  # noqa: E402

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
from kram.app.sidebar import VIEWS  # noqa: E402
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

WIDE = 100  # columns: from here on the panels are pinned beside and under the list, below it they slide over it
TALL = 34   # rows: from here on (in a wide terminal) the sidebar lists every view at its bottom, as the GUIs do

STATUS_CHAR = {Status.INSTALLED: "■", Status.UPGRADABLE: "▲", Status.NOT_INSTALLED: "□", Status.ORPHAN: "◆",
               Status.UNNEEDED: "◇", Status.NEWER: "▼"}
PANELS = ("side", "details")
# the GUIs' headers are longer than these columns; a terminal has no room to spare
SHORT_HEADERS = {COL_INSTALLED: "Installed", COL_CANDIDATE: "Latest", COL_SIZE: "Size"}


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
    return []  # search results: no searches in the spike yet


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
            base = Style(bold=True, color="#9a9da3")
            return [s for col, w, right in self.columns for s in (
                Segment(_fit(SHORT_HEADERS.get(col, HEADERS[col] if col >= 0 else "S"), w, right), base),
                Segment(" ", base))], base
        r = self.plist.row(pos)
        marked = r.key in self.marked
        base = Style(bgcolor="#2f4b73", color="white") if pos == self.cursor and self.has_focus else (
            Style(bgcolor="#3a3d44") if pos == self.cursor else Style())
        segs = []
        for col, w, right in self.columns:
            if col == -1:
                text = "✓" if marked else STATUS_CHAR.get(r.status, " ")
                style = base + Style(color="#5aa0f0" if marked else "#e5a63a" if r.status is Status.UPGRADABLE
                                     else "#6fbf73" if r.installed_evr else "#9a9da3")
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

    def _go(self, pos: int) -> None:
        n = len(self.plist)
        if not n:
            return
        self.cursor = max(0, min(n - 1, pos))
        self.ensure_visible()
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
    the previous and next view, V lists them all. A wide and tall terminal also lists the views at the bottom."""

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
    number, and T for the list."""

    def show(self, tabs: list[str], current: str, width: int) -> None:
        titles = tab_titles()
        full = Text()
        for i, name in enumerate(tabs, 1):
            style = "reverse bold" if name == current else ("bold #e5a63a" if name == "advisories" else "")
            if i > 1:
                full.append(" │ ", "#4a4d55")
            full.append(f" {i} {titles[name]} ", style)
        if full.cell_len <= width:
            self.update(full)
            return
        i = tabs.index(current)
        compact = Text()
        compact.append("◂ ", "#9a9da3")
        compact.append(f" {titles[current]} ", "reverse bold")
        compact.append(" ▸", "#9a9da3")
        compact.append(f"  {i + 1}/{len(tabs)}", "#9a9da3")
        if "advisories" in tabs and current != "advisories":
            compact.append("  ! advisories", "bold #e5a63a")
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
    ChoiceMenu OptionList { width: 30; height: auto; max-height: 80%; border: round $accent;
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


# ---------------------------------------------------------------- the app

class Body(Horizontal):
    """The panels' room. Its resize switches the layout: Textual 8 does not send the app its own Resize when the
    terminal changes size (4.0 does)."""

    def on_resize(self) -> None:
        self.app.apply_layout()


class KramTui(App):
    CSS = """
    #top { height: 1; background: $panel; color: $text; padding: 0 1; }
    #body { height: 1fr; layers: base overlay; }
    .panel { border: round #4a4d55; border-title-color: #9a9da3; border-subtitle-color: #6b6e75; }
    .panel:focus-within { border: round $accent; border-title-color: $accent; border-subtitle-color: $accent; }
    #side { width: 28; height: 1fr; }
    #entries { height: 1fr; border: none; padding: 0; background: transparent; }
    #views { height: auto; border-top: solid #4a4d55; color: #9a9da3; display: none; }
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

    def compose(self) -> ComposeResult:
        yield Static("", id="top")
        with Body(id="body"):
            yield Sidebar(id="side", classes="panel")
            with Vertical(id="main"):
                box = Vertical(id="table-box", classes="panel")
                box.border_title = "Packages"
                box.border_subtitle = "Space mark · ←→ scroll"
                with box:
                    yield PackageTable(self.plist, id="table")
                details = Details(id="details", classes="panel")
                details.border_title = "Details"
                details.border_subtitle = "[ ] tab · T tabs"
                yield details
        yield Footer()

    def on_mount(self) -> None:
        self.set_view("status")
        self.apply_layout()
        self.table.focus()
        self.update_status()
        self.call_after_refresh(self.show_details)

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
            self.table.call_after_refresh(self.table.ensure_visible)  # once the list has its new size
            self.show_details()

    def action_back_to_list(self) -> None:
        self.table.focus()

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
        side.border_title = f"{label} ▾"
        side.border_subtitle = "[ ] view · V views"
        self.entries = view_entries(self.snap, view, self.table.marked)
        entries = self.query_one("#entries", OptionList)
        entries.clear_options()
        if not self.entries:
            entries.add_option(Option(Text(PLACEHOLDER.get(view, "Nothing here"), style="italic #9a9da3"),
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
            doc.update(Text("No package is selected.", style="italic #9a9da3"))
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
        t.append(f"{r.candidate_evr or r.installed_evr}\n", "#9a9da3")
        if self.tab == "description":
            descriptions = getattr(self.snap, "descriptions", None) or []
            i = self.index_of.get(id(r))
            t.append(r.summary + "\n\n", "italic")
            t.append(descriptions[i] if i is not None and i < len(descriptions) else "")
        elif self.tab == "general":
            for label, value in (("Installed", r.installed_evr or "—"), ("Latest", r.candidate_evr or "—"),
                                 ("Repository", r.repo_id), ("Size", cell_text(r, COL_SIZE, self.plist.ctx)),
                                 ("Origin", r.origin.name.lower())):
                t.append(f"{label:<12}", "#9a9da3")
                t.append(f"{value}\n")
        elif self.tab == "advisories":
            for a in r.advisories:
                t.append(f"{a.id}  ", "bold #e5a63a")
                t.append(f"{a.level}  {a.title}\n")
        else:
            t.append(f"({tab_titles()[self.tab]}: read from dnf when the cursor rests, as in the GUIs)",
                     "italic #9a9da3")
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
    t.append(count, "#9a9da3")
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
            print(f"{name}: focus={focused} shown={shown} tab={app.tab} tabs={len(app.tabs)} "
                  f"cursor={app.table.cursor} top={app.table.scroll_offset.y} x={app.table.scroll_offset.x}")


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
