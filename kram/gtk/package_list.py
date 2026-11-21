"""The package list for GTK: a Gtk.ColumnView over kram.app.package_list.PackageList.

How the list model works (spike S1, docs/GTK_FRONTEND.md §14): the store holds fixed items that stand for positions,
not packages. A change of the shown rows only adds or removes items at the end, and the cells already bound are
drawn again from the PackageList. GTK asks for every added item of an items_changed and tears down the cell widgets
of items it no longer finds, so refilling the model with new items cost ~300 ms for 70k rows; this costs a few ms.

Sorting is PackageList's (spike S2): the columns carry sorters only so that their headers show the indicator, and
no Gtk.SortListModel ever asks them to compare.
"""
from collections.abc import Callable

from gi.repository import Gdk, Gio, GObject, Gtk, Pango

from ..app.columns import (
    ALIGN_RIGHT,
    COL_CANDIDATE,
    COL_DOWNLOAD,
    COL_NAME,
    COL_ORIGIN,
    COL_STATUS,
    COL_SUMMARY,
    HEADERS,
    cell_icon,
    cell_style,
    cell_text,
    cell_tooltip,
    row_tint,
)
from ..app.icons import MARK_BACKGROUND
from ..app.package_list import PackageList, Sort
from ..core.model import PkgRow
from .icons import set_image

ICON_COLUMNS = (COL_STATUS, COL_ORIGIN)
HIDDEN_BY_DEFAULT = (COL_DOWNLOAD,)
DEFAULT_WIDTHS = {COL_STATUS: 34, COL_ORIGIN: 30, COL_NAME: 240, 3: 150, 4: 90, COL_CANDIDATE: 170, 6: 120, 7: 90,
                  9: 100, COL_DOWNLOAD: 90}
TINT_CLASSES = {action: f"kram-mark-{action.value}" for action in MARK_BACKGROUND}


def css() -> str:
    """The list's own styles. A marked row's tint is a translucent image over the row's background, so the hover
    and selection colours still show through it. It is drawn by each cell's own box, which takes the cell's padding
    so that the tint fills the row without gaps: changing GTK's own row widget while the list is being filled breaks
    GTK (criticals, then an abort)."""
    tints = "\n".join(f".kram-cell.{cls} {{ background-image: image(rgba({r}, {g}, {b}, {a / 255:.3f})); }}"
                      for action, cls in TINT_CLASSES.items() for r, g, b, a in [MARK_BACKGROUND[action]])
    return tints + """
.kram-bold { font-weight: bold; }
.kram-italic { font-style: italic; }
columnview.kram-packages > listview > row > cell { padding: 0; }
.kram-cell { padding: 2px 6px; }
"""


class Position(GObject.Object):
    """An item of the store: the position it stands for, whatever row is shown there."""
    __gtype_name__ = "KramPosition"

    def __init__(self, pos: int):
        super().__init__()
        self.pos = pos


class _Cell:
    """The widgets of one cell: what the factory set up, and the position and column it is bound to."""
    __slots__ = ("box", "image", "label", "col", "pos")

    def __init__(self, col: int):
        self.col, self.pos = col, -1
        self.box = Gtk.Box(spacing=4, hexpand=True)
        self.box.add_css_class("kram-cell")
        self.image = self.label = None
        if col in ICON_COLUMNS or col == COL_CANDIDATE:
            self.image = Gtk.Image(pixel_size=16)
            self.box.append(self.image)
        if col in ICON_COLUMNS:
            self.image.set_hexpand(True)  # centred in a box that fills the cell, for the tint
        else:
            self.label = Gtk.Label(xalign=1 if col in ALIGN_RIGHT else 0, hexpand=True,
                                   ellipsize=Pango.EllipsizeMode.END, single_line_mode=True)
            if col in ALIGN_RIGHT:
                self.label.add_css_class("numeric")
            self.box.append(self.label)


class PackageListView(Gtk.ScrolledWindow):
    """The view. What the user does with the rows is reported through the callbacks the window sets:
    `on_status_click(pos, widget)`, `on_context_menu(pos, widget, x, y)`, `on_activate(pos)`,
    `on_current(pos | None)`, `on_selection()`, `on_sort(column, descending)` (a header click)."""

    def __init__(self, packages: PackageList):
        super().__init__(hexpand=True, vexpand=True)
        self.packages = packages
        self._items: list[Position] = []
        self._n = 0
        self.store = Gio.ListStore(item_type=Position)
        self.selection = Gtk.MultiSelection(model=self.store)
        self._cells: dict[Gtk.Box, _Cell] = {}       # every cell set up, by its box
        self._bound: dict[Gtk.Box, _Cell] = {}       # the ones bound now
        self._current: int | None = None
        self.on_status_click: Callable[[int, Gtk.Widget], None] = lambda pos, w: None
        self.on_context_menu: Callable[[int, Gtk.Widget, float, float], None] = lambda pos, w, x, y: None
        self.on_activate: Callable[[int], None] = lambda pos: None
        self.on_current: Callable[[int | None], None] = lambda pos: None
        self.on_selection: Callable[[], None] = lambda: None
        self.on_sort: Callable[[int, bool], None] = lambda column, descending: None

        view = self.view = Gtk.ColumnView(model=self.selection, reorderable=True, show_row_separators=False,
                                          show_column_separators=False)
        view.add_css_class("data-table")
        view.add_css_class("kram-packages")
        self.columns: list[Gtk.ColumnViewColumn] = []
        for col, title in enumerate(HEADERS):
            factory = Gtk.SignalListItemFactory()
            factory.connect("setup", self._setup, col)
            factory.connect("bind", self._bind)
            factory.connect("unbind", self._unbind)
            factory.connect("teardown", self._teardown)
            column = Gtk.ColumnViewColumn(title=title, factory=factory, resizable=True,
                                          expand=col == COL_SUMMARY, visible=col not in HIDDEN_BY_DEFAULT,
                                          id=str(col))
            column.set_sorter(Gtk.CustomSorter.new(None))  # only for the header's indicator, never asked
            if col != COL_SUMMARY:
                column.set_fixed_width(DEFAULT_WIDTHS.get(col, 120))
            self.columns.append(column)
            view.append_column(column)
        self._sort_handler = view.get_sorter().connect("changed", self._header_sorted)
        view.connect("activate", lambda _v, pos: self.on_activate(pos))
        self.selection.connect("selection-changed", self._selection_changed)
        self.set_child(view)

        packages.about_to_reset.connect(self.selection.unselect_all)
        packages.reset.connect(self._reset)
        packages.sorted.connect(lambda _moved: self.refresh())
        packages.rows_changed.connect(self.refresh)
        self._reset()

    # ---------------------------------------------------------------- the model

    def _reset(self) -> None:
        new, old = len(self.packages), self._n
        if len(self._items) < new:
            self._items.extend(Position(i) for i in range(len(self._items), new))
        self._n = new
        self._current = None
        if new > old:
            self.store.splice(old, 0, self._items[old:new])
        elif new < old:
            self.store.splice(new, old - new, [])
        self.refresh()

    def refresh(self, positions: list[int] | None = None) -> None:
        """Draw the bound cells again: all of them, or those showing `positions`."""
        wanted = None if positions is None else set(positions)
        for cell in self._bound.values():
            if wanted is None or cell.pos in wanted:
                self._render(cell)

    # ---------------------------------------------------------------- cells

    def _setup(self, _factory, item: Gtk.ListItem, col: int) -> None:
        cell = _Cell(col)
        self._cells[cell.box] = cell
        item.set_child(cell.box)
        click = Gtk.GestureClick(button=0)
        click.connect("pressed", self._pressed, cell)
        cell.box.add_controller(click)

    def _bind(self, _factory, item: Gtk.ListItem) -> None:
        cell = self._cells[item.get_child()]
        cell.pos = item.get_item().pos
        self._bound[cell.box] = cell
        self._render(cell)

    def _unbind(self, _factory, item: Gtk.ListItem) -> None:
        cell = self._bound.pop(item.get_child(), None)
        if cell is not None:
            cell.pos = -1

    def _teardown(self, _factory, item: Gtk.ListItem) -> None:
        self._cells.pop(item.get_child(), None)

    def _render(self, cell: _Cell) -> None:
        if not 0 <= cell.pos < self._n:
            return
        r, col, ctx = self.packages.row(cell.pos), cell.col, self.packages.ctx
        if cell.image is not None:
            set_image(cell.image, cell_icon(r, col, ctx))
        if cell.label is not None:
            cell.label.set_text(cell_text(r, col, ctx) or "")
            style = cell_style(r, col, ctx)
            for flag, cls in ((style.bold, "kram-bold"), (style.italic, "kram-italic"), (style.dimmed, "dim-label")):
                if flag:
                    cell.label.add_css_class(cls)
                else:
                    cell.label.remove_css_class(cls)
        cell.box.set_tooltip_text(cell_tooltip(r, col, ctx))
        tint = row_tint(r, ctx.marks)
        for action, cls in TINT_CLASSES.items():
            if action is tint:
                cell.box.add_css_class(cls)
            else:
                cell.box.remove_css_class(cls)

    # ---------------------------------------------------------------- clicks

    def _pressed(self, gesture: Gtk.GestureClick, n_press: int, x: float, y: float, cell: _Cell) -> None:
        pos = cell.pos
        if pos < 0:
            return
        button = gesture.get_current_button()
        if button == Gdk.BUTTON_SECONDARY:
            # as in Qt: a right click on a selected row keeps the selection, elsewhere it selects that row
            if not self.selection.is_selected(pos):
                self.selection.select_item(pos, True)
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
            self.on_context_menu(pos, cell.box, x, y)
        elif button == Gdk.BUTTON_PRIMARY and n_press == 1 and cell.col == COL_STATUS:
            self.on_status_click(pos, cell.box)

    # ---------------------------------------------------------------- selection

    def _selection_changed(self, _model, _position: int, _n: int) -> None:
        selected = self.selection.get_selection()
        if selected.get_size() == 0:
            current = None
        elif self._current is not None and selected.contains(self._current) and selected.get_size() > 1:
            current = self._current
        else:
            current = selected.get_minimum() if selected.get_size() > 1 else selected.get_nth(0)
        self._set_current(current)
        self.on_selection()

    def _set_current(self, pos: int | None) -> None:
        if pos != self._current:
            self._current = pos
            self.on_current(pos)

    def current(self) -> int | None:
        return self._current

    def current_row(self) -> PkgRow | None:
        return self.packages.row(self._current) if self._current is not None and self._current < self._n else None

    def selected_positions(self) -> list[int]:
        bits = self.selection.get_selection()
        return [bits.get_nth(i) for i in range(bits.get_size())]

    def select(self, pos: int, scroll: bool = True) -> None:
        """Select only `pos`, make it current, and (with `scroll`) bring it into view with the keyboard focus."""
        if not 0 <= pos < self._n:
            return
        flags = Gtk.ListScrollFlags.SELECT
        if self.view.get_focus_child() is not None:  # keep the keyboard focus in the list, never take it there
            flags |= Gtk.ListScrollFlags.FOCUS
        if scroll:
            self.view.scroll_to(pos, None, flags, None)
        else:
            self.selection.select_item(pos, True)
        self._set_current(pos)

    def scroll_to_top(self) -> None:
        if self._n:
            self.view.scroll_to(0, None, Gtk.ListScrollFlags.NONE, None)

    # ---------------------------------------------------------------- sorting

    def _header_sorted(self, sorter: Gtk.ColumnViewSorter, _change) -> None:
        column = sorter.get_primary_sort_column()
        if column is None:
            return
        descending = sorter.get_primary_sort_order() == Gtk.SortType.DESCENDING
        # a header click makes its column the primary one and keeps the others as secondary sorts, each still
        # showing its arrow; PackageList sorts by one column, so the headers show one
        self.show_sort((int(column.get_id()), descending))
        self.on_sort(int(column.get_id()), descending)

    def show_sort(self, sort: Sort | None) -> None:
        """The header's indicator for `sort` (None: none, ranked results), without sorting anything."""
        sorter = self.view.get_sorter()
        sorter.handler_block(self._sort_handler)
        try:
            self.view.sort_by_column(None, Gtk.SortType.ASCENDING)
            if sort is not None:
                order = Gtk.SortType.DESCENDING if sort[1] else Gtk.SortType.ASCENDING
                self.view.sort_by_column(self.columns[sort[0]], order)
        finally:
            sorter.handler_unblock(self._sort_handler)
