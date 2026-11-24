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
TUI = frozenset({"tui"})
ALL = BOTH | TUI  # the settings the terminal front end has too (docs/TUI_SPEC.md §13.1)

STATUS_CLICK = "table/status_click"
WATCH_RELEASES = "distro/watch"
TOOLBAR_STYLE = "toolbar/style"
MENU_BAR = "gtk/menubar"
STALE_DAYS = STALE_DAYS_KEY  # also read by the tray checker, kram.notifier.stale_days
# the terminal front end's own (docs/TUI_SPEC.md §13)
TUI_SCHEME = "tui/scheme"
TUI_CENTRE_SCROLLING = "tui/centre_scrolling"
TUI_STATUS_GLYPHS = "tui/status_glyphs"
TUI_CONFIRM_QUIT = "tui/confirm_quit"
TUI_SIDEBAR_WIDTH = "tui/sidebar_width"
TUI_DETAILS_HEIGHT = "tui/details_height"
TUI_PINNED = "tui/pinned"
# the terminal's colour schemes: Textual's theme names, ours ("kram-…") made of the terminal's 16 colours only
TUI_SCHEME_DEFAULT = "textual-ansi"
TUI_ANSI_SCHEMES = frozenset({"textual-ansi", "kram-midnight", "kram-console"})


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
    # "settings": the Settings menu; "notifications": that dialog; "layout": kept by the window as it is used
    # (panel sizes and pins), in no menu
    section: str = "settings"


def _on_fedora() -> bool:
    return distro.running_release() is not None


def _prefs() -> tuple[Pref, ...]:
    return (
        # Synaptic's "Clicking on the status icon marks the most likely action", off by default there too
        Pref(STATUS_CLICK, "bool", False, _("Clicking the status icon marks the likely action"),
             _("A click on the status icon unmarks a marked package, marks one that is not installed for "
               "installation and one with an upgrade for upgrade. Otherwise it opens the action menu, as "
               "right-clicking does."), toolkits=ALL),
        Pref(WATCH_RELEASES, "bool", True, _("Watch Fedora Releases"),
             _("On Reload, ask Fedora's Bodhi service whether a new release is out"), visible=_on_fedora,
             toolkits=ALL),
        Pref(TOOLBAR_STYLE, "choice", "system", _("Toolbar"), toolkits=frozenset({"qt"}), choices=(
            ("system", _("Follow System Settings")),
            ("under", _("Text Under Icons")),
            ("beside", _("Compact: Text Beside Icons")),
            ("icons", _("Icons Only")),
        )),
        Pref(MENU_BAR, "bool", False, _("Show Menu Bar"), toolkits=frozenset({"gtk"})),
        Pref(STALE_DAYS, "int", STALE_DAYS_DEFAULT, _("Warn when the package information is older than:"), range=(1, 365),
             section="notifications"),
        *_tui_prefs(),
    )


def _tui_prefs() -> tuple[Pref, ...]:
    """The terminal front end's settings. Its menu lists them after the shared ones; the GUIs never see them."""
    return (
        Pref(TUI_SCHEME, "choice", TUI_SCHEME_DEFAULT, _("Colour scheme"), toolkits=TUI, choices=(
            ("textual-ansi", _("Terminal: 16 colours, follows the terminal")),
            ("kram-midnight", _("Midnight: 16 colours, blue")),
            ("kram-console", _("Console: 16 colours, black")),
            # Textual's own themes, by their names
            ("textual-dark", "Textual dark"),
            ("textual-light", "Textual light"),
            ("nord", "Nord"),
            ("gruvbox", "Gruvbox"),
            ("solarized-light", "Solarized light"),
            ("tokyo-night", "Tokyo Night"),
        )),
        Pref(TUI_CENTRE_SCROLLING, "bool", True, _("Centre the cursor when scrolling"), toolkits=TUI),
        Pref(TUI_STATUS_GLYPHS, "choice", "auto", _("Status glyphs"), toolkits=TUI, choices=(
            ("auto", _("Symbols, or letters when the terminal is not UTF-8")),
            ("letters", _("Letters")),
        )),
        Pref(TUI_CONFIRM_QUIT, "bool", True, _("Ask before quitting with changes not applied"), toolkits=TUI),
        Pref(TUI_SIDEBAR_WIDTH, "int", 28, _("Sidebar width"), toolkits=TUI, range=(16, 60), section="layout"),
        Pref(TUI_DETAILS_HEIGHT, "int", 12, _("Details height"), toolkits=TUI, range=(5, 40), section="layout"),
        # the panels shown beside and under the list in a wide terminal
        Pref(TUI_PINNED, "choice", "both", _("Pinned panels"), toolkits=TUI, section="layout", choices=(
            ("both", _("Sidebar and details")),
            ("sidebar", _("Sidebar")),
            ("details", _("Details")),
            ("none", _("Neither")),
        )),
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
