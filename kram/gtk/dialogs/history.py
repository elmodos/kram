"""File → Transaction History for GTK (kram.app.history): a window of its own, not modal: a package of a transaction
opens in the main window."""
import json
from collections.abc import Callable

from gi.repository import Adw, Gtk

from ...app.history import History, PackageLine, TransactionLine, UndoButton, failed_tip, undo_tip
from ...core.catalog import Catalog
from ...core.history import HistoryRow
from ...core.settings import store as settings
from ...core.worker import DnfWorker
from ...i18n import _
from .. import icons
from ..loop import GtkScheduler
from .common import Node, column, label, node_list, standard_button, text_cell

WINDOW_KEY = "gtk/history"  # {"width", "height", "split"}


def _icon_cell() -> Gtk.Widget:
    box = Gtk.Box(spacing=6)
    box.append(Gtk.Image())
    box.append(label())
    return box


class HistoryWindow(Adw.Window):
    """`on_show_package(key)`: open this name.arch in the main window. `on_undo(tid)`: mark the changes that undo
    the transaction with this id."""

    def __init__(self, dnf: DnfWorker, catalog: Catalog, parent: Gtk.Window):
        super().__init__(title=_("Transaction History"), transient_for=parent, modal=False, hide_on_close=True,
                         destroy_with_parent=True)
        self.on_show_package: Callable[[tuple[str, str]], None] = lambda key: None
        self.on_undo: Callable[[int], None] = lambda tid: None
        self.history = History(dnf, catalog, GtkScheduler(), self)
        self._hidden: set[int] = set()
        try:
            saved = json.loads(settings.get(WINDOW_KEY, "{}"))
        except (TypeError, ValueError):
            saved = {}
        self.set_default_size(saved.get("width", 1100), saved.get("height", 720))

        header = Adw.HeaderBar()
        self.undo = Gtk.Button(child=Adw.ButtonContent(label=_("Mark Changes to Undo"), icon_name="edit-undo-symbolic"),
                               tooltip_text=undo_tip())
        self.undo.connect("clicked", lambda _b: self.history.current is not None and self.on_undo(self.history.current))
        header.pack_start(self.undo)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_start=12, margin_end=12,
                       margin_top=6, margin_bottom=12)
        view = Adw.ToolbarView(content=body)
        view.add_top_bar(header)
        self.set_content(view)

        top = Gtk.Box(spacing=12)
        self.filter = Gtk.SearchEntry(placeholder_text=_("Filter by package name"), hexpand=True)
        self.filter.connect("search-changed", lambda e: self.history.set_filter(e.get_text()))
        top.append(self.filter)
        self.state = Gtk.Label()
        self.state.add_css_class("dim-label")
        top.append(self.state)
        body.append(top)

        self._filter = Gtk.CustomFilter.new(lambda node: node.data.id not in self._hidden)
        self._store = node_list([])
        self.selection = Gtk.SingleSelection(model=Gtk.FilterListModel(model=self._store, filter=self._filter),
                                             autoselect=False, can_unselect=True)
        self._selection_handler = self.selection.connect("selection-changed", self._selected)
        self.list = Gtk.ColumnView(model=self.selection)
        self.list.add_css_class("data-table")
        column(self.list, _("ID"), _icon_cell, self._bind_id, width=80)
        column(self.list, _("Date"), label, text_cell(lambda t: t.date), width=150)
        column(self.list, _("Changes"), label, text_cell(lambda t: t.changes), width=300)
        column(self.list, _("User"), label, text_cell(lambda t: t.user), width=100)
        column(self.list, _("Command"), label, text_cell(lambda t: t.command, lambda t: t.tooltip), expand=True)

        self.package_selection = Gtk.SingleSelection(model=node_list([]), autoselect=False, can_unselect=True)
        self.packages = Gtk.ColumnView(model=self.package_selection)
        self.packages.add_css_class("data-table")
        self.packages.set_tooltip_text(_("Double-click a package to close the history and show the package in the "
                                         "list"))
        self.packages.connect("activate", self._activated)
        column(self.packages, _("Action"), _icon_cell, self._bind_action, width=140)
        column(self.packages, _("Package"), _icon_cell, self._bind_package, width=300)
        column(self.packages, _("Version"), label, self._bold(lambda p: p.version), width=300)
        column(self.packages, _("Repository"), label, self._bold(lambda p: p.repo), width=200)
        column(self.packages, _("Reason"), label, self._bold(lambda p: p.reason), expand=True)

        self.splitter = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL,
                                  start_child=Gtk.ScrolledWindow(child=self.list),
                                  end_child=Gtk.ScrolledWindow(child=self.packages),
                                  position=saved.get("split", 400), vexpand=True)
        body.append(self.splitter)
        close = standard_button("_Close")
        close.connect("clicked", lambda _b: self.close())
        header.pack_end(close)
        header.set_show_end_title_buttons(False)
        self.connect("close-request", self._save)
        self.show_undo(self.history.undo_button())

    # ---------------------------------------------------------------- cells

    @staticmethod
    def _bind_id(box: Gtk.Box, node: Node) -> None:
        t: TransactionLine = node.data
        image, text = box.get_first_child(), box.get_last_child()
        text.set_text(str(t.id))
        image.set_from_icon_name("dialog-error-symbolic" if t.failed else None)
        image.set_visible(t.failed)
        box.set_tooltip_text(failed_tip() if t.failed else None)

    @staticmethod
    def _set_bold(widget: Gtk.Widget, bold: bool) -> None:
        (widget.add_css_class if bold else widget.remove_css_class)("heading")

    def _bold(self, get: Callable[[PackageLine], str]):
        def bind(widget: Gtk.Label, node: Node) -> None:
            widget.set_text(get(node.data))
            self._set_bold(widget, node.data.bold)
        return bind

    def _bind_icon_cell(self, box: Gtk.Box, line: PackageLine, text: str, with_icon: bool, tip: str) -> None:
        image, label_ = box.get_first_child(), box.get_last_child()
        label_.set_text(text)
        self._set_bold(label_, line.bold)
        icons.set_image(image, line.icon if with_icon else None)
        image.set_visible(with_icon and line.icon is not None)
        box.set_tooltip_text(tip or None)

    def _bind_action(self, box: Gtk.Box, node: Node) -> None:
        line: PackageLine = node.data
        self._bind_icon_cell(box, line, line.action, line.key is not None, "")

    def _bind_package(self, box: Gtk.Box, node: Node) -> None:
        line: PackageLine = node.data
        self._bind_icon_cell(box, line, line.package, line.key is None, line.tooltip)

    # ---------------------------------------------------------------- the owner's calls

    def reload(self) -> None:
        """Read the transactions again (after a change was applied, or the first time)."""
        self.history.reload()

    def rows_of(self, tid: int) -> list[HistoryRow] | None:
        return self.history.rows_of(tid)

    def show_package_name(self, name: str) -> None:
        """Filter the list by a package's name (Package → Show in History)."""
        self.filter.set_text(name)
        self.history.set_filter(name)  # at once, not after the entry's delay

    def set_marking(self, can_mark: bool, busy: bool) -> None:
        self.history.set_marking(can_mark, busy)

    def _selected(self, *_args) -> None:
        node = self.selection.get_selected_item()
        self.history.current_changed(node.data.id if node is not None else None)

    def _activated(self, _view, position: int) -> None:
        key = self.package_selection.get_item(position).data.key
        if key is not None:  # a group or environment is not a package the list can show
            self.on_show_package(key)

    def _save(self, _window) -> bool:
        width, height = self.get_default_size()
        settings.set(WINDOW_KEY, json.dumps({"width": width, "height": height,
                                             "split": self.splitter.get_position()}))
        return False

    # ---------------------------------------------------------------- HistoryView

    def show_transactions(self, lines: list[TransactionLine]) -> None:
        with self.selection.handler_block(self._selection_handler):
            self._store.splice(0, self._store.get_n_items(), [Node(t) for t in lines])
            self.selection.set_selected(Gtk.INVALID_LIST_POSITION)

    def set_changes(self, tid: int, text: str) -> None:
        for i in range(self._store.get_n_items()):
            node = self._store.get_item(i)
            if node.data.id == tid:
                old = node.data
                line = TransactionLine(old.id, old.date, text, old.user, old.command, old.tooltip, old.failed)
                with self.selection.handler_block(self._selection_handler):  # the same row stays the current one
                    self._store.splice(i, 1, [Node(line)])  # a new item: GTK does not bind the same one again
                    self._select(self.history.current)
                return

    def _select(self, tid: int | None) -> None:
        for i in range(self.selection.get_n_items()):
            if self.selection.get_item(i).data.id == tid:
                self.selection.set_selected(i)
                return
        self.selection.set_selected(Gtk.INVALID_LIST_POSITION)

    def set_current(self, tid: int | None) -> None:
        """As a click would: the logic hears of it."""
        self._select(tid)

    def show_packages(self, lines: list[PackageLine]) -> None:
        self.package_selection.set_model(node_list(lines))
        self.package_selection.set_selected(Gtk.INVALID_LIST_POSITION)

    def set_hidden(self, hidden: set[int]) -> None:
        self._hidden = set(hidden)
        with self.selection.handler_block(self._selection_handler):  # a hidden current one stays current
            self._filter.changed(Gtk.FilterChange.DIFFERENT)
            self._select(self.history.current)

    def show_state(self, text: str) -> None:
        self.state.set_text(text)

    def show_undo(self, button: UndoButton) -> None:
        self.undo.set_sensitive(button.enabled)
        self.undo.get_child().set_label(button.text)
        self.undo.set_tooltip_text(button.tooltip or None)
