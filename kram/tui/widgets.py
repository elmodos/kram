"""The controls of the terminal front end that Textual has no look for that fits (docs/TUI_SPEC.md §4.3, §8):

- `Button`: `< Apply >`, one line, as dialog(1) and whiptail draw it. Textual's own Button is three lines high and
  does not fit a narrow terminal (T14).
- `CheckBox`: `[x] Label`, the one checkbox look everywhere (T21); Textual's Checkbox and SelectionList each look
  different.
- `ChoiceList`: a short modal list (views, tabs, sort columns, schemes) that returns the chosen value.
- `PopupMenu`: a context menu, with separators and disabled items.
- `hint`: key hints for a panel's or a dialog's bottom border (§4.5).

They draw with the styles of a 16-colour terminal only (reverse, bold, dim) and take colours from roles, so they read
the same in every scheme.
"""
from collections.abc import Hashable, Sequence

from rich.cells import cell_len
from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from ..i18n import _
from .palette import role


def hint(*pairs: tuple[str, str]) -> Text:
    """Key hints: each key in the key role, then the word for what it does; lower case, as the key is typed. A Text,
    not markup: Textual's markup has no working escape for "[", and "[ prev  ] next" is a common hint."""
    t = Text()
    for i, (key, label) in enumerate(pairs):
        if i:
            t.append("  ")
        t.append(key, role("key"))
        t.append(f" {label}")
    return t


class Button(Widget, can_focus=True):
    """A one-line button. Focused: reverse; the default button (variant "primary"): bold; a dangerous one
    ("error"): the error colour; a disabled one: dim, not focusable (Tab skips it) and deaf to keys and clicks.
    Enter, space or a click presses it."""

    class Pressed(Message):
        def __init__(self, button: "Button"):
            super().__init__()
            self.button = button

        @property
        def control(self) -> "Button":
            return self.button

    BINDINGS = [Binding("enter,space", "press", show=False)]
    DEFAULT_CSS = """
    Button { width: auto; height: 1; padding: 0; background: transparent; color: $foreground; }
    Button.-primary { text-style: bold; }
    Button.-error { color: $error; }
    Button:focus { text-style: reverse bold; }
    Button.-off { text-style: dim; }
    """

    def __init__(self, label: str, id: str | None = None, variant: str = "default", disabled: bool = False,
                 classes: str = ""):
        super().__init__(id=id, classes=f"-{variant} {classes}".strip())
        self.label = label
        self.variant = variant
        self.enabled = not disabled
        self.can_focus = not disabled
        self.set_class(disabled, "-off")

    def render(self) -> Text:
        return Text(f"< {self.label} >")

    def set_label(self, label: str) -> None:
        self.label = label
        self.refresh(layout=True)

    def set_enabled(self, on: bool) -> None:
        # not Textual's `disabled`: that dims by blending, which a 16-colour terminal cannot show
        moving = not on and self.has_focus
        self.enabled = on
        self.can_focus = on
        self.set_class(not on, "-off")
        if moving and self.is_attached:
            self.screen.focus_next()

    def action_press(self) -> None:
        if self.enabled:
            self.post_message(self.Pressed(self))

    def on_click(self) -> None:
        self.action_press()


class CheckBox(Widget, can_focus=True):
    """`[x] Label` / `[ ] Label`; space, Enter or a click ticks it. The tick is in the marked role."""

    class Changed(Message):
        def __init__(self, checkbox: "CheckBox", value: bool):
            super().__init__()
            self.checkbox, self.value = checkbox, value

        @property
        def control(self) -> "CheckBox":
            return self.checkbox

    BINDINGS = [Binding("space,enter", "toggle", show=False)]
    DEFAULT_CSS = """
    CheckBox { width: auto; height: 1; background: transparent; color: $foreground; }
    CheckBox:focus { text-style: reverse; }
    """

    def __init__(self, label: str, value: bool = False, id: str | None = None, classes: str = ""):
        super().__init__(id=id, classes=classes)
        self.label = label
        self.value = value

    def render(self) -> Text:
        t = Text()
        t.append("[x]" if self.value else "[ ]", role("marked") if self.value else Style())
        t.append(f" {self.label}")
        return t

    def set_value(self, value: bool) -> None:
        """Without the Changed message: the program sets it, the user did not."""
        self.value = value
        self.refresh()

    def action_toggle(self) -> None:
        self.value = not self.value
        self.refresh()
        self.post_message(self.Changed(self, self.value))

    def on_click(self) -> None:
        self.action_toggle()


class ChoiceList(ModalScreen):
    """A short list over everything else, the current item highlighted: Enter picks (the screen's result is the
    item's value), Esc closes (None). Its frame is the app's `.window` rule, as every modal window's."""

    BINDINGS = [Binding("escape", "close", show=False)]
    DEFAULT_CSS = """
    ChoiceList { align: center middle; }
    ChoiceList > OptionList { width: auto; min-width: 30; max-width: 90%; height: auto; max-height: 80%;
                              padding: 0 1; }
    """

    def __init__(self, title: str, items: Sequence[tuple[Hashable, str]], current: Hashable | None = None):
        super().__init__()
        self.title_text = title
        self.values = [v for v, _label in items]
        self.labels = [label for _v, label in items]
        self.current = current

    def compose(self) -> ComposeResult:
        menu = OptionList(*self.labels, classes="window")
        menu.border_title = self.title_text
        menu.border_subtitle = hint(("enter", _("pick")), ("esc", _("close")))
        yield menu

    def on_mount(self) -> None:
        menu = self.query_one(OptionList)
        if self.current in self.values:
            menu.highlighted = self.values.index(self.current)
        elif self.values:
            menu.highlighted = 0
        menu.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.dismiss(self.values[event.option_index])

    def action_close(self) -> None:
        self.dismiss(None)


class PopupMenu(ModalScreen):
    """A small menu next to what it is about (a context menu): `items` are (label, enabled) pairs, None between
    groups of them for a separator. The screen's result is the index in `items` of the one run, None when closed.
    Disabled items are dim and cannot be run; the cursor skips them. `at` is the screen cell to open at; the menu
    moves left and up as far as it must to stay on the screen."""

    BINDINGS = [Binding("escape", "close", show=False)]
    DEFAULT_CSS = """
    PopupMenu { align: left top; }
    PopupMenu > OptionList { width: auto; max-width: 90%; height: auto; max-height: 90%; padding: 0 1; }
    """

    def __init__(self, title: str, items: Sequence[tuple[str, bool] | None], at: tuple[int, int] = (0, 0)):
        super().__init__()
        self.title_text = title
        self.items = list(items)
        self.at = at

    def compose(self) -> ComposeResult:
        options: list[Option | None] = []
        for i, item in enumerate(self.items):
            if item is None:
                if options and options[-1] is not None:  # never two separators in a row, nor one first
                    options.append(None)
            else:
                options.append(Option(Text(item[0]), id=str(i), disabled=not item[1]))
        while options and options[-1] is None:
            options.pop()
        menu = OptionList(*options, classes="window")
        menu.border_title = self.title_text
        menu.border_subtitle = hint(("enter", _("pick")), ("esc", _("close")))
        yield menu

    def on_mount(self) -> None:
        menu = self.query_one(OptionList)
        labels = [item[0] for item in self.items if item is not None]
        # the frame and the padding: 4 cells across, 2 lines down; one line for each separator
        width = max([cell_len(label) for label in labels] + [cell_len(self.title_text) + 2, 20]) + 4
        height = len(menu.options) + 2 + sum(1 for item in self.items if item is None)
        screen_w, screen_h = self.app.size
        x, y = self.at
        menu.styles.offset = (max(0, min(x, screen_w - width)), max(0, min(y, screen_h - height)))
        first = next((i for i, option in enumerate(menu.options) if not option.disabled), None)
        menu.highlighted = first
        menu.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.dismiss(int(event.option.id))

    def action_close(self) -> None:
        self.dismiss(None)
