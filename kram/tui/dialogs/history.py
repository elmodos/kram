"""The Transaction History dialog (docs/TUI_SPEC.md §10.7): the `HistoryView` of kram.app.history.History, as
kram.gtk.dialogs.history is.

A filter line (a package's name) with the state of the loading under it, then dnf's transactions in a table
(kram.tui.table): the id, the date, what changed ("3 installed, 12 upgraded"), and on a wide table the user and the
command. A transaction that failed has the warning glyph before its id in the danger role, and the line under the
table says so in words with the transaction's whole command (§9.5). Under it the packages of the transaction under
the cursor: the action, the package, the version (`old → new`), and on a wide table the repository and the reason;
those whose name matches the filter are bold.

`< Mark Changes to Undo >` (`Undo Transaction…` when the transaction changed groups) marks what takes its packages
back, through Browser.undo_transaction, which closes the dialog once they are marked. `Enter` on a package (or a
double click) closes the history and selects the package in the window; `Enter` on a transaction goes down to its
packages.

The dialog's result is the name.arch of the package to show, or None. Its owner acts on it from the dismissal
callback.
"""
from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Input

from ...app.history import History, PackageLine, TransactionLine, UndoButton, failed_tip
from ...core.history import HistoryRow
from ...i18n import _
from ..palette import role
from ..table import Column, Table
from ..widgets import Button, ButtonBar, hint
from .apply import Lines


def transaction_columns() -> list[Column]:
    return [
        Column("id", _("ID"), 6, 7, right=True),
        Column("date", _("Date"), 16, 16),
        Column("changes", _("Changes"), 14, 40, grow=0),
        Column("user", _("User"), 8, 12, wide=True),
        Column("command", _("Command"), 10, wide=True),
    ]


def package_columns() -> list[Column]:
    return [
        Column("action", _("Action"), 9, 13),
        Column("package", _("Package"), 14, 36, grow=0),
        Column("version", _("Version"), 10),
        Column("repo", _("Repository"), 10, 16, wide=True),
        Column("reason", _("Reason"), 10, 12, wide=True),
    ]


class HistoryDialog(ModalScreen):
    """`history_args`: the presenter's (DnfWorker, Catalog, Scheduler). `on_undo(tid)` marks the undo of a
    transaction; `name` filters by a package's name from the start (Package → Show in History)."""

    BINDINGS = [
        Binding("escape", "close", show=False),
        Binding("enter", "activate", show=False),
    ]
    DEFAULT_CSS = """
    HistoryDialog { align: center middle; }
    HistoryDialog #history-box { height: 90%; }
    HistoryDialog #transactions { height: 1fr; margin-top: 1; }
    HistoryDialog #packages { height: 1fr; margin-top: 1; }
    """

    def __init__(self, dnf, catalog, scheduler, on_undo=None, name: str = ""):
        super().__init__()
        self.on_undo = on_undo or (lambda tid: None)
        self.name_filter = name
        self.history = History(dnf, catalog, scheduler, self)
        self.transactions: dict[int, TransactionLine] = {}
        self.order: list[int] = []
        self.hidden: set[int] = set()
        self.packages: list[PackageLine] = []
        self._packages_of: int | None = None  # the transaction whose packages are shown
        self.state = ""
        self.undo = self.history.undo_button()
        self._result: tuple[str, str] | None = None
        self._dismissing = self._close_pending = False
        self._ready = False  # composed and mounted (`is_mounted` is not, during on_mount)

    # ---------------------------------------------------------------- the widgets

    def compose(self) -> ComposeResult:
        box = Vertical(classes="window dialog history", id="history-box")
        box.border_title = _("Transaction History")
        box.border_subtitle = hint(("tab", _("next")), ("enter", _("show package")), ("esc", _("close")))
        with box:
            yield Input(self.name_filter, placeholder=_("Filter by package name"), id="history-filter")
            yield Lines(lambda: Text(self.state, role("muted")), id="state")
            yield Table(transaction_columns(), self._transaction_cell, self.app.glyphs.ellipsis, id="transactions")
            yield Lines(id="about")
            yield Table(package_columns(), self._package_cell, self.app.glyphs.ellipsis, id="packages")
            with ButtonBar(classes="buttons"):
                with Horizontal():
                    yield Button(self.undo.text, id="undo", variant="primary")

    def on_mount(self) -> None:
        self._ready = True
        if self.name_filter:
            self.history.set_filter(self.name_filter)
        self.history.reload()
        self._draw_transactions()
        self._draw_packages()
        self.show_undo(self.undo)
        self.transaction_table.focus()

    @property
    def transaction_table(self) -> Table:
        return self.query_one("#transactions", Table)

    @property
    def package_table(self) -> Table:
        return self.query_one("#packages", Table)

    # ---------------------------------------------------------------- the cells

    def _transaction_cell(self, tid: int, column: str) -> Text:
        t = self.transactions[tid]
        match column:
            case "id":
                if t.failed:  # the line under the table says it in words
                    return Text(f"{self.app.glyphs.warning} {t.id}", role("danger"))
                return Text(str(t.id))
            case "date":
                return Text(t.date)
            case "changes":
                return Text(t.changes)
            case "user":
                return Text(t.user, role("muted"))
            case "command":
                return Text(t.command, role("muted"))
        return Text()

    def _package_cell(self, key: tuple[int, int], column: str) -> Text:
        line = self.packages[key[1]]
        style = Style(bold=True) if line.bold else Style()
        match column:
            case "action":
                return Text(line.action, style)
            case "package":
                return Text(line.package, style)
            case "version":
                return Text(line.version, style)
            case "repo":
                return Text(line.repo, role("muted") + style)
            case "reason":
                return Text(line.reason, role("muted") + style)
        return Text()

    def about_text(self) -> Text:
        """The transaction under the cursor: whether it failed, and its whole command line and comment."""
        t = self.transactions.get(self.history.current) if self.history.current is not None else None
        if t is None:
            return Text()
        text = Text()
        if t.failed:
            text.append(failed_tip(), role("danger"))
        if t.tooltip:
            text.append(("\n" if text else "") + " ".join(t.tooltip.split()), role("muted"))
        return text

    # ---------------------------------------------------------------- drawing

    def _draw_transactions(self) -> None:
        if not self._ready:
            return
        table = self.transaction_table
        table.set_rows([i for i in self.order if i not in self.hidden])
        if self.history.current in table.keys:
            table.select_key(self.history.current)
        table.redraw()
        self._draw_about()

    def _draw_about(self) -> None:
        about = self.about_text()
        self.query_one("#about", Lines).show(lambda: about)

    def _draw_packages(self) -> None:
        if not self._ready:
            return
        table = self.package_table
        if self._packages_of != self.history.current:  # another transaction: from its first package
            self._packages_of = self.history.current
            table.cursor = 0
            table.scroll_to(y=0, animate=False, force=True)
        table.set_rows([(self._packages_of, i) for i in range(len(self.packages))])
        table.redraw()

    def _follow_cursor(self) -> None:
        """The transaction under the cursor is the current one: the presenter shows its packages."""
        tid = self.transaction_table.current
        if tid != self.history.current:
            self.history.current_changed(tid)
        self._draw_about()

    # ---------------------------------------------------------------- the user

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        if event.value != self.history.filter:
            self.history.set_filter(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.transaction_table.focus()

    def on_table_highlighted(self, event: Table.Highlighted) -> None:
        event.stop()
        if event.table is self.transaction_table:
            self._follow_cursor()

    def on_table_clicked(self, event: Table.Clicked) -> None:
        event.stop()
        if event.table is self.package_table and event.chain == 2:
            self.open_package()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "undo":
            self.mark_undo()

    def mark_undo(self) -> None:
        if self.history.undo_button().enabled and self.history.current is not None:
            self.on_undo(self.history.current)

    def action_activate(self) -> None:
        """Enter: on a transaction, down to its packages; on a package, it opens in the window."""
        if self.focused is self.transaction_table and self.packages:
            self.package_table.focus()
        elif self.focused is self.package_table:
            self.open_package()

    def open_package(self) -> None:
        key = self.package_table.current
        line = self.packages[key[1]] if key is not None else None
        if line is not None and line.key is not None:  # a group or environment is not a package the list shows
            self._close(line.key)

    def action_close(self) -> None:
        self._close(None)

    # ---------------------------------------------------------------- closing

    def _close(self, result: tuple[str, str] | None) -> None:
        """Only from the top of the screens (kram.tui.dialogs.repos.ReposDialog._close): the undo closes it from
        the dnf thread's answer, which may come while a question is over it."""
        if self._dismissing:
            return
        self._result = result
        if self.app.screen is not self:
            self._close_pending = True
            return
        self._dismissing = True
        self._ready = False  # what the history still reads (its packages come in chunks) draws nothing now
        self.dismiss(result)

    def on_screen_resume(self) -> None:
        if self._close_pending:
            self._close_pending = False
            self._close(self._result)

    def close_history(self) -> None:
        """Browser.undo_transaction: the changes are marked, the Marked list shows them."""
        self._close(None)

    # ---------------------------------------------------------------- the window's

    def reload(self) -> None:
        """Read the transactions again: after a change was applied, the new one shows."""
        self.history.reload()

    def rows_of(self, tid: int) -> list[HistoryRow] | None:
        return self.history.rows_of(tid)

    def set_marking(self, can_mark: bool, busy: bool) -> None:
        self.history.set_marking(can_mark, busy)

    # ---------------------------------------------------------------- HistoryView

    def show_transactions(self, lines: list[TransactionLine]) -> None:
        self.transactions = {t.id: t for t in lines}
        self.order = [t.id for t in lines]
        self.hidden = set()
        self._draw_transactions()

    def set_changes(self, tid: int, text: str) -> None:
        old = self.transactions.get(tid)
        if old is not None:
            self.transactions[tid] = TransactionLine(old.id, old.date, text, old.user, old.command, old.tooltip,
                                                     old.failed)
            if self._ready:
                self.transaction_table.redraw()

    def set_current(self, tid: int | None) -> None:
        """As the cursor would: the presenter hears of it."""
        if self._ready and tid is not None:
            self.transaction_table.select_key(tid)
        if tid != self.history.current:
            self.history.current_changed(tid)
        if self._ready:
            self._draw_about()

    def show_packages(self, lines: list[PackageLine]) -> None:
        self.packages = lines
        self._draw_packages()

    def set_hidden(self, hidden: set[int]) -> None:
        self.hidden = set(hidden)
        self._draw_transactions()

    def show_state(self, text: str) -> None:
        self.state = text
        if self._ready:
            self.query_one("#state", Lines).refresh(layout=True)

    def show_undo(self, button: UndoButton) -> None:
        self.undo = button
        if not self._ready:
            return
        undo = self.query_one("#undo", Button)
        if undo.label != button.text:
            undo.set_label(button.text)
            self.query_one(ButtonBar).fit()
        undo.set_enabled(button.enabled)

