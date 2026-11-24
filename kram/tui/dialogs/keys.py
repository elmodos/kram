"""The keys of the focused panel and of the window (docs/TUI_SPEC.md §10.20), as `?` and `f1` show them: built from
the bindings themselves (`Screen.active_bindings`), so that the list cannot drift from what the keys do. A binding
with a description is listed; several keys of one description share a line ("↑ ↓ k j  Move the cursor").

Two columns, the keys and what they do, under a heading for each part; what does not fit scrolls.
"""
from collections.abc import Sequence

from rich.console import Group
from rich.table import Table
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.dom import DOMNode
from textual.screen import ModalScreen, Screen
from textual.widgets import Static

from ...i18n import _
from ..glyphs import Glyphs
from ..keymap import key_name
from ..palette import role
from ..widgets import hint

Section = tuple[str, list[tuple[str, str]]]  # a heading, and (keys, what they do) under it


def _textual_words(node: DOMNode) -> set[str]:
    """The descriptions of the bindings `node` has from Textual's own classes (a scroll view's ctrl+pgup "Page
    Left"): not Kram's words, nor translated. A class that does not inherit its bases' bindings (KramApp) ends the
    search."""
    words = set()
    for cls in type(node).__mro__:
        if cls.__module__.startswith("textual."):
            words |= {b.description for b in cls.__dict__.get("BINDINGS", ()) if isinstance(b, Binding)}
        if not cls.__dict__.get("_inherit_bindings", True):
            break
    return words


def key_sections(screen: Screen, scope: str, g: Glyphs) -> list[Section]:
    """The keys active on `screen` now: those of the focused widget and its panel under `scope` (the panel's
    name), then the app's under "Window". Textual's own keys (Tab between widgets, a scroll view's) are left out:
    they carry no words of Kram's."""
    parts: dict[bool, dict[str, list[str]]] = {False: {}, True: {}}
    for key, active in screen.active_bindings.items():
        binding = active.binding
        if not binding.description or binding.system or isinstance(active.node, Screen) \
                or binding.description in _textual_words(active.node):
            continue
        keys = parts[isinstance(active.node, App)].setdefault(binding.description, [])
        name = key_name(key, g)
        if name not in keys:
            keys.append(name)
    sections = []
    for window, heading in ((False, scope), (True, _("Window"))):
        if parts[window]:
            sections.append((heading, [(" ".join(keys), words) for words, keys in parts[window].items()]))
    return sections


def sections_view(sections: Sequence[Section]) -> Group:
    """Each heading, then its keys and their words in two columns; a long cell wraps within its column."""
    parts = []
    for i, (heading, rows) in enumerate(sections):
        parts.append(Text(("\n" if i else "") + heading, "bold"))
        table = Table.grid(padding=(0, 2, 0, 0), expand=True)
        table.add_column(ratio=2, style=role("key"))
        table.add_column(ratio=3)
        for keys, words in rows:
            table.add_row(keys, words)
        parts.append(table)
    return Group(*parts)


class KeysDialog(ModalScreen):
    BINDINGS = [Binding("escape,question_mark,f1", "close", show=False)]

    def __init__(self, sections: Sequence[Section]):
        super().__init__()
        self.sections = sections

    def compose(self) -> ComposeResult:
        box = Vertical(classes="window dialog keys")
        box.border_title = _("Keys")
        g = self.app.glyphs
        box.border_subtitle = hint((f"{g.up} {g.down}", _("scroll")), ("esc", _("close")))
        with box:
            with VerticalScroll(id="keys-list"):
                yield Static(sections_view(self.sections), markup=False)

    def on_mount(self) -> None:
        self.query_one("#keys-list").focus()

    def action_close(self) -> None:
        self.dismiss(None)
