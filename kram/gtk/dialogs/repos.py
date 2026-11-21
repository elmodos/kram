"""Settings → Repositories for GTK (kram.app.repos): enable/disable configured repositories, show their packages,
remove the user's own."""
from collections import Counter
from collections.abc import Callable

from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

from ...app.repos import RepoLine, Repos, matches
from ...core.model import RepoInfo
from ...i18n import _
from .. import icons
from ..ui_port import GtkUi
from .common import Node, frame, label, standard_button


class ReposDialog(Adw.Dialog):
    def __init__(self, repos: list[RepoInfo], counts: Counter, done: Callable[["ReposDialog", bool], None], *,
                 owners: dict[str, str] | None = None, listed: Counter | None = None,
                 installed: Counter | None = None):
        """`counts`: available packages per repo; `owners`: .repo file -> the package that owns it; `listed`: rows
        of the package list per repo (its Origin filter); `installed`: installed packages per repo they came from.

        `done(dialog, accepted)` once it closes; `show_repo` or `remove_repos` then says what the user asked for
        instead of applying changes."""
        super().__init__(title=_("Repositories"), content_width=1180, content_height=620)
        self._done = done
        self._accepted = False
        self.ui = GtkUi(self)
        self.repos = Repos(repos, counts, self.ui, self, owners=owners, listed=listed, installed=installed)
        header, body = frame(self)
        close = standard_button("_Close")
        close.connect("clicked", lambda _b: self.close())
        header.pack_start(close)
        self.apply_btn = Gtk.Button(label=_("Apply changes"))
        self.apply_btn.add_css_class("suggested-action")
        self.apply_btn.connect("clicked", self._apply)
        header.pack_end(self.apply_btn)

        top = Gtk.Box(spacing=12)
        self.filter = Gtk.SearchEntry(placeholder_text=_("Filter…"), hexpand=True)
        self.filter.connect("search-changed", lambda _e: self._apply_filter())
        top.append(self.filter)
        self.show_aux = Gtk.CheckButton(label=_("Show debuginfo and source repositories"))
        self.show_aux.connect("toggled", lambda _b: self._apply_filter())
        top.append(self.show_aux)
        body.append(top)

        store = Gio.ListStore(item_type=Node)
        for line in self.repos.lines():
            store.append(Node(line))
        self._filter = Gtk.CustomFilter.new(self._matches)
        self.selection = Gtk.SingleSelection(model=Gtk.FilterListModel(model=store, filter=self._filter),
                                             autoselect=False, can_unselect=True)
        self.selection.connect("selection-changed", lambda *_a: self._update_buttons())
        self.table = Gtk.ColumnView(model=self.selection)
        self.table.add_css_class("data-table")
        self._columns()
        body.append(Gtk.ScrolledWindow(child=self.table, vexpand=True))

        row = Gtk.Box(spacing=6)
        self.packages_btn = Gtk.Button(child=Adw.ButtonContent(label=_("Show packages"),
                                                               icon_name="view-list-symbolic"))
        self.packages_btn.connect("clicked", lambda _b: self.repos.show_packages(self._selected_id()))
        self.remove_btn = Gtk.Button(child=Adw.ButtonContent(label=_("Remove…"), icon_name="user-trash-symbolic"))
        self.remove_btn.connect("clicked", lambda _b: self.repos.remove(self._selected_id()))
        row.append(self.packages_btn)
        row.append(self.remove_btn)
        body.append(row)
        self.summary = Gtk.Label(xalign=0)
        body.append(self.summary)

        self._menu_repo: str | None = None
        group = Gio.SimpleActionGroup()
        for name, fn in (("show", lambda: self.repos.show_packages(self._menu_repo)),
                         ("remove", lambda: self.repos.remove(self._menu_repo)),
                         ("copy", lambda: self.ui.copy_text(self.repos.repos[self._menu_repo].file_path)),
                         ("reveal", lambda: self.ui.show_in_file_manager(self.repos.repos[self._menu_repo].file_path))):
            act = Gio.SimpleAction(name=name)
            act.connect("activate", lambda _a, _p, fn=fn: fn())
            group.add_action(act)
        self.menu_actions = group
        self.insert_action_group("repo", group)
        self._popover = Gtk.PopoverMenu(has_arrow=False)
        self._popover.set_parent(self.table)
        click = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        click.connect("pressed", self._pressed)
        self.table.add_controller(click)

        self.connect("closed", self._closed)
        self._update_buttons()

    def _columns(self) -> None:
        def add(title: str, setup: Callable[[], Gtk.Widget], bind: Callable[[Gtk.Widget, RepoLine], None],
                expand: bool = False, width: int = 0) -> None:
            factory = Gtk.SignalListItemFactory()
            factory.connect("setup", lambda _f, item: item.set_child(setup()))

            def on_bind(_f, item: Gtk.ListItem) -> None:
                bind(item.get_child(), item.get_item().data)
            factory.connect("bind", on_bind)
            col = Gtk.ColumnViewColumn(title=title, factory=factory, expand=expand, resizable=True)
            if width:
                col.set_fixed_width(width)
            self.table.append_column(col)

        def setup_check() -> Gtk.Widget:
            check = Gtk.CheckButton(halign=Gtk.Align.CENTER)
            check.connect("toggled", self._toggled)
            return check

        def bind_check(check: Gtk.CheckButton, line: RepoLine) -> None:
            check.repo_id = None  # no "toggled" from filling it
            check.set_active(self.repos.enabled[line.repo.id])
            check.repo_id = line.repo.id

        def text(get: Callable[[RepoLine], str], tip: bool = False):
            def bind(widget: Gtk.Label, line: RepoLine) -> None:
                value = get(line)
                widget.set_text(value)
                widget.set_tooltip_text(value if tip and value else None)
            return bind

        def bind_packages(widget: Gtk.Label, line: RepoLine) -> None:
            widget.set_text(line.packages)
            widget.set_tooltip_text(line.packages_tip or None)

        def setup_origin() -> Gtk.Widget:
            box = Gtk.Box(spacing=6)
            box.append(Gtk.Image())
            box.append(label())
            return box

        def bind_origin(box: Gtk.Box, line: RepoLine) -> None:
            icons.set_image(box.get_first_child(), line.origin_icon)
            box.get_last_child().set_text(line.origin)

        middle = Pango.EllipsizeMode.MIDDLE  # a long id or path keeps both its start and its end
        add(_("Enabled"), setup_check, bind_check)
        add(_("ID"), lambda: label(middle), text(lambda line: line.repo.id, tip=True), width=200)
        add(_("Name"), lambda: label(middle), text(lambda line: line.repo.name, tip=True), expand=True)
        add(_("Packages"), lambda: label(numeric=True), bind_packages)
        add(_("Priority"), lambda: label(numeric=True), text(lambda line: line.priority))
        add(_("Origin"), setup_origin, bind_origin)
        add(_("File"), lambda: label(middle), text(lambda line: line.repo.file_path, tip=True), width=300)

    def _matches(self, node: Node) -> bool:
        return matches(node.data.repo, self.filter.get_text(), self.show_aux.get_active())

    def _apply_filter(self) -> None:
        self._filter.changed(Gtk.FilterChange.DIFFERENT)
        self._update_buttons()

    def _toggled(self, check: Gtk.CheckButton) -> None:
        repo_id = getattr(check, "repo_id", None)
        if repo_id is not None:
            self.repos.set_enabled(repo_id, check.get_active())
            self._update_buttons()

    def _selected_id(self) -> str | None:
        node = self.selection.get_selected_item()
        return node.data.repo.id if node is not None else None

    def _pressed(self, _gesture: Gtk.GestureClick, _n: int, x: float, y: float) -> None:
        widget = self.table.pick(x, y, Gtk.PickFlags.DEFAULT)
        while widget is not None and widget is not self.table and widget.get_css_name() != "row":
            widget = widget.get_parent()
        if widget is not None and widget is not self.table:  # the row under the pointer, selected as a click would
            for i in range(self.selection.get_n_items()):
                if self._row_shows(widget, self.selection.get_item(i).data.repo.id):
                    self.selection.set_selected(i)
                    break
        if (repo_id := self._selected_id()) is not None:
            self.show_menu(repo_id, x, y)

    @staticmethod
    def _row_shows(row: Gtk.Widget, repo_id: str) -> bool:
        """Whether a row widget shows `repo_id`: its ID cell's label."""
        stack = [row]
        while stack:
            w = stack.pop()
            if isinstance(w, Gtk.Label) and w.get_text() == repo_id:
                return True
            child = w.get_first_child()
            while child is not None:
                stack.append(child)
                child = child.get_next_sibling()
        return False

    def menu_model(self, repo_id: str) -> Gio.Menu:
        self._menu_repo = repo_id
        self.menu_actions.lookup_action("show").set_enabled(self.repos.packages_blocker(repo_id) is None)
        self.menu_actions.lookup_action("remove").set_enabled(self.repos.removal_blocker(repo_id) is None)
        menu, main = Gio.Menu(), Gio.Menu()
        main.append(_("Show Packages"), "repo.show")
        main.append(_("Remove Repository…"), "repo.remove")
        menu.append_section(None, main)
        if self.repos.repos[repo_id].file_path:
            files = Gio.Menu()
            files.append(_("Copy Path"), "repo.copy")
            files.append(_("Show in File Manager"), "repo.reveal")
            menu.append_section(None, files)
        return menu

    def show_menu(self, repo_id: str, x: float, y: float) -> None:
        self._popover.set_menu_model(self.menu_model(repo_id))
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        self._popover.set_pointing_to(rect)
        self._popover.popup()

    # the choice the dialog closed with, for the main window
    show_repo = property(lambda self: self.repos.show_repo)
    remove_repos = property(lambda self: self.repos.remove_repos)

    def changes(self) -> dict[str, bool]:
        """Repo id -> new enabled state, only for repos the user toggled."""
        return self.repos.changes()

    def close_with_choice(self) -> None:
        GLib.idle_add(lambda: (self.close(), GLib.SOURCE_REMOVE)[1])  # after the question that chose closed

    def _apply(self, _button) -> None:
        if self.repos.changes():
            self._accepted = True
            self.close()

    def _closed(self, _dialog) -> None:
        self._popover.unparent()
        done, self._done = self._done, None
        if done is not None:
            done(self, self._accepted)

    def _update_buttons(self) -> None:
        self.apply_btn.set_sensitive(bool(self.repos.changes()))
        packages, remove = self.repos.actions(self._selected_id())
        for button, state in ((self.packages_btn, packages), (self.remove_btn, remove)):
            button.set_sensitive(state.enabled)
            button.set_tooltip_text(state.tooltip or None)
        self.summary.set_text(self.repos.summary())
