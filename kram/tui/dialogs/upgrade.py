"""The Fedora N dialog (docs/TUI_SPEC.md §10.12): what moving to the new release would do, over
kram.app.upgrade.UpgradeCheck, as kram.gtk.dialogs.upgrade is. Kram itself never upgrades the system.

`UpgradeState` is the check's `UpgradeView`: it keeps what the check said (the COPR line, the findings, the status,
the log), and the main window keeps it for the session, as the GUIs keep their dialog, so that a finished check is
not repeated when the dialog opens again. The dialog draws the state and follows it while it is open.

The findings are lines with their mark as a glyph in its role, as the Install package file dialog marks its notes
(✓ ok, ! a warning, ✗ a problem, i a note: never by colour alone, §9.5), the lines under each indented. While the
simulation runs the busy bar and the log's last lines show, `< Cancel >` takes the place of `< Check >`, and the dialog cannot be closed (nor Kram, whose keys a dialog
keeps): a check is left with Cancel, as in the GUIs. The release notes and the upgrade guide are links (§7.4.5); the
upgrade itself is the command to run in a terminal (`y` copies it), and with a desktop the button that opens its
software centre too.
"""
import os
from collections.abc import Callable

from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import ProgressBar

from ...app.icons import ERROR, INFO, OK, WARN
from ...app.progress import Bar
from ...app.upgrade import Finding, UpgradeCheck, have_text, intro
from ...core import distro, proc
from ...i18n import _
from ..palette import role
from ..ui_port import has_desktop
from ..widgets import Button, ButtonBar, hint
from .about import LinkLine
from .apply import Lines

LOG_SHOWN = 6  # the log's last lines under the findings


def upgrade_commands(target: int) -> list[str]:
    """What upgrades the system from a terminal, as Fedora's upgrade guide gives it."""
    return [f"sudo dnf5 system-upgrade download --releasever={target}", "sudo dnf5 offline reboot"]


class UpgradeState:
    """The `UpgradeView` of a check, kept between openings of the dialog; `listener()` after every change."""

    def __init__(self, target: int):
        self.target = target
        self.copr = Finding(None, _("COPR projects: checking…"))
        self.failed: Finding | None = None
        self.findings: list[Finding] = []
        self.status = intro(target)
        self.running = False
        self.cancelling = False
        self.bar = Bar(0, 0)
        self.log: list[str] = []
        self.listener: Callable[[], None] = lambda: None

    def show_copr(self, finding: Finding, failed: Finding | None) -> None:
        self.copr, self.failed = finding, failed
        self.listener()

    def show_findings(self, findings: list[Finding]) -> None:
        self.findings = list(findings)
        self.listener()

    def show_status(self, text: str) -> None:
        self.status = text
        self.listener()

    def set_running(self, running: bool) -> None:
        self.running = running
        self.cancelling = False
        if running:
            self.log = []
        self.listener()

    def set_cancelling(self) -> None:
        self.cancelling = True
        self.listener()

    def show_progress(self, bar: Bar) -> None:
        self.bar = bar
        self.listener()

    def append_log(self, line: str) -> None:
        self.log.append(line)
        self.listener()


class UpgradeDialog(ModalScreen):
    """`check` runs over `state`; `ui` opens the links and copies the command."""

    BINDINGS = [
        Binding("escape", "close", show=False),
        Binding("y", "copy_command", show=False),
        Binding("pageup", "page(-1)", show=False),
        Binding("pagedown", "page(1)", show=False),
    ]
    DEFAULT_CSS = """
    UpgradeDialog { align: center middle; }
    UpgradeDialog #upgrade-box { height: 90%; }
    UpgradeDialog #upgrade-scroll { height: 1fr; margin-top: 1; }
    UpgradeDialog .check-line { height: auto; margin-top: 1; }
    UpgradeDialog #status { width: 1fr; margin-left: 2; }
    /* a long address wraps in a narrow terminal rather than being cut */
    UpgradeDialog LinkLine { width: 100%; height: auto; }
    UpgradeDialog ProgressBar { width: 100%; height: 1; margin-top: 1; }
    UpgradeDialog ProgressBar Bar { width: 1fr; }
    UpgradeDialog .head { margin-top: 1; }
    """

    def __init__(self, state: UpgradeState, check: UpgradeCheck, running: int, running_eol: str, ui):
        super().__init__()
        self.state, self.check, self.ui = state, check, ui
        self.running_release, self.running_eol = running, running_eol
        self.program = distro.upgrade_program(os.environ.get("XDG_CURRENT_DESKTOP", "")) if has_desktop() else None
        self._ready = False
        self._dismissing = False

    # ---------------------------------------------------------------- the widgets

    def compose(self) -> ComposeResult:
        target = self.state.target
        box = Vertical(classes="window dialog upgrade", id="upgrade-box")
        box.border_title = f"Fedora {target}"
        with box:
            yield Lines(lambda: Text(_("Fedora {version} is available").format(version=target), Style(bold=True)))
            yield Lines(lambda: Text(have_text(self.running_release, self.running_eol), role("muted")), id="have")
            with Horizontal(classes="check-line"):
                yield Button(_("Check"), id="check", variant="primary")
                yield Button(_("Cancel"), id="cancel")
                yield Lines(lambda: Text(self.state.status), id="status")
            yield ProgressBar(total=None, show_eta=False, show_percentage=False, id="busy")
            with VerticalScroll(id="upgrade-scroll"):
                yield Lines(self._findings, id="findings")
                yield Lines(self._log, id="log", classes="gap")
                yield Lines(lambda: Text(_("Release notes"), Style(bold=True)), classes="head")
                yield LinkLine(distro.RELEASE_NOTES_URL.format(version=target), self.ui, id="notes")
                yield Lines(lambda: Text(_("Upgrade guide"), Style(bold=True)), classes="head")
                yield LinkLine(distro.UPGRADE_GUIDE_URL, self.ui, id="guide")
                yield Lines(lambda: Text(_("To upgrade, run in a terminal:"), Style(bold=True)), classes="head")
                yield Lines(lambda: Text("\n".join(upgrade_commands(target)), role("muted")), id="command")
            with ButtonBar(classes="buttons"):
                if self.program is not None:
                    with Horizontal():
                        yield Button(_("Open {program}").format(program=self.program.name), id="program")
                with Horizontal():
                    yield Button(_("Close"), id="close")

    def on_mount(self) -> None:
        self._ready = True
        self.state.listener = self._show
        self._show()
        self.query_one("#check", Button).focus()

    def on_unmount(self) -> None:
        self.state.listener = lambda: None

    # ---------------------------------------------------------------- drawing the state

    def _mark(self, kind: str | None) -> Text:
        """The marks of the Install package file dialog's notes; " " while the COPR line still waits."""
        g = self.app.glyphs
        glyph, name = {OK: (g.yes, "ok"), WARN: (g.warning, "danger"), ERROR: (g.no, "danger"),
                       INFO: ("i", "info")}.get(kind, (" ", "muted"))
        return Text(glyph, role(name) + Style(bold=True)) + Text(" ")

    def _findings(self) -> Text:
        s = self.state
        out = Text()
        for i, f in enumerate([s.copr, *([s.failed] if s.failed else []), *s.findings]):
            if i:
                out.append("\n")
            out.append_text(self._mark(f.kind))
            out.append(f.title)
            for line in f.lines:
                out.append("\n    " + line, role("muted"))
        return out

    def _log(self) -> Text:
        return Text("\n".join(self.state.log[-LOG_SHOWN:]), role("muted"))

    def _show(self) -> None:
        if not self._ready or self._dismissing:
            return
        s = self.state
        check, cancel = self.query_one("#check", Button), self.query_one("#cancel", Button)
        check.display = not s.running
        cancel.display = s.running
        cancel.set_enabled(s.running and not s.cancelling)
        if s.running and self.focused is check:
            cancel.focus()
        elif not s.running and self.focused is cancel:
            check.focus()
        self.query_one("#close", Button).set_enabled(not s.running)
        busy = self.query_one("#busy", ProgressBar)
        busy.display = s.running
        if s.bar.maximum:
            busy.update(total=s.bar.maximum, progress=s.bar.value)
        else:
            busy.update(total=None)
        for name in ("#status", "#findings", "#log"):
            self.query_one(name, Lines).refresh(layout=True)
        self.query_one("#log").display = bool(s.log)
        box = self.query_one("#upgrade-box")
        keys = [("tab", _("next")), ("y", _("copy"))]
        keys.append(("esc", _("not while it runs")) if s.running else ("esc", _("close")))
        box.border_subtitle = hint(*keys)

    # ---------------------------------------------------------------- the user

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        match event.button.id:
            case "check":
                self.check.start()
            case "cancel":
                self.check.cancel()
            case "program":
                proc.spawn_detached(self.program.argv)
            case "close":
                self.action_close()

    def action_copy_command(self) -> None:
        self.ui.copy_text("\n".join(upgrade_commands(self.state.target)))

    def action_page(self, step: int) -> None:
        scroll = self.query_one("#upgrade-scroll", VerticalScroll)
        scroll.scroll_to(y=scroll.scroll_y + step * max(1, scroll.size.height - 1), animate=False)

    def action_close(self) -> None:
        """Not while a check runs: it is left with Cancel (the GUIs' dialogs cannot be closed meanwhile either)."""
        if self.state.running:
            self.app.bell()
            return
        if not self._dismissing and self.app.screen is self:
            self._dismissing = True
            self.dismiss(None)
