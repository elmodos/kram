"""The COPR dialog (docs/TUI_SPEC.md §10.6): the `CoprView` of kram.app.copr.CoprProjects, as kram.gtk.dialogs.copr
is.

"On this system": the COPR projects of the system's repositories in a table (kram.tui.table): whether the project is
on as `[x]`, its name, its packages and how many of them are installed; without any, a line says to search for one.
Under it the search line: `Enter` asks Copr for projects, its status line says how that went, and the results show
in a second table: the project, whether it builds for this system (`✓ fedora-45-x86_64` in the ok role, `✗` in the
danger role: the glyph says it without the colour, §9.5) and its description. A network error stays on the status
line with the key that tries again (`ctrl+r`).

The buttons are the GUIs': Packages, Disable (Enable for a project that is off) and Remove… act on the project
under the cursor of the top table; Enable selected (`ctrl+e`, as the GUIs call it) enables the result under the cursor, or the `owner/project`
typed in the line when that is what the line holds (it is not the search the results came from, and the results
table does not have the focus). The presenter asks before a removal (with Show packages when installed packages come
from the project) and before enabling a project with no build for this Fedora. A change runs over the dialog through
root and the progress dialog, then the catalog is read again and the window hands the dialog the new state
(`set_catalog`): it stays open. When Enable is off, the line under the results says why; it also says what a
result without a build for this system builds for, as the GUIs' tooltip does.

The dialog's result is the repository whose packages the main window is to show (Packages, Show packages), or
None. Its owner acts on it from the dismissal callback.
"""
from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Input

from ...app.copr import CoprProjects, EnabledProject, ResultLine
from ...core.copr import DEFAULT_HUB, PROJECT_RE, CoprProject
from ...core.model import CatalogSnapshot
from ...i18n import _, pgettext
from .. import loop
from ..palette import role
from ..table import Column, Table
from ..widgets import Button, ButtonBar, hint
from .apply import Lines
from .repos import reasons_text

PROJECTS_SHOWN = 6  # rows of the top table before it scrolls: the results below need the room more


def project_columns() -> list[Column]:
    return [
        Column("on", pgettext("short column header", "On"), 3, 3),
        Column("project", _("Project"), 12),
        Column("packages", _("Packages"), 8, 8, right=True),
        Column("installed", _("Installed"), 9, 9, right=True),
    ]


def result_columns() -> list[Column]:
    return [
        Column("project", _("Project"), 12, 30, grow=0),
        Column("builds", _("Builds for this system"), 18, 22, grow=1),
        Column("description", _("Description"), 10),
    ]


class CoprDialog(ModalScreen):
    """`ui`: the questions of the presenter; `run_helper(request, title)` runs a change with its progress dialog and
    reads the catalog again after it. The search goes through kram.core.net, which the tests replace."""

    BINDINGS = [
        Binding("escape", "close", show=False),
        # the search line's own ctrl+e (end of line) would take it first
        Binding("ctrl+e", "enable", show=False, priority=True),
        Binding("ctrl+r", "retry", show=False),
        Binding("enter", "activate", show=False),
    ]
    DEFAULT_CSS = """
    CoprDialog { align: center middle; }
    CoprDialog #copr-box { height: 90%; }
    CoprDialog #copr-projects { height: 2; }
    CoprDialog #copr-search { margin-top: 1; }
    CoprDialog #copr-results { height: 1fr; }
    CoprDialog #why { margin-top: 1; }
    """

    def __init__(self, ui, run_helper):
        super().__init__()
        self.ui = ui
        self.copr = CoprProjects(self, ui, loop.post, run_helper, self.close_with_packages)
        self.projects: dict[str, EnabledProject] = {}
        self.project_order: list[str] = []
        self.results: list[ResultLine] = []
        self.status = ""
        self.searching = False
        self.failed = False          # the last search brought no answer: ctrl+r tries again
        self.searched = ""           # the text of the last search
        self._answered = False       # results came since the last search ended (else it failed)
        self._result: str | None = None
        self._dismissing = self._close_pending = self._stopped = False
        self._ready = False  # composed and mounted (`is_mounted` is not, during on_mount)

    # ---------------------------------------------------------------- the widgets

    def compose(self) -> ComposeResult:
        box = Vertical(classes="window dialog copr", id="copr-box")
        box.border_title = _("COPR repositories")
        box.border_subtitle = hint(("enter", pgettext("search key hint", "search")), ("ctrl+e", _("enable")),
                                   ("esc", _("close")))
        with box:
            yield Lines(lambda: Text(_("On this system"), Style(bold=True)), id="on-system")
            yield Table(project_columns(), self._project_cell, self.app.glyphs.ellipsis, id="copr-projects")
            yield Lines(id="no-projects")
            yield Input(placeholder=_("owner/project, or words to search for"), id="copr-search")
            yield Lines(self._status_text, id="status")
            yield Table(result_columns(), self._result_cell, self.app.glyphs.ellipsis, id="copr-results")
            yield Lines(id="why")
            yield Lines(lambda: Text(_("COPR projects are built by community members and are not reviewed by "
                                       "Fedora."), role("muted")), id="note", classes="gap")
            with ButtonBar(classes="buttons"):
                with Horizontal():  # the project's under the cursor of the top table
                    yield Button(_("Packages"), id="packages")
                    yield Button(_("Disable"), id="toggle")
                    yield Button(_("Remove…"), id="remove", variant="error")
                with Horizontal():
                    yield Button(_("Enable selected"), id="enable", variant="primary")

    def on_mount(self) -> None:
        self._ready = True
        self._show_projects()
        self._show_results()
        self.query_one("#copr-search", Input).focus()

    @property
    def project_table(self) -> Table:
        return self.query_one("#copr-projects", Table)

    @property
    def result_table(self) -> Table:
        return self.query_one("#copr-results", Table)

    def _button(self, name: str) -> Button:
        return self.query_one(f"#{name}", Button)

    def typed(self) -> str:
        return self.query_one("#copr-search", Input).value if self._ready else ""

    # ---------------------------------------------------------------- the cells

    def _project_cell(self, repo_id: str, column: str) -> Text:
        p = self.projects[repo_id]
        match column:
            case "on":
                return Text("[x]" if p.enabled else "[ ]", role("marked") if p.enabled else Style())
            case "project":
                # a project of another Copr instance says which: the same name can be on two hubs
                return Text(p.project if p.hub == DEFAULT_HUB else f"{p.project} ({p.hub})")
            case "packages":
                return Text(p.packages)
            case "installed":
                return Text(p.installed)
        return Text()

    def _result_cell(self, index: int, column: str) -> Text:
        line = self.results[index]
        match column:
            case "project":
                return Text(line.name)
            case "builds":
                # the presenter's "✓ chroot" with the terminal's glyph: "✓" is a question mark where it is not UTF-8
                chroot = line.builds.split(" ", 1)[-1]
                g = self.app.glyphs
                return Text(f"{g.yes if line.builds_ok else g.no} {chroot}", role("ok" if line.builds_ok else "danger"))
            case "description":
                return Text(" ".join(line.description.split()), role("muted"))
        return Text()

    def _status_text(self) -> Text:
        text = Text(self.status, role("danger") if self.failed else Style())
        if self.failed:
            text.append("  ")
            text.append_text(hint(("ctrl+r", _("try again"))))
        return text

    # ---------------------------------------------------------------- what is selected

    def selected_project(self) -> EnabledProject | None:
        if not self._ready:
            return None
        repo_id = self.project_table.current
        return self.projects.get(repo_id) if repo_id is not None else None

    def selected_result(self) -> CoprProject | None:
        """The result under the cursor, unless the line holds an `owner/project` of its own: one typed after the
        search, while the results table does not have the focus."""
        if not self._ready or not self.results or self.result_table.current is None:
            return None
        typed = self.typed().strip()
        if self.focused is not self.result_table and typed != self.searched and PROJECT_RE.match(typed):
            return None
        return self.results[self.result_table.current].project

    def _update(self) -> None:
        """The buttons, and why those that are off are off, for what is under the cursors and in the line."""
        if not self._ready:
            return
        project, result, typed = self.selected_project(), self.selected_result(), self.typed()
        state = self.copr.buttons(project, result, typed)
        toggle = self._button("toggle")
        label = _("Enable") if project is not None and not project.enabled else _("Disable")
        if toggle.label != label:
            toggle.set_label(label)
            self.query_one(ButtonBar).fit()
        self._button("packages").set_enabled(state.packages)
        toggle.set_enabled(state.enable or state.disable)
        self._button("remove").set_enabled(state.remove)
        self._button("enable").set_enabled(state.add)
        reasons = [(_("Enable selected"), "" if state.add else self.enable_reason(result, typed))]
        builds = ""
        if result is not None and self.result_table.current is not None:
            builds = self.results[self.result_table.current].builds_tip
        why = "\n".join(t for t in (builds, reasons_text(reasons)) if t)
        self.query_one("#why", Lines).show(lambda: Text(why, role("muted")))

    def enable_reason(self, result: CoprProject | None, typed: str) -> str:
        """Why Enable is off: the project is on already."""
        if result is not None:
            return _("{project} is already enabled").format(project=result.full_name)
        text = typed.strip()
        # with nothing to enable yet the line's placeholder and the hints say what to do
        return _("{project} is already enabled").format(project=text) if PROJECT_RE.match(text) else ""

    def _show_projects(self) -> None:
        if not self._ready:
            return
        table = self.project_table
        table.set_rows(self.project_order)
        table.styles.height = min(len(self.project_order), PROJECTS_SHOWN) + 1  # and the header
        table.display = bool(self.project_order)
        table.redraw()
        self.query_one("#no-projects", Lines).show(
            lambda: Text(_("No COPR projects yet. Search for one below."), role("muted"))
            if not self.project_order else Text())
        self._update()

    def _show_results(self) -> None:
        if not self._ready:
            return
        self.result_table.set_rows(list(range(len(self.results))))
        self.result_table.redraw()
        self._update()

    # ---------------------------------------------------------------- the user

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        self._update()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.search(event.value)

    def search(self, text: str) -> None:
        if text.strip():
            self.searched = text.strip()
            self.copr.search(text)

    def on_table_highlighted(self, event: Table.Highlighted) -> None:
        event.stop()
        self._update()

    def on_table_clicked(self, event: Table.Clicked) -> None:
        event.stop()
        if event.table is self.result_table and event.chain == 2:
            self.action_enable()

    def on_descendant_focus(self, _event) -> None:
        self._update()  # whether Enable takes the result or the typed project depends on the focus

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        project = self.selected_project()
        match event.button.id:
            case "packages":
                if project is not None:
                    self.copr.show_packages(project)
            case "toggle":
                if project is not None:
                    self.copr.change(project, "enable" if not project.enabled else "disable")
            case "remove":
                if project is not None:
                    self.copr.remove(project)
            case "enable":
                self.action_enable()

    def action_enable(self) -> None:
        if self._button("enable").enabled:
            self.copr.enable(self.selected_result(), self.typed())

    def action_activate(self) -> None:
        """Enter on a result enables it, as a double click (GTK's activate)."""
        if self.focused is self.result_table:
            self.action_enable()

    def action_retry(self) -> None:
        if self.failed and self.searched:
            self.copr.search(self.searched)

    def action_close(self) -> None:
        self._close(None)

    # ---------------------------------------------------------------- closing

    def _close(self, result: str | None) -> None:
        """Only from the top of the screens (kram.tui.dialogs.repos.ReposDialog._close): under the question whose
        Show packages chose it, once that is gone."""
        if self._dismissing:
            return
        self._result = result
        if self.app.screen is not self:
            self._close_pending = True
            return
        self._dismissing = True
        self.stop()
        self.dismiss(result)

    def on_screen_resume(self) -> None:
        if self._close_pending:
            self._close_pending = False
            self._close(self._result)

    def stop(self) -> None:
        """A search still on its way is dropped with the dialog (CoprProjects.close)."""
        if not self._stopped:
            self._stopped = True
            self.copr.close()

    def on_unmount(self) -> None:
        self.stop()

    def close_with_packages(self, repo_id: str) -> None:
        """Packages, Show packages: the main window shows them, once the dialog is gone."""
        self._close(repo_id)

    # ---------------------------------------------------------------- CoprView, and the window's

    def set_catalog(self, snap: CatalogSnapshot, counts) -> None:
        """The projects as they are now: at the start, and after every change made from the dialog."""
        self.copr.set_catalog(snap, counts)

    def show_projects(self, projects: list[EnabledProject]) -> None:
        """The table keeps the cursor on its project after a reload (its key)."""
        self.projects = {p.repo_id: p for p in projects}
        self.project_order = [p.repo_id for p in projects]
        self._show_projects()

    def show_results(self, results: list[ResultLine]) -> None:
        self._answered = True
        self.results = results
        self._show_results()

    def show_search_status(self, text: str) -> None:
        self.status = text
        # a search that ended with no results shown failed (CoprProjects._on_search_failed, an unexpected answer)
        self.failed = not self.searching and not self._answered and bool(self.searched)
        if self._ready:
            self.query_one("#status", Lines).refresh(layout=True)

    def set_searching(self, on: bool) -> None:
        self.searching = on
        self._answered = False
        if on:
            self.failed = False
            if self._ready:
                self.query_one("#status", Lines).refresh(layout=True)

    def select_first_result(self) -> None:
        if self._ready and self.results:
            self.result_table.go(0)
            self.result_table.focus()
