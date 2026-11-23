"""TUI spike T1 (Textual): a package list over 70k rows that draws only the lines on screen, and the groups and
details panels that are pinned in a wide terminal and slide over the list in a narrow one.

Run it:   python3 scripts/spikes/t1_tui.py            (the app; G groups, D details, Esc closes a slide-over)
Measure:  python3 scripts/spikes/t1_tui.py bench      (headless; prints timings for a narrow and a wide terminal)
Shots:    python3 scripts/spikes/t1_tui.py shots DIR  (headless; SVG screenshots of the layouts)

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
from textual import __version__ as TEXTUAL_VERSION  # noqa: E402
from textual.app import App, ComposeResult  # noqa: E402
from textual.binding import Binding  # noqa: E402
from textual.containers import Horizontal, Vertical  # noqa: E402
from textual.geometry import Size  # noqa: E402
from textual.message import Message  # noqa: E402
from textual.scroll_view import ScrollView  # noqa: E402
from textual.strip import Strip  # noqa: E402
from textual.widgets import Footer, OptionList, Static  # noqa: E402

from kram.app.columns import COL_CANDIDATE, COL_INSTALLED, COL_NAME, COL_SIZE, COL_SUMMARY, cell_text  # noqa: E402
from kram.app.package_list import PackageList  # noqa: E402
from kram.core.model import Status  # noqa: E402

WIDE = 100  # columns: from here on the panels are pinned beside and under the list, below it they slide over it

STATUS_CHAR = {Status.INSTALLED: "■", Status.UPGRADABLE: "▲", Status.NOT_INSTALLED: "□", Status.ORPHAN: "◆",
               Status.UNNEEDED: "◇", Status.NEWER: "▼"}

FILTERS = {
    "All": None,
    "Installed": lambda r: bool(r.installed_evr),
    "Upgradable": lambda r: r.status is Status.UPGRADABLE,
    "Not installed": lambda r: not r.installed_evr,
    "Marked": "marked",
}


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


# ---------------------------------------------------------------- widgets

class PackageTable(ScrollView, can_focus=True):
    """Draws only the lines on screen: `render_line` reads `PackageList` for the row at that line, so 70k rows cost
    nothing until they scroll into view."""

    BINDINGS = [
        Binding("up,k", "move(-1)", "Up", show=False),
        Binding("down,j", "move(1)", "Down", show=False),
        Binding("pageup", "page(-1)", "Page up", show=False),
        Binding("pagedown", "page(1)", "Page down", show=False),
        Binding("home", "jump(0)", show=False),
        Binding("end", "jump(-1)", show=False),
        Binding("space", "toggle_mark", "Mark"),
    ]
    DEFAULT_CSS = "PackageTable { height: 1fr; scrollbar-size-vertical: 1; }"

    def __init__(self, plist: PackageList, **kw):
        super().__init__(**kw)
        self.plist = plist
        self.cursor = 0
        self.marked: set[tuple[str, str]] = set()
        self.lines_drawn = 0  # render_line calls and their time, for the bench
        self.render_seconds = 0.0

    # columns: status, name (flexible), installed, latest, size; the version columns go first when it is narrow
    def _columns(self, width: int) -> list[tuple[int, int, bool]]:
        cols = [(-1, 2, False)]
        if width >= WIDE:
            fixed = [(COL_INSTALLED, 16, False), (COL_CANDIDATE, 16, False), (COL_SIZE, 9, True)]
        else:
            fixed = [(COL_CANDIDATE, 14, False), (COL_SIZE, 9, True)]
        name_w = max(12, width - 1 - sum(w + 1 for _, w, _ in cols + fixed))
        if width >= WIDE + 40:  # room for the summary too
            name_w = 30
            fixed.append((COL_SUMMARY, max(10, width - 1 - 3 - 31 - sum(w + 1 for _, w, _ in fixed)), False))
        return cols + [(COL_NAME, name_w, False)] + fixed

    def on_resize(self) -> None:
        self.virtual_size = Size(self.size.width, len(self.plist))

    def reset(self) -> None:
        self.cursor = 0
        self.virtual_size = Size(self.size.width, len(self.plist))
        self.scroll_to(y=0, animate=False)
        self.refresh()
        self.post_message(CursorMoved())

    def render_line(self, y: int) -> Strip:
        t = time.perf_counter()
        try:
            return self._render_line(y)
        finally:
            self.lines_drawn += 1
            self.render_seconds += time.perf_counter() - t

    def _render_line(self, y: int) -> Strip:
        width = self.size.width
        pos = self.scroll_offset.y + y
        if pos >= len(self.plist):
            return Strip.blank(width)
        r = self.plist.row(pos)
        marked = r.key in self.marked
        base = Style(bgcolor="#2f4b73", color="white") if pos == self.cursor and self.has_focus else (
            Style(bgcolor="#3a3d44") if pos == self.cursor else Style())
        segs = []
        for col, w, right in self._columns(width):
            if col == -1:
                text = ("✓" if marked else STATUS_CHAR.get(r.status, " "))
                style = base + Style(color="#5aa0f0" if marked else "#e5a63a" if r.status is Status.UPGRADABLE
                                     else "#6fbf73" if r.installed_evr else "#9a9da3")
            else:
                text = cell_text(r, col, self.plist.ctx) or ""
                style = base + Style(bold=col == COL_CANDIDATE and r.status is Status.UPGRADABLE)
            text = text[:w - 1] + "…" if len(text) > w else text
            segs.append(Segment(text.rjust(w) if right else text.ljust(w), style))
            segs.append(Segment(" ", base))
        return Strip(segs).adjust_cell_length(width, base)

    def _go(self, pos: int) -> None:
        n = len(self.plist)
        if not n:
            return
        old, self.cursor = self.cursor, max(0, min(n - 1, pos))
        top, h = self.scroll_offset.y, self.size.height
        if self.cursor < top:
            self.scroll_to(y=self.cursor, animate=False)
        elif self.cursor >= top + h:
            self.scroll_to(y=self.cursor - h + 1, animate=False)
        self.refresh_line(old - top) if 0 <= old - top < h else None
        self.refresh()
        self.post_message(CursorMoved())

    def action_move(self, d: int) -> None:
        self._go(self.cursor + d)

    def action_page(self, d: int) -> None:
        self._go(self.cursor + d * max(1, self.size.height - 1))

    def action_jump(self, pos: int) -> None:
        self._go(pos if pos >= 0 else len(self.plist) - 1)

    def action_toggle_mark(self) -> None:
        if len(self.plist):
            key = self.plist.row(self.cursor).key
            self.marked.symmetric_difference_update({key})
            self.app.update_status()
            self._go(self.cursor + 1)

    def on_focus(self) -> None:
        self.refresh()
        self.app.list_focused()

    def on_blur(self) -> None:
        self.refresh()



class CursorMoved(Message):
    pass


class Details(Static, can_focus=True):
    pass


class KramTui(App):
    CSS = """
    Screen { layers: base overlay; }
    #top { height: 1; background: $panel; color: $text; padding: 0 1; }
    #body { height: 1fr; }
    #groups { width: 24; height: 1fr; border: round $secondary; border-title-color: $secondary; }
    #main { width: 1fr; }
    #table-box { height: 1fr; border: round $accent; border-title-color: $accent; }
    #details { height: 9; border: round $secondary; border-title-color: $secondary; padding: 0 1; }
    .hidden { display: none; }
    /* narrow terminal: the panels slide over the list instead of taking room from it */
    .narrow #groups { layer: overlay; position: absolute; offset: 0 1; height: 1fr; max-height: 80%;
                      background: $surface; border: round $warning; border-title-color: $warning; }
    .narrow #details { layer: overlay; dock: bottom; height: 8; width: 100%;
                       background: $surface; border: round $warning; border-title-color: $warning; }
    """
    BINDINGS = [
        Binding("g", "toggle_panel('groups')", "Groups"),
        Binding("d", "toggle_panel('details')", "Details"),
        Binding("escape", "close_overlays", "Close", show=False),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, snap):
        super().__init__()
        self.snap = snap
        self.plist = PackageList()
        self.plist.set_rows(snap.rows, getattr(snap, "basearch", "x86_64") or "x86_64")
        self.filter_name = "All"
        self.pinned = {"groups": True, "details": True}  # wide terminal: which panels the user keeps shown
        self.narrow = False

    def compose(self) -> ComposeResult:
        yield Static("", id="top")
        with Horizontal(id="body"):
            groups = OptionList(*FILTERS, id="groups")
            groups.border_title = "Groups"
            yield groups
            with Vertical(id="main"):
                box = Vertical(id="table-box")
                box.border_title = "Packages"
                with box:
                    yield PackageTable(self.plist, id="table")
                details = Details("", id="details")
                details.border_title = "Details"
                yield details
        yield Footer()

    def on_mount(self) -> None:
        self.apply_layout(self.size.width)
        self.query_one(PackageTable).focus()
        self.update_status()

    def on_resize(self, event) -> None:
        self.apply_layout(event.size.width)

    # ---------------------------------------------------------------- the panels

    def apply_layout(self, width: int) -> None:
        narrow = width < WIDE
        if narrow != self.narrow or not self.is_mounted:
            self.narrow = narrow
            self.screen.set_class(narrow, "narrow")
            for name in ("groups", "details"):  # a narrow terminal starts with both slide-overs closed
                self.query_one(f"#{name}").set_class(narrow or not self.pinned[name], "hidden")

    def action_toggle_panel(self, name: str) -> None:
        panel = self.query_one(f"#{name}")
        show = panel.has_class("hidden")
        if self.narrow:
            self.action_close_overlays()
            panel.set_class(not show, "hidden")
            if show:
                panel.focus()
        else:
            self.pinned[name] = show
            panel.set_class(not show, "hidden")
        if show and name == "details":
            self.on_cursor_moved(None)

    def action_close_overlays(self) -> None:
        if self.narrow:
            for name in ("groups", "details"):
                self.query_one(f"#{name}").add_class("hidden")
            self.query_one(PackageTable).focus()

    def list_focused(self) -> None:
        """Focus moved to the list: a slide-over closes."""
        if self.narrow:
            for name in ("groups", "details"):
                self.query_one(f"#{name}").add_class("hidden")

    # ---------------------------------------------------------------- the list

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.set_filter(str(event.option.prompt))
        self.query_one(PackageTable).focus()  # closes the slide-over in a narrow terminal

    def set_filter(self, name: str) -> None:
        table = self.query_one(PackageTable)
        f = FILTERS[name]
        rows = self.plist.rows
        if f is None:
            visible = list(range(len(rows)))
        elif f == "marked":
            visible = [i for i, r in enumerate(rows) if r.key in table.marked]
        else:
            visible = [i for i, r in enumerate(rows) if f(r)]
        self.filter_name = name
        self.query_one("#groups", OptionList).highlighted = list(FILTERS).index(name)
        self.plist.set_visible(visible)
        table.reset()
        self.update_status()

    def on_cursor_moved(self, _event: CursorMoved) -> None:
        table = self.query_one(PackageTable)
        details = self.query_one(Details)
        if not len(self.plist) or details.has_class("hidden"):
            return
        r = self.plist.row(table.cursor)
        lines = [f"[b]{r.name}[/b] {r.candidate_evr or r.installed_evr}  {r.summary}",
                 f"Installed {r.installed_evr or '—'}   Repo {r.repo_id}   Size {cell_text(r, COL_SIZE, self.plist.ctx)}"]
        details.update("\n".join(lines))

    def update_status(self) -> None:
        marked = len(self.query_one(PackageTable).marked)
        self.query_one("#top", Static).update(
            f"[b]Kram[/b]  {self.filter_name} ({len(self.plist):,})  ·  {marked} marked")


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
            table = app.query_one(PackageTable)

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
            await timed("space (mark)", ["space"], 50)
            for name in ("Installed", "Upgradable", "All"):
                t = time.perf_counter()
                app.set_filter(name)
                await pilot.pause()
                print(f"  filter {name:<21} {1000 * (time.perf_counter() - t):6.1f} ms ({len(app.plist):,} rows)")
            t = time.perf_counter()
            app.plist.sort(COL_SIZE, True)
            table.refresh()
            await pilot.pause()
            print(f"  sort by size (70k)           {1000 * (time.perf_counter() - t):6.1f} ms")
            await timed("open/close groups (g, esc)", ["g", "escape"], 20)
        print(f"  RSS after: {rss_mb():.0f} MB")

    # the stock DataTable for comparison: it keeps every row as its own cells
    from textual.widgets import DataTable

    class Stock(App):
        def compose(self):
            yield DataTable()

    app = Stock()
    async with app.run_test(size=(160, 50)) as pilot:
        dt = app.query_one(DataTable)
        dt.add_columns("S", "Package", "Installed", "Latest", "Size")
        t = time.perf_counter()
        dt.add_rows([(STATUS_CHAR.get(r.status, " "), r.name, r.installed_evr, r.candidate_evr, str(r.size))
                     for r in snap.rows])
        await pilot.pause()
        print(f"\nDataTable: add {len(snap.rows):,} rows + first frame {1000 * (time.perf_counter() - t):.0f} ms, "
              f"RSS {rss_mb():.0f} MB")
        t, c = time.perf_counter(), time.process_time()
        for _ in range(50):
            await pilot.press("pagedown")
            await pilot.pause()
        print(f"  page down {1000 * (time.perf_counter() - t) / 50:.1f} ms wall, "
              f"{1000 * (time.process_time() - c) / 50:.1f} ms CPU per step")
        t = time.perf_counter()
        dt.clear()
        dt.add_rows([(STATUS_CHAR.get(r.status, " "), r.name, r.installed_evr, r.candidate_evr, str(r.size))
                     for r in snap.rows if r.installed_evr])
        await pilot.pause()
        print(f"  refill with the installed rows {1000 * (time.perf_counter() - t):.0f} ms")


async def shots(snap, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    cases = [("wide", (120, 30), []), ("wide-no-panels", (120, 30), ["g", "d"]),
             ("narrow", (52, 18), []), ("narrow-groups", (52, 18), ["g"]), ("narrow-details", (52, 18), ["d"]),
             ("narrow-groups-then-list", (52, 18), ["g", "down", "enter"])]
    for name, size, keys in cases:
        app = KramTui(snap)
        async with app.run_test(size=size) as pilot:
            app.set_filter("Upgradable") if name != "narrow-groups-then-list" else None
            await pilot.pause()
            for k in keys:
                await pilot.press(k)
                await pilot.pause()
            await pilot.pause()
            app.save_screenshot(filename=f"{name}.svg", path=str(out))
            focused = app.focused.id if app.focused else None
            shown = [n for n in ("groups", "details") if not app.query_one(f"#{n}").has_class("hidden")]
            print(f"{name}: focus={focused} panels shown={shown}")


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
