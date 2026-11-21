"""Runs one helper request (transaction or metadata refresh) and shows its progress (kram.app.progress), for GTK."""
from collections.abc import Callable

from gi.repository import Adw, GLib, Gtk

from ...app.progress import WAITING, Bar, Progress, Stage, shows_download, shows_rpm
from ...core.settings import store as settings
from ...i18n import _
from ...ipc.client import HelperClient
from ..ui_port import GtkUi
from .common import frame, standard_button, text_view, wrapped

AUTO_CLOSE_KEY = "progress/auto_close"  # shared with Qt
PULSE_MS = 120


class ProgressDialog(Adw.Dialog):
    """`done(ok, result)` once it closes. `start()` sends the request: False when the helper is busy with another."""

    def __init__(self, client: HelperClient, request: dict, title: str, done: Callable[[bool, dict], None]):
        super().__init__(title=title, content_width=720, content_height=460, can_close=False)
        self.client, self.request = client, request
        self._done = done
        self._pulsing: dict[Gtk.ProgressBar, int] = {}
        self.progress = Progress(client, request, self, GtkUi(self))
        header, body = frame(self)
        self.close_button = standard_button("_Close")
        self.close_button.set_sensitive(False)
        self.close_button.connect("clicked", lambda _b: self.close())
        header.pack_end(self.close_button)

        heading = Gtk.Label(label=title, xalign=0)
        heading.add_css_class("title-4")
        body.append(heading)
        self.stage = wrapped()
        self.stage.set_text(_(WAITING))
        body.append(self.stage)
        self.download_label = Gtk.Label(label=_("Download"), xalign=0)
        self.download_bar = Gtk.ProgressBar()
        self.rpm_label = Gtk.Label(label=_("Installation"), xalign=0)
        self.rpm_bar = Gtk.ProgressBar()
        for w in (self.download_label, self.download_bar, self.rpm_label, self.rpm_bar):
            body.append(w)
        for w in (self.rpm_label, self.rpm_bar):
            w.set_visible(shows_rpm(request))
        for w in (self.download_label, self.download_bar):
            w.set_visible(shows_download(request))
        self._set_busy(self.download_bar, True)  # busy until the first download reports its size

        details = Gtk.Label(label=_("Details"), xalign=0, margin_top=6)
        details.add_css_class("heading")
        body.append(details)
        log_box, self.log = text_view()
        self._scroller = log_box
        body.append(log_box)

        self.auto_close = Gtk.CheckButton(label=_("Close when finished successfully"),
                                          active=bool(settings.get(AUTO_CLOSE_KEY, False)))
        body.append(self.auto_close)
        self.connect("close-attempt", lambda _d: None)  # Escape mid-transaction: nothing happens
        self.connect("closed", self._closed)

    # the outcome, for the callers
    ok = property(lambda self: self.progress.ok)
    result = property(lambda self: self.progress.result)
    running = property(lambda self: self.progress.running)

    def start(self) -> bool:
        return self.progress.start()

    def _closed(self, _dialog) -> None:
        settings.set(AUTO_CLOSE_KEY, self.auto_close.get_active())
        for bar in list(self._pulsing):
            self._set_busy(bar, False)
        self.progress.stop()
        done, self._done = self._done, None
        if done is not None:
            done(self.progress.ok, self.progress.result)

    def _set_busy(self, bar: Gtk.ProgressBar, busy: bool) -> None:
        if busy and bar not in self._pulsing:
            def pulse() -> bool:
                bar.pulse()
                return GLib.SOURCE_CONTINUE
            self._pulsing[bar] = GLib.timeout_add(PULSE_MS, pulse)
        elif not busy and bar in self._pulsing:
            GLib.source_remove(self._pulsing.pop(bar))

    # ---------------------------------------------------------------- ProgressView

    def show_stage(self, stage: Stage) -> None:
        text = GLib.markup_escape_text(stage.text)
        detail = GLib.markup_escape_text(stage.detail)
        if stage.kind == "done":
            self.stage.set_markup(f"<b>{text}</b>" + (" " + detail if detail else ""))
        elif stage.kind == "error":
            self.stage.set_markup(f"<b>{text}</b> {detail}")
        else:
            self.stage.set_text(stage.text)
        if stage.kind == "error":
            self.stage.add_css_class("error")
        else:
            self.stage.remove_css_class("error")

    def _set_bar(self, bar: Gtk.ProgressBar, label: Gtk.Label, value: Bar, text: str | None) -> None:
        self._set_busy(bar, value.maximum == 0)
        if value.maximum:
            bar.set_fraction(min(value.value / value.maximum, 1.0))
        if text is not None:
            label.set_text(text)

    def show_download(self, bar: Bar, label: str | None) -> None:
        self._set_bar(self.download_bar, self.download_label, bar, label)

    def show_rpm(self, bar: Bar, label: str | None) -> None:
        self._set_bar(self.rpm_bar, self.rpm_label, bar, label)

    def append_log(self, line: str) -> None:
        buffer = self.log.get_buffer()
        adj = self._scroller.get_vadjustment()
        at_end = adj.get_value() >= adj.get_upper() - adj.get_page_size() - 4
        buffer.insert(buffer.get_end_iter(), ("\n" if buffer.get_char_count() else "") + line)
        if at_end:  # follow the log, unless the user scrolled up to read
            GLib.idle_add(lambda: (adj.set_value(adj.get_upper()), GLib.SOURCE_REMOVE)[1])

    def request_done(self, ok: bool) -> None:
        self.set_can_close(True)
        self.close_button.set_sensitive(True)
        self.set_default_widget(self.close_button)
        if ok and self.auto_close.get_active():
            self.close()
