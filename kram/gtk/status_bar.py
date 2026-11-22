"""The main window's status line (the texts are kram.app.status): counts, the missing-repositories warning as a
link, the metadata's age. A transient message replaces the counts for its timeout, as Qt's showMessage does; no
toasts: Kram keeps a Synaptic-like status line."""
from collections.abc import Callable

from gi.repository import GLib, Gtk, Pango

from ..app.status import counts_text, error_text, metadata_age, missing_repos, timings_tip
from ..core.model import CatalogSnapshot


class StatusBar(Gtk.Box):
    def __init__(self, repos_clicked: Callable[[], None]):
        super().__init__(spacing=12, margin_start=8, margin_end=8, margin_top=3, margin_bottom=3)
        self._label = Gtk.Label(xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END)
        self._warning = Gtk.Label(visible=False)
        self._warning.connect("activate-link", lambda _l, _uri: (repos_clicked(), True)[1])
        self._age = Gtk.Label()
        self._age.add_css_class("dim-label")
        for w in (self._label, self._warning, self._age):
            self.append(w)
        self._text = ""
        self._message_source = 0

    def text(self) -> str:
        return self._text

    def set_text(self, text: str) -> None:
        self._text = text
        if not self._message_source:
            self._label.set_text(text)

    def message(self, text: str, timeout_ms: int = 0) -> None:
        """A transient message over the counts, for `timeout_ms` (0: until the next message or text)."""
        if self._message_source:
            GLib.source_remove(self._message_source)
            self._message_source = 0
        self._label.set_text(text)
        if timeout_ms:
            self._message_source = GLib.timeout_add(timeout_ms, self._end_message)

    def _end_message(self) -> bool:
        self._message_source = 0
        self._label.set_text(self._text)
        return GLib.SOURCE_REMOVE

    def show_error(self, error: BaseException) -> None:
        self.set_text(error_text(error))

    def show_catalog(self, snap: CatalogSnapshot) -> None:
        self._age.set_text(metadata_age(snap.metadata_age))
        warning = missing_repos(snap)
        self._warning.set_visible(warning is not None)
        if warning is not None:
            text, tip = warning
            self._warning.set_markup(f"⚠ <a href='repos'>{GLib.markup_escape_text(text)}</a>")
            self._warning.set_tooltip_text(tip)

    def show_counts(self, snap: CatalogSnapshot, shown: int, to_install: int, to_remove: int,
                    ms: float | None = None) -> None:
        self.set_text(counts_text(snap, shown, to_install, to_remove))
        if ms is not None:
            self._label.set_tooltip_text(timings_tip(snap, ms))
