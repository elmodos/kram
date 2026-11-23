"""TUI spike T2 (Textual): the dialogs that need root, over the window of spike T1: authorization, progress, Apply
changes, Repositories and COPR. Nothing runs as root here: the progress is played back, the COPR search answers
with sample results.

Run it:   python3 scripts/spikes/t2_dialogs.py            (F5 reload, a apply, m menu → Settings for the others)
Shots:    python3 scripts/spikes/t2_dialogs.py shots DIR  (headless; SVG screenshots)

How the helper gets root in a terminal (docs/TUI_FRONTEND.md):
- Kram runs as root (sudo kram-tui, a root shell): the helper starts without pkexec; the top bar says ROOT.
- A desktop session with a polkit agent: pkexec is started in a new session, without a controlling terminal, so
  its password prompt can only be the desktop's window; Kram shows "Waiting for authentication…" meanwhile.
- No agent (SSH, a virtual console): that pkexec fails at once with "No authentication agent found". Kram says why,
  steps aside (Textual's App.suspend: the terminal is the shell's again) and runs pkexec on the terminal, where
  polkit's own text agent asks for the password; then Kram comes back.
KRAM_SPIKE_AGENT=desktop|tty picks the path here (default: desktop when DISPLAY or WAYLAND_DISPLAY is set);
KRAM_SPIKE_ROOT=1 plays root, =0 plays a user. KRAM_SPIKE_PKEXEC=1 runs a real `pkexec /usr/bin/true` on the tty path.
"""
import asyncio
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import t1_tui as t1  # noqa: E402
from rich.text import Text  # noqa: E402
from textual.app import ComposeResult  # noqa: E402
from textual.binding import Binding  # noqa: E402
from textual.containers import Horizontal, Vertical, VerticalScroll  # noqa: E402
from textual.message import Message  # noqa: E402
from textual.screen import ModalScreen  # noqa: E402
from textual.widgets import Checkbox, DataTable, Input, ProgressBar, SelectionList, Static  # noqa: E402

from kram.app.apply_review import CRITICAL  # noqa: E402
from kram.app.columns import human_size  # noqa: E402
from kram.core.model import Status  # noqa: E402

t1.WINDOW_ACTIONS |= {"reload", "apply"}
POLKIT_MESSAGE = ("Authentication is required to install, remove or upgrade packages and to change "
                  "repositories")  # data/io.github.elmodos.Kram.policy
DIALOG_CSS = """
.dialog { width: 90%; max-width: 110; height: auto; max-height: 90%; padding: 0 1; background: $surface;
          border: round $accent; border-title-color: $accent; border-subtitle-color: $accent; }
.dialog .note { color: $text-muted; }
.dialog .warning { color: $error; text-style: bold; }
/* the bars as wide as the dialog: Textual's own bar is 32 cells */
.dialog ProgressBar { width: 100%; }
.dialog ProgressBar Bar { width: 1fr; }
.dialog .buttons { height: 1; align-horizontal: right; margin-top: 1; }
.dialog Button { margin-left: 2; }
"""


def agent_kind() -> str:
    kind = os.environ.get("KRAM_SPIKE_AGENT")
    if kind in ("desktop", "tty"):
        return kind
    return "desktop" if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY") else "tty"


def is_root() -> bool:
    forced = os.environ.get("KRAM_SPIKE_ROOT")  # "1" or "0" overrides: the shots' container runs as root
    return forced == "1" if forced in ("0", "1") else os.geteuid() == 0


class Button(Static, can_focus=True):
    """A button one line high, drawn `< Apply >` as dialog(1) and whiptail do: Textual's own is three lines high
    (T14). Only styles a 16-colour terminal has: focused reverse, the default one bold, a dangerous one in the error
    colour, a disabled one dim and skipped by Tab. Enter, Space or a click presses it."""

    class Pressed(Message):
        def __init__(self, button: "Button"):
            super().__init__()
            self.button = button

    BINDINGS = [Binding("enter,space", "press", show=False)]
    DEFAULT_CSS = """
    Button { width: auto; height: 1; padding: 0; background: $surface; color: $foreground; }
    Button.-primary { text-style: bold; }
    Button.-error { color: $error; }
    Button:focus { text-style: reverse bold; }
    Button.-disabled { text-style: dim; }
    """

    def __init__(self, label: str, id: str, variant: str = "default", disabled: bool = False):
        super().__init__(f"< {label} >", id=id, classes=f"-{variant}")
        self.set_disabled(disabled)

    def set_disabled(self, on: bool) -> None:
        self.off = on
        self.can_focus = not on
        self.set_class(on, "-disabled")

    def action_press(self) -> None:
        if not self.off:
            self.post_message(self.Pressed(self))

    def on_click(self) -> None:
        self.action_press()


class Dialog(ModalScreen):
    """A modal dialog: Esc cancels unless the dialog says otherwise; its buttons are real buttons (Tab moves between
    them, Enter presses the focused one), and the main key of each is named in the bottom border."""

    DEFAULT_CSS = "Dialog { align: center middle; background: $background 50%; }" + DIALOG_CSS
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id)


# ---------------------------------------------------------------- authorization and progress

class AuthDialog(Dialog):
    """No polkit agent can show a window: say why Kram steps aside before it does."""

    def __init__(self, what: str):
        super().__init__()
        self.what = what

    def compose(self) -> ComposeResult:
        box = Vertical(classes="dialog")
        box.border_title = "Administrator rights"
        box.border_subtitle = t1.hint(("enter", "continue"), ("esc", "cancel"))
        with box:
            yield Static(f"{self.what} needs administrator rights.\n")
            yield Static("There is no password window here (no desktop, or no polkit agent in it), so Kram steps "
                         "aside for a moment: polkit asks for your password in this terminal, and Kram comes back "
                         "when you have answered. It asks once for the whole session.\n")
            yield Static("Started as root (sudo kram-tui), Kram asks no password at all.", classes="note")
            with Horizontal(classes="buttons"):
                yield Button("Continue", id="continue", variant="primary")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#continue").focus()


class TerminalMock(ModalScreen):
    """What the terminal shows while Kram has stepped aside (for the shots: a suspended app has no screen)."""

    DEFAULT_CSS = "TerminalMock { background: $background; padding: 1 2; } TerminalMock Static { color: $foreground; }"

    def compose(self) -> ComposeResult:
        user = os.environ.get("USER", "user")
        yield Static("Kram needs administrator rights to reload the repositories.\n"
                     "Kram comes back when you have answered.\n\n"
                     "==== AUTHENTICATING FOR io.github.elmodos.Kram.helper ====\n"
                     f"{POLKIT_MESSAGE}\n"
                     f"Authenticating as: {user}\n"
                     "Password: █")


class ProgressDialog(Dialog):
    """A helper request's progress (kram.app.progress): the stage line, the download bar, for a transaction the
    package bar, and the log. It cannot be cancelled once the transaction runs; until then Esc stops it."""

    def __init__(self, title: str, transaction: bool):
        super().__init__()
        self.title_text, self.transaction = title, transaction

    def compose(self) -> ComposeResult:
        box = Vertical(classes="dialog", id="progress-box")
        box.border_title = self.title_text
        box.border_subtitle = t1.hint(("esc", "stop"))
        with box:
            yield Static("", id="stage")
            yield Static("", id="down-label", classes="note")
            yield ProgressBar(total=100, show_eta=False, id="down")
            if self.transaction:
                yield Static("", id="rpm-label", classes="note")
                yield ProgressBar(total=100, show_eta=False, id="rpm")
            yield Static("", id="log", classes="note")
            with Horizontal(classes="buttons"):
                yield Button("Close", id="close", variant="primary")

    def show(self, stage: str, down: float | None, down_label: str = "", rpm: float | None = None,
             rpm_label: str = "", log: list[str] = (), done: bool = False) -> None:
        self.query_one("#stage", Static).update(Text(stage, style="bold"))
        self.query_one("#down-label", Static).update(down_label)
        self.query_one("#down", ProgressBar).update(total=None if down is None else 100, progress=down or 0)
        if self.transaction:
            self.query_one("#rpm-label", Static).update(rpm_label)
            self.query_one("#rpm", ProgressBar).update(total=None if rpm is None else 100, progress=rpm or 0)
        self.query_one("#log", Static).update("\n".join(log[-6:]))
        close = self.query_one("#close", Button)
        close.display = done  # no button that does nothing while it runs
        if done:
            self.query_one("#progress-box").border_subtitle = t1.hint(("enter", "close"))
            close.focus()


# ---------------------------------------------------------------- Apply changes

class ApplyDialog(Dialog):
    """kram.app.apply_review in a terminal: the summary, a loud warning, the changes by kind, the recommendations to
    leave out, Download only, the dnf5 command, Apply / Cancel. The list scrolls; the buttons stay."""

    BINDINGS = [Binding("escape", "cancel", "Cancel"), Binding("ctrl+a", "apply", "Apply", priority=True)]
    DEFAULT_CSS = Dialog.DEFAULT_CSS + """
    #apply-box { height: 90%; }
    #apply-scroll { height: 1fr; }
    #changes { height: auto; border-top: solid $border-blurred; border-bottom: solid $border-blurred; }
    #recs { height: auto; max-height: 6; border: none; padding: 0; background: $surface; }
    #command { color: $text-muted; height: auto; }
    """

    def __init__(self, sections: list[tuple[str, str, list]], summary: str, warning: str, command: str):
        super().__init__()
        self.sections, self.summary, self.warning, self.command = sections, summary, warning, command

    def compose(self) -> ComposeResult:
        box = Vertical(classes="dialog", id="apply-box")
        box.border_title = "Apply changes"
        box.border_subtitle = t1.hint(("tab", "next"), ("space", "tick"), ("ctrl+a", "apply"), ("esc", "cancel"))
        with box:
            yield Static(self.summary)
            if self.warning:
                yield Static(self.warning, classes="warning")
            # everything between the summary and the buttons scrolls as one: in a narrow terminal a list of its own
            # would get no lines at all
            with VerticalScroll(id="apply-scroll"):
                yield Static(self.changes_text(), id="changes")
                yield Static("Recommended packages: untick to leave them out", classes="note")
                yield SelectionList(("vim-data   recommended by vim-enhanced (sample)", "vim-data", True),
                                    ("xxd   recommended by vim-enhanced (sample)", "xxd", True), id="recs")
                yield Checkbox("Download only: install later", id="download-only")
                yield Static("$ " + self.command, id="command")
            with Horizontal(classes="buttons"):
                yield Button("Apply", id="apply", variant="primary")
                yield Button("Cancel", id="cancel")

    def changes_text(self) -> Text:
        """A row per package: name, versions, size, reason; in a narrow terminal only the name, the version it
        ends up at (or the one removed) and the size, so that rows do not wrap."""
        narrow = self.app.size.width < t1.WIDE
        t = Text()
        for title, colour, rows in self.sections:
            t.append(f"{title} ({len(rows)})\n", t1.role(colour))
            for name, old, new, size, reason in rows:
                t.append(f"  {name[:19]:<20}" if narrow else f"  {name:<28}", "bold" if name in CRITICAL else "")
                versions = (new or old) if narrow else (f"{old} → {new}" if old and new else old or new)
                t.append(f"{versions[:16]:<17}" if narrow else f"{versions:<46}", t1.role("muted"))
                t.append(f"{size:>9}" + ("" if narrow else f"  {reason}") + "\n")
        return t

    def on_mount(self) -> None:
        self.query_one("#apply").focus()

    def action_apply(self) -> None:
        self.dismiss("apply")


# ---------------------------------------------------------------- Repositories

class ReposDialog(Dialog):
    """Settings → Repositories (kram.app.repos): a filter, the table with a real checkbox per repository, the
    changes not yet applied, and what a repository's row can do. Debug and source repositories are hidden until
    asked for, as in the GUIs. Applying the changes needs root."""

    BINDINGS = [
        Binding("escape", "cancel", "Close"),
        Binding("space", "toggle", "On/off"),
        Binding("ctrl+d", "aux", "Debug/source", priority=True),
        Binding("ctrl+a", "apply", "Apply", priority=True),
    ]
    DEFAULT_CSS = Dialog.DEFAULT_CSS + """
    #repos-box { height: 90%; }
    #repos-filter { border: none; height: 1; padding: 0; margin-bottom: 1; background: $surface; }
    #repos-table { height: 1fr; }
    #repos-changes { height: auto; color: $warning; }
    """

    def __init__(self, repos, counts: Counter):
        super().__init__()
        self.repos, self.counts = repos, counts
        self.changes: dict[str, bool] = {}
        self.show_aux = False

    def compose(self) -> ComposeResult:
        box = Vertical(classes="dialog", id="repos-box")
        box.border_title = "Repositories"
        box.border_subtitle = t1.hint(("space", "on/off"), ("ctrl+d", "debug/source"), ("ctrl+a", "apply"),
                                      ("esc", "close"))
        with box:
            yield Input(placeholder="Filter: id or name", id="repos-filter")
            yield DataTable(id="repos-table", cursor_type="row", zebra_stripes=False)
            yield Static("", id="repos-changes")
            with Horizontal(classes="buttons"):
                yield Button("Packages", id="packages")
                yield Button("Mirrors…", id="mirrors")
                yield Button("Remove file…", id="remove", variant="error", disabled=True)
                yield Button("Apply", id="apply", variant="primary", disabled=True)

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("On", "Repository", "Name", "Packages", "Prio", "Origin", "Metadata")
        self.fill()
        table.focus()

    def shown(self):
        needle = self.query_one("#repos-filter", Input).value.lower()
        return [r for r in self.repos
                if (self.show_aux or not r.id.endswith(("-debuginfo", "-source", "-debugsource")))
                and (needle in r.id.lower() or needle in r.name.lower())]

    def fill(self) -> None:
        table = self.query_one(DataTable)
        row = table.cursor_row
        table.clear()
        for r in self.shown():
            on = self.changes.get(r.id, r.enabled)
            changed = r.id in self.changes
            box = Text("[x]" if on else "[ ]", style=t1.role("marked") if changed else "")
            age = "—" if r.age_seconds is None else (f"{r.age_seconds // 3600} h" if r.age_seconds < 172800
                                                       else f"{r.age_seconds // 86400} days")
            table.add_row(box, Text(r.id + (" *" if changed else ""), style="bold" if changed else ""),
                          r.name[:34], f"{self.counts.get(r.id, 0):,}" if on else "", str(r.priority),
                          r.origin.name.lower().replace("_", " "), age, key=r.id)
        if row is not None and table.row_count:
            table.move_cursor(row=min(row, table.row_count - 1))
        on = sorted(k for k, v in self.changes.items() if v)
        off = sorted(k for k, v in self.changes.items() if not v)
        text = "; ".join(filter(None, (on and "turn on " + ", ".join(on), off and "turn off " + ", ".join(off))))
        self.query_one("#repos-changes", Static).update(f"Not applied yet: {text}" if text else "")
        self.query_one("#apply", Button).set_disabled(not self.changes)

    def on_input_changed(self, _event) -> None:
        self.fill()

    def action_toggle(self) -> None:
        table = self.query_one(DataTable)
        if not table.row_count or isinstance(self.focused, Input):
            return
        repo = self.shown()[table.cursor_row]
        new = not self.changes.get(repo.id, repo.enabled)
        if new == repo.enabled:
            self.changes.pop(repo.id, None)
        else:
            self.changes[repo.id] = new
        self.fill()

    def action_aux(self) -> None:
        self.show_aux = not self.show_aux
        self.fill()

    def action_apply(self) -> None:
        if self.changes:
            self.dismiss("apply")

    def action_cancel(self) -> None:
        self.dismiss(None)  # the real dialog asks first when there are changes not applied


# ---------------------------------------------------------------- COPR

SAMPLE_RESULTS = [  # what the Copr search API might answer; the spike has no network
    ("elmodos/Kram", "A Synaptic-like package manager for Fedora", True, "fedora-45-x86_64"),
    ("someone/kram-extras", "Sample: a project that builds for older releases only", False, "fedora-42-x86_64"),
    ("example/tui-tools", "Sample: terminal tools", True, "fedora-45-x86_64"),
]


class CoprDialog(Dialog):
    """Settings → COPR (kram.app.copr): the projects on this system, and the search for new ones. A result that
    builds nothing for this release says so in red and cannot be enabled."""

    BINDINGS = [Binding("escape", "cancel", "Close"), Binding("ctrl+e", "enable", "Enable", priority=True)]
    DEFAULT_CSS = Dialog.DEFAULT_CSS + """
    #copr-box { height: 90%; }
    #copr-projects { height: auto; max-height: 8; }
    #copr-search { border: none; height: 1; padding: 0; margin-top: 1; background: $surface; }
    #copr-results { height: 1fr; }
    """

    def __init__(self, projects):
        super().__init__()
        self.projects = projects

    def compose(self) -> ComposeResult:
        box = Vertical(classes="dialog", id="copr-box")
        box.border_title = "COPR"
        box.border_subtitle = t1.hint(("enter", "search"), ("ctrl+e", "enable"), ("esc", "close"))
        with box:
            yield Static("On this system", classes="note")
            if self.projects:
                yield DataTable(id="copr-projects", cursor_type="row")
            else:
                yield Static(Text("No COPR projects yet. Search for one below.", style=t1.role("muted")))
            yield Input(placeholder="Search COPR: a project, an owner or a package", id="copr-search")
            yield Static("", id="copr-status", classes="note")
            yield DataTable(id="copr-results", cursor_type="row")
            with Horizontal(classes="buttons"):
                yield Button("Disable", id="disable", disabled=not self.projects)
                yield Button("Remove…", id="remove", variant="error", disabled=not self.projects)
                yield Button("Enable", id="enable", variant="primary", disabled=True)

    def on_mount(self) -> None:
        results = self.query_one("#copr-results", DataTable)
        results.add_columns("Project", "Builds for this system", "Description")
        if self.projects:
            projects = self.query_one("#copr-projects", DataTable)
            projects.add_columns("On", "Project", "Packages", "Installed")
            for p in self.projects:
                projects.add_row(*p)
        self.query_one("#copr-search").focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        results = self.query_one("#copr-results", DataTable)
        results.clear()
        found = [r for r in SAMPLE_RESULTS if event.value.lower() in (r[0] + r[1]).lower()] or SAMPLE_RESULTS
        for name, desc, ok, chroot in found:
            results.add_row(name, Text(("✓ " if ok else "✗ ") + chroot, style=t1.role("ok" if ok else "danger")),
                            desc)
        self.query_one("#copr-status", Static).update(f"{len(found)} projects (sample results: no network here)")
        self.query_one("#enable", Button).set_disabled(False)
        results.focus()

    def action_enable(self) -> None:
        results = self.query_one("#copr-results", DataTable)
        if results.row_count and SAMPLE_RESULTS[results.cursor_row][2]:
            self.dismiss("enable")


# ---------------------------------------------------------------- the window with them

class KramTui2(t1.KramTui):
    BINDINGS = [
        *t1.KramTui.BINDINGS,
        Binding("f5,ctrl+r", "reload", "Reload"),
        Binding("a", "apply", "Apply"),
    ]

    def update_status(self) -> None:
        super().update_status()
        top = self.query_one("#top", Static)
        label = self.entry.label if self.entry else "All"
        line = Text()
        line.append("Kram", "bold")
        line.append(f"  {label} ({len(self.plist):,})  ·  {len(self.table.marked)} marked  ")
        if is_root():
            line.append(" ROOT ", t1.role("badge"))
            line.append("  changes need no password", t1.role("muted"))
        top.update(line)

    # ---------------------------------------------------------------- root

    def run_privileged(self, what: str, then) -> None:
        """Get the helper (as root) and run `then` with it: at once as root; with the desktop's polkit window; or
        after saying why, on the terminal while Kram steps aside."""
        if is_root():
            then()
        elif agent_kind() == "desktop":
            then(waiting=True)
        else:
            self.push_screen(AuthDialog(what), lambda answer: answer == "continue" and self._tty_auth(then))

    def _tty_auth(self, then) -> None:
        try:
            with self.suspend():
                print("Kram needs administrator rights. Kram comes back when you have answered.\n", flush=True)
                if os.environ.get("KRAM_SPIKE_PKEXEC") == "1":
                    subprocess.run(["pkexec", "/usr/bin/true"], check=False)
                else:
                    input("(spike: pkexec would ask for the password here; press Enter) ")
        except Exception:  # noqa: BLE001 - no terminal to give back (the headless shots): play it through
            pass
        then()

    def action_reload(self) -> None:
        self.run_privileged("Reloading the repositories", self._reload)

    def _reload(self, waiting: bool = False) -> None:
        dialog = ProgressDialog("Reload", transaction=False)
        self.push_screen(dialog)
        if waiting:
            self.call_after_refresh(dialog.show, "Waiting for authentication…", None,
                                    "Your desktop asks for the password in its own window.")
        else:
            self.call_after_refresh(dialog.show, "Refreshing repository metadata", 62, "updates: 41.2 of 66.5 MB",
                                    log=["fedora: metadata is current", "updates: downloading primary.xml.zst"])

    # ---------------------------------------------------------------- apply

    def apply_data(self):
        rows = [r for r in self.plist.rows if r.key in self.table.marked]
        up = [(r.name, r.installed_evr, r.candidate_evr, human_size(r.download_size or 0), "")
              for r in rows if r.status is Status.UPGRADABLE]
        inst = [(r.name, "", r.candidate_evr, human_size(r.download_size or 0), "user")
                for r in rows if not r.installed_evr]
        rem = [(r.name, r.installed_evr, "", "-" + human_size(r.size), "user")
               for r in rows if r.installed_evr and r.status is not Status.UPGRADABLE]
        sections = [s for s in (("To be installed", "ok", inst), ("To be upgraded", "info", up),
                                ("To be removed", "danger", rem)) if s[2]]
        download = sum(r.download_size or 0 for r in rows if r.status is Status.UPGRADABLE or not r.installed_evr)
        summary = Text()
        summary.append(", ".join(f"{len(s[2])} {s[0].split()[-1]}" for s in sections), "bold")
        summary.append(f"   ·   download {human_size(download)}   ·   12.4 GB free on /")
        critical = sorted(r[0] for r in rem if r[0] in CRITICAL)
        warning = (f"⚠ Essential system packages will be removed: {', '.join(critical)}. "
                   "Make sure this is what you want.") if critical else ""
        command = " ; ".join(filter(None, (
            inst and "dnf5 install " + " ".join(r[0] for r in inst),
            up and "dnf5 upgrade " + " ".join(r[0] for r in up),
            rem and "dnf5 remove " + " ".join(r[0] for r in rem))))
        return sections, summary, warning, command

    def action_apply(self) -> None:
        if not self.table.marked:
            self.notify("Nothing is marked", timeout=3)
            return
        self.push_screen(ApplyDialog(*self.apply_data()),
                         lambda answer: answer == "apply" and self.run_privileged("Applying the changes",
                                                                                  self._apply))

    def _apply(self, waiting: bool = False) -> None:
        dialog = ProgressDialog("Apply changes", transaction=True)
        self.push_screen(dialog)
        self.call_after_refresh(dialog.show, "Installing packages", 100, "Downloaded 245.3 of 245.3 MB", 40,
                                "Upgrading vim-data 2:9.2.1302-2.fc44 (6 of 15)",
                                ["Downloaded 15 packages", "Checked the OpenPGP signatures",
                                 "Upgrading file-libs", "Upgrading libavcodec-free"])

    # ---------------------------------------------------------------- settings

    def run_menu_action(self, action: str) -> None:
        if action == "reload":
            self.action_reload()
        elif action == "apply":
            self.action_apply()
        elif action == "repos":
            counts = Counter(r.repo_id for r in self.plist.rows)
            self.push_screen(ReposDialog(getattr(self.snap, "repos", []), counts),
                             lambda answer: answer == "apply" and self.run_privileged(
                                 "Changing the repositories", lambda waiting=False: self.notify("Applied")))
        elif action == "copr":
            projects = [(Text("[x]" if r.enabled else "[ ]"), r.id.split(":", 1)[-1], "", "")
                        for r in getattr(self.snap, "repos", []) if r.id.startswith("copr:")]
            self.push_screen(CoprDialog(projects))
        else:
            super().run_menu_action(action)


# ---------------------------------------------------------------- shots

async def shots(snap, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    W, N = (130, 36), (64, 22)

    def mark(a):
        a.select_entry("status:upgradable")
        a.table.marked |= {r.key for r in a.plist.rows if r.status is Status.UPGRADABLE}
        a.table.marked |= {r.key for r in a.plist.rows if r.name in ("htop", "vim-enhanced", "sudo")}
        a.update_status()

    cases = [
        ("01-user-top-bar", W, {}, [mark]),
        ("02-root-top-bar", W, {"KRAM_SPIKE_ROOT": "1"}, [mark]),
        ("03-reload-desktop-waiting", W, {"KRAM_SPIKE_AGENT": "desktop"}, ["f5"]),
        ("04-reload-tty-why", W, {"KRAM_SPIKE_AGENT": "tty"}, ["f5"]),
        ("05-reload-tty-terminal", W, {}, [lambda a: a.push_screen(TerminalMock())]),
        ("06-reload-progress-root", W, {"KRAM_SPIKE_ROOT": "1"}, ["f5"]),
        ("07-apply-review", W, {}, [mark, "a"]),
        ("08-apply-review-narrow", N, {}, [mark, "a"]),
        ("09-apply-progress", W, {"KRAM_SPIKE_ROOT": "1"}, [mark, "a", "ctrl+a"]),
        ("09b-apply-done", W, {"KRAM_SPIKE_ROOT": "1"}, [mark, "a", "ctrl+a", lambda a: a.screen.show(
            "Done: 2 installed, 13 upgraded, 1 removed", 100, "Downloaded 245.3 MB", 100, "15 of 15",
            ["Upgrading vim-minimal", "Removing sudo", "Running scriptlets", "Done"], done=True)]),
        ("10-repos", W, {}, [lambda a: a.run_menu_action("repos")]),
        ("11-repos-changes-aux", W, {}, [lambda a: a.run_menu_action("repos"), "ctrl+d", "down", "down", "down",
                                         "down", "down", "space", "down", "space"]),
        ("12-repos-filter", W, {}, [lambda a: a.run_menu_action("repos"),
                                    lambda a: a.screen.query_one("#repos-filter").focus(), *"upd"]),
        ("13-repos-narrow", N, {}, [lambda a: a.run_menu_action("repos")]),
        ("14-copr", W, {}, [lambda a: a.run_menu_action("copr")]),
        ("15-copr-results", W, {}, [lambda a: a.run_menu_action("copr"), *"kram", "enter"]),
        ("16-copr-narrow", N, {}, [lambda a: a.run_menu_action("copr"), *"kram", "enter"]),
        ("17-apply-midnight", W, {"KRAM_SCHEME": "kram-midnight"}, [mark, "a"]),
        ("18-apply-textual-light", W, {"KRAM_SCHEME": "textual-light"}, [mark, "a"]),
        ("19-progress-console", W, {"KRAM_SCHEME": "kram-console", "KRAM_SPIKE_ROOT": "1"}, ["f5"]),
    ]
    for name, size, env, steps in cases:
        saved = {k: os.environ.get(k) for k in ("KRAM_SPIKE_ROOT", "KRAM_SPIKE_AGENT", "KRAM_SCHEME")}
        os.environ.update({"KRAM_SPIKE_AGENT": "desktop", "KRAM_SPIKE_ROOT": "0", **env})
        app = KramTui2(snap)
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            for step in steps:
                if callable(step):
                    step(app)
                else:
                    await pilot.press(step)
                await pilot.pause()
            await pilot.pause()
            app.save_screenshot(filename=f"{name}.svg", path=str(out))
            print(f"{name}: screens={[type(s).__name__ for s in app.screen_stack]} "
                  f"focus={app.focused.id if app.focused else None}")
        for k, v in saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def main() -> None:
    snap = t1.snapshot()
    if sys.argv[1:2] == ["shots"]:
        asyncio.run(shots(snap, Path(sys.argv[2])))
    else:
        KramTui2(snap).run()


if __name__ == "__main__":
    main()
