"""Settings → Update Notifications (docs/TUI_SPEC.md §10.11): the `NotificationsView` of kram.app.notifier, as
kram.gtk.dialogs.notifier is. The settings are the GUIs': the tray checker is the same user units whichever front end
turns it on, and the stale-data days are the same setting (the window's top line warns by it too).

Fedora's metadata timer is turned on with systemctl, which needs root. With a desktop, its polkit window asks, as in
the GUIs (and as root nothing is asked). Without one there is no window to ask in: Kram steps aside as it does for
the helper (kram.tui.root, §11.3) and systemctl's own agent asks for the password in the terminal; Ctrl+C there ends
systemctl, not Kram.

The other programs' update notifiers are listed with Turn Off / Turn Back On and Show in File Manager (which copies
the path without a desktop, §12.2). Everything here can change outside Kram while the dialog is open, so it reads
the state again whenever it comes back to the top (after a question over it).
"""
import signal
import subprocess
from collections.abc import Callable
from contextlib import AbstractContextManager

from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from ...app import preferences
from ...app.notifier import Notifications, NotificationsState, notifier_file
from ...i18n import _
from ...notifier import control
from .. import loop
from ..palette import role
from ..root import STEP_ASIDE, _do_nothing, is_root
from ..ui_port import BusctlBus, has_desktop
from ..widgets import Button, ButtonBar, CheckBox, hint
from .apply import Lines


class NotifierDialog(ModalScreen):
    """`ui`: the presenter's warnings; `bus`, `suspend` and `run` (the session bus, the app's suspend and
    subprocess.run) are replaceable in tests."""

    BINDINGS = [Binding("escape", "close", show=False)]
    DEFAULT_CSS = """
    NotifierDialog { align: center middle; }
    NotifierDialog #notifier-scroll { height: auto; }
    /* a long label wraps in a narrow terminal rather than being cut */
    NotifierDialog #tray { width: 100%; height: auto; }
    NotifierDialog .line { height: auto; }
    NotifierDialog .label { width: auto; max-width: 70%; margin-right: 1; }
    NotifierDialog #stale-days { width: 5; }
    NotifierDialog Input.-off { text-style: dim; }
    NotifierDialog .head { margin-top: 1; }
    NotifierDialog .row-buttons { height: 1; margin-bottom: 1; }
    NotifierDialog .after-button { margin-left: 2; }
    """

    def __init__(self, ui, bus=None, suspend: Callable[[], AbstractContextManager] | None = None,
                 run=subprocess.run):
        super().__init__()
        self.ui = ui
        self.notifications = Notifications(self, ui, bus or BusctlBus(), loop.post)
        self._suspend, self._run = suspend, run
        self.state: NotificationsState | None = None
        self._ready = False
        self._closed_down = False  # not `_closed`: that is Textual's own

    # ---------------------------------------------------------------- the widgets

    def compose(self) -> ComposeResult:
        box = Vertical(classes="window dialog notifier")
        box.border_title = _("Update Notifications")
        box.border_subtitle = hint(("tab", _("next")), ("enter", _("choose")), ("esc", _("close")))
        stale = preferences.pref(preferences.STALE_DAYS)
        days = int(preferences.value(stale))
        with box:
            with VerticalScroll(id="notifier-scroll"):
                yield CheckBox(_("Show an icon in the system tray when updates are available"), id="tray")
                yield Lines(lambda: Text(_(
                    "The icon is there only while updates are available. Kram downloads nothing in the background: "
                    "Fedora's own service refreshes the package information, Kram only reads it, at login, hourly "
                    "and after every installation."), role("muted")), id="tray-note")
                yield Lines(id="no-tray")
                with Horizontal(classes="line gap"):
                    yield Static(stale.label, classes="label", markup=False)
                    yield Input(str(days), restrict=r"[0-9]*", max_length=3, id="stale-days")
                    yield Static(preferences.days_suffix(days), id="days", markup=False)
                yield Lines(lambda: Text(_("Fedora's update check"), Style(bold=True)), id="fedora-title",
                            classes="head")
                yield Lines(id="timer")
                with Horizontal(classes="line", id="timer-line"):
                    yield Button(_("Turn On Fedora's Update Check…"), id="timer-on")
                    yield Lines(lambda: Text(_("Asks for your password"), role("muted")), classes="after-button")
                if self.notifications.notifiers:
                    yield Lines(lambda: Text(_("Other update notifiers"), Style(bold=True)), classes="head")
                for i in range(len(self.notifications.notifiers)):
                    yield Lines(id=f"notifier-{i}")
                    with Horizontal(classes="row-buttons"):
                        yield Button(_("Turn Off"), id=f"toggle-{i}")
                        yield Button(_("Show in File Manager"), id=f"show-{i}")
            with ButtonBar(classes="buttons"):
                with Horizontal():
                    yield Button(_("Close"), id="close", variant="primary")

    def on_mount(self) -> None:
        self._ready = True
        self.notifications.refresh()
        self.query_one("#tray", CheckBox).focus()

    def on_resize(self) -> None:
        """What scrolls is what is left of 90% of the screen after the frame and the buttons, which stay in sight
        (a scrolling area of `height: auto` would push them out of the dialog)."""
        self.query_one("#notifier-scroll").styles.max_height = max(3, self.size.height * 9 // 10 - 4)

    def on_screen_resume(self) -> None:
        if self._ready:
            self.notifications.refresh()

    # ---------------------------------------------------------------- NotificationsView

    def show_state(self, state: NotificationsState) -> None:
        self.state = state
        if not self._ready or self._closed_down:
            return
        g = self.app.glyphs
        self.query_one("#tray", CheckBox).set_value(state.enabled)
        self.query_one("#no-tray", Lines).show(lambda: Text() if state.has_tray else Text.assemble(
            (g.warning + " ", role("danger")),
            _("This session has no system tray for such icons (GNOME without the AppIndicator extension, LXDE), so "
              "the icon cannot appear.")))
        days = self.query_one("#stale-days", Input)
        days.can_focus = state.enabled  # as the GUIs grey it out: the days are the tray checker's
        days.set_class(not state.enabled, "-off")
        fedora = state.timer != "missing"
        for name in ("#fedora-title", "#timer"):
            self.query_one(name).display = fedora
        on = state.timer == "enabled"
        self.query_one("#timer", Lines).show(lambda: Text.assemble(
            (f"{g.yes if on else g.warning} ", role("ok" if on else "danger")), state.timer_text))
        self.query_one("#timer-line").display = fedora and state.timer == "disabled"
        self.query_one("#timer-on", Button).set_enabled(state.can_enable_timer)
        for i, line in enumerate(state.notifiers):
            self.query_one(f"#notifier-{i}", Lines).show(
                lambda line=line: Text.assemble((line.notifier.name, Style(bold=True)), "\n" + line.text))
            toggle = self.query_one(f"#toggle-{i}", Button)
            if toggle.label != line.toggle_text:
                toggle.set_label(line.toggle_text)

    # ---------------------------------------------------------------- the user

    def on_check_box_changed(self, event: CheckBox.Changed) -> None:
        event.stop()
        if event.checkbox.id == "tray":
            self.notifications.set_enabled(event.value)

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        low, high = preferences.pref(preferences.STALE_DAYS).range
        if event.value.isdigit() and low <= int(event.value) <= high:
            days = int(event.value)
            self.notifications.set_stale_days(days)
            self.query_one("#days", Static).update(preferences.days_suffix(days))

    def on_descendant_blur(self, event) -> None:
        """A number out of the range is not kept: the field shows the setting again when left."""
        field = self.query_one("#stale-days", Input)
        if event.widget is field:
            days = str(preferences.value(preferences.STALE_DAYS))
            if field.value != days:
                field.value = days

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        name = event.button.id or ""
        kind, _sep, index = name.partition("-")
        if name == "close":
            self.action_close()
        elif name == "timer-on":
            self.turn_on_timer()
        elif kind == "toggle":
            self.notifications.toggle(self.notifications.notifiers[int(index)])
        elif kind == "show":
            self.ui.show_in_file_manager(notifier_file(self.notifications.notifiers[int(index)]))

    def turn_on_timer(self) -> None:
        """With a desktop its polkit window asks (as in the GUIs); as root nothing asks; else in the terminal."""
        if is_root() or has_desktop():
            self.notifications.enable_fedora_timer()
            return
        error = ""
        try:
            with (self._suspend or self.app.suspend)():
                print("\n" + _(STEP_ASIDE) + "\n", flush=True)
                old = signal.signal(signal.SIGINT, _do_nothing)
                try:
                    result = self._run(["systemctl", "enable", "--now", control.FEDORA_TIMER],
                                       stderr=subprocess.PIPE, text=True, check=False)
                    if result.returncode != 0:
                        error = (result.stderr or "").strip() or f"systemctl: {result.returncode}"
                finally:
                    signal.signal(signal.SIGINT, old)
        except Exception as e:  # noqa: BLE001 - systemctl missing, or no terminal to give back
            error = str(e) or type(e).__name__
        if error:
            self.ui.warn(_("Update Notifications"), error)
        self.notifications.refresh()

    def action_close(self) -> None:
        if not self._closed_down and self.app.screen is self:
            self._closed_down = True
            self.notifications.close()
            self.dismiss(None)

    def on_unmount(self) -> None:
        self.notifications.close()
