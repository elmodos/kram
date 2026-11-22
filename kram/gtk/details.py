"""The detail tabs for GTK: an Adw.ViewSwitcher over an Adw.ViewStack; what each tab says is kram.app.details, shown
as docs (kram.gtk.doc_view). Implements kram.app.details.DetailsSink, as kram.qt.details.DetailsTabs does."""
from collections.abc import Callable

from gi.repository import Adw, Gtk, Pango

from ..app.columns import blocked_tip
from ..app.details import (
    TABS,
    TabChoice,
    advisories_doc,
    advisories_tab_tip,
    blocked_doc,
    changelog_doc,
    dependencies_doc,
    description_doc,
    general_doc,
    tab_titles,
    version_rows,
)
from ..app.doc import Doc
from ..core.model import PkgDetails, PkgRow
from ..i18n import _
from .dialogs.common import column, node_list
from .doc_view import DocView
from .files import FileList

TAB_ICONS = {"description": "text-x-generic-symbolic", "general": "dialog-information-symbolic",
             "advisories": "security-medium-symbolic", "dependencies": "network-workgroup-symbolic",
             "files": "folder-symbolic", "versions": "view-list-symbolic", "changelog": "document-edit-symbolic"}


def _scrolled(child: Gtk.Widget) -> Gtk.ScrolledWindow:
    return Gtk.ScrolledWindow(child=child, vexpand=True)


class DetailsView(Gtk.Box):
    """`on_link(kind, target)`: a package or dependency link was clicked ("pkg" / "dep"); web links go to
    `on_web(url)`."""

    def __init__(self, ui=None):
        """`ui` (kram.app.ports.Ui): the Files tab copies paths and shows files with it."""
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.on_link: Callable[[str, str], None] = lambda kind, target: None
        self.on_web: Callable[[str], None] = lambda url: None
        self.stack = Adw.ViewStack(vexpand=True)
        self.docs: dict[str, DocView] = {}
        self.pages: dict[str, Adw.ViewStackPage] = {}
        titles = tab_titles()
        self.files = FileList(ui)
        self.versions = self._versions_view()
        for name in TABS:
            if name == "files":
                child = self.files
            elif name == "versions":
                child = _scrolled(self.versions)
            else:
                view = self.docs[name] = DocView()
                view.on_link = self._link
                child = _scrolled(view)
            self.pages[name] = self.stack.add_titled_with_icon(child, name, titles[name], TAB_ICONS[name])
        self.pages["advisories"].set_visible(False)
        switcher = Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE, halign=Gtk.Align.START)
        self.append(switcher)
        self.append(Gtk.Separator())
        self.append(self.stack)
        self._blocked = Doc()
        self._deps_body = Doc()
        self._choice = TabChoice()
        self._switching = False
        self.stack.connect("notify::visible-child-name", self._on_current_changed)

    def _link(self, kind: str, target: str) -> None:
        if kind in ("pkg", "dep"):
            self.on_link(kind, target)
        elif kind == "web":
            self.on_web(target)

    # ---------------------------------------------------------------- the tab

    def _on_current_changed(self, *_args) -> None:
        if not self._switching and (name := self.stack.get_visible_child_name()):
            self._choice.user_selected(name)

    def current_name(self) -> str:
        return self._choice.saved_name(self.stack.get_visible_child_name() or "description")

    def select_name(self, name: str) -> None:
        shown = self.pages["advisories"].get_visible()
        if (name := self._choice.to_select(name, shown)) is not None:
            self.stack.set_visible_child_name(name)

    # ---------------------------------------------------------------- DetailsSink

    def show_advisories(self, row: PkgRow | None) -> None:
        page = self.pages["advisories"]
        self._switching = True
        try:
            if row is None or not advisories_doc(row):
                if self.stack.get_visible_child_name() == "advisories":
                    self.stack.set_visible_child_name(self._choice.instead_of_advisories())
                page.set_visible(False)
                self.docs["advisories"].set_doc(Doc())
                return
            # libadwaita's tabs take theme icons only: the advisory's colour dot becomes the attention dot
            page.set_needs_attention(True)
            page.get_child().set_tooltip_text(advisories_tab_tip(row))
            self.docs["advisories"].set_doc(advisories_doc(row))
            page.set_visible(True)
            if self._choice.wants_advisories:
                self.stack.set_visible_child_name("advisories")
        finally:
            self._switching = False

    def show_blocked(self, reason: str | None) -> None:
        blocked = reason is not None
        page = self.pages["dependencies"]
        page.set_needs_attention(blocked)
        page.get_child().set_tooltip_text(blocked_tip(reason) if blocked else None)
        self._blocked = blocked_doc(reason) if blocked else Doc()
        self.docs["dependencies"].set_doc(self._blocked + self._deps_body)

    def clear(self) -> None:
        for name in ("description", "general", "changelog"):
            self.docs[name].set_doc(Doc())
        self._deps_body = Doc()
        self.show_blocked(None)
        self._set_files([], True)
        self._set_versions([])
        self.show_advisories(None)

    def show_package(self, row: PkgRow, d: PkgDetails) -> None:
        self.docs["description"].set_doc(description_doc(d))
        self.docs["general"].set_doc(general_doc(row, d))
        self._deps_body = dependencies_doc(d)
        self.docs["dependencies"].set_doc(self._blocked + self._deps_body)
        self._set_files(d.files, d.files_complete)
        self._set_versions(version_rows(d))
        self.docs["changelog"].set_doc(changelog_doc(d))

    # ---------------------------------------------------------------- files and versions

    def _set_files(self, files, complete: bool) -> None:
        self.files.set_files(list(files), complete)

    @staticmethod
    def _versions_view() -> Gtk.ColumnView:
        view = Gtk.ColumnView(model=Gtk.NoSelection(model=node_list([])))
        view.add_css_class("data-table")

        def cell(title: str, get, width: int = 0, expand: bool = False):
            def bind(widget: Gtk.Label, node) -> None:
                v = node.data
                widget.set_text(get(v))
                (widget.add_css_class if v.bold else widget.remove_css_class)("kram-bold")
                (widget.add_css_class if v.dimmed else widget.remove_css_class)("dim-label")
            column(view, title, lambda: Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END), bind,
                   expand=expand, width=width)
        cell(_("Version"), lambda v: v.evr, width=260)
        cell(_("Repository"), lambda v: v.repo, width=360)
        cell(_("State"), lambda v: v.state, expand=True)
        return view

    def _set_versions(self, rows) -> None:
        self.versions.get_model().set_model(node_list(rows))
