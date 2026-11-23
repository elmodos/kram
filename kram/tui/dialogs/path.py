"""Choosing a file in a terminal: a path line, as a shell has it (docs/TUI_SPEC.md §10.8, §10.15). `Tab` completes
the path; `Enter` takes it. For a file to open it must exist; a file to save that exists is replaced only after a
question. The screen's result is the path, or None.

The filters are the GUIs' (`kram.app.ports.parse_filters`): completion offers folders and the files that match.
"""
import fnmatch
import os
from pathlib import Path
from typing import Literal

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from ...app.ports import CANCEL, Question, parse_filters
from ...app.ports import Button as QuestionButton
from ...i18n import _
from ..widgets import Button, hint
from .question import QuestionDialog

SHOWN_MATCHES = 8  # names listed on the status line when Tab cannot choose one


def complete(text: str, patterns: list[str] | None = None) -> tuple[str, list[str]]:
    """Complete `text` as far as every match agrees: (the completed text, the names that still match). A folder that
    is the only match gets its "/". Hidden names only when the text asks for them, as a shell does."""
    if text == "~":
        return "~/", []
    path = os.path.expanduser(text) if text.startswith("~") else text
    folder, sep, prefix = path.rpartition("/")
    base = Path(folder + "/" if sep else ".")
    try:
        entries = sorted(base.iterdir(), key=lambda p: p.name)
    except OSError:
        return text, []
    matches = []
    for entry in entries:
        name = entry.name
        if not name.startswith(prefix) or (name.startswith(".") and not prefix.startswith(".")):
            continue
        is_dir = entry.is_dir()
        if not is_dir and patterns and not any(fnmatch.fnmatch(name, p) for p in patterns):
            continue
        matches.append(name + "/" if is_dir else name)
    if not matches:
        return text, []
    common = _common_prefix(matches)
    head = text[:len(text) - len(prefix)]
    return head + common, matches if len(matches) > 1 else []


def _common_prefix(names: list[str]) -> str:
    """By characters, as a shell completes (os.path.commonprefix does that too, but is deprecated in Python 3.15)."""
    first, last = min(names), max(names)
    i = 0
    while i < min(len(first), len(last)) and first[i] == last[i]:
        i += 1
    return first[:i]


class PathDialog(ModalScreen):
    BINDINGS = [
        Binding("escape", "cancel", show=False),
        Binding("tab", "complete", show=False, priority=True),
    ]

    def __init__(self, title: str, start: str, mode: Literal["open", "save"], filters: str = ""):
        super().__init__()
        self.title_text, self.start, self.mode = title, start, mode
        self.patterns = [p for _label, patterns in parse_filters(filters) for p in patterns if p != "*"] \
            if filters else []

    def compose(self) -> ComposeResult:
        box = Vertical(classes="window dialog path")
        box.border_title = self.title_text
        box.border_subtitle = hint(("tab", _("complete")), ("enter", _("choose")), ("esc", _("cancel")))
        with box:
            yield Input(self.start, id="path")
            yield Static("", id="path-status", classes="note", markup=False)
            with Horizontal(classes="buttons"):
                yield Button(_("Open") if self.mode == "open" else _("Save"), id="accept", variant="primary")
                yield Button(_("Cancel"), id="cancel")

    def on_mount(self) -> None:
        field = self.query_one("#path", Input)
        field.focus()
        field.cursor_position = len(field.value)

    def say(self, text: str) -> None:
        self.query_one("#path-status", Static).update(text)

    def action_complete(self) -> None:
        field = self.query_one("#path", Input)
        if self.focused is not field:
            self.focus_next()
            return
        completed, matches = complete(field.value, self.patterns)
        if completed != field.value:
            field.value = completed
            field.cursor_position = len(completed)
        names = matches[:SHOWN_MATCHES] + (["…"] if len(matches) > SHOWN_MATCHES else [])
        self.say("  ".join(names))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.accept()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "accept":
            self.accept()
        else:
            self.dismiss(None)

    def accept(self) -> None:
        text = self.query_one("#path", Input).value.strip()
        if not text:
            return
        path = Path(os.path.expanduser(text)).absolute()
        if path.is_dir():
            self.say(_("“{name}” is a folder").format(name=text))
            return
        if self.mode == "open":
            if not path.is_file():
                self.say(_("No such file: {path}").format(path=text))
                return
            self.dismiss(str(path))
            return
        if not path.parent.is_dir():
            self.say(_("No such folder: {path}").format(path=str(path.parent)))
            return
        if not path.exists():
            self.dismiss(str(path))
            return
        question = Question(self.title_text, _("“{name}” already exists. Replace it?").format(name=path.name),
                            buttons=(QuestionButton("replace", _("Replace"), "destructive"), CANCEL),
                            default="cancel", icon="warning")
        def answered(answer: str | None) -> None:
            # from the question's dismissal, never right after it (docs/TUI_SPEC.md §11.3.8); not returning
            # dismiss()'s awaitable, which Textual would await in this screen's own handler
            if answer == "replace":
                self.dismiss(str(path))
        self.app.push_screen(QuestionDialog(question), answered)

    def action_cancel(self) -> None:
        self.dismiss(None)
