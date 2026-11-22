"""The search field and its mode in the header bar: a Gtk.DropDown and a Gtk.SearchEntry over
kram.app.search.SearchController. The entry's own search-delay stays 0: the controller debounces."""
from gi.repository import Gtk

from ..app.search import SearchController
from ..core.search import MODE_LABELS, Mode
from ..i18n import _

MODE_TIP = _("Name / Name + summary / Description: instant ranked search.\n"
             "Provides: packages providing a capability (libvulkan.so.1, python3dist(requests), webbrowser).\n"
             "File: owner of a file (/usr/bin/7z or just 7z; only the main files for packages not installed).\n\n"
             "Several words: all must match. ^start, end$, * and ? are wildcards.")


class SearchBox(Gtk.Box):
    def __init__(self, controller: SearchController):
        super().__init__()
        self.add_css_class("linked")
        self.controller = c = controller
        self.mode_box = Gtk.DropDown.new_from_strings([MODE_LABELS[m] for m in Mode])
        self.mode_box.set_tooltip_text(MODE_TIP)
        self._mode_handler = self.mode_box.connect("notify::selected",
                                                   lambda d, _p: c.mode_chosen(d.get_selected()))
        self.entry = Gtk.SearchEntry(placeholder_text=_("Search (Ctrl+F)"), search_delay=0, width_chars=22)
        self._text_handler = self.entry.connect("search-changed", self._on_text)
        self.entry.connect("activate", lambda _e: c.submit())
        self.append(self.mode_box)
        self.append(self.entry)
        c.shown.connect(self._show)

    def _on_text(self, entry: Gtk.SearchEntry) -> None:
        self.controller.edited(entry.get_text())
        self._update_hint()

    def _show(self, text: str, mode: Mode) -> None:
        with self.entry.handler_block(self._text_handler):
            if self.entry.get_text() != text:
                self.entry.set_text(text)
        with self.mode_box.handler_block(self._mode_handler):
            self.mode_box.set_selected(int(mode))
        self._update_hint()

    def focus(self) -> None:
        self.entry.grab_focus()
        self.entry.select_region(0, -1)

    def _update_hint(self) -> None:
        """While the search text filters the list the field says so (Adwaita has no funnel icon: an accent
        outline and a tooltip instead)."""
        active = self.controller.filtering
        (self.entry.add_css_class if active else self.entry.remove_css_class)("kram-filtering")
        self.entry.set_tooltip_text(_("The list is filtered by the search text") if active else None)
