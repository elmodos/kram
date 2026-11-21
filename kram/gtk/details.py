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
from .doc_view import CHUNK, DocView

TAB_ICONS = {"description": "text-x-generic-symbolic", "general": "dialog-information-symbolic",
             "advisories": "security-medium-symbolic", "dependencies": "network-workgroup-symbolic",
             "files": "folder-symbolic", "versions": "view-list-symbolic", "changelog": "document-edit-symbolic"}


def _scrolled(child: Gtk.Widget) -> Gtk.ScrolledWindow:
    return Gtk.ScrolledWindow(child=child, vexpand=True)


class DetailsView(Gtk.Box):
    """`on_link(kind, target)`: a package or dependency link was clicked ("pkg" / "dep"); web links go to
    `on_web(url)`."""

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.on_link: Callable[[str, str], None] = lambda kind, target: None
        self.on_web: Callable[[str], None] = lambda url: None
        self.stack = Adw.ViewStack(vexpand=True)
        self.docs: dict[str, DocView] = {}
        self.pages: dict[str, Adw.ViewStackPage] = {}
        titles = tab_titles()
        self.files = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_start=12, margin_end=12, margin_top=12,
                             margin_bottom=12)
        self.versions = Gtk.Grid(column_spacing=24, row_spacing=4, margin_start=12, margin_end=12, margin_top=12,
                                 margin_bottom=12)
        for name in TABS:
            if name == "files":
                child = self.files
            elif name == "versions":
                child = self.versions
            else:
                child = self.docs[name] = DocView()
                child.on_link = self._link
            self.pages[name] = self.stack.add_titled_with_icon(_scrolled(child), name, titles[name], TAB_ICONS[name])
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

    # ---------------------------------------------------------------- files and versions (to become their own
    # widgets: a tree with a filter and a context menu, and a small column view)

    def _set_files(self, files, complete: bool) -> None:
        while (child := self.files.get_first_child()) is not None:
            self.files.remove(child)
        paths = list(files)
        for start in range(0, len(paths), CHUNK):
            label = Gtk.Label(label="\n".join(paths[start:start + CHUNK]), xalign=0, selectable=True)
            label.add_css_class("monospace")
            self.files.append(label)

    def _set_versions(self, rows) -> None:
        while (child := self.versions.get_first_child()) is not None:
            self.versions.remove(child)
        for y, v in enumerate(rows):
            for x, text in enumerate((v.evr, v.repo, v.state)):
                label = Gtk.Label(label=text, xalign=0, selectable=True, ellipsize=Pango.EllipsizeMode.END)
                if v.bold:
                    label.add_css_class("kram-bold")
                if v.dimmed:
                    label.add_css_class("dim-label")
                self.versions.attach(label, x, y, 1, 1)
