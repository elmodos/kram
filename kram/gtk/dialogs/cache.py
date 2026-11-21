"""Settings → Cleanup for GTK (kram.app.cache): the package caches and rpm's leftover configuration files."""
from gi.repository import Adw, Gio, Gtk

from ...app.cache import CACHES, LEFTOVERS_ICONS, CacheLine, Cleanup, LeftoverLine, RunHelper, describe
from ...core.leftovers import Leftover
from ...i18n import _
from ..icons import first_themed
from ..ui_port import GtkUi
from .common import frame, standard_button, text_view, wrapped


def _image(names: tuple[str, ...], size: int = 32) -> Gtk.Image:
    return Gtk.Image(icon_name=first_themed(names) or "", pixel_size=size)


def _dim(text: str = "", xalign: float = 0) -> Gtk.Label:
    label = Gtk.Label(label=text, xalign=xalign, wrap=True)
    label.add_css_class("dim-label")
    return label


class _CacheRow(Adw.ActionRow):
    def __init__(self, target: str, icons: tuple[str, ...], title: str, description: str, button: str,
                 cleanup: Cleanup):
        super().__init__(title=title, subtitle=description, use_markup=False, subtitle_lines=0)
        self.folder = ""
        self.add_prefix(_image(icons))
        numbers = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        self.size = Gtk.Label(xalign=1)
        self.size.add_css_class("heading")
        self.files = _dim(xalign=1)
        numbers.append(self.size)
        numbers.append(self.files)
        self.add_suffix(numbers)
        self.open = Gtk.Button(icon_name="folder-open-symbolic", valign=Gtk.Align.CENTER)
        self.open.add_css_class("flat")
        self.open.connect("clicked", self._open_folder)
        self.add_suffix(self.open)
        self.button = Gtk.Button(label=button, valign=Gtk.Align.CENTER)
        self.button.connect("clicked", lambda _b: cleanup.clean(target))
        self.add_suffix(self.button)

    def _open_folder(self, _button) -> None:
        if self.folder:
            Gtk.FileLauncher(file=Gio.File.new_for_path(self.folder)).launch(self.get_root(), None, None)


class CacheDialog(Adw.PreferencesDialog):
    describe = staticmethod(describe)

    def __init__(self, dnf, clean_system, *, helper: RunHelper | None = None):
        """`clean_system(target, done)` runs the helper's clean_cache; `helper(request, title, done)` any other
        request (kram.app.cache.Cleanup)."""
        super().__init__(title=_("Cleanup"), content_width=820, content_height=640, search_enabled=False)
        self.ui = GtkUi(self)
        self.cleanup = Cleanup(dnf, self, self.ui, clean_system, helper)
        page = Adw.PreferencesPage()
        self.add(page)

        self.note_group = Adw.PreferencesGroup(visible=False)
        self.note = wrapped("warning")
        self.note_group.add(self.note)
        page.add(self.note_group)

        caches = Adw.PreferencesGroup()
        page.add(caches)
        self.rows: dict[str, _CacheRow] = {}
        group = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)  # the same width in every row, in every language
        for target, icons, title, description, button in CACHES:
            row = self.rows[target] = _CacheRow(target, icons, _(title), _(description), _(button), self.cleanup)
            group.add_widget(row.button)
            caches.add(row)

        self.leftovers_group = Adw.PreferencesGroup(
            title=_("Leftover configuration files"),
            description=_("Copies rpm keeps when you had changed a package's configuration file: your earlier "
                          "version (.rpmsave) or the package's new default it did not apply (.rpmnew)."))
        buttons = Gtk.Box(spacing=6, halign=Gtk.Align.END, margin_top=6)
        self.search_root_btn = Gtk.Button(child=Adw.ButtonContent(label=_("Search All Folders…"),
                                                                  icon_name="edit-find-symbolic"),
                                          tooltip_text=_("Also search the folders only root can read"))
        self.search_root_btn.connect("clicked", lambda _b: self.cleanup.search_as_root())
        self.delete_unused_btn = Gtk.Button(child=Adw.ButtonContent(label=_("Delete Unused…"),
                                                                    icon_name="user-trash-symbolic"),
                                            tooltip_text=_("Delete the copies of files that no longer exist"))
        self.delete_unused_btn.connect("clicked", lambda _b: self.cleanup.delete_unused())
        buttons.append(self.search_root_btn)
        buttons.append(self.delete_unused_btn)
        self.leftovers_status = Adw.ActionRow(use_markup=False, title_lines=0)
        self.leftovers_status.add_prefix(_image(LEFTOVERS_ICONS))
        self.leftovers_group.add(self.leftovers_status)
        # under the list, not in the group's header or a row: there they squeeze the text in a narrow page
        self.leftovers_group.add(buttons)
        page.add(self.leftovers_group)
        self.leftover_rows: list[Adw.ActionRow] = []

        self.connect("closed", lambda _d: self.cleanup.close())  # results that arrive later are dropped
        self.cleanup.start()

    @property
    def leftovers(self):
        return self.cleanup.leftovers

    def _leftover_row(self, line: LeftoverLine) -> Adw.ActionRow:
        leftover = line.leftover
        row = Adw.ActionRow(title=leftover.path, subtitle=line.description, use_markup=False, subtitle_lines=0)
        row.set_name(leftover.path)  # found again by tests
        row.add_prefix(_image(line.icons))
        row.add_suffix(_dim(line.when, xalign=1))
        show = Gtk.Button(icon_name="folder-open-symbolic", valign=Gtk.Align.CENTER,
                          tooltip_text=_("Show in File Manager"))
        show.add_css_class("flat")
        show.connect("clicked", lambda _b: self.ui.show_in_file_manager(leftover.path))
        compare = Gtk.Button(label=_("Compare"), valign=Gtk.Align.CENTER, sensitive=line.can_compare,
                             tooltip_text=line.compare_tip or None)
        compare.connect("clicked", lambda _b: self.cleanup.compare(leftover))
        delete = Gtk.Button(label=_("Delete…"), valign=Gtk.Align.CENTER, sensitive=line.can_delete)
        delete.add_css_class("destructive-action")
        delete.connect("clicked", lambda _b: self.cleanup.delete([leftover]))
        for w in (show, compare, delete):
            row.add_suffix(w)
        return row

    # ---------------------------------------------------------------- CleanupView

    def show_measuring(self) -> None:
        for row in self.rows.values():
            row.size.set_text("…")
            row.files.set_text("")
            row.button.set_sensitive(False)

    def show_caches(self, lines: list[CacheLine]) -> None:
        for line in lines:
            row = self.rows[line.target]
            row.set_visible(line.shown)
            if not line.shown:
                continue
            row.folder = line.folder
            row.open.set_tooltip_text(f"{_('Open in the file manager')}\n{line.path}")
            row.size.set_text(line.size)
            row.files.set_text(line.files)
            row.files.set_visible(bool(line.files))
            row.button.set_sensitive(line.can_clean)

    def set_clean_enabled(self, target: str, on: bool) -> None:
        self.rows[target].button.set_sensitive(on)

    def show_note(self, text: str | None) -> None:
        self.note.set_text("⚠ " + text if text else "")
        self.note_group.set_visible(bool(text))

    def show_leftovers_status(self, text: str) -> None:
        """Searching, or the search failed: nothing to act on meanwhile."""
        self.leftovers_status.set_title(text)
        self.search_root_btn.set_visible(False)
        self.delete_unused_btn.set_sensitive(False)

    def show_leftovers(self, lines: list[LeftoverLine], status: str, can_search_root: bool,
                       can_delete_unused: bool) -> None:
        for row in self.leftover_rows:
            self.leftovers_group.remove(row)
        self.leftover_rows = [self._leftover_row(line) for line in lines]
        for row in self.leftover_rows:
            self.leftovers_group.add(row)
        self.leftovers_status.set_title(status)
        self.search_root_btn.set_visible(can_search_root)
        self.delete_unused_btn.set_sensitive(can_delete_unused)

    def show_diff(self, leftover: Leftover, text: str) -> None:
        DiffDialog(leftover, text).present(self)


class DiffDialog(Adw.Dialog):
    def __init__(self, leftover: Leftover, text: str):
        super().__init__(title=_("Compare"), content_width=900, content_height=640)
        header, body = frame(self)
        close = standard_button("_Close")
        close.connect("clicked", lambda _b: self.close())
        header.pack_end(close)
        body.append(wrapped())
        body.get_first_child().set_text(
            _("Lines with “-” are in the current file {current}; lines with “+” only in {path}.").format(
                current=leftover.current, path=leftover.path))
        scroller, self.view = text_view()
        body.append(scroller)
        buffer = self.view.get_buffer()
        dark = Adw.StyleManager.get_default().get_dark()
        tags = {prefix: buffer.create_tag(None, foreground=dark_color if dark else light_color)
                for prefix, light_color, dark_color in (("+", "#1b7a1b", "#7fd67f"), ("-", "#b02020", "#ff8a8a"),
                                                        ("@", "#5a5aa0", "#a0a0ff"))}
        for n, line in enumerate(text.splitlines()):
            tag = None if line.startswith(("+++", "---")) else tags.get(line[:1])
            end = buffer.get_end_iter()
            chunk = ("\n" if n else "") + line
            if tag is None:
                buffer.insert(end, chunk)
            else:
                buffer.insert_with_tags(end, chunk, tag)
