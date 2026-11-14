"""What Kram's "Update Notifications" dialog reads and changes: our user units, Fedora's metadata timer and the
update notifiers of other programs. No Qt here; the D-Bus questions (is a notifier running) are the dialog's.
"""
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import TRAY_UNIT

CHECK_UNITS = ("kram-update-check.timer", "kram-update-check.path")
CHECK_SERVICE = "kram-update-check.service"
FEDORA_TIMER = "dnf-makecache.timer"
SYSTEM_AUTOSTART = Path("/etc/xdg/autostart")


def _systemctl(*args: str, timeout: float = 15) -> subprocess.CompletedProcess:
    return subprocess.run(["systemctl", *args], capture_output=True, text=True, timeout=timeout, check=False)


def checker_enabled() -> bool:
    return _systemctl("--user", "is-enabled", "--quiet", CHECK_UNITS[0]).returncode == 0


def set_checker_enabled(on: bool) -> str:
    """Turn the checker on (and count right away) or off (and hide the icon). Returns an error, or ""."""
    if on:
        result = _systemctl("--user", "enable", "--now", *CHECK_UNITS)
        if result.returncode == 0:
            _systemctl("--user", "start", "--no-block", CHECK_SERVICE)
    else:
        result = _systemctl("--user", "disable", "--now", *CHECK_UNITS, TRAY_UNIT)
    return "" if result.returncode == 0 else (result.stderr.strip() or f"systemctl: {result.returncode}")


def recheck() -> None:
    """Count again now, if the checker is on: after Kram's helper ran, which may have refreshed the metadata
    (Reload, or libdnf5 refreshing expired repositories before a transaction). The path unit only watches the rpm
    database, and the hourly timer may be an hour away. Cheap: the check exits early when nothing changed."""
    try:
        if checker_enabled():
            _systemctl("--user", "start", "--no-block", CHECK_SERVICE, timeout=5)
    except (OSError, subprocess.SubprocessError):
        pass  # no systemd user instance: no checker to tell


def fedora_timer_state() -> str:
    """"enabled", "disabled", or "missing" (no such unit: not Fedora, or dnf5 without it)."""
    state = _systemctl("is-enabled", FEDORA_TIMER).stdout.strip()
    if state in ("enabled", "enabled-runtime", "static", "alias"):
        return "enabled"
    if state in ("disabled", "masked", "masked-runtime", "indirect"):
        return "disabled"
    return "missing"


@dataclass(frozen=True)
class Notifier:
    """Another program's update notifier, started from the system autostart folder."""
    name: str               # as the user knows the program
    bus_name: str           # what it owns on the session bus while it runs
    autostart: tuple[str, ...]  # its file names in /etc/xdg/autostart, any of them
    icons: tuple[str, ...] = ()  # the program's icon, in the order to try

    def system_file(self) -> Path | None:
        return next((SYSTEM_AUTOSTART / f for f in self.autostart if (SYSTEM_AUTOSTART / f).exists()), None)

    def override(self) -> Path | None:
        """Our copy in the user's autostart folder, which hides the system file for this user only."""
        system = self.system_file()
        return user_autostart() / system.name if system else None

    def turned_off(self) -> bool:
        override = self.override()
        try:
            return override is not None and "Hidden=true" in override.read_text().splitlines()
        except OSError:
            return False

    def turn_off(self) -> None:
        """XDG autostart: a file of the same name in ~/.config/autostart wins; Hidden=true means "deleted"."""
        override = self.override()
        override.parent.mkdir(parents=True, exist_ok=True)
        override.write_text(f"[Desktop Entry]\n# written by Kram (Settings → Update Notifications): {self.name}'s "
                            "update notifier is turned off for this user. Delete this file to turn it back on.\n"
                            "Type=Application\nHidden=true\n")

    def turn_on(self) -> None:
        if self.turned_off():
            self.override().unlink()


NOTIFIERS = (
    Notifier("Discover", "org.kde.discover.notifier", ("org.kde.discover.notifier.desktop",), ("plasmadiscover",)),
    Notifier("GNOME Software", "org.gnome.Software", ("org.gnome.Software.desktop", "gnome-software-service.desktop"),
             ("org.gnome.Software", "gnome-software")),
)


def user_autostart() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "autostart"
