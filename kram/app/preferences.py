"""The user's settings, declared once for every front end.

Both front ends build their Settings menu (and the dialogs that hold a setting) from `PREFS`, so a setting added
here appears in both with no front-end code. A setting for one toolkit only (Qt's toolbar style, GTK's menu bar)
names that toolkit, and the other front end leaves it out. The values live in kram.core.settings; a key another
front end wrote is never deleted.
"""
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from ..core import distro
from ..core.mainloop import Signal
from ..core.settings import store
from ..i18n import _, ngettext
from ..notifier import STALE_DAYS_DEFAULT, STALE_DAYS_KEY

BOTH = frozenset({"qt", "gtk"})

STATUS_CLICK = "table/status_click"
WATCH_RELEASES = "distro/watch"
TOOLBAR_STYLE = "toolbar/style"
MENU_BAR = "gtk/menubar"
STALE_DAYS = STALE_DAYS_KEY  # also read by the tray checker, kram.notifier.stale_days


@dataclass(frozen=True)
class Pref:
    key: str                                    # the settings key
    kind: Literal["bool", "choice", "int"]
    default: Any
    label: str                                  # translated, as the menu or dialog shows it
    tip: str = ""
    choices: tuple[tuple[str, str], ...] = ()   # (value, label) of a "choice"
    range: tuple[int, int] = (0, 0)             # the smallest and largest value of an "int"
    toolkits: frozenset[str] = BOTH             # a front end not listed ignores the setting entirely
    visible: Callable[[], bool] = lambda: True
    section: str = "settings"                   # "settings": the Settings menu; "notifications": that dialog


def _on_fedora() -> bool:
    return distro.running_release() is not None


def _prefs() -> tuple[Pref, ...]:
    return (
        # Synaptic's "Clicking on the status icon marks the most likely action", off by default there too
        Pref(STATUS_CLICK, "bool", False, _("Clicking the status icon marks the likely action"),
             _("A click on the status icon unmarks a marked package, marks one that is not installed for "
               "installation and one with an upgrade for upgrade. Otherwise it opens the action menu, as "
               "right-clicking does.")),
        Pref(WATCH_RELEASES, "bool", True, _("Watch Fedora Releases"),
             _("On Reload, ask Fedora's Bodhi service whether a new release is out"), visible=_on_fedora),
        Pref(TOOLBAR_STYLE, "choice", "system", _("Toolbar"), toolkits=frozenset({"qt"}), choices=(
            ("system", _("Follow System Settings")),
            ("under", _("Text Under Icons")),
            ("beside", _("Compact: Text Beside Icons")),
            ("icons", _("Icons Only")),
        )),
        Pref(MENU_BAR, "bool", False, _("Show Menu Bar"), toolkits=frozenset({"gtk"})),
        Pref(STALE_DAYS, "int", STALE_DAYS_DEFAULT, _("Warn when the package information is older than:"), range=(1, 365),
             section="notifications"),
    )


PREFS: tuple[Pref, ...] = _prefs()  # in menu order
changed = Signal()  # (key): a setting was changed through `set_value`


def pref(key: str) -> Pref:
    return next(p for p in PREFS if p.key == key)


def prefs_for(toolkit: str, section: str = "settings") -> list[Pref]:
    """The settings of `section` a front end of `toolkit` shows, in order (whether visible or not)."""
    return [p for p in PREFS if toolkit in p.toolkits and p.section == section]


def value(p: Pref | str) -> Any:
    p = pref(p) if isinstance(p, str) else p
    v = store.get(p.key, p.default)
    if p.kind == "choice" and v not in {c for c, _label in p.choices}:
        return p.default
    if p.kind == "int" and p.range != (0, 0):
        return min(max(v, p.range[0]), p.range[1])
    return v


def set_value(p: Pref | str, v: Any) -> None:
    p = pref(p) if isinstance(p, str) else p
    if v == value(p) and store.contains(p.key):
        return
    store.set(p.key, v)
    changed.emit(p.key)


def days_suffix(days: int) -> str:
    """The unit after the stale-days number."""
    return " " + ngettext("day", "days", days)
