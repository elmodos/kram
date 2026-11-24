"""The characters the terminal front end draws with, in two sets: one for a terminal that speaks UTF-8, one for a
terminal that does not (`LANG=C`, the Linux console without a Unicode font), where box drawing, arrows and the
status symbols would come out as question marks (docs/TUI_SPEC.md §4.4, §7.3.4, §9.6).

The status column has a set of its own: a setting asks for letters on a UTF-8 terminal too (§13), so that the
column reads the same on every terminal a user works in.
"""
import os
from collections.abc import Mapping
from dataclasses import dataclass

from ..app import preferences
from ..core.marks import Action
from ..core.model import Status

_C_LOCALES = ("", "C", "POSIX")


def is_utf8(environ: Mapping[str, str] = os.environ) -> bool:
    """Whether the terminal's locale is UTF-8, from the locale variables as the C library reads them.

    Python's own view cannot tell: its UTF-8 mode says UTF-8 whatever the locale, and in the C locale it sets
    LC_CTYPE=C.UTF-8 itself (PEP 538) before any code runs. That coerced value is taken for what it replaced."""
    lc_all, lc_ctype, lang = (environ.get(v, "") for v in ("LC_ALL", "LC_CTYPE", "LANG"))
    if not lc_all and lc_ctype == "C.UTF-8" and lang in _C_LOCALES:
        return False
    value = lc_all or lc_ctype or lang
    if value in _C_LOCALES:
        return False
    codeset = value.partition(".")[2].partition("@")[0]
    return codeset.lower().replace("-", "") == "utf8"


@dataclass(frozen=True)
class Glyphs:
    left: str
    right: str
    up: str
    down: str
    ellipsis: str
    times: str            # "40×12"
    bullet: str           # the current view in the sidebar's list of views
    selected: str         # the package list's margin of a row in a selection of several (§7.3.6)
    warning: str          # before a warning on the top line (§5.4)
    panel_border: str     # Textual border types: a panel's single line, a modal window's double one
    modal_border: str


UNICODE = Glyphs(left="←", right="→", up="↑", down="↓", ellipsis="…", times="×", bullet="●", selected="▌", warning="!",
                 panel_border="solid", modal_border="double")
ASCII = Glyphs(left="<-", right="->", up="^", down="v", ellipsis="...", times="x", bullet="*", selected="|", warning="!",
               panel_border="ascii", modal_border="ascii")


@dataclass(frozen=True)
class StatusGlyphs:
    """The first two cells of a package row: its state or its mark, then a flag."""
    status: Mapping[Status, str]
    marks: Mapping[Action, str]
    locked: str = "L"
    blocked: str = "!"
    security: str = "s"


SYMBOLS = StatusGlyphs(
    status={Status.INSTALLED: "■", Status.NOT_INSTALLED: "□", Status.UPGRADABLE: "▲", Status.NEWER: "▼",
            Status.ORPHAN: "◆", Status.UNNEEDED: "◇"},
    marks={Action.INSTALL: "+", Action.UPGRADE: "↑", Action.REMOVE: "-", Action.REINSTALL: "~",
           Action.DOWNGRADE: "↓", Action.MARK_USER: "*", Action.MARK_DEP: "*"},
)
LETTERS = StatusGlyphs(
    status={Status.INSTALLED: "i", Status.NOT_INSTALLED: "p", Status.UPGRADABLE: "u", Status.NEWER: "n",
            Status.ORPHAN: "o", Status.UNNEEDED: "a"},
    marks={Action.INSTALL: "+", Action.UPGRADE: "^", Action.REMOVE: "-", Action.REINSTALL: "~",
           Action.DOWNGRADE: "v", Action.MARK_USER: "*", Action.MARK_DEP: "*"},
)


def glyphs(utf8: bool | None = None) -> Glyphs:
    return UNICODE if (is_utf8() if utf8 is None else utf8) else ASCII


def status_glyphs(utf8: bool | None = None, setting: str | None = None) -> StatusGlyphs:
    """Symbols on a UTF-8 terminal unless the setting asks for letters; letters on any other."""
    setting = preferences.value(preferences.TUI_STATUS_GLYPHS) if setting is None else setting
    utf8 = is_utf8() if utf8 is None else utf8
    return SYMBOLS if utf8 and setting != "letters" else LETTERS
