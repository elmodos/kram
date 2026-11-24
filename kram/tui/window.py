"""The main window of the terminal front end: a view of kram.app.browser.Browser (docs/TUI_SPEC.md §7), as
kram.gtk.window.MainWindow is. It wires the sidebar (kram.tui.sidebar), the package list (kram.tui.package_list),
the details (kram.tui.details) and the top line (§5.4) to the Browser; the app (kram.tui.app) lays out the panels
and decides who gets a key.

The parts of `BrowserView` that later steps bring (the Apply dialog, the progress of the helper, the repositories,
the mirrors) say so through the Ui port meanwhile, each with the section that replaces it. So do the actions of the
menu whose dialogs come later (`NOT_YET`).

The actions of kram.app.actions run here, by id (`run_action`), whether from the menu, a context menu or a key: what
each runs is what the GUIs connect to it (kram.gtk.window._connect_actions). Whether one is enabled comes from
`Browser.update_actions` (`apply_actions`), and the menu says why one is not (`disabled_reason`).
"""
from collections.abc import Callable

from rich.text import Text

from .. import instance
from ..app.actions import MARK_ACTIONS, ActionDef, ActionState, DynamicItem, action_defs, mark_id, mark_upgrades_id
from ..app.browser import STATUS_MESSAGE_MS, UPGRADE_KINDS, Browser, ReposChoice
from ..app.custom_filters import CustomFilters
from ..app.details import DETAILS_TAB_KEY
from ..app.doc import Doc, para
from ..app.marking import group_menu
from ..app.mirrors import MirrorChoice
from ..app.package_list import Sort
from ..app.progress import BUSY
from ..app.status import error_text, metadata_age, missing_repos
from ..core.marks import Action
from ..core.model import CatalogSnapshot, GroupInfo, PkgRow, TransactionPreview
from ..core.settings import store as settings
from ..i18n import _, ngettext
from ..notifier import stale_days
from . import loop
from .details import Details
from .dialogs.about import AboutDialog
from .menu import open_table_menu
from .package_list import PackageTable, column_label
from .palette import role
from .search import open_search
from .sidebar import Sidebar
from .widgets import ChoiceList

FRONT_PACKAGE = "kram-tui"
# the actions whose dialogs or progress come in later steps (docs/TUI_SPEC.md §17): "Not in this version yet"
NOT_YET = frozenset({"reload", "apply", "lock", "unlock", "history", "show_in_history", "open_file", "repos", "copr",
                     "cache", "notifications"})
# Browser says this while the catalog load waits for the system repo lock (Browser._waiting_for_lock)
LOCK_STATUS = "Waiting for another package manager to finish…"


class MainWindow:
    """`app`: the KramApp, whose screen shows `list` in its Packages panel and whose top line this fills."""

    def __init__(self, app):
        self.app = app
        self.ui = app.ui
        self.details = Details(self, app.glyphs, id="details", classes="panel")
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
        self.defs: dict[str, ActionDef] = {d.id: d for d in action_defs()}
        self.actions: ActionState | None = None  # from Browser.update_actions; None until it first says
        self.reload_enabled = self.apply_enabled = False

    def start(self) -> None:
        """Once the app runs (its loop takes what the worker posts): the settings, then the catalog."""
        b = self.browser
        b.restore_settings()
        b.custom_filters.restore()
        self.details.select_name(settings.get(DETAILS_TAB_KEY, "description"))
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
        text = b.search.text()
        # an entry of Search results is labelled with its search already
        if text and (b.filter is None or b.filter.query != (text, int(b.search.mode()))):
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
        self.actions = state  # the menus (§7.7) and the keys (§6.5) read it when used

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
        return self.defs[item].label, self.action_enabled(item)

    def run_menu_item(self, item: DynamicItem | str) -> None:
        if not self.menu_item(item)[1]:
            return
        if isinstance(item, DynamicItem):
            item.run()
        else:
            self.run_action(item)

    # ---------------------------------------------------------------- the actions (kram.app.actions)

    def action_enabled(self, action_id: str) -> bool:
        """`action_id` is an action of kram.app.actions or one of the ids of `ActionState` ("downgrade",
        "mark_upgrades_menu")."""
        if action_id in ("reload", "reload_cache"):
            return self.reload_enabled
        default = self.defs[action_id].enabled if action_id in self.defs else False
        return self.actions.enabled.get(action_id, default) if self.actions is not None else default

    def action_visible(self, action_id: str) -> bool:
        default = self.defs[action_id].visible
        return self.actions.visible.get(action_id, default) if self.actions is not None else default

    def disabled_reason(self, action_id: str) -> str:
        """Why an action is off now, for the menu's status line (§7.7.1): the GUIs grey it out and say nothing,
        a terminal has room for a line."""
        b = self.browser
        if b.snapshot is None or action_id in ("reload", "reload_cache"):
            return _("Loading the package catalog…")
        if b.busy():
            return _(BUSY)
        if action_id in ("apply", "unmark_all", "save_marks"):
            return _("Nothing is marked")
        if action_id in ("mark_upgrades", "mark_upgrades_menu"):
            return _("No package has an upgrade")
        if action_id.startswith("mark_upgrades."):
            return _("No upgrade of this kind")
        if action_id == "mark_unneeded":
            return _("No unneeded dependencies")
        if action_id in ("downgrade", "show_in_history"):
            return _("Only for one package at a time") if len(self.selected_rows()) != 1 else \
                _("Not for this package")
        if action_id == "unmark":
            return _("Not marked")
        return _("Not for this package") if self.selected_rows() else ""

    def run_action(self, action_id: str) -> None:
        """What the action does, as the GUIs' menus run it; an action that is off says why on the top line."""
        if not self.action_enabled(action_id):
            if reason := self.disabled_reason(action_id):
                self.ui.status(reason, STATUS_MESSAGE_MS)
            return
        if action_id in NOT_YET:
            self._not_yet()
            return
        self.action_runs()[action_id]()

    def action_runs(self) -> dict[str, Callable[[], None]]:
        """What each action runs, but those of NOT_YET."""
        b, marker = self.browser, self.browser.marker
        return {
            "reload_cache": b.reload, "mark_upgrades": marker.mark_all_upgrades,
            "mark_unneeded": marker.mark_unneeded, "unmark_all": marker.unmark_all,
            "properties": lambda: self.show_tab("general"), "why_blocked": lambda: self.show_tab("dependencies"),
            "find": self.find, "back": b.go_back, "quit": self.app.request_quit, "about": self.about,
            "copy_name": b.copy_names, "copy_nevra": b.copy_nevras, "unmark": b.unmark_selected,
            "filters": b.custom_filters.edit,
            "new_filter": lambda: b.custom_filters.new_from_view(b.filter, b.search.text(), b.search.mode()),
            "save_marks": b.save_marks, "read_marks": b.read_marks, "export_csv": b.export_csv,
            **{mark_upgrades_id(kind): lambda kind=kind: marker.mark_upgrades(kind) for kind in UPGRADE_KINDS},
            **{mark_id(a): lambda a=a: b.mark_selected(a) for a in MARK_ACTIONS},
        }

    def run_either(self, *action_ids: str) -> None:
        """A key with two actions (`+`: install or upgrade, `=`: lock or unlock): the first one that is on."""
        self.run_action(next((a for a in action_ids if self.action_enabled(a)), action_ids[0]))

    def show_tab(self, name: str) -> None:
        """Properties, Why It Cannot Be Upgraded: that tab of the details, shown."""
        self.details.select_name(name)
        self.open_details()

    def about(self) -> None:
        self.app.push_screen(AboutDialog(self.ui))

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

    def context_menu(self, at: tuple[int, int]) -> None:
        """The row's menu (§7.7.2) at the screen cell `at`."""
        open_table_menu(self, at)

    def find(self) -> None:
        """`/`, ctrl+f and the menu's Find (§7.6): the search dialog, once there is a catalog to search."""
        if self.browser.snapshot is not None:
            open_search(self)

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
