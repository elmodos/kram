"""The GTK implementation of kram.app.ports.Ui and Bus: alert dialogs, file dialogs, links, the clipboard, the bus.

GTK 4 has no blocking dialogs: every method returns at once and calls its continuation when the user answers, as the
port allows (kram.app.ports). The standard buttons' labels are GTK's own, translated in its "gtk40" catalog, as Qt
takes them from qtbase.
"""
import weakref
from collections.abc import Callable
from pathlib import Path

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from ..app.ports import STANDARD, Question, is_web_link, parse_filters
from ..i18n import _

CLOSED = "__closed__"


def gtk_text(msgid: str) -> str:
    """A string from GTK's own translations ("_Yes", "_Cancel"…), with its mnemonic underscore."""
    return GLib.dgettext("gtk40", msgid)


STANDARD_LABELS = {"yes": "_Yes", "no": "_No", "ok": "_OK", "cancel": "_Cancel", "close": "_Close"}
_APPEARANCE = {"accept": Adw.ResponseAppearance.SUGGESTED, "destructive": Adw.ResponseAppearance.DESTRUCTIVE}


def _details_child(details: str) -> Gtk.Widget:
    label = Gtk.Label(label=details, xalign=0, selectable=True, wrap=True)
    label.add_css_class("monospace")
    scroller = Gtk.ScrolledWindow(child=label, max_content_height=300, propagate_natural_height=True)
    return Gtk.Expander(label=_("Details"), child=scroller)


class GtkUi:
    """Dialogs belong to `window` (held weakly, as QtUi holds its parent); `status(text, ms)` shows a status line
    message, if given."""

    def __init__(self, window: Gtk.Window | None, status: Callable[[str, int], None] | None = None):
        self._window_ref = weakref.ref(window) if window is not None else None
        self._status = status
        self._open = 0  # dialogs of this port on screen

    @property
    def _window(self) -> Gtk.Window | None:
        return self._window_ref() if self._window_ref is not None else None

    # ---------------------------------------------------------------- messages and questions

    def _alert(self, question: Question, done: Callable[[str | None], None] | None) -> None:
        body = question.text + (f"\n\n{question.informative}" if question.informative else "")
        dialog = Adw.AlertDialog(heading=question.title, body=body)
        if question.details:
            dialog.set_extra_child(_details_child(question.details))
        escape = None
        for button in question.buttons:
            label = button.label or gtk_text(STANDARD_LABELS.get(button.id, button.id))
            dialog.add_response(button.id, label)
            role = STANDARD[button.id].role if not button.label and button.id in STANDARD else button.role
            if role in _APPEARANCE:
                dialog.set_response_appearance(button.id, _APPEARANCE[role])
            if role == "reject" and escape is None:
                escape = button.id  # Escape presses it, as in Qt's message boxes
        if question.default:
            dialog.set_default_response(question.default)
        dialog.set_close_response(escape or CLOSED)

        def answered(_dialog, response: str) -> None:
            self._open -= 1
            if done is not None:
                done(None if response == CLOSED else response)
        dialog.connect("response", answered)
        self._open += 1
        dialog.present(self._window)

    def _message(self, title: str, text: str, informative: str, details: str) -> None:
        self._alert(Question(title, text, buttons=(STANDARD["ok"],), informative=informative, details=details),
                    None)

    def info(self, title: str, text: str, informative: str = "", details: str = "") -> None:
        self._message(title, text, informative, details)

    def warn(self, title: str, text: str, informative: str = "", details: str = "") -> None:
        self._message(title, text, informative, details)

    def error(self, title: str, text: str, informative: str = "", details: str = "") -> None:
        self._message(title, text, informative, details)

    def status(self, text: str, timeout_ms: int = 0) -> None:
        if self._status is not None:
            self._status(text, timeout_ms)

    def ask(self, question: Question, done: Callable[[str | None], None]) -> None:
        self._alert(question, done)

    # ---------------------------------------------------------------- files

    @staticmethod
    def _filters(filters: str) -> Gio.ListStore:
        store = Gio.ListStore(item_type=Gtk.FileFilter)
        for label, patterns in parse_filters(filters):
            f = Gtk.FileFilter(name=label)
            for pattern in patterns:
                f.add_pattern(pattern)
            store.append(f)
        return store

    def _file_dialog(self, title: str, filters: str) -> Gtk.FileDialog:
        return Gtk.FileDialog(title=title, modal=True, filters=self._filters(filters))

    def _finish(self, finish, done: Callable[[str | None], None]):
        def finished(dialog, result) -> None:
            self._open -= 1
            try:
                file = finish(dialog, result)
            except GLib.Error:  # dismissed
                file = None
            done(file.get_path() if file is not None else None)
        return finished

    def choose_open_file(self, title: str, start_dir: str, filters: str, done: Callable[[str | None], None]) -> None:
        dialog = self._file_dialog(title, filters)
        if start_dir and Path(start_dir).is_dir():
            dialog.set_initial_folder(Gio.File.new_for_path(start_dir))
        self._open += 1
        dialog.open(self._window, None, self._finish(Gtk.FileDialog.open_finish, done))

    def choose_save_file(self, title: str, start_path: str, filters: str,
                         done: Callable[[str | None], None]) -> None:
        dialog = self._file_dialog(title, filters)
        if start_path:
            path = Path(start_path)
            folder = path if path.is_dir() else path.parent
            if folder.is_dir():
                dialog.set_initial_folder(Gio.File.new_for_path(str(folder)))
            if not path.is_dir():
                dialog.set_initial_name(path.name)
        self._open += 1
        dialog.save(self._window, None, self._finish(Gtk.FileDialog.save_finish, done))

    # ---------------------------------------------------------------- the desktop

    def open_web_link(self, url: str) -> bool:
        if not is_web_link(url):
            return False
        Gtk.UriLauncher(uri=url).launch(self._window, None, None)
        return True

    def show_in_file_manager(self, path: str) -> None:
        # GTK asks the FileManager1 interface itself (through the portal when sandboxed)
        Gtk.FileLauncher(file=Gio.File.new_for_path(path)).open_containing_folder(self._window, None, None)

    def copy_text(self, text: str) -> None:
        display = Gdk.Display.get_default()
        if display is not None:
            display.get_clipboard().set_content(Gdk.ContentProvider.new_for_value(text))

    def is_modal_open(self) -> bool:
        window = self._window
        dialog = window.get_visible_dialog() if isinstance(window, Adw.ApplicationWindow) else None
        return self._open > 0 or dialog is not None


class GioBus:
    """kram.app.ports.Bus on the session bus through Gio."""

    def _call(self, method: str, name: str):
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            reply = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", method,
                                  GLib.Variant("(s)", (name,)), None, Gio.DBusCallFlags.NONE, 3000, None)
            return reply.unpack()[0]
        except GLib.Error:
            return None

    def has_owner(self, name: str) -> bool:
        return bool(self._call("NameHasOwner", name))

    def owner_pid(self, name: str) -> int | None:
        return self._call("GetConnectionUnixProcessID", name) or None
