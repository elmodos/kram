"""The main window's logic without its widgets: loading the catalog, filtering and searching, sorting, following
dependency links, marking, the version lock, reviewing and applying changes, running the helper, the repositories,
undoing a transaction, and the status line.

`Browser` drives the toolkit-free models (PackageList, SidebarModel, SearchController, Marker, DetailsLoader); the
window is a view that shows them and implements `BrowserView`. Every flow that waits for the user goes through a
continuation (the Ui port and the view's dialogs), so that it works the same where dialogs do not block (GTK 4).
"""
import json
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .. import instance
from ..core.catalog import Catalog
from ..core.csv_export import write_csv
from ..core.filters import UPGRADES_FIXES, UPGRADES_SECURITY, UPGRADES_SECURITY_HIGH, FilterEntry
from ..core.history import Change, UndoProblem, UndoStep, changes_comps, plan_undo
from ..core.mainloop import Post, Signal
from ..core.marks import Action, group_request
from ..core.model import CatalogSnapshot, GroupInfo, PkgRow, Status, TransactionPreview
from ..core.repo_files import file_owners
from ..core.search import MODE_LABELS, Mode, NarrowingSearch, SearchIndex
from ..core.settings import store as settings
from ..core.updates import Cancelled
from ..core.worker import DnfWorker
from ..i18n import _, ngettext
from ..ipc.client import HelperClient
from ..notifier import control as notifier_control
from . import empty_list
from .actions import ActionState, DynamicItem, action_state, downgrade_items
from .columns import COL_NAME
from .details import DetailsLoader, DetailsSink
from .doc import Doc
from .marking import Marker, group_menu
from .markings import ask_markings_file, save_markings
from .package_list import PackageList, Sort
from .ports import OK, Button, Question, Ui
from .scheduler import Scheduler
from .search import SearchController
from .sidebar import SidebarModel

BLOCKED_ENTRY = "status:blocked"  # Status → Cannot be upgraded now
# the empty list of a sidebar entry that stays empty until the user does something: how to fill it
EMPTY_HINTS = {
    "status:locked": _("To keep an installed package at its version, select it and choose Package → Lock Version: "
                       "upgrades then leave it out until it is unlocked."),
}
UPGRADE_KINDS = (UPGRADES_SECURITY, UPGRADES_SECURITY_HIGH, UPGRADES_FIXES)
STATUS_MESSAGE_MS = 5000
LONG_MESSAGE_MS = 8000


@dataclass(frozen=True)
class ReposChoice:
    """What the user did in the Repositories dialog: show one repository's packages, remove repositories, or
    enable and disable them (`changes`: repo id -> enabled)."""
    show_repo: str | None = None
    remove_repos: tuple[str, ...] = ()
    changes: dict | None = None


class BrowserView(Protocol):
    """What `Browser` needs from the window."""

    # the package list
    def current_key(self) -> tuple[str, str] | None: ...

    def select_key(self, key: tuple[str, str], scroll: bool = True) -> bool:
        """Select the row of `key` if it is listed (scrolled to the middle with `scroll`); False if it is not."""
        ...

    def select_first(self, to_top: bool) -> None:
        """Select the first row; `to_top`: and scroll to it (ranked results: the best match)."""
        ...

    def selected_rows(self) -> list[PkgRow]: ...

    def show_sort(self, sort: Sort | None) -> None:
        """Show the sort indicator of `sort` (None: none, the order is ranked) without sorting anything."""
        ...

    def set_empty(self, doc: Doc) -> None:
        """What the list says while it is empty."""
        ...

    def focus_list(self) -> None: ...

    # the status line and the actions
    def set_status(self, text: str) -> None: ...

    def status_text(self) -> str: ...

    def show_catalog(self, snap: CatalogSnapshot) -> None: ...

    def show_counts(self, snap: CatalogSnapshot, shown: int, to_install: int, to_remove: int,
                    ms: float | None) -> None: ...

    def show_error(self, error: BaseException) -> None: ...

    def apply_actions(self, state: ActionState, catalog: bool, busy: bool) -> None: ...

    def set_reload_enabled(self, on: bool) -> None: ...

    def set_apply_enabled(self, on: bool) -> None: ...

    # dialogs that are flows of their own
    def review_changes(self, preview: TransactionPreview, request: dict, basearch: str,
                       resolve: Callable, done: Callable[[dict | None], None]) -> None:
        """Show what `request` does; `done(request)` with the user's changes to it ("download_only", unchecked
        recommendations) when they apply it, None when they do not."""
        ...

    def run_helper(self, request: dict, title: str, done: Callable[[dict | None], None]) -> None:
        """Run a helper request with its progress; `done(final event)` if it succeeded, None if not."""
        ...

    def show_repos(self, snap: CatalogSnapshot, counts: dict, owners: dict, listed: Counter, installed: Counter,
                   done: Callable[[ReposChoice | None], None]) -> None: ...


def rpm_path(paths: list[str]) -> str | None:
    """A drop of exactly one local .rpm file: its path."""
    return paths[0] if len(paths) == 1 and paths[0].endswith(".rpm") else None


class Browser:
    """`catalog_loaded(snap)`: after every (re)load. `refreshed()`: the metadata was refreshed (Reload)."""

    def __init__(self, view: BrowserView, ui: Ui, scheduler: Scheduler, details: DetailsSink, post: Post,
                 catalog: Catalog | None = None, dnf: DnfWorker | None = None, helper: HelperClient | None = None):
        self.view, self.ui, self._post = view, ui, post
        self.dnf = dnf or DnfWorker(post)
        self.catalog = catalog or Catalog()
        self.helper = helper or HelperClient(post)
        self.snapshot: CatalogSnapshot | None = None
        self.filter: FilterEntry | None = None
        self.history: list[tuple[str, str]] = []  # packages visited via dependency links, for Back
        self.index: SearchIndex | None = None
        self.narrowing: NarrowingSearch | None = None
        self._candidates_cache: tuple[FilterEntry, CatalogSnapshot, list[int]] | None = None
        self.key_index: dict[tuple[str, str], int] = {}
        self._search_gen = 0  # drops stale async (provides/file) results
        self.user_sort: Sort = (COL_NAME, False)  # the column sort the user chose, kept while results are ranked
        self._last_count = 0
        self._wider_searches: tuple[SearchIndex, NarrowingSearch, NarrowingSearch] | None = None  # see _why_empty
        # True from the start of a resolve until its preview arrives: the helper is idle then, but the apply flow
        # is not done, and a second apply or refresh started meanwhile would run the same request twice
        self._reviewing = False
        self._restore_filter = ("status", "status:all")
        self.custom_filters = None  # set by the window: queries(), resolve_missing(done), menu_items(entry)
        self.catalog_loaded = Signal()
        self.refreshed = Signal()

        self.packages = PackageList()
        self.sidebar = SidebarModel(scheduler)
        self.sidebar.marked = self.packages.marks
        self.sidebar.blocked = self.packages.blocked  # the same dict for good: the list changes it in place
        self.sidebar.filter_changed.connect(self._on_filter)
        self.search = SearchController(scheduler)
        self.search.changed.connect(self.apply_filter)
        self.search.submitted.connect(self._on_search_enter)
        self.search.settled.connect(self._remember_search)
        self.marker = Marker(self.packages, self.catalog, self.dnf, ui)
        self.marker.changed.connect(self._marks_changed)
        self.marker.groups_changed.connect(self.update_actions)
        self.marker.message.connect(ui.status)
        self.marker.failed.connect(view.show_error)
        self.details_loader = DetailsLoader(details, self.catalog, self.dnf, self.packages.blocked.get,
                                            self.packages.set_blocked_reason, scheduler)

    # ---------------------------------------------------------------- settings

    def restore_settings(self) -> None:
        self.search.set_mode(settings.get("search/mode", int(Mode.NAME)))
        try:
            self.sidebar.history = [tuple(h) for h in json.loads(settings.get("search/history", "[]"))]
        except (TypeError, ValueError):
            self.sidebar.history = []
        self._restore_filter = (settings.get("sidebar/view", "status"), settings.get("sidebar/entry", "status:all"))

    def save_settings(self) -> None:
        settings.set("search/history", json.dumps(self.sidebar.history, ensure_ascii=False))
        settings.set("search/mode", int(self.search.mode()))
        settings.set("sidebar/view", self.sidebar.current_view)
        if entry := self.sidebar.current_entry_id:
            settings.set("sidebar/entry", entry)

    def show_view(self, view: str) -> None:
        """`view` from kram.instance: "" keeps the filter, UPGRADABLE selects Status → Upgradable."""
        if view != instance.UPGRADABLE:
            return
        if self.filter is None:  # still loading: the filter to select once the catalog is there
            self._restore_filter = ("status", "status:upgradable")
        else:
            self.sidebar.select("status", "status:upgradable")

    def can_close(self, done: Callable[[bool], None]) -> None:
        """Quitting: not while something runs; with unapplied marks only if the user says so."""
        if self.busy():
            done(False)
            return
        n = len(self.packages.marks)
        if not n:
            done(True)
            return
        self.ui.ask(Question("Kram", ngettext("{n} marked change has not been applied. Quit anyway?",
                                              "{n} marked changes have not been applied. Quit anyway?",
                                              n).format(n=n)),
                    lambda answer: done(answer == "yes"))

    def shutdown(self) -> None:
        self.helper.stop()
        self.save_settings()
        self.dnf.shutdown()

    # ---------------------------------------------------------------- loading

    def reload(self) -> None:
        self.view.set_status(_("Loading metadata…"))
        self.view.set_reload_enabled(False)  # a second load at once would read the same catalog twice
        if self.snapshot is None:
            self.view.set_empty(empty_list.loading())
        queries = self.custom_filters.queries() if self.custom_filters is not None else set()
        self.dnf.submit(lambda: self.catalog.load(queries, self._waiting_for_lock, self.dnf.cancelled),
                        self._on_loaded, self._on_error)

    def _waiting_for_lock(self) -> None:
        """On the worker thread: another package manager holds the system repo lock, the load waits for it."""
        self._post(lambda: self.view.set_status(_("Waiting for another package manager to finish…")))

    def _on_loaded(self, snap: CatalogSnapshot) -> None:
        keep = self.view.current_key()
        self.snapshot = snap
        self.view.set_reload_enabled(True)
        self.packages.set_rows(snap.rows, snap.basearch)
        if any(r.status is Status.UPGRADABLE for r in snap.rows):
            # after the list is up: the full upgrade resolve takes a few tenths of a second
            self.dnf.submit(self.catalog.blocked_upgrades,
                            lambda blocked: self._on_blocked(blocked) if self.snapshot is snap else None,
                            lambda e: None)  # without it every upgrade just looks installable, as before
        self.index = SearchIndex(snap.rows, snap.descriptions)
        self.narrowing = NarrowingSearch(self.index)
        self.key_index = {r.key: i for i, r in enumerate(snap.rows)}
        self.marker.set_snapshot(snap)
        self.update_actions()
        self.catalog_loaded.emit(snap)
        self.view.show_catalog(snap)
        view, entry = self._restore_filter if self.filter is None else (
            self.sidebar.current_view, self.sidebar.current_entry_id)
        self.sidebar.set_snapshot(snap)
        self.sidebar.select(view, entry)  # emits filter_changed -> apply_filter
        if keep:
            self.view.select_key(keep)
        # a filter edited while this catalog was loading
        if self.custom_filters is not None:
            self.custom_filters.resolve_missing(lambda: self.sidebar.set_view(self.sidebar.current_view))

    def _on_error(self, e: BaseException) -> None:
        if isinstance(e, Cancelled):  # the window is closing: nothing to report
            return
        self.view.set_reload_enabled(True)
        self.view.show_error(e)
        if self.snapshot is None:
            self.view.set_empty(empty_list.failed())
        self.ui.error("Kram", _("Could not load the package catalog:\n\n{error}").format(error=e))

    def _on_blocked(self, blocked: dict[tuple[str, str], str]) -> None:
        self.packages.set_blocked(blocked)
        self.details_loader.refresh_blocked()
        self.update_actions()
        if self.sidebar.current_view == "status":
            self.sidebar.refresh_counts()
        if self.filter is not None and self.filter.id == BLOCKED_ENTRY:  # restored before they were known
            self.apply_filter()

    def once_loaded(self, slot: Callable[[CatalogSnapshot], None]) -> None:
        """Call `slot` after the next load only."""
        def once(snap: CatalogSnapshot) -> None:
            self.catalog_loaded.disconnect(once)
            slot(snap)
        self.catalog_loaded.connect(once)

    # ---------------------------------------------------------------- filtering and searching

    def _on_filter(self, entry: FilterEntry) -> None:
        self.filter = entry
        self.packages.optional = entry.optional  # in italics: what installing the group leaves out
        if entry.query is not None:  # a search-history entry: re-run that search
            self.search.set_query(*entry.query)
            self.apply_filter()
            self.search.stop_history()  # already in the history; don't reorder the list under the cursor
            return
        self.apply_filter()

    def _candidates(self) -> list[int]:
        """Rows the sidebar filter lets in. Worked out again only for another filter entry or catalog: a keystroke
        used to run the predicate over every row (36 ms of a 45 ms keystroke here). Entries are rebuilt whenever
        what they count changes, except "Marked", which follows the marks as they are, and "Cannot be upgraded
        now", which fills in after the list: never cached."""
        entry, snap = self.filter, self.snapshot
        cached = self._candidates_cache
        if (cached is not None and cached[0] is entry and cached[1] is snap
                and entry.id not in ("status:marked", BLOCKED_ENTRY)):
            return cached[2]
        pred = entry.predicate
        found = [i for i, r in enumerate(snap.rows) if pred(r)]
        self._candidates_cache = (entry, snap, found)
        return found

    def apply_filter(self) -> None:
        """Sidebar filter, then search. Searches rank their results; an empty search uses the column sort."""
        if not self.snapshot or not self.filter:
            return
        self.search.cancel_pending()
        t0 = time.perf_counter()
        self._search_gen += 1
        candidates = self._candidates()
        text = self.search.text()
        mode = self.search.mode()
        if not text:
            self.search.stop_history()
            # a copy: the list keeps the list it is given, and this one is cached
            self._show(list(candidates), ranked=False, ms=(time.perf_counter() - t0) * 1000)
        elif mode.local:
            self._show(self.narrowing.search(text, mode, candidates), ranked=True,
                       ms=(time.perf_counter() - t0) * 1000)
            self.search.start_history()
        else:
            gen = self._search_gen
            allowed = set(candidates)
            lookup = self.catalog.search_provides if mode is Mode.PROVIDES else self.catalog.search_files
            if mode is Mode.PROVIDES and not self.catalog.capabilities_ready:
                self.view.set_status(_("Searching “{text}” ({mode}); the first search also indexes what packages "
                                       "provide…").format(text=text, mode=MODE_LABELS[mode]))
            else:
                self.view.set_status(_("Searching “{text}” ({mode})…").format(text=text, mode=MODE_LABELS[mode]))
            # not the empty list's last explanation, which was about another search
            self.view.set_empty(empty_list.message(self.view.status_text()))

            def done(keys):
                if keys is None or gen != self._search_gen:
                    return
                everywhere = [i for k in keys if (i := self.key_index.get(k)) is not None]
                found = [i for i in everywhere if i in allowed]
                self._show(self.index.rank_keys(found), ranked=True, ms=(time.perf_counter() - t0) * 1000,
                           found_in_all=len(everywhere))
                self.search.start_history()
            # the dnf thread takes jobs one after the other: a search typed over by then is skipped, not run for nothing
            self.dnf.submit(lambda: lookup(text) if gen == self._search_gen else None, done, self._on_search_failed)

    def _on_search_failed(self, e: BaseException) -> None:
        """A Provides or file search that failed: the catalog itself is fine, so only the search says so."""
        self.ui.status(_("Search failed: {error}").format(error=e), LONG_MESSAGE_MS)

    def _show(self, visible: list[int], ranked: bool, ms: float, found_in_all: int | None = None) -> None:
        # switch the header between "ranked" (no indicator) and the user's column sort without
        # triggering a sort of the old rows; set_visible sorts the new ones
        if ranked or self.packages.sort_column is None:
            self.view.show_sort(None if ranked else self.user_sort)
            if ranked:
                self.packages.sort(-1)
            else:
                self.packages.set_sort_column(self.user_sort)
        keep = self.view.current_key()
        self.packages.set_visible(visible, ranked=ranked)
        self._last_count = len(visible)
        self.update_status(len(visible), ms)
        if not visible:
            self.details_loader.clear()
            self.view.set_empty(empty_list.explain(self._why_empty(found_in_all)))
        elif ranked:  # best match first: select it rather than keeping an old selection
            self.view.select_first(to_top=True)
        elif not (keep and self.view.select_key(keep, scroll=True)):
            self.view.select_first(to_top=False)

    def _why_empty(self, found_in_all: int | None) -> empty_list.EmptyList:
        """What the empty list says. The searches over all packages or descriptions run only when it is empty, and
        narrow as the user types on, as the search itself does (`found_in_all`: an async search counted them)."""
        entry, text, mode = self.filter, self.search.text(), self.search.mode()
        in_all = entry.id == "status:all" or entry.query is not None  # a search-history entry lets every row in
        wider = self._wider_searches
        if wider is None or wider[0] is not self.index:
            wider = self._wider_searches = (self.index, NarrowingSearch(self.index), NarrowingSearch(self.index))
        _index, everywhere, descriptions = wider
        everything = range(len(self.snapshot.rows))
        if text and not in_all and found_in_all is None:
            found_in_all = len(everywhere.search(text, mode, everything)) if mode.local else 0
        in_descriptions = 0
        if text and mode < Mode.DESCRIPTION and self.index.descriptions and not (found_in_all and not in_all):
            in_descriptions = len(descriptions.search(text, Mode.DESCRIPTION, self._candidates()))
        return empty_list.EmptyList(entry.label, in_all, text, file_search=mode is Mode.FILE,
                                    found_in_all=found_in_all or 0, found_in_descriptions=in_descriptions,
                                    missing_repos=len(self.snapshot.unavailable_repos),
                                    hint=EMPTY_HINTS.get(entry.id, ""))

    def empty_link(self, link: str) -> None:
        """A link of the empty list (kram.app.empty_list)."""
        if link == empty_list.ALL:
            self.sidebar.select("status", "status:all")  # the search stays and runs in "All"
        elif link == empty_list.DESCRIPTIONS:
            self.search.set_mode(Mode.DESCRIPTION)  # searches again
        elif link == empty_list.RELOAD:
            self.refresh_metadata()
        elif link == empty_list.REPOS:
            self.open_repos()
        elif link == empty_list.RETRY:
            self.reload()

    def user_sorted(self, column: int, descending: bool) -> None:
        """The user clicked a column header (a negative column: the indicator was cleared for ranked results)."""
        if column >= 0:
            self.user_sort = (column, descending)

    def _on_search_enter(self) -> None:
        self.apply_filter()
        if not self.search.mode().local:
            return  # async: remembered when results arrive (timer started in done())
        self._remember_search()

    def _remember_search(self) -> None:
        self.search.stop_history()
        if text := self.search.text():
            self.sidebar.add_search(text, int(self.search.mode()), self._last_count)

    def update_status(self, shown: int | None = None, ms: float | None = None) -> None:
        s = self.snapshot
        if s is None:
            return
        self.view.show_counts(s, len(self.packages) if shown is None else shown, *self.packages.marks.counts(), ms)

    # ---------------------------------------------------------------- selection, details and links

    def current_changed(self, row: PkgRow | None) -> None:
        if row is not None:
            self.details_loader.follow(row)

    def follow_link(self, kind: str, value: str) -> None:
        """A link in the details: "pkg" (name.arch) or "dep" (a requirement: go to what provides it)."""
        if kind == "pkg":
            name, _sep, arch = value.rpartition(".")
            self.navigate((name, arch))
        else:
            self.dnf.submit(lambda: self.catalog.find_provider(value),
                            lambda key: self.navigate(key) if key else self.ui.status(
                                _("Nothing provides “{what}”").format(what=value), STATUS_MESSAGE_MS),
                            lambda e: self.ui.status(
                                _("Could not look up “{what}”: {error}").format(what=value, error=e),
                                LONG_MESSAGE_MS))

    def navigate(self, key: tuple[str, str] | None, remember: bool = True) -> None:
        if not key:
            return
        if remember and (cur := self.view.current_key()) and cur != key:
            self.history.append(cur)
        if self.view.select_key(key):
            return
        # not visible under the current filter: fall back to "All" with no search
        self.search.clear(quietly=True)
        self.sidebar.select("status", "status:all")
        if not self.view.select_key(key):
            self.ui.status(_("Package {name} not found in the catalog").format(name=f"{key[0]}.{key[1]}"),
                           STATUS_MESSAGE_MS)

    def go_back(self) -> None:
        if self.history:
            self.navigate(self.history.pop(), remember=False)

    def copy_names(self) -> None:
        self.ui.copy_text(" ".join(r.name for r in self.view.selected_rows()))

    def copy_nevras(self) -> None:
        self.ui.copy_text(" ".join(f"{r.name}-{r.installed_evr or r.candidate_evr}.{r.arch}"
                                   for r in self.view.selected_rows()))

    def downgrade_items(self) -> list[DynamicItem]:
        rows = self.view.selected_rows()
        row = rows[0] if len(rows) == 1 else None
        details = self.details_loader.details_of(row.key) if row is not None else None
        return downgrade_items(row, details, lambda evr: self.mark_selected(Action.DOWNGRADE, evr))

    def sidebar_menu(self, entry: FilterEntry | None) -> list[DynamicItem | str | None]:
        """The sidebar's context menu for `entry`: dynamic items, action ids (kram.app.actions), None for a
        separator."""
        items: list[DynamicItem | str | None] = []
        if entry is not None and entry.group and (group := self.marker.group(entry.group)) is not None:
            items += [*group_menu(group, busy=self.busy(), run=self.change_group), None]
        if entry is not None and entry.id == "status:unneeded":
            items += ["mark_unneeded", None]
        if entry is not None and (repo_id := self.enabled_repo(entry)) is not None:
            items += [DynamicItem(_("Refresh Metadata"), lambda: self.refresh_repo_metadata(repo_id), "view-refresh",
                                  not self.busy()), None]
        if self.custom_filters is not None:
            items += self.custom_filters.menu_items(entry)
        if self.sidebar.current_view == "search":
            if entry is not None and entry.query is not None:
                text, mode = entry.query
                items.append(DynamicItem(_("Remove from History"), lambda: self.sidebar.remove_search(text, mode),
                                         "edit-delete"))
            items += [DynamicItem(_("Clear Search History"), self.sidebar.clear_history, "edit-clear-history",
                                  bool(self.sidebar.history)), None]
        return items + ["new_filter", "filters"]

    def enabled_repo(self, entry: FilterEntry) -> str | None:
        """The repo id of a sidebar repository entry, if that repository is enabled."""
        if not entry.id.startswith("repo:") or self.snapshot is None:
            return None
        repo_id = entry.id.removeprefix("repo:")
        return repo_id if any(r.id == repo_id and r.enabled for r in self.snapshot.repos) else None

    # ---------------------------------------------------------------- marking

    def busy(self) -> bool:
        """A helper request runs, or the marks are being resolved for review: nothing else may start meanwhile."""
        return self.helper.busy or self._reviewing

    def can_open_file(self) -> bool:
        """Not while another dialog or a transaction is running: a dropped file or a stray shortcut then does
        nothing, whatever the toolkit's modality lets through."""
        return self.snapshot is not None and not self.busy() and not self.ui.is_modal_open()

    def update_actions(self, *_args) -> None:
        snap = self.snapshot
        state = action_state(
            self.view.selected_rows(), catalog=snap is not None, n_upgradable=snap.n_upgradable if snap else 0,
            marks=self.packages.marks, blocked=self.packages.blocked, busy=self.busy(),
            upgrades_of_kind={kind: bool(self.marker.upgrades_of(kind)) for kind in UPGRADE_KINDS},
            unneeded=bool(self.marker.unneeded), can_open_file=self.can_open_file())
        self.view.apply_actions(state, snap is not None, self.busy())

    def _marks_changed(self, keys) -> None:
        self.packages.marks_changed(keys)
        self.update_actions()
        self.update_status()
        if self.sidebar.current_view == "status":
            self.sidebar.refresh_marked_count()

    def mark_selected(self, action: Action, evr: str = "") -> None:
        self.marker.mark(self.view.selected_rows(), action, evr)

    def unmark_selected(self) -> None:
        self.marker.unmark(self.view.selected_rows())

    def save_marks(self) -> None:
        def saved(path: str) -> None:
            n = len(self.packages.marks)
            self.ui.status(ngettext("{n} marking saved to {path}", "{n} markings saved to {path}", n)
                           .format(n=n, path=path), STATUS_MESSAGE_MS)
        save_markings(self.ui, self.packages.marks, saved)

    def read_marks(self) -> None:
        ask_markings_file(self.ui, self.marker.read_file)

    def export_csv(self) -> None:
        title = _("Export List as CSV")
        folder = settings.get("export/dir", str(Path.home()))

        def chosen(path: str | None) -> None:
            if not path:
                return
            rows = self.packages.shown_rows()  # in the order shown
            try:
                with open(path, "w", encoding="utf-8", newline="") as out:
                    n = write_csv(out, rows, self.packages.marks)
            except OSError as e:
                self.ui.error(title, _("Could not save {path}:\n\n{error}").format(path=path, error=e.strerror or e))
                return
            settings.set("export/dir", str(Path(path).parent))
            self.ui.status(ngettext("{n} package exported to {path}", "{n} packages exported to {path}", n)
                           .format(n=n, path=path), STATUS_MESSAGE_MS)
        self.ui.choose_save_file(title, str(Path(folder) / "kram-packages.csv"),
                                 _("CSV files (*.csv);;All files (*)"), chosen)

    def set_version_lock(self, lock: bool) -> None:
        """Lock the selected installed packages to their installed versions (`dnf5 versionlock add`), or remove
        their locks. A configuration change, not a transaction: it runs at once, and the catalog reloads after it."""
        if self.busy():
            return
        rows = self.view.selected_rows()
        names = sorted({r.name for r in rows if (r.installed and not r.locked if lock else r.locked)})
        if not names:
            return
        if lock:
            # the lock leaves no other version to go to: drop the marks that would need one, and say so
            wanted = set(names)
            moving = [r for r in self.snapshot.rows if r.name in wanted and (m := self.packages.marks.get(r.key))
                      and m.action in (Action.UPGRADE, Action.DOWNGRADE)]
            if moving:
                self.marker.unmark(moving)
                self.ui.status(ngettext(
                    "{n} upgrade or downgrade unmarked: the version lock keeps the installed version",
                    "{n} upgrades or downgrades unmarked: the version lock keeps the installed versions",
                    len(moving)).format(n=len(moving)), LONG_MESSAGE_MS)
            title = ngettext("Locking the version of {n} package", "Locking the versions of {n} packages", len(names))
        else:
            title = ngettext("Unlocking the version of {n} package", "Unlocking the versions of {n} packages",
                             len(names))
        self.run_helper_and_reload({"op": "versionlock", "action": "add" if lock else "delete", "names": names},
                                   title.format(n=len(names)))

    # ---------------------------------------------------------------- applying

    def apply(self) -> None:
        if not len(self.packages.marks) or self.busy():
            return
        rows = {r.key: r for r in self.snapshot.rows}
        self._review({"op": "transaction", **self.packages.marks.request(rows)}, marked=True,
                     keys=frozenset(self.packages.marks.keys()))

    def change_group(self, group: GroupInfo, action: Action, optional: bool = False) -> None:
        """Install, upgrade or remove a comps group or environment at once, after the review. Only that: the marks
        stay for a later Apply (a reload drops the ones it has carried out)."""
        if self.busy():
            return
        self._review({"op": "transaction", **group_request(group, action, optional)}, marked=False)

    def _review(self, request: dict, marked: bool, keys: frozenset = frozenset()) -> None:
        """Resolve `request`, show what it does, run it if the user agrees. `marked`: it is the marked changes, which
        are the ones with `keys` (the marks when the request was built): only those are unmarked afterwards."""
        self._reviewing = True
        self.update_actions()
        self.view.set_status(_("Resolving dependencies…"))
        self.dnf.submit(lambda: self.catalog.resolve(request),
                        lambda p: self._on_preview(p, request, marked, keys=keys),
                        self._on_review_failed)

    def _on_review_failed(self, e: BaseException) -> None:
        self._reviewing = False
        self.update_status()
        self.update_actions()
        self.ui.error("Kram", _("Could not resolve the changes:\n\n{error}").format(error=e))

    def _on_preview(self, preview: TransactionPreview, request: dict, marked: bool = True,
                    can_skip: bool | None = None, keys: frozenset = frozenset()) -> None:
        """`can_skip` (an undo that cannot be done whole): whether leaving out what is unavailable would work; None
        until that has been tried."""
        self._reviewing = False
        self.update_status()
        self.update_actions()
        if not preview.ok and request.get("revert") and not request.get("skip_unavailable") and can_skip is None:
            # offer the partial undo only when it resolves: when the transaction cannot be reverted for another
            # reason (its environment was removed since), it would fail the same way
            partial = {**request, "skip_unavailable": True}
            self._reviewing = True
            self.update_actions()
            self.dnf.submit(lambda: self.catalog.resolve(partial, sizes=False).ok,
                            lambda ok: self._on_preview(preview, request, marked, ok, keys),
                            lambda _e: self._on_preview(preview, request, marked, False, keys))
            return
        if not preview.ok:
            self._cannot_apply(preview, request, marked, can_skip)
            return

        def resolve(req, done, failed):
            self.dnf.submit(lambda: self.catalog.resolve(req, sizes=False), done, failed)

        def reviewed(final: dict | None) -> None:
            if final is None:
                return

            def ran(result: dict | None) -> None:
                if final.get("download_only"):
                    return
                if result is not None and marked:
                    # the marks added since the request was built stay; a failed run keeps all of them, and the
                    # reload drops those that no longer apply
                    self.marker.unmark([r for r in self.snapshot.rows if r.key in keys])
                # even after a failure: part of the change may have happened
                self.reload()
            self.run_helper(final, _("Applying changes"), ran)
        self.view.review_changes(preview, request, self.snapshot.basearch, resolve, reviewed)

    def _cannot_apply(self, preview: TransactionPreview, request: dict, marked: bool, can_skip: bool | None) -> None:
        info = preview.problems[0][:500]
        buttons = []
        if can_skip:
            info += "\n\n" + _("Undoing the whole transaction needs versions the repositories no longer have. "
                               "What is still possible can be undone without them.")
            buttons.append(Button("skip", _("Undo What Is Possible…")))
        if preview.versionlock:
            info += "\n\n" + _("They need a version the version lock excludes. Unlock the package "
                               "(Package → Unlock Version) or unmark the change.")
            buttons.append(Button("locked", _("Show Locked Packages")))
        question = Question(_("Cannot apply changes"),
                            _("The marked changes cannot be carried out. Unmark or change them.") if marked else
                            _("This change cannot be carried out."),
                            (*buttons, OK), informative=info, details="\n".join(preview.problems), icon="warning")

        def answered(answer: str | None) -> None:
            if answer == "locked":
                self.search.clear()
                self.sidebar.select("status", "status:locked")
            elif answer == "skip":
                self._review({**request, "skip_unavailable": True}, marked=False)
        self.ui.ask(question, answered)

    # ---------------------------------------------------------------- the helper

    def run_helper(self, request: dict, title: str, done: Callable[[dict | None], None] | None = None) -> None:
        """Run a helper request with its progress; `done(final event or None)` after it."""
        self.view.set_apply_enabled(False)
        self.view.set_reload_enabled(False)

        def finished(result: dict | None) -> None:
            self.view.set_reload_enabled(True)
            self.update_actions()
            notifier_control.recheck()  # even after a failure: the metadata may have been refreshed
            if done is not None:
                done(result)
        self.view.run_helper(request, title, finished)

    def run_helper_and_reload(self, request: dict, title: str,
                              done: Callable[[bool], None] | None = None) -> None:
        def ran(result: dict | None) -> None:
            self.reload()  # even after a failure: part of the change may have happened
            if done is not None:
                done(result is not None)
        self.run_helper(request, title, ran)

    def refresh_metadata(self) -> None:
        if self.busy():
            return

        def ran(_result) -> None:
            self.refreshed.emit()
            self.reload()
        self.run_helper({"op": "refresh"}, _("Refreshing metadata"), ran)

    def refresh_repo_metadata(self, repo_id: str) -> None:
        if self.busy():
            return
        self.run_helper({"op": "refresh", "repos": [repo_id]}, _("Refreshing metadata"), lambda _r: self.reload())

    def clean_cache(self, target: str, done: Callable[[], None] | None = None) -> None:
        """Clean a system cache with the helper (kram.app.cache); `done()` after it, whatever came of it."""
        request = {"op": "clean_cache", "target": target}
        if target == "dnf_metadata":
            self.run_helper_and_reload(request, _("Downloading metadata again"), lambda _ok: done and done())
        else:
            self.run_helper(request, _("Cleaning the package cache"), lambda _result: done and done())

    # ---------------------------------------------------------------- repositories

    def open_repos(self) -> None:
        if not self.snapshot or self.busy():
            return
        paths = [r.file_path for r in self.snapshot.repos]
        self.dnf.submit(lambda: (self.catalog.repo_package_counts(), file_owners(paths)), self._show_repos,
                        lambda e: self.ui.warn("Kram", _("Could not read the repositories:\n\n{error}").format(
                            error=e)))

    def _show_repos(self, result) -> None:
        counts, owners = result
        snap = self.snapshot
        self.view.show_repos(snap, counts, owners, Counter(r.origin_repo for r in snap.rows),
                             Counter(r.from_repo_id for r in snap.rows if r.installed), self._repos_chosen)

    def _repos_chosen(self, choice: ReposChoice | None) -> None:
        if choice is None:
            return
        if choice.show_repo:
            self.show_repo_packages(choice.show_repo)
        elif choice.remove_repos:
            # back to the list once it is reloaded without them
            self.once_loaded(lambda _snap: self.open_repos())
            n = len(choice.remove_repos)
            self.run_helper_and_reload({"op": "repo_remove", "repos": list(choice.remove_repos)},
                                       ngettext("Removing {n} repository", "Removing {n} repositories", n).format(n=n))
        elif choice.changes:
            self.run_helper_and_reload({"op": "repo_set_enabled", "repos": choice.changes}, _("Changing repositories"))

    def show_repo_packages(self, repo_id: str) -> None:
        """The repository's entry of the Origin filters, with the search cleared."""
        self.search.clear()
        self.sidebar.select("origin", f"repo:{repo_id}")

    # ---------------------------------------------------------------- undo

    def undo_transaction(self, tid: int, rows, close_history: Callable[[], None]) -> None:
        """Mark the changes that undo transaction `tid` (its `rows` from the history), show them in the Marked list
        and say what cannot be undone; `close_history` once they are marked."""
        if not rows or self.snapshot is None or self.busy():
            return
        if any(r.change is Change.UNREADABLE for r in rows):
            # which groups changed is not known: an undo could leave some of them recorded as installed
            self.ui.warn(_("Undo Transaction {id}").format(id=tid),
                         _("The groups this transaction changed could not be read."))
            return
        if changes_comps(rows):
            # groups are not marked, and package marks alone would leave the groups recorded as installed:
            # `dnf5 history undo`, after the review
            self._review({"op": "transaction", "revert": [tid]}, marked=False)
            return
        snap = self.snapshot

        def done(states) -> None:
            if self.snapshot is not snap:
                return  # reloaded meanwhile: the states may be out of date
            steps, problems = plan_undo(rows, states)
            failed = self.marker.mark_undo(steps)
            problems += [UndoProblem(f"{s.key[0]}.{s.key[1]}", _("cannot be marked")) for s in failed]
            marked = [s for s in steps if s not in failed]
            close_history()
            if marked:
                self.search.clear(quietly=True)
                self.sidebar.select("status", "status:marked")
                self.apply_filter()  # already on Marked: the list shows the new marks too
            self._report_undo(tid, marked, problems)
        self.dnf.submit(lambda: self.catalog.package_states({r.key for r in rows}), done, self._on_undo_failed)

    def _on_undo_failed(self, e: BaseException) -> None:
        self.ui.warn(_("Undo Transaction"), _("Could not read what the transaction changed:\n\n{error}").format(
            error=e))

    def _report_undo(self, tid: int, marked: list[UndoStep], problems: list[UndoProblem]) -> None:
        title = _("Undo Transaction {id}").format(id=tid)
        text = ngettext("{n} change marked to undo transaction {id}.", "{n} changes marked to undo transaction {id}.",
                        len(marked)).format(n=len(marked), id=tid)
        others = [_("{package}: installs {version}, {old} is no longer in the repositories").format(
                      package=f"{s.key[0]}.{s.key[1]}", version=s.evr, old=s.instead_of)
                  for s in marked if s.instead_of]
        if not problems and not others:
            if marked:
                self.ui.status(text + " " + _("Review them, then apply."), LONG_MESSAGE_MS)
            return
        if not marked:
            text = _("Nothing of transaction {id} can be undone.").format(id=tid)
        lines = [f"{p.package}: {p.why}" for p in problems]
        info = []
        if problems:
            info.append(ngettext("{n} package cannot be undone:", "{n} packages cannot be undone:",
                                 len(problems)).format(n=len(problems)) + "\n" + "\n".join(lines[:12])
                        + ("\n…" if len(lines) > 12 else ""))
        if others:
            info.append(ngettext("{n} package comes back in another version:",
                                 "{n} packages come back in another version:", len(others)).format(n=len(others))
                        + "\n" + "\n".join(others[:6]) + ("\n…" if len(others) > 6 else ""))
        (self.ui.info if marked else self.ui.warn)(title, text, "\n\n".join(info), "\n".join(lines + others))
