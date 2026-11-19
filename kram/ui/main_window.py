"""Main window: Synaptic layout — browse, mark, preview, apply."""
import html
import json
import time
from collections import Counter
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSplitter,
    QToolButton,
    QWidget,
)

from .. import HOMEPAGE, __version__, instance
from ..core import releases
from ..core.catalog import Catalog
from ..core.csv_export import write_csv
from ..core.evr import evr_cmp
from ..core.filters import FilterEntry
from ..core.marks import Action, allowed_actions
from ..core.model import CatalogSnapshot, PkgRow, Status, TransactionPreview
from ..core.repo_files import file_owners
from ..core.search import MODE_LABELS, Mode, NarrowingSearch, SearchIndex
from ..core.worker import DnfWorker
from ..i18n import _, ngettext
from ..ipc.client import HelperClient
from ..notifier import control as notifier_control
from . import empty_list
from .actions import WindowActions
from .apply_dialog import ApplyDialog
from .cache_dialog import CacheDialog
from .copr_dialog import CoprDialog
from .custom_filters import CustomFilters
from .details import DetailsTabs
from .details_loader import DetailsLoader
from .install_dialog import InstallDialog
from .marking import Marker
from .markings_file import ask_markings_file, save_markings
from .notifier_dialog import NotifierDialog
from .package_model import COL_NAME, COL_STATUS, PackageTableModel
from .package_view import PackageView
from .progress_dialog import ProgressDialog
from .qt_loop import post
from .release_watch import ReleaseWatcher
from .repos_dialog import ReposDialog
from .search_bar import SearchBar
from .sidebar import Sidebar
from .status_bar import MainStatusBar
from .toolbar import MainToolBar
from .upgrade_dialog import UpgradeDialog
from .whats_new import WhatsNewDialog

DETAILS_TAB_KEY = "details/tab-name"  # "details/tab" held its position before the advisories tab came
FILES_VIEW_KEY = "details/files-view"  # "tree" or "list"


class MainWindow(QMainWindow):
    catalogLoaded = Signal(object)  # CatalogSnapshot, after every (re)load

    def __init__(self):
        super().__init__()
        self.setWindowTitle(_("Package Manager"))  # Qt appends " — Kram" (the application display name)
        self.resize(1320, 860)

        self.dnf = DnfWorker(post)
        self.catalog = Catalog()
        self.snapshot: CatalogSnapshot | None = None
        self.filter: FilterEntry | None = None
        self.history: list[tuple[str, str]] = []  # packages visited via dependency links, for Alt+Left
        self.index: SearchIndex | None = None
        self.narrowing: NarrowingSearch | None = None
        self._candidates_cache: tuple[FilterEntry, CatalogSnapshot, list[int]] | None = None
        self.key_index: dict[tuple[str, str], int] = {}
        self._search_gen = 0                 # drops stale async (provides/file) results
        self._user_sort = (COL_NAME, Qt.SortOrder.AscendingOrder)
        self._last_count = 0
        self._wider_searches: tuple[SearchIndex, NarrowingSearch, NarrowingSearch] | None = None  # see _why_empty
        self.helper = HelperClient(post)
        self.releases = ReleaseWatcher(self)
        self.releases.act_upgrade.triggered.connect(self.open_upgrade)
        self._upgrade_dialog: UpgradeDialog | None = None
        self.search = SearchBar(self)
        self.search.changed.connect(self.apply_filter)
        self.search.submitted.connect(self._on_search_enter)
        self.search.settled.connect(self._remember_search)
        self.status = MainStatusBar()
        self.status.reposClicked.connect(self.open_repos)
        self.setStatusBar(self.status)

        self._build_central()
        self._connect_actions()
        self.table.addActions(self.acts.table_actions())
        self._build_toolbar()
        self.acts.fill_menu_bar(self.menuBar(), [self.releases.act_watch], self.toolbar.styles.actions())

        self.setAcceptDrops(True)  # an .rpm file dropped anywhere on the window opens the installer
        self._restore_settings()
        self.reload()

    # ---------------------------------------------------------------- construction

    def _connect_actions(self):
        acts = self.acts = WindowActions(self)
        for action, slot in [
            (acts.reload, self.refresh_metadata), (acts.reload_cache, self.reload),
            (acts.mark_upgrades, self.marker.mark_all_upgrades), (acts.mark_unneeded, self.marker.mark_unneeded),
            (acts.apply, self.apply), (acts.unmark_all, self.marker.unmark_all),
            (acts.properties, lambda: self.details.select_name("general")),
            (acts.repos, self.open_repos), (acts.copr, self.open_copr), (acts.cache, self.open_cache),
            (acts.notifications, self.open_notifications),
            (acts.filters, lambda: self.custom_filters.edit()), (acts.new_filter, self.new_filter_from_view),
            (acts.find, self.search.focus), (acts.back, self.go_back),
            (acts.save_marks, self.save_marks), (acts.read_marks, self.read_marks), (acts.export_csv, self.export_csv),
            (acts.open_file, lambda: self.open_package_file()), (acts.quit, self.close), (acts.about, self.about),
            (acts.copy_name, self.copy_names), (acts.copy_nevra, self.copy_nevras), (acts.unmark, self.unmark_selected),
        ]:
            action.triggered.connect(slot)
        for kind, action in acts.mark_upgrades_of_kind.items():
            action.triggered.connect(lambda _on=False, k=kind: self.marker.mark_upgrades(k))
        for mark, action in acts.mark.items():
            action.triggered.connect(lambda _on=False, m=mark: self.mark_selected(m))
        acts.downgrade_menu.aboutToShow.connect(self._fill_downgrade_menu)

    def createPopupMenu(self) -> QMenu:
        # instead of Qt's default "show/hide toolbars" menu: the toolbar can't be hidden, only restyled
        menu = QMenu(self)
        menu.addActions(self.toolbar.styles.actions())
        return menu

    def _build_toolbar(self):
        tb = self.toolbar = MainToolBar()
        tb.addActions([self.acts.reload, self.acts.mark_upgrades, self.acts.apply])
        # a click marks every upgrade, as before; the arrow next to it offers the other ways
        mark_button = tb.widgetForAction(self.acts.mark_upgrades)
        mark_button.setMenu(self.acts.mark_upgrades_menu)
        mark_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        tb.addSeparator()
        tb.addActions([self.acts.repos, self.acts.copr, self.releases.act_upgrade])
        spacer = QWidget()
        spacer.setSizePolicy(spacer.sizePolicy().Policy.Expanding, spacer.sizePolicy().Policy.Preferred)
        tb.addWidget(spacer)
        tb.addWidget(self.search.mode_box)
        tb.addWidget(self.search.edit)
        self.addToolBar(tb)

    def _build_central(self):
        self.sidebar = Sidebar()
        self.sidebar.filterChanged.connect(self._on_filter)
        self.sidebar.contextMenuRequested.connect(self._sidebar_menu)
        self.custom_filters = CustomFilters(self.sidebar, self.catalog, self.dnf, lambda: self.snapshot, self)

        self.model = PackageTableModel(self)
        self.sidebar.marked = self.model.marks
        self.marker = Marker(self.model, self.catalog, self.dnf, self)
        self.marker.changed.connect(self._marks_changed)
        self.marker.groupsChanged.connect(self._group_marks_changed)
        self.marker.message.connect(self.statusBar().showMessage)
        self.marker.failed.connect(self.status.show_error)
        self.table = PackageView()
        self.table.setModel(self.model)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(COL_NAME, Qt.SortOrder.AscendingOrder)
        self.table.header().sortIndicatorChanged.connect(self._on_sort_indicator)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.selectionModel().currentRowChanged.connect(self._on_current)
        self.table.selectionModel().selectionChanged.connect(self._update_actions)
        self.table.clicked.connect(self._on_table_click)
        self.table.doubleClicked.connect(self._on_double_click)
        self.table.emptyLinkActivated.connect(self._on_empty_link)

        self.details = DetailsTabs()
        self.details.linkActivated.connect(self._on_link)
        self.details_loader = DetailsLoader(self.details, self.catalog, self.dnf, self._blocked_reason, self)

        self.vsplit = QSplitter(Qt.Orientation.Vertical)
        self.vsplit.addWidget(self.table)
        self.vsplit.addWidget(self.details)
        self.vsplit.setSizes([540, 260])
        self.vsplit.setCollapsible(1, False)  # the details can shrink to their tab bar, not vanish
        self.hsplit = QSplitter(Qt.Orientation.Horizontal)
        self.hsplit.addWidget(self.sidebar)
        self.hsplit.addWidget(self.vsplit)
        self.hsplit.setStretchFactor(1, 1)
        self.hsplit.setSizes([270, 1050])
        self.setCentralWidget(self.hsplit)

    # ---------------------------------------------------------------- settings

    def _restore_settings(self):
        s = QSettings()
        self.toolbar.set_style(s.value("toolbar/style", self.toolbar.style_id()))
        self.releases.restore()
        self.acts.status_click.setChecked(s.value("table/status_click", False, type=bool))
        if geom := s.value("window/geometry"):
            self.restoreGeometry(geom)
        for key, splitter in (("window/hsplit", self.hsplit), ("window/vsplit", self.vsplit)):
            if state := s.value(key):
                splitter.restoreState(state)
        self.table.restore_columns(s)
        if name := s.value(DETAILS_TAB_KEY):
            self.details.select_name(name)
        else:  # saved before 0.7 by position, from the tabs before the advisories tab came
            old = ("description", "general", "dependencies", "files", "versions", "changelog")
            self.details.select_name(old[min(max(int(s.value("details/tab", 0)), 0), len(old) - 1)])
        self.details.files.tree_mode = s.value(FILES_VIEW_KEY, "tree") != "list"
        self.search.set_mode(int(s.value("search/mode", Mode.NAME)))
        try:
            self.sidebar.history = [tuple(h) for h in json.loads(s.value("search/history", "[]"))]
        except (TypeError, ValueError):
            self.sidebar.history = []
        self.custom_filters.restore()
        self._restore_filter = (s.value("sidebar/view", "status"), s.value("sidebar/entry", "status:all"))

    def show_view(self, view: str) -> None:
        """`view` from kram.instance: "" keeps the filter, UPGRADABLE selects Status → Upgradable."""
        if view != instance.UPGRADABLE:
            return
        if self.filter is None:  # still loading: the filter to select once the catalog is there
            self._restore_filter = ("status", "status:upgradable")
        else:
            self.sidebar.select("status", "status:upgradable")

    def activate_from_outside(self, view: str) -> None:
        """Another `kram` or the tray icon asked for this window. It comes to the front; while a dialog is open over
        it the user is in the middle of something there (marking, applying, a setting): the dialog stays open and
        comes to the front with it, and the filter is left alone."""
        dialog = QApplication.activeModalWidget()
        if dialog is None:
            self.show_view(view)
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        front = dialog or self
        front.raise_()
        front.activateWindow()

    def _save_settings(self):
        s = QSettings()
        if self.model.sort_column is None:  # ranked search results: save the user's column sort instead
            self.table.header().setSortIndicator(*self._user_sort)
        s.setValue("search/history", json.dumps(self.sidebar.history, ensure_ascii=False))
        s.setValue("toolbar/style", self.toolbar.style_id())
        s.setValue("window/geometry", self.saveGeometry())
        s.setValue("window/hsplit", self.hsplit.saveState())
        s.setValue("window/vsplit", self.vsplit.saveState())
        self.table.save_columns(s)
        s.setValue(DETAILS_TAB_KEY, self.details.current_name())
        s.setValue(FILES_VIEW_KEY, "tree" if self.details.files.tree_mode else "list")
        s.setValue("search/mode", self.search.mode_box.currentIndex())
        s.setValue("sidebar/view", self.sidebar.current_view)
        if entry := self.sidebar.current_entry_id:
            s.setValue("sidebar/entry", entry)

    def closeEvent(self, event):
        if self.helper.busy:
            event.ignore()
            return
        if len(self.model.marks) and QMessageBox.question(
                self, "Kram", ngettext("{n} marked change has not been applied. Quit anyway?",
                                       "{n} marked changes have not been applied. Quit anyway?",
                                       len(self.model.marks)).format(n=len(self.model.marks))) \
                != QMessageBox.StandardButton.Yes:
            event.ignore()
            return
        self.helper.stop()
        self._save_settings()
        self.dnf.shutdown()
        super().closeEvent(event)

    # ---------------------------------------------------------------- loading and filtering

    def reload(self):
        self.status.set_text(_("Loading metadata…"))
        self.acts.reload.setEnabled(False)
        if self.snapshot is None:
            self.table.set_empty_text(empty_list.loading())
        queries = self.custom_filters.queries()
        self.dnf.submit(lambda: self.catalog.load(queries, self._waiting_for_lock), self._on_loaded, self._on_error)

    def _blocked_reason(self, key: tuple[str, str]) -> str | None:
        return self.model.blocked.get(key)

    def _on_blocked(self, blocked: dict[tuple[str, str], str]) -> None:
        self.model.set_blocked(blocked)
        self.details_loader.refresh_blocked()

    def _waiting_for_lock(self):
        """On the worker thread: another package manager holds the system repo lock, the load waits for it."""
        post(lambda: self.status.set_text(_("Waiting for another package manager to finish…")))

    def _on_loaded(self, snap: CatalogSnapshot):
        keep = self._current_key()
        self.snapshot = snap
        self.acts.reload.setEnabled(True)
        self.model.set_rows(snap.rows, snap.basearch)
        if any(r.status is Status.UPGRADABLE for r in snap.rows):
            # after the list is up: the full upgrade resolve takes a few tenths of a second
            self.dnf.submit(self.catalog.blocked_upgrades,
                            lambda blocked: self._on_blocked(blocked) if self.snapshot is snap else None,
                            lambda e: None)  # without it every upgrade just looks installable, as before
        self.index = SearchIndex(snap.rows, snap.descriptions)
        self.narrowing = NarrowingSearch(self.index)
        self.key_index = {r.key: i for i, r in enumerate(snap.rows)}
        self.marker.set_snapshot(snap)
        self._update_actions()
        self.catalogLoaded.emit(snap)
        self.status.show_catalog(snap)
        view, entry = self._restore_filter if self.filter is None else (
            self.sidebar.current_view, self.sidebar.current_entry_id)
        self.sidebar.set_snapshot(snap)
        self.sidebar.select(view, entry)  # emits filterChanged -> apply_filter
        if keep:
            self._select_key(keep)
        # a filter edited while this catalog was loading
        self.custom_filters.resolve_missing(lambda: self.sidebar.set_view(self.sidebar.current_view))

    def _on_error(self, e: BaseException):
        self.acts.reload.setEnabled(True)
        self.status.show_error(e)
        if self.snapshot is None:
            self.table.set_empty_text(empty_list.failed())
        QMessageBox.critical(self, "Kram", _("Could not load the package catalog:\n\n{error}").format(error=e))

    def _on_filter(self, entry: FilterEntry):
        self.filter = entry
        if entry.query is not None:  # a search-history entry: re-run that search
            self.search.set_query(*entry.query)
            self.apply_filter()
            self.search.stop_history()  # already in the history; don't reorder the list under the cursor
            return
        self.apply_filter()

    def _candidates(self) -> list[int]:
        """Rows the sidebar filter lets in. Worked out again only for another filter entry or catalog: a keystroke
        used to run the predicate over every row (36 ms of a 45 ms keystroke here). Entries are rebuilt whenever
        what they count changes, except "Marked", which follows the marks as they are: never cached."""
        entry, snap = self.filter, self.snapshot
        cached = self._candidates_cache
        if cached is not None and cached[0] is entry and cached[1] is snap and entry.id != "status:marked":
            return cached[2]
        pred = entry.predicate
        found = [i for i, r in enumerate(snap.rows) if pred(r)]
        self._candidates_cache = (entry, snap, found)
        return found

    def apply_filter(self):
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
            # a copy: the model keeps the list it is given, and this one is cached
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
                self.status.set_text(_("Searching “{text}” ({mode}); the first search also indexes what packages "
                                      "provide…").format(text=text, mode=MODE_LABELS[mode]))
            else:
                self.status.set_text(_("Searching “{text}” ({mode})…").format(text=text, mode=MODE_LABELS[mode]))
            # not the empty list's last explanation, which was about another search
            self.table.set_empty_text(html.escape(self.status.text()))

            def done(keys):
                if keys is None or gen != self._search_gen:
                    return
                everywhere = [i for k in keys if (i := self.key_index.get(k)) is not None]
                found = [i for i in everywhere if i in allowed]
                self._show(self.index.rank_keys(found), ranked=True, ms=(time.perf_counter() - t0) * 1000,
                           found_in_all=len(everywhere))
                self.search.start_history()
            # the dnf thread takes jobs one after the other: a search typed over by then is skipped, not run for nothing
            self.dnf.submit(lambda: lookup(text) if gen == self._search_gen else None, done, self._on_error)

    def _show(self, visible: list[int], ranked: bool, ms: float, found_in_all: int | None = None):
        # switch the header between "ranked" (no indicator) and the user's column sort without
        # triggering a sort of the old rows; set_visible sorts the new ones
        header = self.table.header()
        if ranked or self.model.sort_column is None:
            header.blockSignals(True)
            header.setSortIndicator(*((-1, Qt.SortOrder.AscendingOrder) if ranked else self._user_sort))
            header.blockSignals(False)
            self.model.sort(-1) if ranked else self.model.set_sort_column(self._user_sort)
        keep = self._current_key()
        self.model.set_visible(visible, ranked=ranked)
        self._last_count = len(visible)
        self._update_status(len(visible), ms)
        if not visible:
            self.details_loader.clear()
            self.table.set_empty_text(empty_list.explain(self._why_empty(found_in_all)))
        elif ranked:  # best match first: select it rather than keeping an old selection
            self.table.setCurrentIndex(self.model.index(0, COL_NAME))
            self.table.scrollToTop()
        elif not (keep and self._select_key(keep, scroll=True)):
            self.table.setCurrentIndex(self.model.index(0, COL_NAME))

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
                                    missing_repos=len(self.snapshot.unavailable_repos))

    def _on_empty_link(self, link: str):
        if link == empty_list.ALL:
            self.sidebar.select("status", "status:all")  # the search stays and runs in "All"
        elif link == empty_list.DESCRIPTIONS:
            self.search.set_mode(Mode.DESCRIPTION)  # searches again
        elif link == empty_list.RELOAD:
            self.acts.reload.trigger()
        elif link == empty_list.REPOS:
            self.open_repos()
        elif link == empty_list.RETRY:
            self.reload()

    def _on_sort_indicator(self, column: int, order):
        if column >= 0:
            self._user_sort = (column, order)

    def _on_search_enter(self):
        self.apply_filter()
        if not self.search.mode().local:
            return  # async: remembered when results arrive (timer started in done())
        self._remember_search()

    def _remember_search(self):
        self.search.stop_history()
        if text := self.search.text():
            self.sidebar.add_search(text, int(self.search.mode()), self._last_count)

    def _update_status(self, shown: int | None = None, ms: float | None = None):
        s = self.snapshot
        if s is None:
            return
        self.status.show_counts(s, self.model.rowCount() if shown is None else shown, *self.model.marks.counts(), ms)

    # ---------------------------------------------------------------- selection and details

    def _current_key(self) -> tuple[str, str] | None:
        idx = self.table.currentIndex()
        return self.model.row_at(idx).key if idx.isValid() else None

    def _select_key(self, key, scroll=True) -> bool:
        idx = self.model.index_of_key(key)
        if not idx.isValid():
            return False
        self.table.setCurrentIndex(idx)
        if scroll:
            self.table.scrollTo(idx, QAbstractItemView.ScrollHint.PositionAtCenter)
        return True

    def _on_current(self, current, _previous):
        if current.isValid():
            self.details_loader.follow(self.model.row_at(current))

    def _on_link(self, kind: str, value: str):
        if kind == "pkg":
            name, _, arch = value.rpartition(".")
            self.navigate((name, arch))
        else:
            self.dnf.submit(lambda: self.catalog.find_provider(value),
                            lambda key: self.navigate(key) if key else self.statusBar().showMessage(
                                _("Nothing provides “{what}”").format(what=value), 5000))

    def navigate(self, key: tuple[str, str], remember=True):
        if remember and (cur := self._current_key()) and cur != key:
            self.history.append(cur)
        if self._select_key(key):
            return
        # not visible under the current filter: fall back to "All" with no search
        self.search.clear(quietly=True)
        self.sidebar.select("status", "status:all")
        if not self._select_key(key):
            self.statusBar().showMessage(_("Package {name} not found in the catalog").format(name=f"{key[0]}.{key[1]}"), 5000)

    def go_back(self):
        if self.history:
            self.navigate(self.history.pop(), remember=False)

    # ---------------------------------------------------------------- misc actions

    def _selected_rows(self) -> list[PkgRow]:
        return [self.model.row_at(i) for i in self.table.selectionModel().selectedRows()]

    def copy_names(self):
        QGuiApplication.clipboard().setText(" ".join(r.name for r in self._selected_rows()))

    def copy_nevras(self):
        QGuiApplication.clipboard().setText(" ".join(
            f"{r.name}-{r.installed_evr or r.candidate_evr}.{r.arch}" for r in self._selected_rows()))

    def _context_menu(self, pos):
        if not self.table.indexAt(pos).isValid():
            return
        m = QMenu(self)
        self.acts.fill_package_menu(m)
        m.addSeparator()
        m.addActions([self.acts.copy_name, self.acts.copy_nevra])
        m.exec(self.table.viewport().mapToGlobal(pos))

    def new_filter_from_view(self) -> None:
        self.custom_filters.new_from_view(self.filter, self.search.text(), self.search.mode())

    def _sidebar_menu(self, pos, entry: FilterEntry | None) -> None:
        m = QMenu(self)
        if entry is not None and entry.group and (group := self.marker.group(entry.group)) is not None:
            self.marker.fill_group_menu(m, group, busy=self.helper.busy)
            m.addSeparator()
        if entry is not None and entry.id == "status:unneeded":
            m.addAction(self.acts.mark_unneeded)
            m.addSeparator()
        self.custom_filters.fill_menu(m, entry)
        if self.sidebar.current_view == "search":
            if entry is not None and entry.query is not None:
                text, mode = entry.query
                m.addAction(QIcon.fromTheme("edit-delete"), _("Remove from History"),
                            lambda: self.sidebar.remove_search(text, mode))
            clear = m.addAction(QIcon.fromTheme("edit-clear-history"), _("Clear Search History"),
                                self.sidebar.clear_history)
            clear.setEnabled(bool(self.sidebar.history))
            m.addSeparator()
        m.addAction(self.acts.new_filter)
        m.addAction(self.acts.filters)
        m.exec(pos)

    def _group_marks_changed(self) -> None:
        self._update_actions()
        if self.sidebar.current_view == "groups":
            self.sidebar.refresh_counts()

    def about(self):
        box = QMessageBox(QMessageBox.Icon.NoIcon, _("About Kram"),
                          f"<h3>Kram {__version__}</h3><p>{_('A Synaptic-style package manager for Fedora.')}</p>"
                          f"<p><a href='{HOMEPAGE}'>{HOMEPAGE}</a></p>"
                          f"<p>Copyright © 2026 Modo Ltunzher<br>{_('Released under the MIT License.')}</p>",
                          QMessageBox.StandardButton.Close, self)
        box.setIconPixmap(self.windowIcon().pixmap(64, 64))
        whats_new = box.addButton(_("What's New"), QMessageBox.ButtonRole.ActionRole)
        box.exec()
        if box.clickedButton() is whats_new:
            WhatsNewDialog(releases.load(), self).exec()

    # ---------------------------------------------------------------- marking

    def _update_actions(self, *_args):
        rows = self._selected_rows()
        allowed = set()
        for r in rows:
            allowed.update(allowed_actions(r))
        for action, a in self.acts.mark.items():
            a.setEnabled(action in allowed)
        self.acts.downgrade_menu.setEnabled(len(rows) == 1 and rows[0].installed)
        self.acts.unmark.setEnabled(any(r.key in self.model.marks for r in rows))
        n = len(self.model.marks)
        self.acts.apply.setEnabled(n > 0 and not self.helper.busy)
        self.acts.unmark_all.setEnabled(n > 0)
        self.acts.save_marks.setEnabled(n > 0)
        self.acts.read_marks.setEnabled(self.snapshot is not None)
        self.acts.export_csv.setEnabled(self.snapshot is not None)
        for needs_catalog in (self.acts.repos, self.acts.copr, self.acts.cache, self.acts.filters, self.acts.new_filter,
                              self.releases.act_upgrade):
            needs_catalog.setEnabled(self.snapshot is not None)
        self.acts.open_file.setEnabled(self._can_open_file())
        self.acts.set_upgrades_available(bool(self.snapshot and self.snapshot.n_upgradable))
        for kind, a in self.acts.mark_upgrades_of_kind.items():
            a.setEnabled(bool(self.marker.upgrades_of(kind)))
        self.acts.mark_unneeded.setEnabled(bool(self.marker.unneeded))

    def _marks_changed(self, keys):
        self.model.marks_changed(keys)
        self._update_actions()
        self._update_status()
        if self.sidebar.current_view == "status":
            self.sidebar.refresh_counts()

    def mark_selected(self, action: Action, evr: str = ""):
        self.marker.mark(self._selected_rows(), action, evr)

    def unmark_selected(self):
        self.marker.unmark(self._selected_rows())

    def save_marks(self):
        if path := save_markings(self, self.model.marks):
            n = len(self.model.marks)
            self.statusBar().showMessage(ngettext("{n} marking saved to {path}", "{n} markings saved to {path}", n)
                                         .format(n=n, path=path), 5000)

    def export_csv(self):
        title = _("Export List as CSV")
        folder = QSettings().value("export/dir", str(Path.home()))
        path, _filter = QFileDialog.getSaveFileName(self, title, str(Path(folder) / "kram-packages.csv"),
                                                    _("CSV files (*.csv);;All files (*)"))
        if not path:
            return
        rows = [self.model.rows[i] for i in self.model.visible]  # in the order shown
        try:
            with open(path, "w", encoding="utf-8", newline="") as out:
                n = write_csv(out, rows, self.model.marks)
        except OSError as e:
            QMessageBox.critical(self, title, _("Could not save {path}:\n\n{error}").format(
                path=path, error=e.strerror or e))
            return
        QSettings().setValue("export/dir", str(Path(path).parent))
        self.statusBar().showMessage(ngettext("{n} package exported to {path}", "{n} packages exported to {path}", n)
                                     .format(n=n, path=path), 5000)

    def read_marks(self):
        if path := ask_markings_file(self):
            self.marker.read_file(path)

    def _fill_downgrade_menu(self):
        self.acts.downgrade_menu.clear()
        rows = self._selected_rows()
        d = self.details_loader.details_of(rows[0].key) if len(rows) == 1 else None
        if d is None:
            self.acts.downgrade_menu.addAction(_("(loading…)")).setEnabled(False)
            return
        row = rows[0]
        installed = {v.evr for v in d.versions if v.installed}
        older = [v for v in d.versions if not v.installed and v.evr not in installed
                 and evr_cmp(v.evr, row.installed_evr) < 0]
        if not older:
            self.acts.downgrade_menu.addAction(_("No older versions in the repositories")).setEnabled(False)
        for v in older:
            self.acts.downgrade_menu.addAction(f"{v.evr}  ({v.repo_id})",
                                          lambda evr=v.evr: self.mark_selected(Action.DOWNGRADE, evr))

    def _on_table_click(self, index):
        # Synaptic: clicking the status box opens the action menu, or marks the likely action if the user chose that
        if index.column() == COL_STATUS:
            if self.acts.status_click.isChecked() and self.marker.toggle_likely(self.model.row_at(index)):
                return
            m = QMenu(self)
            self.acts.fill_package_menu(m)
            m.exec(self.table.viewport().mapToGlobal(self.table.visualRect(index).bottomLeft()))

    def _on_double_click(self, index):
        if index.column() != COL_STATUS:
            self.marker.toggle_likely(self.model.row_at(index))

    # ---------------------------------------------------------------- applying

    def apply(self):
        if not len(self.model.marks) or self.helper.busy:
            return
        rows = {r.key: r for r in self.snapshot.rows}
        request = {"op": "transaction", **self.model.marks.request(rows)}
        self.status.set_text(_("Resolving dependencies…"))
        self.dnf.submit(lambda: self.catalog.resolve(request), lambda p: self._on_preview(p, request),
                        lambda e: QMessageBox.critical(self, "Kram", _("Could not resolve the changes:\n\n{error}").format(error=e)))

    def _on_preview(self, preview: TransactionPreview, request: dict):
        self._update_status()
        if not preview.ok:
            box = QMessageBox(QMessageBox.Icon.Warning, _("Cannot apply changes"),
                              _("The marked changes cannot be carried out. Unmark or change them."), parent=self)
            box.setInformativeText(preview.problems[0][:500])
            box.setDetailedText("\n".join(preview.problems))
            box.exec()
            return
        def resolve(req, done, failed):
            self.dnf.submit(lambda: self.catalog.resolve(req, sizes=False), done, failed)

        dlg = ApplyDialog(preview, request, self.snapshot.basearch, self, resolve=resolve)
        if dlg.exec() != ApplyDialog.Accepted:
            return
        request = dlg.request  # with the recommendations the user unchecked
        download_only = dlg.download_only.isChecked()
        if download_only:
            request = {**request, "download_only": True}
        if self._run_helper(request, _("Applying changes")) and not download_only:
            self.marker.unmark_all()
            self.reload()

    def refresh_metadata(self):
        if self.helper.busy:
            return
        self._run_helper({"op": "refresh"}, _("Refreshing metadata"))
        self.releases.check()
        self.reload()

    def run_helper_and_reload(self, request: dict, title: str) -> bool:
        ok = self._run_helper(request, title)
        self.reload()  # even after a failure: part of the change may have happened
        return ok

    def open_repos(self):
        if not self.snapshot or self.helper.busy:
            return
        paths = [r.file_path for r in self.snapshot.repos]
        self.dnf.submit(lambda: (self.catalog.repo_package_counts(), file_owners(paths)), self._show_repos)

    def _show_repos(self, result):
        counts, owners = result
        snap = self.snapshot
        dlg = ReposDialog(snap.repos, counts, self, owners=owners, listed=Counter(r.origin_repo for r in snap.rows),
                          installed=Counter(r.from_repo_id for r in snap.rows if r.installed))
        accepted = dlg.exec() == ReposDialog.Accepted
        if dlg.show_repo:
            self.show_repo_packages(dlg.show_repo)
        elif dlg.remove_repos:
            # back to the list once it is reloaded without them
            self.catalogLoaded.connect(lambda _snap: self.open_repos(), Qt.ConnectionType.SingleShotConnection)
            title = ngettext("Removing {n} repository", "Removing {n} repositories", len(dlg.remove_repos))
            self.run_helper_and_reload({"op": "repo_remove", "repos": dlg.remove_repos},
                                       title.format(n=len(dlg.remove_repos)))
        elif accepted and (changes := dlg.changes()):
            self.run_helper_and_reload({"op": "repo_set_enabled", "repos": changes}, _("Changing repositories"))

    def show_repo_packages(self, repo_id: str) -> None:
        """The repository's entry of the Origin filters, with the search cleared."""
        self.search.clear()
        self.sidebar.select("origin", f"repo:{repo_id}")

    def open_copr(self):
        if not self.snapshot or self.helper.busy:
            return
        dlg = CoprDialog(self.run_helper_and_reload, self)

        def refresh(snap):
            self.dnf.submit(self.catalog.repo_package_counts, lambda counts: dlg.set_catalog(snap, counts))

        def show_packages(repo_id):
            dlg.accept()
            self.show_repo_packages(repo_id)
        refresh(self.snapshot)
        self.catalogLoaded.connect(refresh)
        dlg.showPackages.connect(show_packages)
        dlg.exec()
        self.catalogLoaded.disconnect(refresh)

    def open_cache(self):
        if not self.snapshot or self.helper.busy:
            return
        CacheDialog(self.dnf, self._clean_cache, self, helper=self._helper_result).exec()

    def open_notifications(self):
        NotifierDialog(self).exec()

    def _clean_cache(self, target: str) -> None:
        request = {"op": "clean_cache", "target": target}
        if target == "dnf_metadata":
            self.run_helper_and_reload(request, _("Downloading metadata again"))
        else:
            self._run_helper(request, _("Cleaning the package cache"))

    def open_upgrade(self) -> None:
        target = self.releases.target()
        if target is None or self.snapshot is None:
            return
        if self._upgrade_dialog is None or self._upgrade_dialog.target != target:
            self._upgrade_dialog = UpgradeDialog(target, self.releases.running, self.releases.running_eol(),
                                                 self.snapshot, self.dnf, self)
        self._upgrade_dialog.exec()

    # ---------------------------------------------------------------- package files

    def _can_open_file(self) -> bool:
        """Not while another dialog or a transaction is running: a dropped file or a stray shortcut then does
        nothing, whatever Qt's modality lets through."""
        return self.snapshot is not None and not self.helper.busy and QApplication.activeModalWidget() is None

    @staticmethod
    def _dropped_rpm(mime) -> str | None:
        urls = mime.urls() if mime.hasUrls() else []
        if len(urls) == 1 and urls[0].isLocalFile() and urls[0].toLocalFile().endswith(".rpm"):
            return urls[0].toLocalFile()
        return None

    def dragEnterEvent(self, event):
        if self._dropped_rpm(event.mimeData()) and self._can_open_file():
            event.acceptProposedAction()

    def dropEvent(self, event):
        if (path := self._dropped_rpm(event.mimeData())) and self._can_open_file():
            event.acceptProposedAction()
            # after the drop returns: a modal dialog inside a drop handler blocks the drag source
            QTimer.singleShot(0, lambda: self.open_package_file(path))

    def open_package_file(self, path: str | None = None) -> None:
        if not self._can_open_file():
            return
        if not path:
            s = QSettings()
            downloads = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
            start = s.value("install/dir", downloads)
            path, _filter = QFileDialog.getOpenFileName(self, _("Open Package File"), start,
                                                        _("RPM packages (*.rpm)"))
            if not path:
                return
            s.setValue("install/dir", str(Path(path).parent))
            if not self._can_open_file():
                return
        dlg = InstallDialog(path, self.catalog, self.dnf, self.helper, self.snapshot.basearch,
                            marks=len(self.model.marks), parent=self)
        dlg.exec()
        if dlg.changed_system:
            self.reload()
        self._update_actions()

    def _run_helper(self, request: dict, title: str) -> bool:
        return self._helper_result(request, title) is not None

    def _helper_result(self, request: dict, title: str) -> dict | None:
        """Run a helper request with a progress dialog: its final event if it succeeded, else None."""
        self.acts.apply.setEnabled(False)
        self.acts.reload.setEnabled(False)
        # a child of the dialog that started it (COPR, Package Cache): as a sibling, that one could be raised over it
        dlg = ProgressDialog(self.helper, request, title, QApplication.activeModalWidget() or self)
        dlg.exec()
        self.acts.reload.setEnabled(True)
        self._update_actions()
        notifier_control.recheck()  # even after a failure: the metadata may have been refreshed
        return dlg.result if dlg.ok else None
