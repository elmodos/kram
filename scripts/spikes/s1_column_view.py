#!/usr/bin/python3
"""Spike S1 (docs/GTK_FRONTEND.md §7.1): Gtk.ColumnView over ~70k rows.

A Python GObject implementing Gio.ListModel over kram.app.package_list.PackageList: items are made on demand (only
the rows GTK asks for, about a screenful) and cached until the next reset; a reset is one items_changed(0, old, new).
Compared with a Gio.ListStore holding one item per row.

    KRAM_SPIKE_SNAPSHOT=snap.pickle python3 scripts/spikes/s1_column_view.py [positions|lazy|store] [--stay]

Models compared:
  lazy       a Python Gio.ListModel making an item per position on demand; a reset is items_changed(0, old, new).
             GTK asks for every added item on such a change (it looks for widgets it can keep), so a reset calls
             do_get_item ~70k times from C into Python.
  store      a Gio.ListStore refilled with new items at each reset: GTK finds none of the old items, tears down every
             cell widget and builds new ones.
  positions  (chosen) a Gio.ListStore of fixed items that stand for positions, not packages. A reset only adds or
             removes items at the end, and the cells already bound are re-rendered from PackageList; nothing is torn
             down unless the list gets shorter than the screen.

It runs a fixed script and prints the numbers: resets (all rows, a filter, back), a re-sort, a slow scroll (three
rows a frame) and a fast one (half a page a frame) with their frame times, and the memory. --stay keeps the window
open afterwards to scroll by hand.
"""
import statistics
import sys

from common import Stopwatch, rss_mb, snapshot, versions
from gi.repository import Gio, GLib, GObject, Gtk

from kram.app.columns import COL_DOWNLOAD, COL_NAME, COL_STATUS, COL_SUMMARY, HEADERS, cell_text
from kram.app.package_list import PackageList


class Row(GObject.Object):
    """One shown position. Light: a plain attribute, no GObject properties."""
    __gtype_name__ = "KramSpikeRow"

    def __init__(self, pos: int):
        super().__init__()
        self.pos = pos


class LazyModel(GObject.Object, Gio.ListModel):
    __gtype_name__ = "KramSpikeLazyModel"

    def __init__(self, packages: PackageList):
        super().__init__()
        self.packages = packages
        self._items: dict[int, Row] = {}
        self._n = len(packages)
        packages.reset.connect(self._reset)
        packages.sorted.connect(lambda _moved: self._reset())

    def _reset(self):
        old, self._n = self._n, len(self.packages)
        self._items.clear()
        self.items_changed(0, old, self._n)

    def do_get_item_type(self):
        return Row.__gtype__

    def do_get_n_items(self):
        return self._n

    def do_get_item(self, pos):
        if pos >= self._n:
            return None
        item = self._items.get(pos)
        if item is None:
            item = self._items[pos] = Row(pos)
        return item


class StoreModel:
    """The same over a Gio.ListStore: every row an item, made at each reset."""

    def __init__(self, packages: PackageList):
        self.packages = packages
        self.store = Gio.ListStore(item_type=Row)
        packages.reset.connect(self._reset)
        packages.sorted.connect(lambda _moved: self._reset())

    def _reset(self):
        self.store.splice(0, self.store.get_n_items(), [Row(i) for i in range(len(self.packages))])


class PositionsModel:
    """Fixed position items in a Gio.ListStore; the bound cells are re-rendered on a change."""

    def __init__(self, packages: PackageList):
        self.packages = packages
        self.store = Gio.ListStore(item_type=Row)
        self.items: list[Row] = []
        self.bound: dict[Gtk.Label, tuple[int, int]] = {}  # label -> (position, column)
        self._n = 0
        packages.reset.connect(self._reset)
        packages.sorted.connect(lambda _moved: self.refresh())
        self._reset()

    def _reset(self):
        new, old = len(self.packages), self._n
        if len(self.items) < new:
            self.items.extend(Row(i) for i in range(len(self.items), new))
        self._n = new
        if new > old:
            self.store.splice(old, 0, self.items[old:new])
        elif new < old:
            self.store.splice(new, old - new, [])
        self.refresh()

    def refresh(self):
        ctx = self.packages.ctx
        for label, (pos, col) in self.bound.items():
            if pos < self._n:
                label.set_text(cell_text(self.packages.row(pos), col, ctx) or "")


def build(packages: PackageList, model: Gio.ListModel, bound: dict | None = None) -> Gtk.ColumnView:
    view = Gtk.ColumnView(model=Gtk.MultiSelection(model=model), reorderable=True, show_row_separators=False)
    view.add_css_class("data-table")
    ctx = packages.ctx
    for col, title in enumerate(HEADERS):
        if col == COL_STATUS or col == 1:
            continue  # icons: S3/S7
        factory = Gtk.SignalListItemFactory()

        def setup(_f, item):
            item.set_child(Gtk.Label(xalign=0, ellipsize=3))  # PANGO_ELLIPSIZE_END

        def bind(_f, item, col=col):
            label, pos = item.get_child(), item.get_item().pos
            if bound is not None:
                bound[label] = (pos, col)
            label.set_text(cell_text(packages.row(pos), col, ctx) or "")

        def unbind(_f, item):
            if bound is not None:
                bound.pop(item.get_child(), None)

        factory.connect("setup", setup)
        factory.connect("bind", bind)
        factory.connect("unbind", unbind)
        column = Gtk.ColumnViewColumn(title=title, factory=factory, resizable=True, expand=col == COL_SUMMARY,
                                      visible=col != COL_DOWNLOAD)
        if col == COL_NAME:
            column.set_fixed_width(260)
        view.append_column(column)
    return view


class Runner:
    def __init__(self, win: Gtk.Window, view: Gtk.ColumnView, scroller: Gtk.ScrolledWindow, packages, stay: bool):
        self.win, self.view, self.scroller, self.packages, self.stay = win, view, scroller, packages, stay
        self.steps = iter(self.script())

    def next(self, *_a):
        try:
            next(self.steps)
        except StopIteration:
            if not self.stay:
                self.win.get_application().quit()
        return GLib.SOURCE_REMOVE

    def after_paint(self, then):
        clock = self.win.get_frame_clock()
        handler = None

        def painted(_clock):
            clock.disconnect(handler)
            then()
        handler = clock.connect("after-paint", painted)
        self.win.queue_draw()

    def timed(self, label, change):
        sw = Stopwatch()
        change()
        py = sw.ms()
        self.after_paint(lambda: (print(f"{label}: {py:.1f} ms in Python, {sw.ms():.1f} ms to the painted frame"),
                                  GLib.timeout_add(300, self.next)))

    def scroll(self, label, step_rows, seconds=3.0):
        adj = self.scroller.get_vadjustment()
        adj.set_value(0)
        frames = []
        last = [None]
        row_h = max(1.0, adj.get_upper() / max(1, len(self.packages)))
        page = adj.get_page_size()

        def tick(_w, clock):
            t = clock.get_frame_time()
            if last[0] is not None:
                frames.append((t - last[0]) / 1000)
            last[0] = t
            step = page / 2 if step_rows is None else step_rows * row_h
            adj.set_value(min(adj.get_value() + step, adj.get_upper() - page))
            if sum(frames) / 1000 >= seconds or adj.get_value() >= adj.get_upper() - page:
                frames.sort()
                p95 = frames[int(len(frames) * 0.95)] if frames else 0
                print(f"{label}: {len(frames)} frames, median {statistics.median(frames):.1f} ms, "
                      f"p95 {p95:.1f} ms, worst {frames[-1]:.1f} ms, frames over 33 ms: "
                      f"{sum(f > 33 for f in frames)}")
                GLib.timeout_add(300, self.next)
                return GLib.SOURCE_REMOVE
            return GLib.SOURCE_CONTINUE
        self.view.add_tick_callback(tick)

    def script(self):
        p = self.packages
        n = len(p.rows)
        yield self.timed(f"reset to all {n} rows", lambda: p.set_visible(list(range(n))))
        yield self.timed("reset to all rows again", lambda: p.set_visible(list(range(n))))
        installed = [i for i, r in enumerate(p.rows) if r.installed]
        yield self.timed(f"reset to the {len(installed)} installed", lambda: p.set_visible(installed))
        yield self.timed(f"reset back to all {n}", lambda: p.set_visible(list(range(n))))
        yield self.timed("reset to one row", lambda: p.set_visible([5]))
        yield self.timed(f"reset from one row to all {n}", lambda: p.set_visible(list(range(n))))
        yield self.timed("re-sort all by summary", lambda: p.sort(8))
        yield self.timed("re-sort all by name", lambda: p.sort(COL_NAME))
        yield self.scroll("slow scroll (3 rows a frame)", 3)
        yield self.scroll("fast scroll (half a page a frame)", None)
        print(f"memory: {rss_mb():.0f} MB RSS")
        yield None


def main():
    kinds = [a for a in sys.argv[1:] if a in ("positions", "lazy", "store")]
    kind = kinds[0] if kinds else "positions"
    stay = "--stay" in sys.argv
    print(versions())
    sw = Stopwatch()
    snap = snapshot()
    print(f"catalog: {len(snap.rows)} rows in {sw.ms():.0f} ms, memory {rss_mb():.0f} MB RSS; model: {kind}")
    packages = PackageList()
    packages.set_rows(snap.rows, snap.basearch)

    app = Gtk.Application(application_id=None, flags=Gio.ApplicationFlags.NON_UNIQUE)

    def activate(app):
        sw = Stopwatch()
        bound = None
        if kind == "lazy":
            model = LazyModel(packages)
        elif kind == "positions":
            holder = PositionsModel(packages)
            model, bound = holder.store, holder.bound
            app._holder = holder
        else:
            holder = StoreModel(packages)
            holder._reset()
            model = holder.store
            app._holder = holder
        print(f"model built in {sw.ms():.0f} ms")
        win = Gtk.ApplicationWindow(application=app, title=f"S1 ({kind})", default_width=1320, default_height=860)
        scroller = Gtk.ScrolledWindow()
        view = build(packages, model, bound)
        scroller.set_child(view)
        win.set_child(scroller)
        win.present()
        runner = Runner(win, view, scroller, packages, stay)
        app._runner = runner
        runner.after_paint(lambda: (print(f"first frame {sw.ms():.0f} ms after building the model; "
                                          f"memory {rss_mb():.0f} MB RSS"), GLib.timeout_add(500, runner.next)))

    app.connect("activate", activate)
    app.run([])


if __name__ == "__main__":
    main()
