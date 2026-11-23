"""Repositories → Mirrors… for GTK (kram.app.mirrors): the mirrors of one repository with a speed test; choose one to pin
the repository to it, or go back to letting libdnf5 choose."""
from collections.abc import Callable

from gi.repository import Adw, Gio, Gtk, Pango

from ...app.mirrors import MirrorLine, Mirrors, dialog_title
from ...core.mirrors import MirrorSource
from ...core.model import RepoInfo
from ...i18n import _
from ..loop import post
from ..ui_port import GtkUi
from .common import Node, column, frame, label, standard_button, text_cell, wrapped


class MirrorsDialog(Adw.Dialog):
    def __init__(self, repo: RepoInfo, source: MirrorSource, fastestmirror: bool,
                 done: Callable[["MirrorsDialog"], None], *, on_choice=None, **network):
        """`on_choice(choice)` applies a choice while the dialog stays open; `set_state` then shows the new state.
        `done(dialog)` once it closes. `network` replaces the fetching and the speed test, for the tests (see
        kram.app.mirrors.Mirrors)."""
        super().__init__(title=dialog_title(repo), content_width=900, content_height=540)
        self.mirrors = Mirrors(repo.id, source, fastestmirror, self, GtkUi(self), post, on_choice=on_choice,
                               **network)
        self._done = done
        header, body = frame(self)
        close = standard_button("_Close")
        close.connect("clicked", lambda _b: self.close())
        header.pack_start(close)

        self.status = wrapped()
        body.append(self.status)
        self.store = Gio.ListStore(item_type=Node)
        self.selection = Gtk.SingleSelection(model=self.store, autoselect=False, can_unselect=True)
        self.selection.connect("selection-changed", lambda *_a: self._update_buttons())
        self.table = Gtk.ColumnView(model=self.selection)
        self.table.add_css_class("data-table")
        self.table.connect("activate", lambda _t, _i: self.mirrors.use(self._selected_url()))
        def bind_mirror(widget: Gtk.Label, node: Node) -> None:
            widget.set_text(node.data.name)
            widget.set_tooltip_text(node.data.mirror.url)
            (widget.add_css_class if node.data.current else widget.remove_css_class)("heading")  # bold: in use

        column(self.table, _("Mirror"), lambda: label(Pango.EllipsizeMode.MIDDLE), bind_mirror, expand=True)
        column(self.table, _("Country"), label, text_cell(lambda ln: ln.country), width=80)
        column(self.table, _("Protocol"), label, text_cell(lambda ln: ln.protocol), width=80)
        column(self.table, _("Response"), lambda: label(numeric=True), text_cell(lambda ln: ln.response), width=100)
        column(self.table, _("Speed"), lambda: label(numeric=True), text_cell(lambda ln: ln.speed), width=110)
        column(self.table, _("Note"), label, text_cell(lambda ln: ln.note, lambda ln: ln.note), width=200)
        body.append(Gtk.ScrolledWindow(child=self.table, vexpand=True))

        row = Gtk.Box(spacing=6)
        self.test_btn = Gtk.Button(child=Adw.ButtonContent(label=_("Test Speed"), icon_name="media-playback-start-symbolic"))
        self.test_btn.connect("clicked", lambda _b: self.mirrors.toggle_test())
        self.use_btn = Gtk.Button(child=Adw.ButtonContent(label=_("Use Selected Mirror"), icon_name="emblem-ok-symbolic"))
        self.use_btn.connect("clicked", lambda _b: self.mirrors.use(self._selected_url()))
        self.automatic_btn = Gtk.Button(child=Adw.ButtonContent(label=_("Automatic"), icon_name="view-refresh-symbolic"))
        self.automatic_btn.connect("clicked", lambda _b: self.mirrors.use_automatic())
        for b in (self.test_btn, self.use_btn, self.automatic_btn):
            row.append(b)
        body.append(row)

        fastest = Gtk.Box(spacing=12)
        self.fastest_label = wrapped()
        self.fastest_label.set_hexpand(True)
        self.fastest_btn = Gtk.Button()
        self.fastest_btn.connect("clicked", lambda _b: self.mirrors.toggle_fastest())
        fastest.append(self.fastest_label)
        fastest.append(self.fastest_btn)
        body.append(fastest)

        self.connect("closed", self._closed)
        self.mirrors.start()
        self._update_buttons()

    choice = property(lambda self: self.mirrors.choice)  # the choice being applied, until set_state

    def set_state(self, source: MirrorSource, fastestmirror: bool) -> None:
        """What is configured now: after a choice was applied, the dialog shows it."""
        self.mirrors.update(source, fastestmirror)
        self._update_buttons()

    # ---------------------------------------------------------------- MirrorsView

    def show_lines(self, lines: list[MirrorLine]) -> None:
        selected = self._selected_url()
        self.store.splice(0, self.store.get_n_items(), [Node(ln) for ln in lines])
        self.selection.set_selected(Gtk.INVALID_LIST_POSITION)
        for i, ln in enumerate(lines):
            if ln.mirror.url == selected:
                self.selection.set_selected(i)
                break
        self._update_buttons()

    def show_status(self, text: str) -> None:
        self.status.set_text(text)

    def set_testing(self, on: bool) -> None:
        self.test_btn.set_child(Adw.ButtonContent(
            label=_("Stop Test") if on else _("Test Speed"),
            icon_name="media-playback-stop-symbolic" if on else "media-playback-start-symbolic"))
        self._update_buttons()

    def show_fastest(self, text: str, button: str) -> None:
        self.fastest_label.set_text(text)
        self.fastest_btn.set_label(button)

    # ---------------------------------------------------------------- the buttons

    def _selected_url(self) -> str | None:
        node = self.selection.get_selected_item()
        return node.data.mirror.url if node is not None else None

    def _update_buttons(self) -> None:
        state = self.mirrors.buttons(self._selected_url())
        self.test_btn.set_sensitive(state.test or self.mirrors.testing)
        for button, action in ((self.use_btn, state.use), (self.automatic_btn, state.automatic)):
            button.set_sensitive(action.enabled)
            button.set_tooltip_text(action.tooltip or None)

    def _closed(self, _dialog) -> None:
        self.mirrors.close()  # a test that is still running stops with the dialog
        done, self._done = self._done, None
        if done is not None:
            done(self)
