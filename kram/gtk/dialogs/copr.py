"""Settings → COPR for GTK (kram.app.copr): the enabled projects, and search/enable new ones via the Copr API."""
from collections import Counter
from collections.abc import Callable

from gi.repository import Adw, Gtk

from ...app.copr import CoprProjects, EnabledProject, ResultLine
from ...core.copr import CoprProject
from ...core.model import CatalogSnapshot
from ...i18n import _
from ..loop import post
from ..ui_port import GtkUi
from .common import column, frame, label, node_list, standard_button, text_cell


def _heading(text: str) -> Gtk.Label:
    widget = Gtk.Label(label=text, xalign=0)
    widget.add_css_class("heading")
    return widget


def _button(text: str, icon: str) -> Gtk.Button:
    return Gtk.Button(child=Adw.ButtonContent(label=text, icon_name=icon))


class CoprDialog(Adw.Dialog):
    def __init__(self, run_helper: Callable[[dict, str], object], show_packages: Callable[[str], None]):
        """`run_helper(request, title)` runs a helper request with a progress dialog (and reloads after it);
        `show_packages(repo id)` shows a repository's packages in the main window, after this dialog closed."""
        super().__init__(title=_("COPR repositories"), content_width=940, content_height=680)
        self._show_packages = show_packages
        self.copr = CoprProjects(self, GtkUi(self), post, run_helper, self._packages_chosen)
        header, body = frame(self)
        close = standard_button("_Close")
        close.connect("clicked", lambda _b: self.close())
        header.pack_start(close)
        self.add_btn = Gtk.Button(child=Adw.ButtonContent(label=_("Enable selected"), icon_name="list-add-symbolic"))
        self.add_btn.add_css_class("suggested-action")
        self.add_btn.connect("clicked", lambda _b: self._enable())
        header.pack_end(self.add_btn)

        body.append(_heading(_("Enabled projects")))
        self.enabled_selection = Gtk.SingleSelection(model=node_list([]), autoselect=False, can_unselect=True)
        self.enabled_selection.connect("selection-changed", lambda *_a: self._update_buttons())
        t = self.enabled_table = Gtk.ColumnView(model=self.enabled_selection)
        t.add_css_class("data-table")
        column(t, _("Enabled"), lambda: Gtk.Label(), text_cell(lambda p: "✓" if p.enabled else ""), width=80)
        column(t, _("Project"), label, text_cell(lambda p: p.project), expand=True)
        column(t, _("Hub"), label, text_cell(lambda p: p.hub), width=220)
        column(t, _("Packages"), lambda: label(numeric=True), text_cell(lambda p: p.packages), width=90)
        column(t, _("Installed"), lambda: label(numeric=True), text_cell(lambda p: p.installed), width=90)
        scroller = Gtk.ScrolledWindow(child=t, min_content_height=150, max_content_height=200,
                                      propagate_natural_height=True)
        body.append(scroller)

        row = Gtk.Box(spacing=6)
        self.enable_btn = _button(_("Enable"), "object-select-symbolic")
        self.disable_btn = _button(_("Disable"), "process-stop-symbolic")
        self.remove_btn = _button(_("Remove…"), "user-trash-symbolic")
        self.packages_btn = _button(_("Show packages"), "view-list-symbolic")
        self.enable_btn.connect("clicked", lambda _b: self._with_project(lambda p: self.copr.change(p, "enable")))
        self.disable_btn.connect("clicked", lambda _b: self._with_project(lambda p: self.copr.change(p, "disable")))
        self.remove_btn.connect("clicked", lambda _b: self._with_project(self.copr.remove))
        self.packages_btn.connect("clicked", lambda _b: self._with_project(self.copr.show_packages))
        for b in (self.enable_btn, self.disable_btn, self.remove_btn, self.packages_btn):
            row.append(b)
        body.append(row)

        add = _heading(_("Add a project"))
        add.set_margin_top(10)
        body.append(add)
        row = Gtk.Box(spacing=6)
        self.query = Gtk.SearchEntry(placeholder_text=_("owner/project, or words to search for"), hexpand=True)
        self.query.connect("activate", lambda _e: self.copr.search(self.query.get_text()))
        self.query.connect("search-changed", lambda _e: self._update_buttons())
        row.append(self.query)
        self.search_btn = _button(_("Search Copr"), "edit-find-symbolic")
        self.search_btn.connect("clicked", lambda _b: self.copr.search(self.query.get_text()))
        row.append(self.search_btn)
        body.append(row)

        self.results_selection = Gtk.SingleSelection(model=node_list([]), autoselect=False, can_unselect=True)
        self.results_selection.connect("selection-changed", lambda *_a: self._update_buttons())
        r = self.results_table = Gtk.ColumnView(model=self.results_selection)
        r.add_css_class("data-table")
        r.connect("activate", lambda _v, _pos: self._enable())
        column(r, _("Project"), label, text_cell(lambda line: line.name), width=260)
        column(r, _("Description"), label, text_cell(lambda line: line.description, lambda line: line.tooltip),
               expand=True)
        column(r, _("Builds for this system"), label, self._bind_builds, width=180)
        body.append(Gtk.ScrolledWindow(child=r, vexpand=True))

        self.search_status = Gtk.Label(xalign=0)
        body.append(self.search_status)
        note = Gtk.Label(label="ⓘ " + _("COPR projects are built by community members and are not reviewed by "
                                         "Fedora."), xalign=0, wrap=True)
        note.add_css_class("dim-label")
        body.append(note)

        self.connect("closed", lambda _d: self.copr.close())  # results that arrive later are dropped
        self._update_buttons()

    @staticmethod
    def _bind_builds(widget: Gtk.Label, node) -> None:
        line: ResultLine = node.data
        widget.set_text(line.builds)
        widget.set_tooltip_text(line.builds_tip or None)
        if line.builds_ok:
            widget.remove_css_class("error")
        else:
            widget.add_css_class("error")

    def set_catalog(self, snap: CatalogSnapshot, counts: Counter) -> None:
        self.copr.set_catalog(snap, counts)

    def _packages_chosen(self, repo_id: str) -> None:
        self.close()
        self._show_packages(repo_id)

    def _selected_project(self) -> EnabledProject | None:
        node = self.enabled_selection.get_selected_item()
        return node.data if node is not None else None

    def _with_project(self, fn: Callable[[EnabledProject], None]) -> None:
        if (project := self._selected_project()) is not None:
            fn(project)

    def _selected_result(self) -> CoprProject | None:
        node = self.results_selection.get_selected_item()
        return node.data.project if node is not None else None

    def _enable(self) -> None:
        self.copr.enable(self._selected_result(), self.query.get_text())

    def _update_buttons(self) -> None:
        b = self.copr.buttons(self._selected_project(), self._selected_result(), self.query.get_text())
        self.enable_btn.set_sensitive(b.enable)
        self.disable_btn.set_sensitive(b.disable)
        self.remove_btn.set_sensitive(b.remove)
        self.packages_btn.set_sensitive(b.packages)
        self.add_btn.set_sensitive(b.add)

    # ---------------------------------------------------------------- CoprView

    def show_projects(self, projects: list[EnabledProject]) -> None:
        selected = self._selected_project()
        self.enabled_selection.set_model(node_list(projects))
        self.enabled_selection.set_selected(Gtk.INVALID_LIST_POSITION)
        if selected is not None:  # the same project after a reload
            for i, p in enumerate(projects):
                if p.repo_id == selected.repo_id:
                    self.enabled_selection.set_selected(i)
        self._update_buttons()

    def show_results(self, results: list[ResultLine]) -> None:
        self.results_selection.set_model(node_list(results))
        self.results_selection.set_selected(Gtk.INVALID_LIST_POSITION)
        self._update_buttons()

    def show_search_status(self, text: str) -> None:
        self.search_status.set_text(text)

    def set_searching(self, on: bool) -> None:
        self.search_btn.set_sensitive(not on)

    def select_first_result(self) -> None:
        if self.results_selection.get_n_items():
            self.results_selection.set_selected(0)
