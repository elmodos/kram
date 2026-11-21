"""The main window for GTK: a view of kram.app.browser.Browser, as kram.qt.main_window is. It builds the widgets
(docs/GTK_FRONTEND.md §6), wires them to Browser and shows its dialogs.

The dialogs themselves (Apply, progress, repositories, COPR, …) come in later steps of phase 2; until then their
actions say so instead.
"""
import json
from collections.abc import Callable

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from .. import HOMEPAGE, __version__
from ..app import preferences
from ..app.actions import ActionState, DynamicItem
from ..app.browser import Browser, ReposChoice
from ..app.custom_filters import CustomFilters
from ..app.doc import Doc
from ..app.package_list import Sort
from ..app.progress import BUSY
from ..core import releases
from ..core.model import CatalogSnapshot, PkgRow, TransactionPreview
from ..core.settings import store as settings
from ..i18n import _
from . import icons
from .actions import WindowActions, action_name
from .details import DetailsView
from .dialogs.apply import ApplyDialog
from .dialogs.cache import CacheDialog
from .dialogs.notifier import NotifierDialog
from .dialogs.progress import ProgressDialog
from .doc_view import DocView, release_notes
from .loop import GtkScheduler, post
from .package_list import PackageListView
from .search import SearchBox
from .sidebar import Sidebar
from .status_bar import StatusBar
from .ui_port import GtkUi

DETAILS_TAB_KEY = "details/tab-name"  # shared with Qt
WINDOW_KEY = "gtk/window"             # {"width", "height", "maximized"}
PANES_KEY = "gtk/panes"               # {"sidebar", "details"}: the two dividers' positions
# the actions whose dialogs the GTK front end does not have yet (phase 2, §7.4 steps 4–5); not translated yet
NOT_YET = ("repos", "copr", "history", "show_in_history", "filters", "new_filter",
           "open_file")
NOT_YET_TEXT = "This is not in the GTK front end yet."


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application):
        super().__init__(application=app, title="Kram", icon_name=app.get_application_id())
        self._restore_size()
        self._closing = False
        self.status = StatusBar(lambda: self.browser.open_repos())
        self.ui = GtkUi(self, self.status.message)
        self.details = DetailsView()
        self.scheduler = GtkScheduler()
        self.browser = b = Browser(self, self.ui, self.scheduler, self.details, post)
        self.dnf, self.catalog, self.helper, self.marker = b.dnf, b.catalog, b.helper, b.marker
        self.custom_filters = b.custom_filters = CustomFilters(b.sidebar, self.catalog, self.dnf,
                                                               lambda: b.snapshot, b.ui, self._edit_filters)
        self.acts = WindowActions(self, app)
        self.acts.set_downgrade_source(b.downgrade_items)
        self.search = SearchBox(b.search)
        self._build()
        self._connect_actions()
        self._restore_settings()
        self.connect("close-request", self._close_request)
        self.connect("realize", self._realized)
        preferences.changed.connect(self._pref_changed)
        b.reload()

    # ---------------------------------------------------------------- construction

    def _build(self) -> None:
        b = self.browser
        header = Adw.HeaderBar(title_widget=Adw.WindowTitle(title="Kram", subtitle=_("Package Manager")))
        reload = Gtk.Button(icon_name="view-refresh-symbolic", action_name="win.reload",
                            tooltip_text=f"{self.acts.defs['reload'].label} (Ctrl+R)")
        mark = Adw.SplitButton(icon_name="software-update-available-symbolic",
                               action_name=f"win.{action_name('mark_upgrades')}",
                               menu_model=self.acts.mark_upgrades_menu(),
                               tooltip_text=self.acts.defs["mark_upgrades"].tip)
        apply = Gtk.Button(label=self.acts.defs["apply"].label, action_name="win.apply",
                           tooltip_text=self.acts.defs["apply"].tip)
        apply.add_css_class("suggested-action")
        for w in (reload, mark, apply):
            header.pack_start(w)
        self.menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=self.acts.main_menu(),
                                          primary=True)
        header.pack_end(self.menu_button)
        for action_id, icon in (("copr", "folder-remote-symbolic"), ("repos", "preferences-system-symbolic")):
            header.pack_end(Gtk.Button(icon_name=icon, action_name=f"win.{action_name(action_id)}",
                                       tooltip_text=self.acts.defs[action_id].label))
        header.pack_end(self.search)
        self.menu_bar = Gtk.PopoverMenuBar.new_from_model(self.acts.menu_bar())

        # the package list, with what it says while it is empty over it
        self.list = PackageListView(b.packages)
        self.list.view.add_controller(self.acts.table_shortcuts())
        self.list.on_current = lambda pos: b.current_changed(self.list.current_row())
        self.list.on_selection = self._selection_changed
        self.list.on_sort = self._sorted
        self.list.on_status_click = self._status_click
        self.list.on_context_menu = self._context_menu
        self.list.on_activate = lambda pos: self.marker.toggle_likely(b.packages.row(pos))
        self.empty = DocView(margin=24)
        self.empty.set_halign(Gtk.Align.CENTER)
        self.empty.set_valign(Gtk.Align.CENTER)
        self.empty.on_link = lambda kind, target: b.empty_link(target) if kind == "action" else None
        self.empty.set_visible(False)
        overlay = Gtk.Overlay(child=self.list)
        overlay.add_overlay(self.empty)

        self.details.on_link = b.follow_link
        self.details.on_web = self.ui.open_web_link
        self.details.set_size_request(-1, 120)  # the details can shrink to their tabs, not vanish
        self.vpaned = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL, start_child=overlay, end_child=self.details,
                                shrink_end_child=False, resize_end_child=False, position=520)
        self.sidebar = Sidebar(b.sidebar)
        self.sidebar.on_context_menu = self._sidebar_menu
        self.sidebar.on_activate = self.custom_filters.activated
        self.sidebar.set_size_request(180, -1)
        self.hpaned = Gtk.Paned(start_child=self.sidebar, end_child=self.vpaned, shrink_start_child=False,
                                resize_start_child=False, position=270)

        view = Adw.ToolbarView(content=self.hpaned)
        view.add_top_bar(header)
        view.add_top_bar(self.menu_bar)
        view.add_bottom_bar(self.status)
        self.set_content(view)
        self._show_menu_bar(preferences.value(preferences.MENU_BAR))

        self._popover = Gtk.PopoverMenu(has_arrow=False)
        self._popover.connect("closed", lambda p: GLib.idle_add(self._unparent_popover))

    def _connect_actions(self) -> None:
        acts, b = self.acts, self.browser
        for action_id, slot in [
            ("reload", b.refresh_metadata), ("reload_cache", b.reload),
            ("mark_upgrades", self.marker.mark_all_upgrades), ("mark_unneeded", self.marker.mark_unneeded),
            ("apply", b.apply), ("unmark_all", self.marker.unmark_all),
            ("properties", lambda: self.details.select_name("general")),
            ("why_blocked", lambda: self.details.select_name("dependencies")),
            ("find", self.search.focus), ("back", b.go_back), ("quit", self.close), ("about", self.about),
            ("copy_name", b.copy_names), ("copy_nevra", b.copy_nevras), ("unmark", b.unmark_selected),
            ("lock", lambda: b.set_version_lock(True)), ("unlock", lambda: b.set_version_lock(False)),
            ("cache", self.open_cache), ("notifications", self.open_notifications),
            ("save_marks", b.save_marks), ("read_marks", b.read_marks), ("export_csv", b.export_csv),
        ]:
            acts.connect(action_id, slot)
        for action_id in NOT_YET:
            acts.connect(action_id, self._not_yet)
        from ..app.actions import MARK_ACTIONS, mark_id, mark_upgrades_id
        from ..app.browser import UPGRADE_KINDS
        for kind in UPGRADE_KINDS:
            acts.connect(mark_upgrades_id(kind), lambda k=kind: self.marker.mark_upgrades(k))
        for mark in MARK_ACTIONS:
            acts.connect(mark_id(mark), lambda m=mark: b.mark_selected(m))

    def _not_yet(self) -> None:
        self.ui.info("Kram", NOT_YET_TEXT)

    def _edit_filters(self, filters, snap, select, new, resolve_provides, done) -> None:
        self._not_yet()
        done(None)

    def _sorted(self, column: int, descending: bool) -> None:
        self.browser.user_sorted(column, descending)
        self.browser.packages.sort(column, descending)

    # ---------------------------------------------------------------- settings and lifetime

    def _restore_size(self) -> None:
        try:
            saved = json.loads(settings.get(WINDOW_KEY, "{}"))
        except (TypeError, ValueError):
            saved = {}
        self.set_default_size(saved.get("width", 1320), saved.get("height", 860))
        if saved.get("maximized"):
            self.maximize()

    def _restore_settings(self) -> None:
        try:
            panes = json.loads(settings.get(PANES_KEY, "{}"))
        except (TypeError, ValueError):
            panes = {}
        self.hpaned.set_position(panes.get("sidebar", 270))
        self.vpaned.set_position(panes.get("details", 520))
        self.details.select_name(settings.get(DETAILS_TAB_KEY, "description"))
        self.browser.restore_settings()
        self.custom_filters.restore()

    def _save_settings(self) -> None:
        settings.set(DETAILS_TAB_KEY, self.details.current_name())
        width, height = self.get_default_size()
        settings.set(WINDOW_KEY, json.dumps({"width": width, "height": height, "maximized": self.is_maximized()}))
        settings.set(PANES_KEY, json.dumps({"sidebar": self.hpaned.get_position(),
                                            "details": self.vpaned.get_position()}))

    def _realized(self, _window) -> None:
        surface = self.get_surface()
        surface.connect("notify::scale", lambda s, _p: icons.set_scale(s.get_scale()))
        icons.set_scale(surface.get_scale())

    def _pref_changed(self, key: str) -> None:
        if key == preferences.MENU_BAR:
            self._show_menu_bar(preferences.value(key))

    def _show_menu_bar(self, on: bool) -> None:
        """D6, D12: the classic menu bar is a setting; while it is shown the hamburger button is not."""
        self.menu_bar.set_visible(on)
        self.menu_button.set_visible(not on)

    def _close_request(self, _window) -> bool:
        if self._closing:
            return False

        def answered(ok: bool) -> None:
            if ok:
                self._closing = True
                self._save_settings()
                self.browser.shutdown()
                preferences.changed.disconnect(self._pref_changed)
                self.close()
        self.browser.can_close(answered)
        return not self._closing  # GTK closes only when the answer came at once and was yes

    def show_view(self, view: str) -> None:
        self.browser.show_view(view)

    def activate_from_outside(self, view: str, token: str = "") -> None:
        """The tray or another `kram` asked for this window: to the front, with the activation token on Wayland.
        While a dialog is open over it the user is in the middle of something there: the filter stays."""
        if not self.ui.is_modal_open():
            self.show_view(view)
        if token:
            self.set_startup_id(token)
        self.present()

    # ---------------------------------------------------------------- BrowserView: the package list

    def current_key(self) -> tuple[str, str] | None:
        row = self.list.current_row()
        return row.key if row is not None else None

    def select_key(self, key: tuple[str, str], scroll: bool = True) -> bool:
        pos = self.browser.packages.position_of(key)
        if pos is None:
            return False
        self.list.select(pos, scroll=True)  # GTK selects by scrolling to it; `scroll` only centres in Qt
        return True

    def select_first(self, to_top: bool) -> None:
        if len(self.browser.packages):
            self.list.select(0, scroll=to_top)
            if to_top:
                self.list.scroll_to_top()

    def selected_rows(self) -> list[PkgRow]:
        packages = self.browser.packages
        return [packages.row(p) for p in self.list.selected_positions() if p < len(packages)]

    def show_sort(self, sort: Sort | None) -> None:
        self.list.show_sort(sort)

    def set_empty(self, doc: Doc) -> None:
        self.empty.set_doc(doc)
        self.empty.set_visible(bool(doc))

    def focus_list(self) -> None:
        self.present()
        self.list.view.grab_focus()

    def _selection_changed(self) -> None:
        empty = len(self.browser.packages) == 0
        if not empty:
            self.empty.set_visible(False)
        self.browser.update_actions()

    # ---------------------------------------------------------------- BrowserView: status and actions

    def set_status(self, text: str) -> None:
        self.status.set_text(text)

    def status_text(self) -> str:
        return self.status.text()

    def show_catalog(self, snap: CatalogSnapshot) -> None:
        self.status.show_catalog(snap)

    def show_counts(self, snap, shown, to_install, to_remove, ms) -> None:
        self.status.show_counts(snap, shown, to_install, to_remove, ms)
        self.empty.set_visible(shown == 0 and bool(self.empty.get_first_child()))

    def show_error(self, error: BaseException) -> None:
        self.status.show_error(error)

    def apply_actions(self, state: ActionState, catalog: bool, busy: bool) -> None:
        self.acts.apply_state(state)

    def set_reload_enabled(self, on: bool) -> None:
        self.acts.by_id["reload"].set_enabled(on)
        self.acts.by_id["reload_cache"].set_enabled(on)

    def set_apply_enabled(self, on: bool) -> None:
        self.acts.by_id["apply"].set_enabled(on)

    # ---------------------------------------------------------------- BrowserView: dialogs

    def review_changes(self, preview: TransactionPreview, request: dict, basearch: str, resolve,
                       done: Callable[[dict | None], None]) -> None:
        # with the recommendations the user unchecked, and download only if chosen; None when cancelled
        ApplyDialog(preview, request, basearch, done, resolve=resolve).present(self)

    def run_helper(self, request: dict, title: str, done: Callable[[dict | None], None]) -> None:
        dlg = ProgressDialog(self.helper, request, title, lambda ok, result: done(result if ok else None))
        if not dlg.start():
            self.ui.warn(title, _(BUSY))
            done(None)
            return
        dlg.present(self)  # over the dialog that started it (COPR, Package Cache): libadwaita stacks them

    def show_repos(self, snap, counts, owners, listed, installed, done: Callable[[ReposChoice | None], None]) -> None:
        self._not_yet()
        done(None)

    # ---------------------------------------------------------------- the other dialogs

    def open_cache(self) -> None:
        b = self.browser
        if not b.snapshot or b.busy():
            return
        CacheDialog(self.dnf, b.clean_cache, helper=b.run_helper).present(self)

    def open_notifications(self) -> None:
        NotifierDialog().present(self)

    # ---------------------------------------------------------------- menus and clicks

    def _unparent_popover(self) -> bool:
        if self._popover.get_parent() is not None and not self._popover.get_visible():
            self._popover.unparent()
        return GLib.SOURCE_REMOVE

    def _popup(self, model: Gio.Menu, widget: Gtk.Widget, x: float, y: float) -> None:
        if self._popover.get_parent() is not None:
            self._popover.unparent()
        self._popover.set_menu_model(model)
        self._popover.set_parent(widget)
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        self._popover.set_pointing_to(rect)
        self._popover.popup()

    def _status_click(self, pos: int, widget: Gtk.Widget) -> None:
        # Synaptic: the status box opens the action menu, or marks the likely action if the user chose that
        row = self.browser.packages.row(pos)
        if preferences.value(preferences.STATUS_CLICK) and self.marker.toggle_likely(row):
            return
        self.acts.refresh_downgrade()
        self._popup(self.acts.package_menu(), widget, 0, widget.get_height())

    def _context_menu(self, pos: int, widget: Gtk.Widget, x: float, y: float) -> None:
        self.acts.refresh_downgrade()
        self._popup(self.acts.table_menu(), widget, x, y)

    def _sidebar_menu(self, entry, widget: Gtk.Widget, x: float, y: float) -> None:
        items: list[DynamicItem | str | None] = self.browser.sidebar_menu(entry)
        self._popup(self.acts.dynamic_menu(items, "sidebar"), widget, x, y)

    def about(self) -> None:
        about = Adw.AboutDialog(application_name="Kram", application_icon=self.get_application().get_application_id(),
                                version=__version__, website=HOMEPAGE, issue_url=f"{HOMEPAGE}/issues",
                                comments=_("A Synaptic-style package manager for Fedora."),
                                copyright="© 2026 Modo Ltunzher", license_type=Gtk.License.MIT_X11)
        notes = release_notes(releases.load())
        if notes:  # libadwaita's own What's New page
            about.set_release_notes(notes)
            about.set_release_notes_version(__version__)
        about.present(self)

