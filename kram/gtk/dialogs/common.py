"""Pieces the GTK dialogs share: a tree of plain rows in a Gtk.ColumnView, read-only text, the buttons."""
from collections.abc import Callable

from gi.repository import Adw, Gio, GObject, Gtk, Pango

from ..ui_port import gtk_text


class Node(GObject.Object):
    """A row of a tree: `data` is whatever the columns show, `children` the rows under it."""
    __gtype_name__ = "KramTreeNode"

    def __init__(self, data, children: list["Node"] | None = None):
        super().__init__()
        self.data = data
        self.children = children or []


def tree_model(nodes: list[Node], expanded: Callable[[Node], bool] = lambda _n: True) -> Gtk.TreeListModel:
    """`nodes` and their children as a tree, rows open where `expanded` says so."""
    def children(node: Node):
        if not node.children:
            return None
        store = Gio.ListStore(item_type=Node)
        for child in node.children:
            store.append(child)
        return store
    root = Gio.ListStore(item_type=Node)
    for node in nodes:
        root.append(node)
    model = Gtk.TreeListModel.new(root, False, False, children)
    i = 0
    while i < model.get_n_items():  # opening a row adds its children after it: the count grows as it goes
        row = model.get_row(i)
        if row is not None and row.get_depth() == 0 and row.get_item().children and expanded(row.get_item()):
            row.set_expanded(True)
        i += 1
    return model


def column(view: Gtk.ColumnView, title: str, setup: Callable[[], Gtk.Widget],
           bind: Callable[[Gtk.Widget, Node], None], expand: bool = False, tree: bool = False) -> Gtk.ColumnViewColumn:
    """A column whose cells are `setup()` widgets, filled by `bind(widget, node)`. `tree`: the first column, with the
    expander arrow."""
    factory = Gtk.SignalListItemFactory()

    def on_setup(_f, item: Gtk.ListItem) -> None:
        child = setup()
        item.set_child(Gtk.TreeExpander(child=child) if tree else child)

    def on_bind(_f, item: Gtk.ListItem) -> None:
        row: Gtk.TreeListRow = item.get_item()
        widget = item.get_child()
        if tree:
            widget.set_list_row(row)
            widget = widget.get_child()
        bind(widget, row.get_item())
    factory.connect("setup", on_setup)
    factory.connect("bind", on_bind)
    col = Gtk.ColumnViewColumn(title=title, factory=factory, expand=expand, resizable=True)
    view.append_column(col)
    return col


def label(ellipsize: Pango.EllipsizeMode = Pango.EllipsizeMode.END, numeric: bool = False) -> Gtk.Label:
    widget = Gtk.Label(xalign=1 if numeric else 0, ellipsize=ellipsize)
    if numeric:
        widget.add_css_class("numeric")
    return widget


def text_view(height: int = 0) -> tuple[Gtk.ScrolledWindow, Gtk.TextView]:
    """Read-only monospace text, scrolled; `height` 0 lets it grow."""
    text = Gtk.TextView(editable=False, cursor_visible=False, monospace=True, wrap_mode=Gtk.WrapMode.NONE,
                        left_margin=6, right_margin=6, top_margin=4, bottom_margin=4)
    scroller = Gtk.ScrolledWindow(child=text, vexpand=height == 0)
    scroller.add_css_class("card")
    if height:
        scroller.set_size_request(-1, height)
    return scroller, text


def wrapped(css: str = "") -> Gtk.Label:
    widget = Gtk.Label(xalign=0, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR, selectable=False)
    if css:
        widget.add_css_class(css)
    return widget


def standard_button(msgid: str) -> Gtk.Button:
    """A button with GTK's own translated label ("_Cancel", "_Close")."""
    return Gtk.Button(label=gtk_text(msgid), use_underline=True)


def frame(dlg: Adw.Dialog) -> tuple[Adw.HeaderBar, Gtk.Box]:
    """Give `dlg` a header bar without title buttons (the dialog's own buttons close it) over a padded box."""
    header = Adw.HeaderBar(show_start_title_buttons=False, show_end_title_buttons=False)
    body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_start=12, margin_end=12,
                   margin_top=6, margin_bottom=12)
    view = Adw.ToolbarView(content=body)
    view.add_top_bar(header)
    dlg.set_child(view)
    return header, body
