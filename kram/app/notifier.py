"""Settings → Update Notifications: Kram's tray update checker (kram.notifier), Fedora's metadata timer it relies on,
and other programs' update notifiers that would show a second icon. `Notifications` reads all of it again on
`refresh` (the dialog does that whenever it is activated: everything here can change outside Kram) and tells its
`NotificationsView`; it turns them on and off."""
import os
import signal
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from ..core import proc
from ..core.mainloop import Post
from ..i18n import _
from ..notifier import control
from . import preferences
from .ports import Bus, Ui, view_ref

TRAY_HOST = "org.kde.StatusNotifierWatcher"
# icon names in the order to try (not every theme has them); checked with Breeze and Papirus, light and dark.
# Monochrome for the actions, the program's own colours for headings and programs.
FEDORA_ICONS = ("fedora-logo-icon", "distributor-logo", "system-software-update")
ON_ICONS = ("dialog-ok-apply",)  # emblem-ok-symbolic vanishes on a dark Papirus palette
OFF_ICONS = ("dialog-warning",)
TURN_ON_ICONS = ("media-playback-start",)
TURN_OFF_ICONS = ("system-shutdown",)
FILE_MANAGER_ICONS = ("document-open-folder",)  # not folder-*: colourful folders in Papirus
NOTIFIER_FALLBACK_ICONS = ("system-software-install",)


@dataclass(frozen=True)
class NotifierLine:
    """Another program's update notifier: what it does to ours, and the button that turns it off or back on."""
    notifier: control.Notifier
    text: str
    toggle_text: str
    toggle_icons: tuple[str, ...]
    toggle_tip: str


@dataclass(frozen=True)
class NotificationsState:
    enabled: bool               # Kram's tray icon is on
    has_tray: bool              # the session has a tray for it
    timer: str                  # dnf-makecache.timer: "enabled", "disabled" or "missing"
    timer_text: str
    timer_icons: tuple[str, ...]
    can_enable_timer: bool      # no systemctl waits for the password now
    notifiers: tuple[NotifierLine, ...]


class NotificationsView(Protocol):
    def show_state(self, state: NotificationsState) -> None: ...


def notifiers() -> list[control.Notifier]:
    """The other notifiers installed here, one row each."""
    return [n for n in control.NOTIFIERS if n.system_file()]


def notifier_line(notifier: control.Notifier, bus: Bus) -> NotifierLine:
    name = notifier.name
    if notifier.turned_off():
        return NotifierLine(notifier, _("{program}'s update notifier is turned off for you.").format(program=name),
                            _("Turn Back On"), TURN_ON_ICONS, _("It starts again at your next login"))
    running = bus.owner_pid(notifier.bus_name) is not None
    text = ((_("{program}'s update notifier is running.") if running else
             _("{program}'s update notifier starts at login.")).format(program=name) + " " +
            _("It checks for updates too: you would see two icons, and PackageKit downloads its own copy of the "
              "package information. Keep it and leave Kram's icon off, or turn it off."))
    return NotifierLine(notifier, text, _("Turn Off"), TURN_OFF_ICONS, _("Only for you: stops it now and at every login"))


def notifier_file(notifier: control.Notifier) -> str:
    """The file "Show in File Manager" shows: our override when there is one, else the system's."""
    override = notifier.override()
    return str(override if override and override.exists() else notifier.system_file())


class Notifications:
    def __init__(self, view: NotificationsView, ui: Ui, bus: Bus, post: Post,
                 kill: Callable[[int, int], None] = os.kill):
        self._view, self._ui, self._bus, self._post, self._kill = view_ref(view), ui, bus, post, kill
        self.notifiers = notifiers()
        self._systemctl: proc.Process | None = None

    def state(self) -> NotificationsState:
        timer = control.fedora_timer_state()
        return NotificationsState(
            control.checker_enabled(), self._bus.has_owner(TRAY_HOST), timer,
            _("On: dnf-makecache.timer refreshes the package information every few hours, when the computer is not "
              "on battery.") if timer == "enabled" else
            _("Off: dnf-makecache.timer is disabled, so Kram only sees new updates after a Reload."),
            ON_ICONS if timer == "enabled" else OFF_ICONS, self._systemctl is None,
            tuple(notifier_line(n, self._bus) for n in self.notifiers))

    def refresh(self) -> None:
        self._view.show_state(self.state())

    def _warn(self, text: str) -> None:
        self._ui.warn(_("Update Notifications"), text)

    def set_enabled(self, on: bool) -> None:
        if error := control.set_checker_enabled(on):
            self._warn(error)
        self.refresh()

    @staticmethod
    def set_stale_days(days: int) -> None:
        preferences.set_value(preferences.STALE_DAYS, days)

    def toggle(self, notifier: control.Notifier) -> None:
        try:
            if notifier.turned_off():
                notifier.turn_on()
            else:
                notifier.turn_off()
                if pid := self._bus.owner_pid(notifier.bus_name):
                    self._kill(pid, signal.SIGTERM)
        except OSError as e:
            self._warn(str(e))
        self.refresh()

    def enable_fedora_timer(self) -> None:
        # asynchronous: systemd waits for the password in the desktop's polkit dialog
        self._systemctl = proc.run(["systemctl", "enable", "--now", control.FEDORA_TIMER], post=self._post,
                                   done=self._fedora_timer_done)
        self.refresh()

    def _fedora_timer_done(self, code: int, _stdout: str, stderr: str) -> None:
        self._systemctl = None
        error = stderr.strip()
        if code != 0 and error:
            self._warn(error)
        self.refresh()

    def close(self) -> None:
        if self._systemctl is not None:  # closed while the password was asked: the request goes too
            self._systemctl.kill()
            self._systemctl = None
