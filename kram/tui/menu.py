"""The menus of the terminal front end (docs/TUI_SPEC.md §7.7): the GUIs' menu bar as a popup, and the package
list's context menu. Both are built from kram.app.actions, so an action added there shows up here too; what an
entry runs is the window's (`MainWindow.run_action`).

The menu popup (`m`, `f9`) has the menus of `menu_bar()` on the left and the chosen one's entries on the right,
each with its key in the terminal (kram.tui.keymap, not the GUIs' shortcuts, §6.6). A submenu opens in place with a
"← back" line above its entries; Downgrade to Version is filled when it opens, from the details of the package. An
entry that is off is dim and can still get the cursor, so that the status line under the entries can say why it is
off; for one that is on it shows the action's tooltip. The Settings menu's preferences come from the registry for
the toolkit "tui" (kram.app.preferences): a bool is a `[x]` entry ticked in place, a choice a submenu of `(•)`
entries; Colours… and Columns… follow them (§7.7.3).

An entry that runs something closes the popup first and runs from its dismissal callback (the screen's result is
what to run), so that a dialog it opens is pushed once the popup is gone (§11.3.8).
"""
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from rich.cells import cell_len, set_cell_size
from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from ..app import preferences
from ..app.actions import DynamicItem, Menu, MenuItem, menu_bar, table_menu
from ..app.preferences import Pref
from ..i18n import _
from .dialogs.columns import columns_label
from .keymap import action_key
from .palette import role
from .widgets import PopupMenu, hint

TOOLKIT = "tui"
ENTRIES_MAX = 64  # the entries' column at most, in cells; less when the terminal is narrower
STATUS_LINES = 3  # the status line under the columns: its rule and two lines of text (the app's CSS)


def menu_title(menu: Menu) -> str:
    """Qt's "&File" without the mnemonic's "&": a terminal menu is reached by its arrows."""
    return menu.title.replace("&&", "\0").replace("&", "").replace("\0", "&")


def colours_label() -> str:
    return _("Colours…")


@dataclass
class Entry:
    """A line of the entries' column. `kind`: "action", "submenu", "dynamic" (a DynamicItem), "bool" and "choice"
    (preferences), "value" (one choice of a choice preference), "colours", "columns", "back"."""
    kind: str
    label: str
    key: str = ""
    enabled: bool = True
    note: str = ""          # for the status line: why it is off, else what it does
    action: str | None = None
    submenu: Menu | None = None
    item: DynamicItem | None = None
    pref: Pref | None = None
    value: Any = None


# ---------------------------------------------------------------- the entries: built and drawn without the screen

def menu_entries(main, items: tuple[MenuItem, ...], g, scheme: str, fill: bool = True) -> list[Entry | None]:
    """The lines of a menu as the window's state makes them (`main`: the MainWindow; None separators). `fill`
    False: without asking the window anything, to measure."""
    out: list[Entry | None] = []
    for item in items:
        if item.separator:
            out.append(None)
        elif item.action is not None:
            if fill and not main.action_visible(item.action):
                continue
            d = main.defs[item.action]
            on = main.action_enabled(item.action) if fill else True
            out.append(Entry("action", d.label, action_key(item.action, g), on,
                             d.tip if on else main.disabled_reason(item.action), action=item.action))
        elif item.submenu is not None:
            sub = item.submenu
            state_id = {"downgrade": "downgrade", "mark_upgrades": "mark_upgrades_menu"}.get(sub.id)
            on = main.action_enabled(state_id) if fill and state_id else True
            out.append(Entry("submenu", menu_title(sub), g.right, on, "" if on else main.disabled_reason(state_id),
                             submenu=sub))
        elif item.prefs is not None:
            out += pref_entries(item.prefs, g, scheme, fill)
    return out


def pref_entries(section: str, g, scheme: str, fill: bool = True) -> list[Entry | None]:
    """The registry's preferences for the terminal in `section`; Settings also has Colours… and Columns…."""
    out: list[Entry | None] = []
    for pref in preferences.prefs_for(TOOLKIT, section):
        if pref.key == preferences.TUI_SCHEME or (fill and not pref.visible()):
            continue  # the scheme has its own dialog, Colours…
        if pref.kind == "bool":
            out.append(Entry("bool", pref.label, note=pref.tip, pref=pref))
        elif pref.kind == "choice":
            label = dict(pref.choices).get(preferences.value(pref), "") if fill else ""
            out.append(Entry("choice", pref.label, g.right, note=label or pref.tip, pref=pref))
    if section == "settings":
        schemes = preferences.pref(preferences.TUI_SCHEME)
        out.append(Entry("colours", colours_label(), note=dict(schemes.choices).get(scheme, schemes.label)))
        out.append(Entry("columns", columns_label(),
                         note=_("Which columns the package list shows, their order and their widths")))
    return out


def choice_entries(pref: Pref) -> list[Entry | None]:
    return [Entry("value", label, pref=pref, value=value) for value, label in pref.choices]


def dynamic_entries(items: list[DynamicItem]) -> list[Entry | None]:
    return [Entry("dynamic", i.label, enabled=i.enabled and i.run is not None, note=i.tip, item=i) for i in items]


def _prefix_len(e: Entry) -> int:
    return 4 if e.kind in ("bool", "value") else 0


def entries_width(main, items: tuple[MenuItem, ...], g, scheme: str) -> int:
    """The cells the widest entry of `items` asks for, its submenus' entries included."""
    widest = 0
    for e in menu_entries(main, items, g, scheme, fill=False):
        if e is not None:
            widest = max(widest, _prefix_len(e) + cell_len(e.label) + (cell_len(e.key) + 2 if e.key else 0))
        if e is not None and e.submenu is not None:
            widest = max(widest, entries_width(main, e.submenu.items, g, scheme))
        if e is not None and e.kind == "choice":
            widest = max(widest, *(4 + cell_len(label) for _value, label in e.pref.choices))
    return widest + 1


def entry_line(e: Entry, width: int, g) -> Text:
    """An entry as one line `width` cells wide: the tick of a preference, the label cut with "…", the key or the
    submenu's arrow at the right; dim when it is off."""
    prefix, ticked = "", False
    if e.kind == "bool":
        ticked = bool(preferences.value(e.pref))
        prefix = "[x] " if ticked else "[ ] "
    elif e.kind == "value":
        ticked = preferences.value(e.pref) == e.value
        prefix = f"({g.item}) " if ticked else "( ) "
    right = e.key
    room = width - cell_len(prefix) - (cell_len(right) + 2 if right else 0)
    label = e.label
    if cell_len(label) > room:
        label = set_cell_size(label, max(0, room - cell_len(g.ellipsis))) + g.ellipsis
    line = Text(no_wrap=True, overflow="crop")
    base = Style(dim=True) if not e.enabled else Style()
    if prefix:
        line.append(prefix[:3], role("marked") if ticked else base)
        line.append(" ", base)
    line.append(label, base + Style(bold=True) if e.kind == "back" else base)
    if right:
        line.append(" " * (width - line.cell_len - cell_len(right)), base)
        line.append(right, base + role("muted"))
    return line


class MenuPopup(ModalScreen):
    """The screen's result: what to run (a callable without arguments), or None when closed."""

    BINDINGS = [
        Binding("escape,f9", "close", show=False),  # f9 opens and closes it, as in mc
        Binding("left", "left", show=False),
        Binding("right", "right", show=False),
    ]

    def __init__(self, main):
        super().__init__()
        self.main = main
        self.menus = menu_bar()
        self.entries: list[Entry | None] = []  # the right column's lines; None for a separator
        self.stack: list[Entry] = []           # the submenus opened in place, the innermost last
        self.menu_index = 0                    # the menu shown, on the left
        self.width = 0

    def compose(self) -> ComposeResult:
        g = self.app.glyphs
        box = Vertical(classes="window menu", id="menu-box")
        box.border_title = _("Menu")
        box.border_subtitle = hint(("enter", _("run")), (f"{g.left} {g.right}", _("move")), ("esc", _("close")))
        with box:
            with Horizontal(id="menu-columns"):
                yield OptionList(*[menu_title(m) for m in self.menus], id="menu-titles")
                yield OptionList(id="menu-entries")
            yield Static("", id="menu-status", markup=False)

    def on_mount(self) -> None:
        titles = self.query_one("#menu-titles", OptionList)
        titles.styles.width = max(cell_len(menu_title(m)) for m in self.menus) + 3  # its padding and rule
        # the double frame, the entries' padding and their scrollbar's cell
        room = self.app.size.width - int(titles.styles.width.value) - 5
        g = self.app.glyphs
        needed = max(entries_width(self.main, m.items, g, self.app.scheme) for m in self.menus)
        self.width = max(20, min(ENTRIES_MAX, needed, room))
        entries = self.query_one("#menu-entries", OptionList)
        entries.styles.width = self.width + 3  # its padding, and a cell for the scrollbar when it scrolls
        # the columns scroll within 90% of the screen, less the frame and the status line under them
        lines = max(3, self.app.size.height * 9 // 10 - 2 - STATUS_LINES)
        entries.styles.max_height = titles.styles.max_height = lines
        titles.highlighted = 0
        self.show(self.menus[0].items)
        titles.focus()

    # ---------------------------------------------------------------- showing them

    def show(self, items: tuple[MenuItem, ...] | list[Entry | None], back: str = "") -> None:
        """The entries of a menu (MenuItems) or ready lines (Entries); `back`: a submenu's title, on its "back"
        line."""
        g = self.app.glyphs
        lines = (menu_entries(self.main, items, g, self.app.scheme) if items and isinstance(items[0], MenuItem)
                 else list(items))
        if back:
            lines.insert(0, Entry("back", f"{self.app.glyphs.left} {back}", note=_("Back")))
        self.entries = lines
        options: list[Option | None] = []
        for i, e in enumerate(lines):
            if e is None:
                if options and options[-1] is not None:  # never two in a row, nor one first
                    options.append(None)
            else:
                options.append(Option(entry_line(e, self.width, g), id=str(i)))
        while options and options[-1] is None:
            options.pop()
        column = self.query_one("#menu-entries", OptionList)
        column.clear_options()
        column.add_options(options)
        column.highlighted = 0 if options else None
        self._status(lines[int(options[0].id)] if options else None)

    def show_menu(self, index: int) -> None:
        """The menu at `index` of the menu bar, as ↑ ↓ on the menus' column show it."""
        self.stack = []
        self.menu_index = index
        self.query_one("#menu-titles", OptionList).highlighted = index
        self.show(self.menus[index].items)

    def entry(self, label: str) -> Entry:
        """The shown entry whose label starts with `label`."""
        found = next((e for e in self.entries if e is not None and e.label.startswith(label)), None)
        if found is None:
            raise LookupError(label)
        return found

    def _status(self, e: Entry | None) -> None:
        self.query_one("#menu-status", Static).update(e.note if e is not None else "")

    def current(self) -> Entry | None:
        column = self.query_one("#menu-entries", OptionList)
        if column.highlighted is None:
            return None
        return self.entries[int(column.get_option_at_index(column.highlighted).id)]

    # ---------------------------------------------------------------- keys and choices

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        event.stop()
        if event.option_list.id == "menu-titles":
            if self.stack or event.option_index != self.menu_index:
                self.stack = []
                self.menu_index = event.option_index
                self.show(self.menus[event.option_index].items)
        else:
            self._status(self.entries[int(event.option.id)])

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if event.option_list.id == "menu-titles":
            self.action_right()
            return
        self.choose(self.entries[int(event.option.id)])

    def choose(self, e: Entry) -> None:
        if not e.enabled:
            self.app.bell()  # the status line says why
            return
        main = self.main
        if e.kind == "action":
            self.dismiss(lambda action=e.action: main.run_action(action))
        elif e.kind == "dynamic":
            self.dismiss(e.item.run)
        elif e.kind == "colours":
            self.dismiss(self.app.open_colours)
        elif e.kind == "columns":
            self.dismiss(main.open_columns)
        elif e.kind == "bool":
            preferences.set_value(e.pref, not preferences.value(e.pref))
            self._redraw(e)
        elif e.kind == "value":
            preferences.set_value(e.pref, e.value)
            self.back()
        elif e.kind in ("submenu", "choice"):
            self.open(e)
        elif e.kind == "back":
            self.back()

    def open(self, e: Entry) -> None:
        self.stack.append(e)
        self._show_top()

    def back(self) -> None:
        opened = self.stack.pop()
        if self.stack:
            self._show_top()
        else:
            self.show(self.menus[self.menu_index].items)
        # the cursor back on the entry the submenu was opened from
        column = self.query_one("#menu-entries", OptionList)
        for index in range(column.option_count):
            line = self.entries[int(column.get_option_at_index(index).id)]
            if line is not None and line.label == opened.label and line.kind == opened.kind:
                column.highlighted = index
                break

    def _show_top(self) -> None:
        e = self.stack[-1]
        if e.kind == "choice":
            self.show(choice_entries(e.pref), back=e.label)
        elif e.submenu.id == "downgrade":  # filled now, for the package under the cursor
            self.show(dynamic_entries(self.main.browser.downgrade_items()), back=e.label)
        else:
            self.show(e.submenu.items, back=e.label)

    def _redraw(self, e: Entry) -> None:
        column = self.query_one("#menu-entries", OptionList)
        index = next(i for i, line in enumerate(self.entries) if line is e)
        column.replace_option_prompt(str(index), entry_line(e, self.width, self.app.glyphs))

    def action_left(self) -> None:
        """← in the entries: out of a submenu, else to the menus."""
        if self.query_one("#menu-entries").has_focus and self.stack:
            self.back()
        else:
            self.query_one("#menu-titles").focus()

    def action_right(self) -> None:
        """→: from the menus to their entries; on a submenu, into it."""
        entries = self.query_one("#menu-entries", OptionList)
        if not entries.has_focus:
            entries.focus()
            return
        e = self.current()
        if e is not None and e.kind in ("submenu", "choice"):
            self.choose(e)

    def action_close(self) -> None:
        self.dismiss(None)


# ---------------------------------------------------------------- the package list's context menu (§7.7.2)

def open_table_menu(main, at: tuple[int, int], items: tuple[MenuItem, ...] | None = None) -> None:
    """`table_menu()` as a popup at the screen cell `at`, or `items` (the status cell's menu, the Package menu's
    items); Downgrade to Version opens a second one there with the package's older versions."""
    g = main.app.glyphs
    lines: list[tuple[MenuItem | None, tuple[str, bool, str] | None]] = []
    for item in items if items is not None else table_menu().items:
        if item.separator:
            lines.append((None, None))
        elif item.action is not None and main.action_visible(item.action):
            lines.append((item, (main.defs[item.action].label, main.action_enabled(item.action),
                                 action_key(item.action, g))))
        elif item.submenu is not None and item.submenu.id == "downgrade":
            lines.append((item, (menu_title(item.submenu), main.action_enabled("downgrade"), g.right)))
    row = main.list.current_row()

    def chosen(i: int | None) -> None:
        if i is None:
            return
        item = lines[i][0]
        if item.submenu is not None:
            items = main.browser.downgrade_items()
            main.app.push_screen(PopupMenu(menu_title(item.submenu),
                                           [(d.label, d.enabled and d.run is not None) for d in items], at),
                                 lambda j: j is not None and items[j].run())
        else:
            main.run_action(item.action)
    main.app.push_screen(PopupMenu(row.name if row is not None else "", [line for _item, line in lines], at), chosen)


def run_result(run: Callable[[], None] | None) -> None:
    """The menu popup's dismissal callback."""
    if run is not None:
        run()
