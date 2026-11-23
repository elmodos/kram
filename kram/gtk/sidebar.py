"""Left panel for GTK: the filter list and, below it, the views as a vertical Adw.ToggleGroup (D7); a view over
kram.app.sidebar.SidebarModel, as kram.qt.sidebar is.

One widget for every view (spike S5): a Gtk.ListView over a Gtk.TreeListModel. A flat view is a tree whose entries
have no children; the Origin view's repositories are children that are always unfolded and show no arrow; only the
views in COLLAPSIBLE (Environments) fold.
"""
from collections.abc import Callable

from gi.repository import Adw, Gdk, Gio, GObject, Gtk, Pango

from ..app.sidebar import VIEW_ICONS, VIEWS, Listing, SidebarModel, entry_font, entry_icon
from ..core.filters import FilterEntry
from .icons import set_image


class _Entry(GObject.Object):
    """One entry of the listing: its index in the model's entries, and its children's entries."""
    __gtype_name__ = "KramSidebarEntry"

    def __init__(self, index: int, entry: FilterEntry):
        super().__init__()
        self.index, self.entry = index, entry
        self.children: list["_Entry"] = []


class _Row:
    __slots__ = ("expander", "image", "label", "count", "entry")

    def __init__(self):
        self.expander = Gtk.TreeExpander()
        box = Gtk.Box(spacing=6)
        self.image = Gtk.Image(pixel_size=16)
        self.label = Gtk.Label(xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END)
        self.count = Gtk.Label(xalign=1)
        self.count.add_css_class("dim-label")
        self.count.add_css_class("numeric")
        for w in (self.image, self.label, self.count):
            box.append(w)
        self.expander.set_child(box)
        self.entry: _Entry | None = None


class Sidebar(Gtk.Box):
    """`on_context_menu(entry | None, widget, x, y)` and `on_activate(entry)` (a double click) are set by the
    window; the filter itself changes through the model's `filter_changed`."""

    def __init__(self, model: SidebarModel):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.model = model
        self.on_context_menu: Callable[[FilterEntry | None, Gtk.Widget, float, float], None] = lambda *a: None
        self.on_activate: Callable[[FilterEntry], None] = lambda e: None
        self._collapsible = False
        self._drawing = False
        self._rows: dict[Gtk.TreeExpander, _Row] = {}
        self._by_index: dict[int, _Row] = {}  # bound rows by entry index, for entry_changed

        self._root = Gio.ListStore(item_type=_Entry)
        self._tree = Gtk.TreeListModel.new(self._root, False, False, self._children)
        self._selection = Gtk.SingleSelection(model=self._tree, autoselect=False, can_unselect=True)
        self._selection.connect("notify::selected", self._selected)
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._setup)
        factory.connect("bind", self._bind)
        factory.connect("unbind", self._unbind)
        self.list = Gtk.ListView(model=self._selection, factory=factory)
        self.list.add_css_class("navigation-sidebar")
        self.list.connect("activate", self._activated)
        click = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        click.connect("pressed", self._right_click)
        self.list.add_controller(click)

        self.placeholder = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER, margin_start=12, margin_end=12)
        self.placeholder.add_css_class("dim-label")
        self.stack = Gtk.Stack(vexpand=True)
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, child=self.list)
        self.stack.add_named(scroller, "list")
        self.stack.add_named(self.placeholder, "empty")
        self.append(self.stack)
        self.append(Gtk.Separator())

        self.views = Adw.ToggleGroup(orientation=Gtk.Orientation.VERTICAL, homogeneous=True,
                                     margin_start=6, margin_end=6, margin_top=6, margin_bottom=6)
        for view_id, label, _builder in VIEWS:
            self.views.add(Adw.Toggle(name=view_id, label=label, icon_name=VIEW_ICONS[view_id]))
        self.views.set_active_name(model.current_view)
        self.views.connect("notify::active-name", self._view_chosen)
        self.append(self.views)

        model.listed.connect(self._draw)
        model.entry_changed.connect(self._redraw_entry)

    # ---------------------------------------------------------------- drawing

    def _children(self, item: _Entry):
        if not item.children:
            return None
        store = Gio.ListStore(item_type=_Entry)
        store.splice(0, 0, item.children)
        return store

    def _draw(self, listing: Listing) -> None:
        self._drawing = True
        try:
            if self.views.get_active_name() != listing.view:
                self.views.set_active_name(listing.view)
            self._collapsible = listing.collapsible
            items = [_Entry(i, e) for i, e in enumerate(listing.entries)]
            top = []
            for item, parent in zip(items, listing.parents, strict=True):
                (items[parent].children if parent is not None else top).append(item)
            self._tree.set_autoexpand(not listing.collapsible)
            self._root.splice(0, self._root.get_n_items(), top)
            if listing.collapsible:
                pos = 0
                while pos < self._tree.get_n_items():  # unfolding inserts the children after pos
                    row = self._tree.get_row(pos)
                    if row.get_item().entry.id in listing.expanded:
                        row.set_expanded(True)
                    pos += 1
            current = Gtk.INVALID_LIST_POSITION
            for pos in range(self._tree.get_n_items()):
                if self._tree.get_row(pos).get_item().entry.id == listing.current:
                    current = pos
                    break
            self._selection.set_selected(current)
            if current != Gtk.INVALID_LIST_POSITION:
                self.list.scroll_to(current, Gtk.ListScrollFlags.NONE, None)
            self.placeholder.set_text(listing.placeholder)
            self.stack.set_visible_child_name("empty" if listing.placeholder else "list")
        finally:
            self._drawing = False

    def _setup(self, _factory, item: Gtk.ListItem) -> None:
        row = _Row()
        self._rows[row.expander] = row
        item.set_child(row.expander)

    def _bind(self, _factory, item: Gtk.ListItem) -> None:
        tree_row = item.get_item()
        entry: _Entry = tree_row.get_item()
        row = self._rows[item.get_child()]
        row.entry = entry
        self._by_index[entry.index] = row
        row.expander.set_list_row(tree_row)
        row.expander.set_hide_expander(not self._collapsible)
        row.expander.set_indent_for_icon(self._collapsible)
        e = entry.entry
        set_image(row.image, entry_icon(e))
        row.image.set_visible(entry_icon(e) is not None)
        row.label.set_text(e.label)
        bold, italic = entry_font(e)
        for flag, cls in ((bold, "kram-bold"), (italic, "kram-italic")):
            (row.label.add_css_class if flag else row.label.remove_css_class)(cls)
        row.count.set_text(str(e.count) if e.count is not None else "")
        row.expander.set_tooltip_text(e.tip or None)
        tree_row.connect("notify::expanded", self._folded)

    def _unbind(self, _factory, item: Gtk.ListItem) -> None:
        row = self._rows[item.get_child()]
        tree_row = item.get_item()
        if tree_row is not None:
            try:
                tree_row.disconnect_by_func(self._folded)
            except TypeError:
                pass
        if row.entry is not None and self._by_index.get(row.entry.index) is row:
            del self._by_index[row.entry.index]
        row.entry = None

    def _redraw_entry(self, index: int, entry: FilterEntry) -> None:
        row = self._by_index.get(index)
        if row is not None:
            row.count.set_text(str(entry.count) if entry.count is not None else "")

    # ---------------------------------------------------------------- what the user does

    def _view_chosen(self, *_args) -> None:
        name = self.views.get_active_name()
        if not self._drawing and name and name != self.model.current_view:
            self.model.set_view(name)

    def _entry_at(self, pos: int) -> _Entry | None:
        if pos == Gtk.INVALID_LIST_POSITION or pos >= self._tree.get_n_items():
            return None
        return self._tree.get_row(pos).get_item()

    def _selected(self, *_args) -> None:
        if self._drawing:
            return
        item = self._entry_at(self._selection.get_selected())
        self.model.chosen(item.index if item is not None else None)

    def _folded(self, tree_row: Gtk.TreeListRow, _pspec) -> None:
        if not self._drawing:
            self.model.folded(tree_row.get_item().index, tree_row.get_expanded())

    def _activated(self, _list, pos: int) -> None:
        if (item := self._entry_at(pos)) is not None:
            self.on_activate(item.entry)

    def _right_click(self, gesture: Gtk.GestureClick, _n: int, x: float, y: float) -> None:
        picked = self.list.pick(x, y, Gtk.PickFlags.DEFAULT)
        entry = None
        while picked is not None and picked is not self.list:
            if isinstance(picked, Gtk.TreeExpander) and picked in self._rows:
                entry = self._rows[picked].entry
                break
            picked = picked.get_parent()
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        self.on_context_menu(entry.entry if entry is not None else None, self.list, x, y)
