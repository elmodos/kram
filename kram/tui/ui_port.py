"""The terminal implementation of kram.app.ports.Ui: messages and questions as modal dialogs, a path line for
files, the terminal's clipboard, and the desktop only when there is one (docs/TUI_SPEC.md §12).

Every method returns at once and calls its continuation from the dialog's dismissal, as the port allows. Over SSH
or on the Linux console there is no browser and no file manager to hand anything to: the address or the path is
copied to the clipboard instead (OSC 52, which most terminals pass on to the machine the user sits at), and the
status line says so.
"""
import os
import shutil
from collections.abc import Callable
from pathlib import Path

from textual.app import App

from ..app.ports import OK, Question, is_web_link
from ..core.proc import spawn_detached
from ..i18n import _
from .dialogs.path import PathDialog
from .dialogs.question import QuestionDialog

STATUS_MS = 4000  # how long the confirmations of this port stay on the top line


def has_desktop(environ=os.environ) -> bool:
    """A graphical session to hand links and folders to (§12.1)."""
    return bool(environ.get("WAYLAND_DISPLAY") or environ.get("DISPLAY")) and shutil.which("xdg-open") is not None


class TuiUi:
    """Dialogs go on `app`'s screen stack; `status(text, ms)` shows a transient message on the top line, if given."""

    def __init__(self, app: App, status: Callable[[str, int], None] | None = None):
        self.app = app
        self._status = status

    # ---------------------------------------------------------------- messages and questions

    def _show(self, question: Question, done: Callable[[str | None], None] | None) -> None:
        self.app.push_screen(QuestionDialog(question), done)

    def _message(self, title: str, text: str, informative: str, details: str, icon: str) -> None:
        self._show(Question(title, text, buttons=(OK,), informative=informative, details=details, icon=icon), None)

    def info(self, title: str, text: str, informative: str = "", details: str = "") -> None:
        self._message(title, text, informative, details, "info")

    def warn(self, title: str, text: str, informative: str = "", details: str = "") -> None:
        self._message(title, text, informative, details, "warning")

    def error(self, title: str, text: str, informative: str = "", details: str = "") -> None:
        self._message(title, text, informative, details, "error")

    def status(self, text: str, timeout_ms: int = 0) -> None:
        if self._status is not None:
            self._status(text, timeout_ms)

    def ask(self, question: Question, done: Callable[[str | None], None]) -> None:
        self._show(question, done)

    # ---------------------------------------------------------------- files

    def choose_open_file(self, title: str, start_dir: str, filters: str, done: Callable[[str | None], None]) -> None:
        start = start_dir.rstrip("/") + "/" if start_dir and Path(start_dir).is_dir() else ""
        self.app.push_screen(PathDialog(title, start, "open", filters), done)

    def choose_save_file(self, title: str, start_path: str, filters: str,
                         done: Callable[[str | None], None]) -> None:
        self.app.push_screen(PathDialog(title, start_path, "save", filters), done)

    # ---------------------------------------------------------------- the desktop

    def open_web_link(self, url: str) -> bool:
        if not is_web_link(url):
            return False
        if has_desktop() and spawn_detached(["xdg-open", url]):
            return True
        self.copy_text(url, _("No desktop to open it in: the address is copied"))
        return True

    def show_in_file_manager(self, path: str) -> None:
        folder = str(Path(path).parent) if not Path(path).is_dir() else path
        if has_desktop() and spawn_detached(["xdg-open", folder]):
            return
        self.copy_text(path, _("No desktop to show it in: the path is copied"))

    def copy_text(self, text: str, message: str = "") -> None:
        self.app.copy_to_clipboard(text)
        self.status(message or _("Copied"), STATUS_MS)

    def is_modal_open(self) -> bool:
        return len(self.app.screen_stack) > 1
