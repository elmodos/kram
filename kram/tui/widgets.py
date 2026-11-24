"""The controls of the terminal front end that Textual has no look for that fits (docs/TUI_SPEC.md §4.3, §8):

- `Button`: `< Apply >`, one line, as dialog(1) and whiptail draw it. Textual's own Button is three lines high and
  does not fit a narrow terminal (T14).
- `ButtonBar`: a dialog's buttons, on as many lines as they need.
- `CheckBox`: `[x] Label`, the one checkbox look everywhere (T21); Textual's Checkbox and SelectionList each look
  different.
- `ChoiceList`: a short modal list (views, tabs, sort columns, schemes) that returns the chosen value.
- `Choice`: a value from a list in one line of a form (`Name ↓`), the list a ChoiceList: what a drop-down is in the
  GUIs. Textual's Select draws a box three lines high.
- `Radio`: one of a few values side by side, `(•) all  ( ) any`, as RadioSet would, in one line.
- `PopupMenu`: a context menu, with separators and disabled items.
- `hint`: key hints for a panel's or a dialog's bottom border (§4.5).

They draw with the styles of a 16-colour terminal only (reverse, bold, dim) and take colours from roles, so they read
the same in every scheme.
"""
from collections.abc import Hashable, Sequence

from rich.cells import cell_len, set_cell_size
from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
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

    def get_content_width(self, container, viewport) -> int:
        # its label's, whatever the container's width (a container of `width: auto` gave it a few cells only)
        return cell_len(f"< {self.label} >")

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


class ButtonBar(Horizontal):
    """A dialog's buttons at the bottom right (§10), in groups (Horizontal containers of Buttons): all on one line,
    or one line per group when the line is too narrow for all of them (a narrow terminal, a long translation), so
    that no button is cut. `fit()` after a label changed; a resize fits by itself. Its look is the app's
    `.dialog .buttons` rules."""

    def on_resize(self) -> None:
        self.fit()

    def fit(self) -> None:
        needed = sum(cell_len(f"< {b.label} >") + b.styles.margin.left + b.styles.margin.right
                     for b in self.query(Button) if b.display)
        self.set_class(needed > self.size.width > 0, "-stacked")


class CheckBox(Widget, can_focus=True):
    """`[x] Label` / `[ ] Label`; space, Enter or a click ticks it. The tick is in the marked role. A disabled one is
    dim and deaf to keys and clicks, but keeps the focus: it is off only for a moment (the Apply dialog resolving
    again), and the focus jumping away from the box just ticked would lose the user's place."""

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
    CheckBox.-off { text-style: dim; }
    CheckBox.-off:focus { text-style: reverse dim; }
    """

    def __init__(self, label: str, value: bool = False, id: str | None = None, classes: str = ""):
        super().__init__(id=id, classes=classes)
        self.label = label
        self.value = value
        self.enabled = True

    def render(self) -> Text:
        t = Text()
        t.append("[x]" if self.value else "[ ]", role("marked") if self.value else Style())
        t.append(f" {self.label}")
        return t

    def set_value(self, value: bool) -> None:
        """Without the Changed message: the program sets it, the user did not."""
        self.value = value
        self.refresh()

    def set_label(self, label: str) -> None:
        self.label = label
        self.refresh(layout=True)

    def set_enabled(self, on: bool) -> None:
        # not Textual's `disabled`: that dims by blending, which a 16-colour terminal cannot show, and drops the focus
        self.enabled = on
        self.set_class(not on, "-off")

    def action_toggle(self) -> None:
        if not self.enabled:
            return
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


class Choice(Widget, can_focus=True):
    """A value of `options` ((value, label) pairs) in one line: the label, cut with the ellipsis, and an arrow after
    it. Enter, space or a click lists the values (ChoiceList, `title` in its frame); ← → step through them in
    place. `Changed` after the user changed it."""

    class Changed(Message):
        def __init__(self, choice: "Choice", value: Hashable):
            super().__init__()
            self.choice, self.value = choice, value

        @property
        def control(self) -> "Choice":
            return self.choice

    BINDINGS = [
        Binding("enter,space", "open", show=False),
        Binding("left", "step(-1)", show=False),
        Binding("right", "step(1)", show=False),
    ]
    DEFAULT_CSS = """
    Choice { width: auto; height: 1; background: transparent; color: $foreground; }
    Choice:focus { text-style: reverse; }
    """

    def __init__(self, options: Sequence[tuple[Hashable, str]], value: Hashable | None = None, title: str = "",
                 id: str | None = None, classes: str = ""):
        super().__init__(id=id, classes=classes)
        self.options = list(options)
        self.title_text = title
        values = [v for v, _label in self.options]
        self.value = value if value in values else (values[0] if values else None)

    @property
    def label(self) -> str:
        return next((label for v, label in self.options if v == self.value), "")

    def get_content_width(self, container, viewport) -> int:
        return max((cell_len(label) for _v, label in self.options), default=1) + 2

    def render(self) -> Text:
        g = self.app.glyphs
        room = max(1, self.size.width - 1 - cell_len(g.down))
        label = self.label
        if cell_len(label) > room:
            cut = room - cell_len(g.ellipsis)
            label = set_cell_size(label, cut) + g.ellipsis if cut > 0 else set_cell_size(label, room)
        # the arrow right after the label, where it reads as this one's and not as the next field's
        text = Text(label + " ", no_wrap=True)
        text.append(g.down, role("muted"))
        text.append(" " * (room - cell_len(label)))
        return text

    def set_value(self, value: Hashable, tell: bool = False) -> None:
        if value == self.value:
            return
        self.value = value
        self.refresh()
        if tell:
            self.post_message(self.Changed(self, value))

    def action_step(self, d: int) -> None:
        values = [v for v, _label in self.options]
        if values:
            i = values.index(self.value) if self.value in values else 0
            self.set_value(values[max(0, min(len(values) - 1, i + d))], tell=True)

    def action_open(self) -> None:
        def chosen(value: Hashable | None) -> None:
            if value is not None:
                self.set_value(value, tell=True)
        self.app.push_screen(ChoiceList(self.title_text, self.options, self.value), chosen)

    def on_click(self) -> None:
        self.action_open()


class Radio(Widget, can_focus=True):
    """One of `options` ((value, label) pairs) side by side: `(•) all conditions  ( ) any condition`. ← → or space
    move the choice, a click picks one; `Changed` after the user changed it."""

    class Changed(Message):
        def __init__(self, radio: "Radio", value: Hashable):
            super().__init__()
            self.radio, self.value = radio, value

        @property
        def control(self) -> "Radio":
            return self.radio

    BINDINGS = [
        Binding("space", "step(1)", show=False),
        Binding("left", "step(-1)", show=False),
        Binding("right", "step(1)", show=False),
    ]
    DEFAULT_CSS = """
    Radio { width: auto; height: 1; background: transparent; color: $foreground; }
    Radio:focus { text-style: reverse; }
    """
    GAP = "  "

    def __init__(self, options: Sequence[tuple[Hashable, str]], value: Hashable, id: str | None = None,
                 classes: str = ""):
        super().__init__(id=id, classes=classes)
        self.options = list(options)
        self.value = value

    def _parts(self) -> list[str]:
        item = self.app.glyphs.item
        return [f"({item if v == self.value else ' '}) {label}" for v, label in self.options]

    def get_content_width(self, container, viewport) -> int:
        return cell_len(self.GAP.join(self._parts()))

    def render(self) -> Text:
        text = Text(no_wrap=True, overflow="ellipsis")
        for i, (part, (v, _label)) in enumerate(zip(self._parts(), self.options, strict=True)):
            if i:
                text.append(self.GAP)
            text.append(part[:3], role("marked") if v == self.value else Style())
            text.append(part[3:])
        return text

    def set_value(self, value: Hashable, tell: bool = False) -> None:
        if value == self.value:
            return
        self.value = value
        self.refresh()
        if tell:
            self.post_message(self.Changed(self, value))

    def action_step(self, d: int) -> None:
        values = [v for v, _label in self.options]
        i = values.index(self.value) if self.value in values else 0
        self.set_value(values[(i + d) % len(values)], tell=True)

    def on_click(self, event) -> None:
        x = 0
        for part, (v, _label) in zip(self._parts(), self.options, strict=True):
            if event.x < x + cell_len(part) + len(self.GAP):
                self.set_value(v, tell=True)
                return
            x += cell_len(part) + len(self.GAP)


class PopupMenu(ModalScreen):
    """A small menu next to what it is about (a context menu): `items` are (label, enabled) or (label, enabled, key)
    tuples, None between groups of them for a separator; a key is drawn at the right, muted. The screen's result is
    the index in `items` of the one run, None when closed. Disabled items are dim and cannot be run; the cursor skips
    them. `at` is the screen cell to open at; the menu moves left and up as far as it must to stay on the screen."""

    BINDINGS = [Binding("escape", "close", show=False)]
    DEFAULT_CSS = """
    PopupMenu { align: left top; }
    PopupMenu > OptionList { width: auto; max-width: 90%; height: auto; max-height: 90%; padding: 0 1; }
    """

    def __init__(self, title: str, items: Sequence[tuple[str, bool] | tuple[str, bool, str] | None],
                 at: tuple[int, int] = (0, 0)):
        super().__init__()
        self.title_text = title
        self.items = list(items)
        self.at = at

    def _width(self) -> int:
        """The items' width: the longest label, and the longest key two cells after it."""
        shown = [item for item in self.items if item is not None]
        labels = max([cell_len(item[0]) for item in shown] + [0])
        keys = max([cell_len(item[2]) for item in shown if len(item) > 2 and item[2]] + [0])
        return labels + (keys + 2 if keys else 0)

    def compose(self) -> ComposeResult:
        width = self._width()
        options: list[Option | None] = []
        for i, item in enumerate(self.items):
            if item is None:
                if options and options[-1] is not None:  # never two separators in a row, nor one first
                    options.append(None)
                continue
            line = Text(item[0])
            if len(item) > 2 and item[2]:
                line.append(" " * (width - line.cell_len - cell_len(item[2])))
                line.append(item[2], role("muted"))
            options.append(Option(line, id=str(i), disabled=not item[1]))
        while options and options[-1] is None:
            options.pop()
        menu = OptionList(*options, classes="window")
        menu.border_title = self.title_text
        menu.border_subtitle = hint(("enter", _("pick")), ("esc", _("close")))
        yield menu

    def on_mount(self) -> None:
        menu = self.query_one(OptionList)
        # the frame and the padding: 4 cells across, 2 lines down; one line for each separator
        width = max(self._width(), cell_len(self.title_text) + 2, 20) + 4
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
