"""The main window of the terminal front end: a view of kram.app.browser.Browser (docs/TUI_SPEC.md §7), as
kram.gtk.window.MainWindow is. It wires the sidebar (kram.tui.sidebar), the package list (kram.tui.package_list) and
the top line (§5.4) to the Browser; the app (kram.tui.app) lays out the panels and decides who gets a key.

The parts of `BrowserView` that later steps bring (the Apply dialog, the progress of the helper, the repositories,
the mirrors) say so through the Ui port meanwhile, each with the section that replaces it.
"""
from collections.abc import Callable

from rich.text import Text

from .. import instance
from ..app.actions import ActionState, DynamicItem, action_defs
from ..app.browser import STATUS_MESSAGE_MS, Browser, ReposChoice
from ..app.custom_filters import CustomFilters
from ..app.doc import Doc, para
from ..app.marking import group_menu
from ..app.mirrors import MirrorChoice
from ..app.package_list import Sort
from ..app.status import error_text, metadata_age, missing_repos
from ..core.marks import Action
from ..core.model import CatalogSnapshot, GroupInfo, PkgDetails, PkgRow, TransactionPreview
from ..i18n import _, ngettext
from ..notifier import stale_days
from . import loop
from .package_list import PackageTable, column_label
from .palette import role
from .sidebar import Sidebar
from .widgets import ChoiceList

FRONT_PACKAGE = "kram-tui"
# Browser says this while the catalog load waits for the system repo lock (Browser._waiting_for_lock)
LOCK_STATUS = "Waiting for another package manager to finish…"


class NoDetails:
    """The details panel's DetailsSink until it shows documents (§7.4, the next step)."""

    def show_advisories(self, row: PkgRow | None) -> None:
        pass

    def show_blocked(self, reason: str | None) -> None:
        pass

    def show_package(self, row: PkgRow, d: PkgDetails) -> None:
        pass

    def clear(self) -> None:
        pass


class MainWindow:
    """`app`: the KramApp, whose screen shows `list` in its Packages panel and whose top line this fills."""

    def __init__(self, app):
        self.app = app
        self.ui = app.ui
        self.details = NoDetails()
        self.scheduler = loop.TuiScheduler()
        self.browser = b = Browser(self, self.ui, self.scheduler, self.details, loop.post,
                                   front_package=FRONT_PACKAGE)
        # the user's filters show and can be deleted; editing them waits for the Custom Filters dialog (§10.10)
        b.custom_filters = CustomFilters(b.sidebar, b.catalog, b.dnf, lambda: b.snapshot, self.ui, self._edit_filters)
        self.sidebar = Sidebar(self, app.glyphs, id="sidebar", classes="panel")
        self.list = PackageTable(b.packages, self, app.glyphs, app.utf8, id="list")
        self.list.on_current = lambda _pos: b.current_changed(self.list.current_row())
        self.list.on_selection = b.update_actions
        self.list.show_sort(b.packages.sort_column)  # the sort the list starts with
        self.waiting_for_lock = False
        self.actions: ActionState | None = None  # for the menu and the window's keys of later steps
        self.reload_enabled = self.apply_enabled = False

    def start(self) -> None:
        """Once the app runs (its loop takes what the worker posts): the settings, then the catalog."""
        b = self.browser
        b.restore_settings()
        b.custom_filters.restore()
        if self.app.upgradable:
            b.show_view(instance.UPGRADABLE)
        b.reload()

    def shutdown(self) -> None:
        self.browser.shutdown()

    @property
    def top(self):
        return self.app.top_line

    # ---------------------------------------------------------------- BrowserView: the package list

    def current_key(self) -> tuple[str, str] | None:
        row = self.list.current_row()
        return row.key if row is not None else None

    def select_key(self, key: tuple[str, str], scroll: bool = True) -> bool:
        pos = self.browser.packages.position_of(key)
        if pos is None:
            return False
        self.list.select(pos, scroll=True)  # never left out of sight, which is all `scroll` asks in Qt
        return True

    def select_first(self, to_top: bool) -> None:
        if len(self.browser.packages):
            self.list.select(0)
            if to_top:
                self.list.scroll_to_top()

    def selected_rows(self) -> list[PkgRow]:
        packages = self.browser.packages
        return [packages.row(p) for p in self.list.selected_positions()]

    def show_sort(self, sort: Sort | None) -> None:
        self.list.show_sort(sort)

    def set_empty(self, doc: Doc) -> None:
        self.waiting_for_lock = False
        self.list.set_empty(doc)

    def focus_list(self) -> None:
        self.list.focus()

    # ---------------------------------------------------------------- BrowserView: the top line and the actions

    def set_status(self, text: str) -> None:
        self.top.set_status(text)
        if text == _(LOCK_STATUS) and self.browser.snapshot is None:
            # §7.1: the load waits for another package manager; Esc quits meanwhile
            self.list.set_empty(Doc([para(_("Another package manager is running: waiting"))]),
                                [("esc", _("quit"))])
            self.waiting_for_lock = True

    def status_text(self) -> str:
        return self.top.status.plain

    def show_catalog(self, snap: CatalogSnapshot) -> None:
        """The right of the top line: what is wrong with the catalog, then its age (dropped first when narrow)."""
        self.waiting_for_lock = False
        warn = self.app.glyphs.warning + " "
        parts = []
        age = snap.metadata_age
        if age is not None and (days := age // 86400) >= stale_days():
            parts.append(Text(warn + ngettext("The package information is {days} day old",
                                              "The package information is {days} days old", days).format(days=days),
                              role("danger")))
        if (missing := missing_repos(snap)) is not None:
            parts.append(Text(warn + missing[0], role("danger")))
        parts.append(Text(metadata_age(age), role("muted")))
        self.top.set_right(parts)

    def show_counts(self, snap: CatalogSnapshot, shown: int, to_install: int, to_remove: int,
                    ms: float | None) -> None:
        """The left of the top line: the filter or the search, its rows, the marks."""
        b = self.browser
        label = b.filter.label if b.filter is not None else ""
        if text := b.search.text():
            label = _("“{text}” in {filter}").format(text=text, filter=label)
        line = Text(label)
        line.append(f"  {shown}", role("muted"))
        if n := len(b.packages.marks):
            line.append("  ")
            line.append(ngettext("{n} change marked", "{n} changes marked", n).format(n=n), role("marked"))
        self.top.set_status(line)

    def show_error(self, error: BaseException) -> None:
        self.top.set_status(error_text(error))

    def apply_actions(self, state: ActionState, catalog: bool, busy: bool) -> None:
        self.actions = state  # the menu (§7.7) and the marking keys (§6.5) read it when they come

    def set_reload_enabled(self, on: bool) -> None:
        self.reload_enabled = on

    def set_apply_enabled(self, on: bool) -> None:
        self.apply_enabled = on

    # ---------------------------------------------------------------- BrowserView: dialogs of later steps

    def _not_yet(self) -> None:
        self.ui.info("Kram", _("Not in this version yet"))

    def review_changes(self, preview: TransactionPreview, request: dict, basearch: str, resolve,
                       done: Callable[[dict | None], None]) -> None:
        self._not_yet()  # replaced by the Apply changes dialog, §10.1
        done(None)

    def run_helper(self, request: dict, title: str, done: Callable[[dict | None], None]) -> None:
        self._not_yet()  # replaced by the Progress dialog and the root flow, §10.2 and §11
        done(None)

    def show_repos(self, data, done: Callable[[ReposChoice | None], None]) -> None:
        self._not_yet()  # replaced by the Repositories dialog, §10.4
        done(None)

    def show_mirrors(self, repo, source, fastestmirror: bool, apply: Callable[[MirrorChoice], None]) -> None:
        self._not_yet()  # replaced by the Mirrors dialog, §10.5

    def quit(self) -> None:
        self.app.request_quit()

    def _edit_filters(self, filters, snap, select, new, resolve_provides, done) -> None:
        self._not_yet()  # replaced by the Custom Filters dialog, §10.10
        done(None)

    # ---------------------------------------------------------------- the sidebar's menu and keys (§7.2.6)

    def sidebar_menu(self, entry) -> list[DynamicItem | str | None]:
        return self.browser.sidebar_menu(entry)

    def menu_item(self, item: DynamicItem | str) -> tuple[str, bool]:
        """(label, enabled) of an item of a menu built when it opens: a dynamic item, or an action by its id."""
        if isinstance(item, DynamicItem):
            return item.label, item.enabled and item.run is not None
        action = next(a for a in action_defs() if a.id == item)
        enabled = self.actions.enabled.get(item, action.enabled) if self.actions is not None else action.enabled
        return action.label, enabled

    def run_menu_item(self, item: DynamicItem | str) -> None:
        if not self.menu_item(item)[1]:
            return
        if isinstance(item, DynamicItem):
            item.run()
            return
        b = self.browser
        run = {"mark_unneeded": b.marker.mark_unneeded, "filters": b.custom_filters.edit,
               "new_filter": lambda: b.custom_filters.new_from_view(b.filter, b.search.text(), b.search.mode())}
        run.get(item, self._not_yet)()

    def change_group(self, key: str, action: Action) -> None:
        """`+` / `-` on a group or an environment of the sidebar: what its menu's first item of that kind does
        (Install, or Upgrade when it is installed; Remove), through Browser.change_group. When that item is off,
        the top line says why, as its tooltip does in the GUIs."""
        b = self.browser
        group = b.marker.group(key)
        if group is None:
            return
        picked: list[tuple[Action, bool]] = []

        def note(_group: GroupInfo, act: Action, optional: bool) -> None:
            picked.append((act, optional))
        for item in group_menu(group, busy=b.busy(), run=note):
            item.run()
            act, optional = picked.pop()
            if optional or (act is Action.REMOVE) != (action is Action.REMOVE):
                continue
            if item.enabled:
                b.change_group(group, act, False)
            elif item.tip:
                self.ui.status(item.tip, STATUS_MESSAGE_MS)
            return

    # ---------------------------------------------------------------- the list's keys (PackageTable.commands)

    def choose_sort(self) -> None:
        """`s`: the shown columns as a list; the one picked sorts ascending, or as it was if it is the sorted one."""
        current = self.list.sort_shown
        items = [(col, column_label(col)) for col, _w in self.list.columns]

        def chosen(col: int | None) -> None:
            if col is not None:
                self.sort(col, current[1] if current is not None and current[0] == col else False)
        self.app.push_screen(ChoiceList(_("Sort by"), items, current[0] if current else None), chosen)

    def reverse_sort(self) -> None:
        """`S`: the sort the other way round; a ranked list gets the user's last column sort, reversed."""
        col, descending = self.list.sort_shown or self.browser.user_sort
        self.sort(col, not descending)

    def sort(self, column: int, descending: bool) -> None:
        b = self.browser
        b.user_sorted(column, descending)
        self.show_sort((column, descending))
        b.packages.sort(column, descending)

    def copy_names(self) -> None:
        self.browser.copy_names()

    def copy_nevras(self) -> None:
        self.browser.copy_nevras()

    def open_details(self) -> None:
        if not self.app.has_focus_in("details"):
            self.app.action_toggle_panel("details")

    def follow_empty_link(self, link: str) -> None:
        self.browser.empty_link(link)

    def escape(self) -> bool:
        """Esc in the list: quits while the catalog waits for the lock (§7.1); False: not taken."""
        if self.waiting_for_lock and self.browser.snapshot is None:
            self.app.request_quit()
            return True
        return False
