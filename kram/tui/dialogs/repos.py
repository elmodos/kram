"""The Repositories dialog (docs/TUI_SPEC.md §10.4): the `ReposView` of kram.app.repos.Repos, as
kram.gtk.dialogs.repos is.

A filter line at the top, then the table (kram.tui.table): whether the repository is on as `[x]`, its id, its name,
its packages, its priority, its origin, its mirror and the age of its metadata; a narrow table drops the name and
the age. `space` (or a click on the box) turns the repository under the cursor on or off; until the changes are
applied such a row is bold, its id followed by `*`, and the changes are listed under the table in words, so that
nothing is told by colour alone (§9.5). Debuginfo and source repositories are hidden until `[ ] Show debuginfo and
source repositories` (`ctrl+d`) is ticked.

The buttons are the GUIs': Packages shows the repository's packages in the main window and closes the dialog;
Mirrors… opens the Mirrors dialog over this one (kram.tui.dialogs.mirrors); Remove file… asks with the question of
`Repos.remove` and runs the removal over the dialog; Apply (`ctrl+a`) closes it with the changes, which the window
runs through root and the progress dialog. A removal or a mirror change made from here is followed by a reload,
after which the window hands the dialog the new state (`set_data`): it stays open and shows it. A button that is off
says why on the line under the table, as the GUIs' tooltips do. Closing with changes not applied asks first.

The dialog's result is a `ReposChoice`, or None. Its owner acts on it from the dismissal callback, so that the
progress dialog of Apply opens once this one is gone (kram.tui.root).
"""
from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Input

from ...app.browser import ReposChoice
from ...app.ports import CANCEL, Question
from ...app.ports import Button as QuestionButton
from ...app.repos import RepoLine, Repos, ReposData, matches
from ...i18n import _, pgettext
from ..palette import role
from ..table import Column, Table
from ..widgets import Button, ButtonBar, CheckBox, hint
from .apply import Lines


def age_text(seconds: int | None) -> str:
    """The age of a repository's metadata, short: the table has no room for the top line's words."""
    if seconds is None:
        return "—"
    if seconds < 3600:
        # TRANSLATORS: the age of a repository's metadata in the terminal's Repositories table
        return _("{minutes} min").format(minutes=seconds // 60)
    if seconds < 2 * 86400:
        # TRANSLATORS: the age of a repository's metadata in the terminal's Repositories table; h: hours
        return _("{hours} h").format(hours=seconds // 3600)
    # TRANSLATORS: the age of a repository's metadata in the terminal's Repositories table; d: days
    return _("{days} d").format(days=seconds // 86400)


def columns() -> list[Column]:
    return [
        Column("on", pgettext("short column header", "On"), 3, 3),
        Column("repo", _("Repository"), 12, 24, grow=0),
        Column("name", _("Name"), 10, wide=True),
        Column("packages", _("Packages"), 8, 8, right=True),
        Column("prio", pgettext("short column header", "Prio"), 4, 4, right=True),
        Column("origin", _("Origin"), 6, 12, grow=2),
        Column("mirror", _("Mirror"), 9, 16, grow=2),
        Column("metadata", pgettext("short column header", "Metadata"), 8, 8, right=True, wide=True),
    ]


def reasons_text(states: list[tuple[str, str]]) -> str:
    """Why the buttons in `states` (label, reason) are off, each with its button's name; once when several are off
    for the same reason (changes not applied)."""
    found = [(label, why) for label, why in states if why]
    if not found:
        return ""
    if len(found) > 1 and len({why for _label, why in found}) == 1:
        return found[0][1]
    # TRANSLATORS: why a button of a terminal dialog is off: "Mirrors: This repository has a single address…"
    return "\n".join(_("{action}: {reason}").format(action=label.rstrip("…"), reason=why) for label, why in found)


class ReposDialog(ModalScreen):
    """`ui`: the questions (Remove, closing with changes); `on_remove(repo ids)` and `on_mirrors(repo id)` run
    while the dialog stays open (kram.app.repos.Repos)."""

    BINDINGS = [
        Binding("escape", "close", show=False),
        Binding("ctrl+a", "apply", show=False, priority=True),
        Binding("ctrl+d", "aux", show=False, priority=True),
        Binding("space", "toggle", show=False),
    ]
    DEFAULT_CSS = """
    ReposDialog { align: center middle; }
    ReposDialog #repos-box { height: 90%; }
    ReposDialog #repos-filter { margin-bottom: 1; }
    ReposDialog #pending, ReposDialog #why { margin-top: 1; }
    """

    def __init__(self, data: ReposData, ui, on_remove=None, on_mirrors=None):
        super().__init__()
        self.ui = ui
        self.repos = Repos(data.repos, data.counts, ui, self, owners=data.owners, listed=data.listed,
                           installed=data.installed, variables=data.variables, on_remove=on_remove,
                           on_mirrors=on_mirrors)
        self.show_aux = False
        self.lines: dict[str, RepoLine] = {}
        self._result: ReposChoice | None = None
        self._dismissing = self._close_pending = False
        self._ready = False  # composed and mounted (`is_mounted` is not, during on_mount)

    # ---------------------------------------------------------------- the widgets

    def compose(self) -> ComposeResult:
        box = Vertical(classes="window dialog repos", id="repos-box")
        box.border_title = _("Repositories")
        box.border_subtitle = hint(("space", _("on/off")), ("ctrl+d", _("debug/source")), ("ctrl+a", _("apply")),
                                   ("esc", _("close")))
        with box:
            yield Input(placeholder=_("Filter…"), id="repos-filter")
            yield Table(columns(), self._cell, self.app.glyphs.ellipsis, id="repos-table")
            yield Lines(id="pending")
            yield Lines(id="why")
            yield CheckBox(_("Show debuginfo and source repositories"), False, id="aux", classes="gap")
            with ButtonBar(classes="buttons"):
                with Horizontal():  # the selected repository's
                    yield Button(_("Packages"), id="packages")
                    yield Button(_("Mirrors…"), id="mirrors")
                    yield Button(_("Remove file…"), id="remove", variant="error")
                with Horizontal():
                    yield Button(_("Apply"), id="apply", variant="primary")

    def on_mount(self) -> None:
        self._ready = True
        self._fill()
        self.table.focus()

    @property
    def table(self) -> Table:
        return self.query_one("#repos-table", Table)

    def selected_id(self) -> str | None:
        return self.table.current if self._ready else None

    def shown_ids(self) -> list[str]:
        return list(self.table.keys)

    def _fill(self) -> None:
        self.lines = {line.repo.id: line for line in self.repos.lines()}
        needle = self.query_one("#repos-filter", Input).value
        self.table.set_rows([i for i, line in self.lines.items() if matches(line.repo, needle, self.show_aux)])
        self._update()

    def _cell(self, repo_id: str, column: str) -> Text:
        line = self.lines[repo_id]
        on = self.repos.enabled[repo_id]
        changed = on != line.repo.enabled
        bold = Style(bold=True) if changed else Style()
        match column:
            case "on":
                return Text("[x]" if on else "[ ]", (role("marked") if on else Style()) + bold)
            case "repo":
                return Text(repo_id + (" *" if changed else ""), bold)
            case "name":
                return Text(line.repo.name, bold)
            case "packages":
                return Text(line.packages, bold)
            case "prio":
                return Text(line.priority, bold)
            case "origin":
                return Text(line.origin, bold)
            case "mirror":
                return Text(line.mirror, bold)
            case "metadata":
                return Text(age_text(line.repo.age_seconds) if line.repo.enabled else "", role("muted") + bold)
        return Text()

    def pending_text(self) -> str:
        """The changes not applied, in words (§10.4)."""
        changes = self.repos.changes()
        on = ", ".join(sorted(i for i, v in changes.items() if v))
        off = ", ".join(sorted(i for i, v in changes.items() if not v))
        parts = ([_("turn on {repos}").format(repos=on)] if on else []) + \
            ([_("turn off {repos}").format(repos=off)] if off else [])
        return _("Not applied yet: {changes}").format(changes="; ".join(parts)) if parts else ""

    def why_text(self) -> str:
        """Why the buttons that are off for the repository under the cursor are off, and what its Packages cell
        means when it is "—"."""
        repo_id = self.selected_id()
        packages, remove = self.repos.actions(repo_id)
        mirrors = self.repos.mirrors_action(repo_id)
        states = [(b.label, "" if s.enabled else s.tooltip)
                  for b, s in ((self._button("packages"), packages), (self._button("mirrors"), mirrors),
                               (self._button("remove"), remove))]
        tip = self.lines[repo_id].packages_tip if repo_id in self.lines else ""
        return "\n".join(t for t in (tip, reasons_text(states)) if t)

    def _button(self, name: str) -> Button:
        return self.query_one(f"#{name}", Button)

    def _update(self) -> None:
        """The buttons, the changes not applied and the reasons, for the state and the row under the cursor."""
        repo_id = self.selected_id()
        packages, remove = self.repos.actions(repo_id)
        for name, state in (("packages", packages), ("mirrors", self.repos.mirrors_action(repo_id)),
                            ("remove", remove)):
            self._button(name).set_enabled(state.enabled)
        self._button("apply").set_enabled(bool(self.repos.changes()))
        pending, why = self.pending_text(), self.why_text()
        self.query_one("#pending", Lines).show(lambda: Text(pending, role("marked")))
        self.query_one("#why", Lines).show(lambda: Text(why, role("muted")))

    # ---------------------------------------------------------------- the user

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        self._fill()

    def on_table_highlighted(self, event: Table.Highlighted) -> None:
        event.stop()
        self._update()

    def on_table_clicked(self, event: Table.Clicked) -> None:
        event.stop()
        if event.column == "on" and event.chain == 1:
            self.toggle(event.key)

    def on_check_box_changed(self, event: CheckBox.Changed) -> None:
        event.stop()
        self.show_aux = event.value
        self._fill()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        repo_id = self.selected_id()
        match event.button.id:
            case "packages":
                self.repos.show_packages(repo_id)
            case "mirrors":
                self.repos.show_mirrors(repo_id)
            case "remove":
                self.repos.remove(repo_id)
            case "apply":
                self.action_apply()

    def toggle(self, repo_id: str | None) -> None:
        if repo_id is None:
            return
        self.repos.set_enabled(repo_id, not self.repos.enabled[repo_id])
        self.table.redraw()
        self._update()

    def action_toggle(self) -> None:
        if self.focused is self.table:
            self.toggle(self.selected_id())

    def action_aux(self) -> None:
        self.query_one("#aux", CheckBox).action_toggle()

    def action_apply(self) -> None:
        if self.repos.changes():
            self._close(ReposChoice(None, self.repos.changes()))

    def action_close(self) -> None:
        """Esc: with changes not applied, asks first (§10.4)."""
        if not self.repos.changes():
            self._close(None)
            return
        question = Question(_("Repositories"), _("The changes to the repositories are not applied yet."),
                            buttons=(QuestionButton("apply", _("Apply"), "accept"),
                                     QuestionButton("discard", _("Close without applying"), "destructive"), CANCEL),
                            default="cancel", informative=self.pending_text())

        def answered(answer: str | None) -> None:
            if answer == "apply":
                self.action_apply()
            elif answer == "discard":
                self._close(None)
        self.ui.ask(question, answered)

    # ---------------------------------------------------------------- closing

    def _close(self, result: ReposChoice | None) -> None:
        """Only from the top of the screens (kram.tui.dialogs.progress.ProgressDialog.close): under a question
        that chose it, once that is gone."""
        if self._dismissing:
            return
        self._result = result
        if self.app.screen is not self:
            self._close_pending = True
            return
        self._dismissing = True
        self.dismiss(result)

    def on_screen_resume(self) -> None:
        if self._close_pending:
            self._close_pending = False
            self._close(self._result)

    # ---------------------------------------------------------------- ReposView, and the window's

    def close_with_choice(self) -> None:
        """Packages: the main window shows them."""
        self._close(ReposChoice(self.repos.show_repo, None))

    def set_data(self, data: ReposData) -> None:
        """The repositories as they are now: after a removal or a mirror change made from the dialog."""
        self.repos.update(data)
        if self._ready:
            self._fill()
