"""The Files tab for GTK: the package's files as a folder tree or a flat list, with a filter field (kram.core.file_tree),
as kram.qt.file_list."""
from gi.repository import Gdk, Gio, GLib, GObject, Gtk, Pango

from ..app.files import (
    can_show_in_file_manager,
    count_text,
    filter_placeholder,
    name_spans,
    partial_notice,
    shown_paths,
)
from ..core.file_tree import Node, PathFilter, build_tree, path_filter
from ..i18n import _

FILTER_DELAY_MS = 150  # a package can have tens of thousands of files: filter once the typing pauses


class FileItem(GObject.Object):
    """A row: a node of the tree, or a path of the flat list."""
    __gtype_name__ = "KramFileItem"

    def __init__(self, name: str, path: str, node: Node | None = None):
        super().__init__()
        self.name, self.path, self.node = name, path, node


class FileIcons:
    """A folder icon, and file icons by the name's type, cached by extension: the views only ask for the rows they
    show."""

    def __init__(self):
        self.folder = Gio.ThemedIcon.new("folder")
        self._icons: dict[str, Gio.Icon] = {}

    def file(self, name: str) -> Gio.Icon:
        key = name.rpartition(".")[2] if "." in name else name
        icon = self._icons.get(key)
        if icon is None:
            content_type, _uncertain = Gio.content_type_guess(name, None)
            icon = self._icons[key] = Gio.content_type_get_icon(content_type)
        return icon


def _children(item: FileItem) -> Gio.ListStore | None:
    node = item.node
    if node is None or not node.children:
        return None
    store = Gio.ListStore(item_type=FileItem)
    store.splice(0, 0, [FileItem(c.name, c.path, c) for c in node.children])
    return store


def name_markup(name: str, path: str, f: PathFilter | None) -> str:
    """`name` with the parts the filter matched in bold: in the tree a file can be shown only because a folder above it
    matched, and then nothing in the file's own name is."""
    spans = name_spans(name, path, f)
    out, pos = [], 0
    for begin, end in spans:
        out.append(GLib.markup_escape_text(name[pos:begin]))
        out.append(f"<b>{GLib.markup_escape_text(name[begin:end])}</b>")
        pos = end
    out.append(GLib.markup_escape_text(name[pos:]))
    return "".join(out)


class FileList(Gtk.Box):
    """The Files tab. The tree is built when the tab is shown, not for every package the cursor passes. `ui` shows a
    file in the file manager and copies paths (kram.app.ports.Ui)."""

    def __init__(self, ui=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=6, margin_end=6,
                         margin_top=6)
        self.ui = ui
        self._paths: list[str] = []
        self._installed = False
        self._stale = False  # new paths or a new filter not shown yet
        self._filter: PathFilter | None = None
        self._icons = FileIcons()

        bar = Gtk.Box(spacing=6)
        self.filter = Gtk.SearchEntry(placeholder_text=filter_placeholder(),
                                      search_delay=FILTER_DELAY_MS, hexpand=True)
        self.filter.connect("search-changed", lambda _e: self._rebuild())
        bar.append(self.filter)
        self.count = Gtk.Label()
        self.count.add_css_class("dim-label")
        bar.append(self.count)
        modes = Gtk.Box()
        modes.add_css_class("linked")
        self.tree_button = Gtk.ToggleButton(active=True, tooltip_text=_("Show the files in their folders"))
        self.tree_button.set_child(self._button_content(_("Tree"), "view-list-symbolic"))
        self.list_button = Gtk.ToggleButton(group=self.tree_button, tooltip_text=_(
            "Show the full path of every file, one per line"))
        self.list_button.set_child(self._button_content(_("List"), "format-justify-left-symbolic"))
        self.tree_button.connect("toggled", lambda b: b.get_active() and self._rebuild())
        self.list_button.connect("toggled", lambda b: b.get_active() and self._rebuild())
        modes.append(self.tree_button)
        modes.append(self.list_button)
        bar.append(modes)
        self.append(bar)
        self.notice = Gtk.Label(label=partial_notice(),
                                xalign=0, wrap=True, visible=False)
        self.notice.add_css_class("dim-label")
        self.append(self.notice)

        self.selection = Gtk.MultiSelection()
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._setup)
        factory.connect("bind", self._bind)
        self.view = Gtk.ListView(model=self.selection, factory=factory)
        self.append(Gtk.ScrolledWindow(child=self.view, vexpand=True))

        keys = Gtk.ShortcutController()
        keys.add_shortcut(Gtk.Shortcut(trigger=Gtk.ShortcutTrigger.parse_string("<Control>c"),
                                       action=Gtk.CallbackAction.new(lambda *_a: (self.copy_paths(), True)[1])))
        self.view.add_controller(keys)
        click = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        click.connect("pressed", self._pressed)
        self.view.add_controller(click)
        group = Gio.SimpleActionGroup()
        for name, fn in (("copy", self.copy_paths), ("show", self._show_in_file_manager)):
            act = Gio.SimpleAction(name=name)
            act.connect("activate", lambda _a, _p, fn=fn: fn())
            group.add_action(act)
        self._actions = group
        self.insert_action_group("files", group)
        menu = Gio.Menu()
        menu.append(_("Copy Path"), "files.copy")
        menu.append(_("Show in File Manager"), "files.show")
        self._popover = Gtk.PopoverMenu(menu_model=menu, has_arrow=False)
        self._popover.set_parent(self.view)
        self._menu_path = ""
        self.connect("map", lambda _w: self._stale and self._rebuild())

    @staticmethod
    def _button_content(label: str, icon: str) -> Gtk.Widget:
        box = Gtk.Box(spacing=4)
        box.append(Gtk.Image(icon_name=icon))
        box.append(Gtk.Label(label=label))
        return box

    # ---------------------------------------------------------------- state

    @property
    def tree_mode(self) -> bool:
        return self.tree_button.get_active()

    @tree_mode.setter
    def tree_mode(self, on: bool) -> None:
        (self.tree_button if on else self.list_button).set_active(True)

    def set_files(self, paths: list[str], complete: bool) -> None:
        """A package's files. `complete` is False for a package that is not installed: the repository metadata list
        only some of its files. The filter text stays, to look for the same file in the next package."""
        self._paths = list(paths)
        self._installed = complete
        self.notice.set_visible(not complete)
        self._stale = True
        if self.get_mapped():
            self._rebuild()

    def clear(self) -> None:
        self.set_files([], True)

    def _rebuild(self) -> None:
        self._stale = False
        self._filter = f = path_filter(self.filter.get_text())
        paths = shown_paths(self._paths, f)
        if self.tree_mode:
            root = build_tree(paths)
            store = Gio.ListStore(item_type=FileItem)
            store.splice(0, 0, [FileItem(c.name, c.path, c) for c in root.children])
            # old-school: every folder open, the filter narrows it
            self.selection.set_model(Gtk.TreeListModel.new(store, False, True, _children))
        else:
            store = Gio.ListStore(item_type=FileItem)
            store.splice(0, 0, [FileItem(p, p) for p in paths])
            self.selection.set_model(store)
        self.count.set_text(count_text(len(paths), len(self._paths)))

    # ---------------------------------------------------------------- rows

    @staticmethod
    def _setup(_factory, item: Gtk.ListItem) -> None:
        box = Gtk.Box(spacing=6)
        box.append(Gtk.Image())
        box.append(Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.MIDDLE))
        item.set_child(Gtk.TreeExpander(child=box, indent_for_icon=True))

    def _bind(self, _factory, item: Gtk.ListItem) -> None:
        row = item.get_item()
        expander: Gtk.TreeExpander = item.get_child()
        if isinstance(row, Gtk.TreeListRow):
            expander.set_list_row(row)
            file = row.get_item()
        else:
            expander.set_list_row(None)
            file = row
        box = expander.get_child()
        image, label = box.get_first_child(), box.get_last_child()
        is_dir = file.node is not None and file.node.is_dir
        image.set_from_gicon(self._icons.folder if is_dir else self._icons.file(file.name))
        label.set_markup(name_markup(file.name, file.path, self._filter))
        box.set_tooltip_text(file.path if file.node is not None else None)

    @staticmethod
    def _path_of(row) -> str:
        return (row.get_item() if isinstance(row, Gtk.TreeListRow) else row).path

    # ---------------------------------------------------------------- actions

    def selected_paths(self) -> list[str]:
        bitset = self.selection.get_selection()
        return [self._path_of(self.selection.get_item(bitset.get_nth(i))) for i in range(bitset.get_size())]

    def copy_paths(self) -> None:
        if (paths := self.selected_paths()) and self.ui is not None:
            self.ui.copy_text("\n".join(paths))

    def _show_in_file_manager(self) -> None:
        if self._menu_path and self.ui is not None:
            self.ui.show_in_file_manager(self._menu_path)

    def _pressed(self, _gesture, _n: int, x: float, y: float) -> None:
        widget = self.view.pick(x, y, Gtk.PickFlags.DEFAULT)
        while widget is not None and widget is not self.view and not isinstance(widget, Gtk.TreeExpander):
            widget = widget.get_parent()
        if not isinstance(widget, Gtk.TreeExpander):
            return
        label = widget.get_child().get_last_child()
        path = label.get_text() if not self.tree_mode else widget.get_child().get_tooltip_text()
        # select the row under the pointer unless it is part of the selection already
        for i in range(self.selection.get_n_items()):
            if self._path_of(self.selection.get_item(i)) == path:
                if not self.selection.is_selected(i):
                    self.selection.select_item(i, True)
                break
        self._menu_path = path or ""
        self._actions.lookup_action("show").set_enabled(can_show_in_file_manager(self._installed, path or ""))
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        self._popover.set_pointing_to(rect)
        self._popover.popup()
