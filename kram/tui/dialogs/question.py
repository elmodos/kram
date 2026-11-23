"""The question and message dialog (docs/TUI_SPEC.md §10.21): a `kram.app.ports.Question` as a modal window, its
title in the frame, its text, its buttons at the bottom right, the default one focused.

The screen's result is the id of the button pressed. `Esc` gives the cancel answer, the first button with the
"reject" role, as Escape does in the GUIs' message boxes; a question without one is closed with None, as GTK's
`CLOSED` response.
"""
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from ...app.ports import STANDARD, Question
from ...app.ports import Button as QuestionButton
from ...i18n import _
from ..widgets import Button, hint


def standard_labels() -> dict[str, str]:
    """The labels of the standard buttons, which the GUIs take from their toolkit's own translations."""
    return {"yes": _("Yes"), "no": _("No"), "ok": _("OK"), "cancel": _("Cancel"), "close": _("Close")}


def button_role(button: QuestionButton) -> str:
    return STANDARD[button.id].role if not button.label and button.id in STANDARD else button.role


def default_button(question: Question) -> str | None:
    """The button focused at first: the question's own default, else its first accepting one, else its first."""
    ids = [b.id for b in question.buttons]
    if question.default in ids:
        return question.default
    accept = [b.id for b in question.buttons if button_role(b) == "accept"]
    return (accept or ids or [None])[0]


def escape_answer(question: Question) -> str | None:
    return next((b.id for b in question.buttons if button_role(b) == "reject"), None)


class QuestionDialog(ModalScreen):
    BINDINGS = [
        Binding("escape", "cancel", show=False),
        Binding("left", "app.focus_previous", show=False),
        Binding("right", "app.focus_next", show=False),
    ]

    def __init__(self, question: Question):
        super().__init__()
        self.question = question
        self._answers: dict[Button, str] = {}

    def compose(self) -> ComposeResult:
        q = self.question
        box = Vertical(classes="window dialog question")
        box.border_title = q.title
        keys = [("tab", _("next"))] if len(q.buttons) > 1 else []
        keys.append(("enter", _("choose")))
        keys.append(("esc", _("cancel") if escape_answer(q) else _("close")))
        box.border_subtitle = hint(*keys)
        default = default_button(q)
        labels = standard_labels()
        with box:
            yield Static(q.text, classes="text", markup=False)
            if q.informative:
                yield Static(q.informative, classes="note", markup=False)
            if q.details:
                with VerticalScroll(classes="details"):
                    yield Static(q.details, classes="note", markup=False)
            with Horizontal(classes="buttons"):
                for b in q.buttons:
                    classes = "-primary" if b.id == default else ""
                    button = Button(b.label or labels.get(b.id, b.id),
                                    variant="error" if button_role(b) == "destructive" else "default",
                                    classes=classes)
                    self._answers[button] = b.id
                    yield button

    def on_mount(self) -> None:
        default = default_button(self.question)
        for button, answer in self._answers.items():
            if answer == default:
                button.focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(self._answers.get(event.button))

    def action_cancel(self) -> None:
        self.dismiss(escape_answer(self.question))
