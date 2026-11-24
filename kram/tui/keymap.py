"""The terminal's keys for the actions of kram.app.actions (docs/TUI_SPEC.md §6.5, §6.6): one table, from which the
window and the package list take their bindings, the menu shows each entry's key and the Keys dialog lists them.

The GUIs' shortcuts are not used: a terminal cannot send some of them (`Ctrl+Shift+Z` arrives as `ctrl+z`,
`Ctrl+Shift+R` as `ctrl+r`), and a letter is quicker where no text field takes it. Keys are Textual's key names;
`key_name` writes them as hints and the menu do (§4.5).
"""
from ..app.actions import mark_id
from ..core.marks import Action
from .glyphs import UNICODE, Glyphs

# the window's keys (KramApp) and the package list's (PackageTable), in Textual's names
ACTION_KEYS: dict[str, tuple[str, ...]] = {
    "find": ("slash", "ctrl+f"),
    "reload": ("f5", "ctrl+r"),
    "reload_cache": ("R",),
    "apply": ("a", "ctrl+p"),
    "mark_upgrades": ("U", "ctrl+u"),
    "unmark_all": ("Z",),
    "history": ("ctrl+h",),
    "save_marks": ("ctrl+s",),
    "read_marks": ("ctrl+o",),
    "quit": ("q", "ctrl+q"),
    "back": ("alt+left",),
    # `+` marks what the row can get: installation, or the upgrade of an installed package
    mark_id(Action.INSTALL): ("plus", "insert"),
    mark_id(Action.UPGRADE): ("plus", "insert"),
    mark_id(Action.REMOVE): ("minus", "delete"),
    "unmark": ("z", "ctrl+z"),
    # `=` locks an unlocked version and unlocks a locked one
    "lock": ("equals_sign",),
    "unlock": ("equals_sign",),
    "copy_name": ("y",),
    "copy_nevra": ("Y",),
}
# the window's actions bound through KramApp.action_run; find, quit and back have actions of their own
WINDOW_RUN = ("reload", "reload_cache", "apply", "mark_upgrades", "unmark_all", "history", "save_marks", "read_marks")
MENU_KEYS = ("m", "f9")
KEYS_KEYS = ("question_mark", "f1")
# the Menu key arrives as f16 and Shift+F10 as f22 in xterm's encoding (§6.6)
CONTEXT_KEYS = ("full_stop", "menu", "f16", "shift+f10", "f22")

_NAMES = {
    "slash": "/", "question_mark": "?", "plus": "+", "minus": "-", "equals_sign": "=", "full_stop": ".",
    "left_square_bracket": "[", "right_square_bracket": "]", "insert": "ins", "delete": "del", "escape": "esc",
    "pageup": "pgup", "pagedown": "pgdn",
}


def key_name(key: str, g: Glyphs = UNICODE) -> str:
    """A Textual key name as hints write it: `/`, `ctrl+f`, `f5`, `alt+←` (`alt+<-` where the terminal is not
    UTF-8)."""
    *mods, base = key.split("+")
    arrows = {"up": g.up, "down": g.down, "left": g.left, "right": g.right}
    return "+".join([*mods, arrows.get(base) or _NAMES.get(base, base)])


def bindings_key(action_id: str) -> str:
    """The keys of an action as a Binding takes them."""
    return ",".join(ACTION_KEYS[action_id])


def action_key(action_id: str, g: Glyphs = UNICODE) -> str:
    """The key the menu shows for an action: its first one; "" when it has none."""
    keys = ACTION_KEYS.get(action_id)
    return key_name(keys[0], g) if keys else ""
