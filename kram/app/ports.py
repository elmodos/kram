"""What the toolkit-free logic needs from the user and the desktop: the `Ui` port, which each front end implements.

Every method returns at once and reports back through a continuation, because GTK 4 has no nested main loop for
dialogs: a flow that asks something continues in the callback. Qt may show a modal dialog and call the
continuation before it returns; the flow must not care which.
"""
import weakref
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

WEB_SCHEMES = ("http", "https")

# the freedesktop interface file managers answer (Dolphin, Nautilus, Nemo and others): show a file in its folder
FILE_MANAGER = "org.freedesktop.FileManager1"
FILE_MANAGER_PATH = "/org/freedesktop/FileManager1"
FILE_MANAGER_METHOD = "ShowItems"  # (uris: as, startup_id: s)


def view_ref(view):
    """How the logic of a dialog keeps its view: weakly. The view (a Qt dialog) keeps its logic, so a strong
    reference back would make a cycle; a Qt dialog in a cycle is freed by the garbage collector at a random moment,
    and PySide6 can crash on that. Whoever shows the view keeps it alive. An object that cannot be referenced
    weakly (a plain test double) is kept as it is: it is no toolkit object."""
    try:
        return weakref.proxy(view)
    except TypeError:
        return view


def is_web_link(url: str) -> bool:
    """Only web addresses are handed to the desktop. A package's URL tag comes from whoever built the file, so a
    file:, smb: or custom-handler link is not opened: one click would run whatever handles it."""
    scheme, sep, _rest = url.partition(":")
    return bool(sep) and scheme.lower() in WEB_SCHEMES


ButtonRole = Literal["accept", "reject", "action", "destructive"]


@dataclass(frozen=True)
class Button:
    """`label` "" for the standard ones below: the toolkit's own, translated, label (Yes, No, OK…)."""
    id: str
    label: str = ""
    role: ButtonRole = "action"


YES = Button("yes", role="accept")
NO = Button("no", role="reject")
OK = Button("ok", role="accept")
CANCEL = Button("cancel", role="reject")
CLOSE = Button("close", role="reject")
STANDARD = {b.id: b for b in (YES, NO, OK, CANCEL, CLOSE)}


@dataclass(frozen=True)
class Question:
    title: str
    text: str
    buttons: tuple[Button, ...] = (YES, NO)
    informative: str = ""   # a second paragraph under the text
    details: str = ""       # long text the user can unfold (a resolver's full message)
    default: str | None = None
    icon: Literal["question", "info", "warning", "error", "none"] = "question"


def parse_filters(filters: str) -> list[tuple[str, list[str]]]:
    """A file chooser's filters, written as Qt's file dialogs take them ("Text files (*.txt);;All files (*)"), as
    (label, patterns) pairs for a toolkit that wants them so."""
    result = []
    for part in filters.split(";;"):
        label, _sep, rest = part.rpartition("(")
        patterns = rest.rstrip(")").split() if _sep else ["*"]
        result.append(((label or part).strip(), patterns))
    return result


class Ui(Protocol):
    def info(self, title: str, text: str, informative: str = "", details: str = "") -> None: ...

    def warn(self, title: str, text: str, informative: str = "", details: str = "") -> None: ...

    def error(self, title: str, text: str, informative: str = "", details: str = "") -> None: ...

    def status(self, text: str, timeout_ms: int = 0) -> None:
        """A transient message in the status bar, for `timeout_ms` (0: until the next one)."""
        ...

    def ask(self, question: Question, done: Callable[[str | None], None]) -> None:
        """`done(id)` of the button pressed, None when the question was closed without one."""
        ...

    def choose_open_file(self, title: str, start_dir: str, filters: str, done: Callable[[str | None], None]) -> None:
        ...

    def choose_save_file(self, title: str, start_path: str, filters: str,
                         done: Callable[[str | None], None]) -> None: ...

    def open_web_link(self, url: str) -> bool:
        """Open `url` in the browser if `is_web_link`; False if it was not opened."""
        ...

    def show_in_file_manager(self, path: str) -> None: ...

    def copy_text(self, text: str) -> None: ...

    def is_modal_open(self) -> bool:
        """A dialog is open over the window: a dropped file or a stray shortcut does nothing meanwhile."""
        ...


class Bus(Protocol):
    """The session bus, asked about who is there (the update notifiers dialog: is a tray host running, is another
    program's notifier). Qt answers with QtDBus, GTK with Gio."""

    def has_owner(self, name: str) -> bool: ...

    def owner_pid(self, name: str) -> int | None:
        """The process that owns `name`; None when nobody does, or the bus does not say."""
        ...


class FakeBus:
    """A `Bus` for tests: `owners` maps the names that are taken to their process ids."""

    def __init__(self, owners: dict[str, int] | None = None):
        self.owners = dict(owners or {})

    def has_owner(self, name):
        return name in self.owners

    def owner_pid(self, name):
        return self.owners.get(name) or None


class RecordingUi:
    """A `Ui` for tests: records every call in `calls` and answers questions with `answers` (button ids, in order;
    None when they run out) and file choosers with `files`."""

    def __init__(self, answers: list[str | None] | None = None, files: list[str | None] | None = None):
        self.calls: list[tuple] = []
        self.answers = list(answers or [])
        self.files = list(files or [])
        self.modal = False

    def _record(self, *call) -> None:
        self.calls.append(call)

    def info(self, title, text, informative="", details=""):
        self._record("info", title, text, informative, details)

    def warn(self, title, text, informative="", details=""):
        self._record("warn", title, text, informative, details)

    def error(self, title, text, informative="", details=""):
        self._record("error", title, text, informative, details)

    def status(self, text, timeout_ms=0):
        self._record("status", text, timeout_ms)

    def ask(self, question, done):
        self._record("ask", question)
        done(self.answers.pop(0) if self.answers else None)

    def choose_open_file(self, title, start_dir, filters, done):
        self._record("open_file", title, start_dir)
        done(self.files.pop(0) if self.files else None)

    def choose_save_file(self, title, start_path, filters, done):
        self._record("save_file", title, start_path)
        done(self.files.pop(0) if self.files else None)

    def open_web_link(self, url):
        self._record("web", url)
        return is_web_link(url)

    def show_in_file_manager(self, path):
        self._record("show_file", path)

    def copy_text(self, text):
        self._record("copy", text)

    def is_modal_open(self):
        return self.modal

    def kinds(self) -> list[str]:
        return [c[0] for c in self.calls]
