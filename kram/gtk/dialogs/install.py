"""Installing one package file for GTK, gdebi-style (kram.app.install): what it is, what installing it changes, and
the button that does it.

Self-contained (it gets the catalog, its dnf thread and the helper client), so it also works without the main
window (`kram file.rpm`): `InstallPage` is the content, shown in an `InstallDialog` over the main window or in an
`InstallWindow` of its own. Marks in the main window are not part of it."""
from collections.abc import Callable

from gi.repository import Adw, GLib, Gtk

from ...app.apply_review import ChangeSection, RecRow
from ...app.doc import Doc, Span
from ...app.icons import STATE_ICONS
from ...app.install import INDENT, Install, InstallButton, Note
from ...app.progress import BUSY
from ...core.worker import DnfWorker
from ...i18n import _
from .. import icons
from ..doc_view import DocView, spans_markup
from ..loop import post
from ..ui_port import GtkUi
from .apply import ChangesTree, RecommendationsList
from .common import standard_button, text_view, wrapped
from .progress import ProgressDialog


def _doc_page() -> tuple[Gtk.ScrolledWindow, DocView]:
    view = DocView()
    return Gtk.ScrolledWindow(child=view, hscrollbar_policy=Gtk.PolicyType.NEVER), view


class InstallPage(Gtk.Box):
    """`close()` closes whatever shows the page; `in_window`: the page is a window's content (title buttons)."""

    def __init__(self, path: str, catalog, dnf: DnfWorker, helper, close: Callable[[], None],
                 basearch: str = "x86_64", marks: int = 0, load_catalog: bool = False, in_window: bool = False):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        toolbar = Adw.ToolbarView(vexpand=True)  # final: held, not subclassed
        self.append(toolbar)
        self.helper = helper
        self._close = close
        self._started = False
        self.ui = GtkUi(None)
        self.install_logic = Install(path, catalog, dnf, post, self, busy=lambda: helper.busy, basearch=basearch,
                                     marks=marks, load_catalog=load_catalog)
        header = Adw.HeaderBar(show_start_title_buttons=in_window, show_end_title_buttons=in_window,
                               title_widget=Adw.WindowTitle(title=_("Install Package File")))
        if not in_window:
            cancel = standard_button("_Close")
            cancel.connect("clicked", lambda _b: self._close())
            header.pack_start(cancel)
        self.install = Gtk.Button(child=Adw.ButtonContent(label=_("Install"), icon_name="list-add-symbolic"))
        self.install.add_css_class("suggested-action")
        self.install.connect("clicked", lambda _b: self.install_logic.install())
        header.pack_end(self.install)
        toolbar.add_top_bar(header)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_start=12, margin_end=12,
                       margin_top=6, margin_bottom=12)
        toolbar.set_content(body)
        head = Gtk.Box(spacing=12)
        file_icon = Gtk.Image(icon_name=icons.first_themed(("application-x-rpm", "package-x-generic")) or "",
                              pixel_size=48, valign=Gtk.Align.START)
        head.append(file_icon)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        self.title = Gtk.Label(xalign=0, wrap=True, selectable=True)  # a long name must not widen the dialog
        self.title.add_css_class("title-2")
        self.subtitle = Gtk.Label(xalign=0, wrap=True, selectable=True)
        self.notes = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        for w in (self.title, self.subtitle, self.notes):
            text.append(w)
        head.append(text)
        body.append(head)

        self.stack = Adw.ViewStack(vexpand=True)
        desc_page, self.desc = _doc_page()
        details_page, self.details = _doc_page()
        self.changes = ChangesTree()
        deps_page, self.deps = _doc_page()
        changes_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        changes_title = Gtk.Label(label=_("What installing it changes"), xalign=0)
        changes_title.add_css_class("heading")
        changes_box.append(changes_title)
        changes_box.append(self.changes)
        deps = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL, start_child=changes_box, end_child=deps_page,
                         shrink_start_child=False, shrink_end_child=False, position=260)
        files_page, self.files = text_view()
        changelog_page, self.changelog = _doc_page()
        scripts_page, self.scripts = text_view()
        for name, widget, title, icon in [
                ("description", desc_page, _("Description"), "text-x-generic-symbolic"),
                ("details", details_page, _("Details"), "dialog-information-symbolic"),
                ("dependencies", deps, _("Dependencies"), "network-workgroup-symbolic"),
                ("files", files_page, _("Files"), "folder-symbolic"),
                ("changelog", changelog_page, _("Changelog"), "document-edit-symbolic"),
                ("scripts", scripts_page, _("Scripts"), "utilities-terminal-symbolic")]:
            self.stack.add_titled_with_icon(widget, name, title, icon)
        for doc in (self.desc, self.details, self.deps, self.changelog):
            doc.on_link = lambda kind, target: kind == "web" and self.ui.open_web_link(target)
        tabs = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        tabs.append(Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE))
        tabs.append(self.stack)

        self.recs = RecommendationsList(self.install_logic.recs)
        self.recs.on_toggled = self.install_logic.recs_changed
        self.recs.set_visible(False)
        split = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL, start_child=tabs, end_child=self.recs,
                          shrink_start_child=False, shrink_end_child=False, vexpand=True, position=420)
        body.append(split)

        self.sizes = wrapped()
        body.append(self.sizes)
        self.warning = wrapped("error")
        self.warning.set_visible(False)
        body.append(self.warning)
        self.cmd_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, visible=False)
        cmd_title = Gtk.Label(label=_("Equivalent command"), xalign=0)
        cmd_title.add_css_class("heading")
        self.cmd = Gtk.Entry(editable=False)
        self.cmd.add_css_class("monospace")
        self.cmd_box.append(cmd_title)
        self.cmd_box.append(self.cmd)
        body.append(self.cmd_box)
        self.status = Gtk.Label(xalign=0)  # what runs now; the buttons wait for it
        self.status.add_css_class("dim-label")
        body.append(self.status)

    def start(self) -> None:
        """Once shown: the questions and messages belong to the window it is in."""
        if self._started:
            return
        self._started = True
        self.ui = GtkUi(self.get_root())
        self.install_logic.start()

    # the logic's state, for the window and the tests
    @property
    def rpm(self):
        return self.install_logic.rpm

    @property
    def changed_system(self) -> bool:
        return self.install_logic.changed_system

    def notes_text(self) -> str:
        """The header's lines as plain text (for tests)."""
        out = []
        row = self.notes.get_first_child()
        while row is not None:
            out.append(row.get_last_child().get_text())
            row = row.get_next_sibling()
        return "\n".join(out)

    def closed(self) -> None:
        self.install_logic.close()

    # ---------------------------------------------------------------- InstallView

    def show_title(self, name: str, version: str, summary: str) -> None:
        e = GLib.markup_escape_text
        self.title.set_markup(f"{e(name)} <span weight='normal'>{e(version)}</span>" if version else e(name))
        self.subtitle.set_text(summary)

    def show_notes(self, notes: list[Note]) -> None:
        while (child := self.notes.get_first_child()) is not None:
            self.notes.remove(child)
        for n in notes:
            row = Gtk.Box(spacing=6)
            mark = Gtk.Image(pixel_size=16, valign=Gtk.Align.START)
            mark.set_size_request(16, -1)
            if n.kind != INDENT:
                icons.set_image(mark, STATE_ICONS[n.kind])
            label = Gtk.Label(xalign=0, wrap=True, selectable=True, hexpand=True)
            label.set_markup(spans_markup(n.spans))
            row.append(mark)
            row.append(label)
            self.notes.append(row)

    def show_sizes(self, spans: list[Span]) -> None:
        self.sizes.set_markup(spans_markup(spans))
        self.sizes.set_visible(bool(spans))

    def show_warning(self, text: str) -> None:
        self.warning.set_markup(f"<b>{GLib.markup_escape_text(text)}</b>" if text else "")
        self.warning.set_visible(bool(text))

    def show_command(self, text: str | None) -> None:
        self.cmd_box.set_visible(text is not None)
        if text is not None:
            self.cmd.set_text(text)

    def show_button(self, button: InstallButton) -> None:
        content = self.install.get_child()
        content.set_label(button.text)
        content.set_icon_name(icons.first_themed((button.icon,)) or button.icon)
        self.install.set_visible(button.visible)
        self.install.set_sensitive(button.enabled)

    def show_status(self, text: str) -> None:
        self.status.set_text(text)

    def show_file(self, description: Doc, details: Doc, changelog: Doc, scripts: str) -> None:
        self.desc.set_doc(description)
        self.details.set_doc(details)
        self.changelog.set_doc(changelog)
        self.scripts.get_buffer().set_text(scripts)

    def show_deps(self, doc: Doc) -> None:
        self.deps.set_doc(doc)

    def show_files(self, text: str) -> None:
        self.files.get_buffer().set_text(text)

    def show_changes(self, sections: list[ChangeSection], problems: list[str]) -> None:
        self.changes.show_sections(sections, problems)

    def show_recs(self, rows: tuple[list[RecRow], list[RecRow]], visible: bool) -> None:
        self.recs.show_rows(*rows)
        self.recs.set_visible(visible)

    def set_recs_enabled(self, on: bool) -> None:
        self.recs.view.set_sensitive(on)

    def run_transaction(self, request: dict, title: str, done: Callable[[bool], None]) -> None:
        progress = ProgressDialog(self.helper, request, title, lambda ok, _result: done(ok))
        if not progress.start():
            self.ui.warn(title, _(BUSY))
            done(False)
            return
        progress.present(self)

    def close_installed(self) -> None:
        self._close()


class InstallDialog(Adw.Dialog):
    """Over the main window; `done(changed_system)` once it closes."""

    def __init__(self, path: str, catalog, dnf: DnfWorker, helper, basearch: str = "x86_64", marks: int = 0,
                 done: Callable[[bool], None] = lambda changed: None):
        super().__init__(title=_("Install Package File"), content_width=880, content_height=760)
        self._done = done
        self.page = InstallPage(path, catalog, dnf, helper, self.close, basearch, marks)
        self.set_child(self.page)
        self.connect("closed", self._closed)

    def present(self, parent: Gtk.Widget | None = None) -> None:
        Adw.Dialog.present(self, parent)
        self.page.start()

    def _closed(self, _dialog) -> None:
        self.page.closed()
        done, self._done = self._done, None
        if done is not None:
            done(self.page.changed_system)


class InstallWindow(Adw.ApplicationWindow):
    """`kram file.rpm`: the installer as the only window, loading the catalog itself."""

    def __init__(self, app: Adw.Application, path: str, catalog, dnf: DnfWorker, helper):
        super().__init__(application=app, title=_("Install Package File"), default_width=880, default_height=760,
                         icon_name=app.get_application_id())
        self.page = InstallPage(path, catalog, dnf, helper, self.close, load_catalog=True, in_window=True)
        self.set_content(self.page)
        self.connect("close-request", lambda _w: (self.page.closed(), False)[1])

    def present(self) -> None:
        Adw.ApplicationWindow.present(self)
        self.page.start()
