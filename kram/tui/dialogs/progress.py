"""The progress dialog (docs/TUI_SPEC.md §10.2): the `ProgressView` of kram.app.progress.Progress for one helper
request, as kram.gtk.dialogs.progress is.

The stage line in bold, the download bar and, for a transaction, the package bar, as wide as the dialog with their
labels above them (T17); the last lines of the log under them, `l` for the whole log; `[x] Close when finished
successfully`, the GUIs' setting. `< Close >` only once the request is over. Nothing can stop the helper once it has
the request, and a transaction must not be stopped anyway: until then, while the authentication runs, Esc stops;
after that Esc does nothing and the hint says so. Quitting is refused meanwhile by Browser.can_close.

The dialog keeps what it shows in its own fields and draws them when it is mounted: during the authentication
(kram.tui.root) the request's progress may arrive before the dialog is on the screen, or the dialog may never be.
"""
from collections.abc import Callable

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Log, ProgressBar, Static

from ...app.progress import BUSY_BAR, WAITING, Bar, Progress, Stage, shows_download, shows_rpm
from ...core.settings import store as settings
from ...i18n import _
from ..palette import role
from ..widgets import Button, CheckBox, hint

AUTO_CLOSE_KEY = "progress/auto_close"  # shared with the GUIs
LOG_TAIL = 4  # lines of the log under the bars


class LogTail(Widget):
    """The last lines of the log, each cut to the width: a long line must not push the others out."""

    DEFAULT_CSS = f"LogTail {{ height: {LOG_TAIL}; margin-top: 1; }}"

    def __init__(self, **kw):
        super().__init__(**kw)
        self.lines: list[str] = []

    def render(self) -> Text:
        width = max(self.size.width, 1)
        out = Text(style=role("muted"))
        for i, line in enumerate(self.lines[-LOG_TAIL:]):
            part = Text(line.replace("\n", " "))
            part.truncate(width, overflow="ellipsis")
            if i:
                out.append("\n")
            out.append_text(part)
        return out


class LogDialog(ModalScreen):
    """`l`: the whole log, with its times, scrolling; it follows new lines while it is open."""

    BINDINGS = [Binding("escape,l,enter", "close", show=False)]
    DEFAULT_CSS = "LogDialog { align: center middle; } LogDialog .progress-log #full-log { height: 1fr; }"

    def __init__(self, title: str, lines: list[str]):
        super().__init__()
        self.title_text, self.lines = title, lines

    def compose(self) -> ComposeResult:
        box = Vertical(classes="window dialog progress-log")
        box.border_title = self.title_text
        arrows = f"{self.app.glyphs.up} {self.app.glyphs.down}"
        box.border_subtitle = hint((arrows, _("scroll")), ("esc", _("close")))
        with box:
            yield Log(id="full-log")

    def on_mount(self) -> None:
        log = self.query_one(Log)
        log.write_lines(self.lines)
        log.focus()

    def append(self, line: str) -> None:
        if self.is_mounted:
            self.query_one(Log).write_line(line)

    def action_close(self) -> None:
        self.dismiss(None)


class ProgressDialog(ModalScreen):
    """`done(ok, result)` once it has closed (or was never shown). `start()` sends the request: False when the
    helper is busy with another. `root` (kram.tui.root.RootAccess) shows it and is told about Esc while it
    authenticates."""

    BINDINGS = [Binding("escape", "escape", show=False), Binding("l", "log", show=False)]

    def __init__(self, client, request: dict, title: str, done: Callable[[bool, dict], None], ui, root=None):
        super().__init__()
        self.client, self.request, self.title_text = client, request, title
        self._done: Callable[[bool, dict], None] | None = done
        self.root = root
        self.stage = Stage(title)
        self.waiting = False     # "Waiting for authentication…": a desktop's agent asks
        self.download: tuple[Bar, str] = (BUSY_BAR, _("Download"))  # busy until the first download says its size
        self.rpm: tuple[Bar, str] = (Bar(0, 1), _("Installation"))
        self.lines: list[str] = []
        self.finished: bool | None = None  # None while the request runs, else whether it succeeded
        self.auto_close = bool(settings.get(AUTO_CLOSE_KEY, False))
        self._close_when_done = False  # Esc stopped the authentication: close when it has ended
        self._log_dialog: LogDialog | None = None
        self._ready = False  # composed and mounted: its widgets can be drawn
        self._dismissing = self._close_pending = False  # not `_closing`: that is Textual's own
        self.progress = Progress(client, request, self, ui)

    # the outcome, for the callers
    ok = property(lambda self: self.progress.ok)
    result = property(lambda self: self.progress.result)
    running = property(lambda self: self.progress.running)

    def start(self) -> bool:
        return self.progress.start()

    def show(self) -> None:
        self.app.push_screen(self, self._dismissed)

    def discard(self) -> None:
        """Never shown (the user cancelled the authentication): the caller hears the outcome all the same."""
        self._dismissed(None)

    def close(self) -> None:
        """Only from the top of the screens: Textual 4 ignores the dismissal of a screen under another, Textual 8
        pops the one on top instead. Under the whole log it closes once that is closed."""
        if not self._ready or self._dismissing:
            return
        if self.app.screen is not self:
            self._close_pending = True
            return
        self._dismissing = True
        self.dismiss(None)

    def on_screen_resume(self) -> None:
        if self._close_pending:
            self._close_pending = False
            self.close()

    def _dismissed(self, _result) -> None:
        settings.set(AUTO_CLOSE_KEY, self.auto_close)
        self.progress.stop()
        done, self._done = self._done, None
        if done is not None:
            done(self.progress.ok, self.progress.result)

    # ---------------------------------------------------------------- the widgets

    def compose(self) -> ComposeResult:
        box = Vertical(classes="window dialog progress", id="progress-box")
        box.border_title = self.title_text
        with box:
            yield Static(id="stage")
            yield Static(id="note", classes="note")
            if shows_download(self.request):
                yield Static(id="download-label", classes="bar-label")
                yield ProgressBar(id="download-bar", show_eta=False)
            if shows_rpm(self.request):
                yield Static(id="rpm-label", classes="bar-label")
                yield ProgressBar(id="rpm-bar", show_eta=False)
            yield LogTail(id="log-tail")
            yield CheckBox(_("Close when finished successfully"), self.auto_close, id="auto-close", classes="gap")
            with Horizontal(classes="buttons"):
                yield Button(_("Close"), id="close", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#log-tail", LogTail).lines = self.lines
        self._ready = True
        self._paint()
        if self.finished is not None:  # shown only to say why it failed (kram.tui.root)
            self.query_one("#close", Button).focus()

    def _paint(self) -> None:
        if not self._ready:
            return
        stage = self.stage
        text = Text()
        if stage.kind == "error":
            text.append(stage.text, "bold")
            text.append(" " + stage.detail)
            text.stylize(role("danger"))
        else:
            text.append(stage.text, "bold")
            if stage.detail:
                text.append(" " + stage.detail)
        self.query_one("#stage", Static).update(text)
        note = self.query_one("#note", Static)
        note.update(_("Your desktop asks for the password in its own window.") if self.waiting else "")
        note.display = self.waiting
        for name, (bar, label) in (("download", self.download), ("rpm", self.rpm)):
            if self.query(f"#{name}-bar"):
                self.query_one(f"#{name}-label", Static).update(label)
                widget = self.query_one(f"#{name}-bar", ProgressBar)
                if bar.maximum:
                    widget.update(total=bar.maximum, progress=min(bar.value, bar.maximum))
                else:
                    widget.update(total=None)
        self.query_one("#log-tail", LogTail).refresh()
        close = self.query_one("#close", Button)
        close.display = self.finished is not None  # no button that does nothing while it runs
        box = self.query_one("#progress-box")
        if self.finished is not None:
            box.border_subtitle = hint(("enter", _("close")), ("l", _("log")))
        elif self.root is not None and self.root.active:
            box.border_subtitle = hint(("esc", _("stop")), ("l", _("log")))
        else:
            box.border_subtitle = hint(("l", _("log")), ("esc", _("not while it runs")))

    def set_waiting(self, on: bool) -> None:
        """While a desktop's agent asks (kram.tui.root): the stage says so, with a line on where to look."""
        self.waiting = on
        if on:
            self.stage = Stage(_(WAITING))
        elif self.stage == Stage(_(WAITING)):
            self.stage = Stage(self.title_text)
        self._paint()

    # ---------------------------------------------------------------- keys

    def action_escape(self) -> None:
        if self.finished is not None:
            self.close()
        elif self.root is not None and self.root.active:
            self._close_when_done = True
            self.root.stop()
        # else: the helper has the request; nothing stops it (the hint says so)

    def action_log(self) -> None:
        self._log_dialog = LogDialog(_("Details"), list(self.lines))
        self.app.push_screen(self._log_dialog, lambda _r: setattr(self, "_log_dialog", None))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "close":
            self.close()

    def on_check_box_changed(self, event: CheckBox.Changed) -> None:
        event.stop()
        self.auto_close = event.value
        settings.set(AUTO_CLOSE_KEY, event.value)  # saved on change (§13.3)

    # ---------------------------------------------------------------- ProgressView

    def show_stage(self, stage: Stage) -> None:
        self.stage = stage
        self.waiting = False
        self._paint()

    def show_download(self, bar: Bar, label: str | None) -> None:
        self.download = (bar, self.download[1] if label is None else label)
        self._paint()

    def show_rpm(self, bar: Bar, label: str | None) -> None:
        self.rpm = (bar, self.rpm[1] if label is None else label)
        self._paint()

    def append_log(self, line: str) -> None:
        self.lines.append(line)
        if self._log_dialog is not None:
            self._log_dialog.append(line)
        self._paint()

    def request_done(self, ok: bool) -> None:
        self.finished = ok
        self._paint()
        if self._ready:
            self.query_one("#close", Button).focus()
        if self._close_when_done or (ok and self.auto_close):
            self.close()
