"""The Mirrors dialog (docs/TUI_SPEC.md §10.5): the `MirrorsView` of kram.app.mirrors.Mirrors, as
kram.gtk.dialogs.mirrors is. It opens over the Repositories dialog, which stays open under it.

A status line (loading the list, the test's progress, what a choice did), then the mirrors of the repository's list
in a table (kram.tui.table): the address, its country and protocol, how fast it answered and downloaded, and a note
("In use", "Fastest", "Out of date", or why it failed); the mirror in use is bold. A narrow table drops the country
and the protocol. `< Test speed >` measures them all, `< Stop >` while it runs; the presenter puts the quickest first
once the test is over. `< Use selected mirror >` (or Enter on a row) pins the repository to it, after a question
when it is out of date or reached over plain http; `< Automatic >` lets dnf choose again; `[ ] Fastest mirror for
every repository` is dnf's own fastestmirror option, with what it means now under it. A choice runs over the dialog,
which stays open: after the reload the window hands it the new state (`set_state`). A button that is off says why on
the line under the table.

Closing it stops the loading and the test: their threads' answers are dropped (`Mirrors.close`).

What the presenter tells the view is kept in fields and drawn once the dialog is mounted: the list may arrive
before that.
"""
from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen

from ...app.mirrors import MirrorLine, Mirrors, dialog_title
from ...core.mirrors import MirrorSource
from ...core.model import RepoInfo
from ...i18n import _
from .. import loop
from ..palette import role
from ..table import Column, Table
from ..widgets import Button, ButtonBar, CheckBox, hint
from .apply import Lines
from .repos import reasons_text


def columns() -> list[Column]:
    return [
        Column("mirror", _("Mirror"), 12, 40, grow=0),
        Column("country", _("Country"), 7, 7, wide=True),
        Column("protocol", _("Protocol"), 8, 8, wide=True),
        Column("response", _("Response"), 8, 8, right=True),
        Column("speed", _("Speed"), 10, 10, right=True),
        Column("note", _("Note"), 8),
    ]


class MirrorsDialog(ModalScreen):
    """`ui`: the question before an out-of-date or plain http mirror; `on_choice(choice)` applies a choice while the
    dialog stays open. `network` replaces the fetching and the speed test, for the tests (kram.app.mirrors)."""

    BINDINGS = [Binding("escape", "close", show=False), Binding("enter", "use", show=False)]
    DEFAULT_CSS = """
    MirrorsDialog { align: center middle; }
    MirrorsDialog #mirrors-box { height: 90%; }
    MirrorsDialog #why { margin-top: 1; }
    """

    def __init__(self, repo: RepoInfo, source: MirrorSource, fastestmirror: bool, ui, on_choice=None, **network):
        super().__init__()
        self.repo = repo
        self.lines: dict[str, MirrorLine] = {}
        self.order: list[str] = []
        self.status = ""
        self.testing = False
        self.fastest = ""
        self._stopped = False
        self._ready = False  # composed and mounted (`is_mounted` is not, during on_mount)
        self.mirrors = Mirrors(repo.id, source, fastestmirror, self, ui, loop.post, on_choice=on_choice, **network)

    choice = property(lambda self: self.mirrors.choice)  # the choice being applied, until set_state

    # ---------------------------------------------------------------- the widgets

    def compose(self) -> ComposeResult:
        box = Vertical(classes="window dialog mirrors", id="mirrors-box")
        box.border_title = dialog_title(self.repo)
        box.border_subtitle = hint(("enter", _("use")), ("esc", _("close")))
        with box:
            yield Lines(lambda: Text(self.status), id="status")
            yield Table(columns(), self._cell, self.app.glyphs.ellipsis, id="mirrors-table")
            yield Lines(id="why")
            yield CheckBox(_("Fastest mirror for every repository"), self.mirrors.fastestmirror, id="fastest",
                           classes="gap")
            yield Lines(lambda: Text(self.fastest, role("muted")), id="fastest-text")
            with ButtonBar(classes="buttons"):
                with Horizontal():
                    yield Button(_("Test speed"), id="test")
                with Horizontal():  # the repository's mirror
                    yield Button(_("Use selected mirror"), id="use", variant="primary")
                    yield Button(_("Automatic"), id="automatic")

    def on_mount(self) -> None:
        self._ready = True
        self.mirrors.start()
        self.show_lines([self.lines[url] for url in self.order])
        self.table.focus()

    @property
    def table(self) -> Table:
        return self.query_one("#mirrors-table", Table)

    def selected_url(self) -> str | None:
        return self.table.current if self._ready else None

    def _cell(self, url: str, column: str) -> Text:
        line = self.lines[url]
        bold = Style(bold=True) if line.current else Style()  # In use (DIALOG_MIRRORS_IN_USE)
        match column:
            case "mirror":
                return Text(line.name, bold)
            case "country":
                return Text(line.country, bold)
            case "protocol":
                return Text(line.protocol, bold)
            case "response":
                return Text(line.response, bold)
            case "speed":
                return Text(line.speed, bold)
            case "note":
                return Text(line.note, (role("danger") if line.failed else Style()) + bold)
        return Text()

    def _update(self) -> None:
        if not self._ready:
            return
        state = self.mirrors.buttons(self.selected_url())
        test = self.query_one("#test", Button)
        label = _("Stop") if self.testing else _("Test speed")
        if test.label != label:
            test.set_label(label)
            self.query_one(ButtonBar).fit()
        test.set_enabled(state.test or self.testing)
        use, automatic = self.query_one("#use", Button), self.query_one("#automatic", Button)
        use.set_enabled(state.use.enabled)
        automatic.set_enabled(state.automatic.enabled)
        why = reasons_text([(use.label, "" if state.use.enabled else state.use.tooltip),
                            (automatic.label, "" if state.automatic.enabled else state.automatic.tooltip)])
        self.query_one("#why", Lines).show(lambda: Text(why, role("muted")))

    # ---------------------------------------------------------------- MirrorsView

    def show_lines(self, lines: list[MirrorLine]) -> None:
        """The view keeps the cursor on its mirror (the table keeps it on its key)."""
        self.lines = {ln.mirror.url: ln for ln in lines}
        self.order = [ln.mirror.url for ln in lines]
        if self._ready:
            self.table.set_rows(self.order)
            self.table.redraw()
            self._update()

    def show_status(self, text: str) -> None:
        self.status = text
        if self._ready:
            self.query_one("#status", Lines).refresh(layout=True)

    def set_testing(self, on: bool) -> None:
        self.testing = on
        self._update()

    def show_fastest(self, text: str, button: str) -> None:
        """What dnf's option is now; the checkbox shows it (`button`, the GUIs' label, is theirs)."""
        self.fastest = text
        if self._ready:
            self.query_one("#fastest", CheckBox).set_value(self.mirrors.fastestmirror)
            self.query_one("#fastest-text", Lines).refresh(layout=True)

    # ---------------------------------------------------------------- the user

    def on_table_highlighted(self, event: Table.Highlighted) -> None:
        event.stop()
        self._update()

    def on_table_clicked(self, event: Table.Clicked) -> None:
        event.stop()
        if event.chain == 2:
            self.mirrors.use(event.key)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        match event.button.id:
            case "test":
                self.mirrors.toggle_test()
            case "use":
                self.mirrors.use(self.selected_url())
            case "automatic":
                self.mirrors.use_automatic()

    def on_check_box_changed(self, event: CheckBox.Changed) -> None:
        event.stop()
        self.mirrors.toggle_fastest()

    def action_use(self) -> None:
        """Enter on the table, as a double click (GTK's activate)."""
        if self.focused is self.table:
            self.mirrors.use(self.selected_url())

    def action_close(self) -> None:
        self.stop()
        self.dismiss(None)

    def stop(self) -> None:
        """A test that is still running stops with the dialog, and the list's loading too."""
        if not self._stopped:
            self._stopped = True
            self.mirrors.close()

    def on_unmount(self) -> None:
        self.stop()

    # ---------------------------------------------------------------- the window's

    def set_state(self, source: MirrorSource, fastestmirror: bool) -> None:
        """What is configured now: after a choice was applied, the dialog shows it."""
        self.mirrors.update(source, fastestmirror)
        self._update()
