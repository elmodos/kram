"""Main window: Synaptic layout — browse, mark, preview, apply."""
import json
import time
from pathlib import Path

from PySide6.QtCore import QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QGuiApplication, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSizePolicy,
    QSplitter,
    QToolBar,
    QTreeView,
    QWidget,
)

from .. import HOMEPAGE, __version__
from ..core.catalog import Catalog
from ..core.custom_filters import CustomFilter, Field, conditions_for_view, load_filters
from ..core.evr import evr_cmp
from ..core.filters import FilterEntry
from ..core.marks import Action, allowed_actions, dump_marks, parse_marks
from ..core.model import CatalogSnapshot, PkgDetails, PkgRow, Status, TransactionPreview
from ..core.search import MODE_LABELS, Mode, SearchIndex
from ..i18n import _, ngettext
from ..ipc.client import HelperClient
from .apply_dialog import ApplyDialog
from .copr_dialog import CoprDialog
from .details import DetailsTabs
from .dnf_thread import DnfThread
from .filters_dialog import FiltersDialog
from .package_model import COL_NAME, COL_STATUS, HEADERS, HIDEABLE, PackageTableModel
from .progress_dialog import ProgressDialog
from .repos_dialog import ReposDialog
from .sidebar import Sidebar

# bumped when columns change: an old saved state would put widths and hidden flags on the wrong columns
HEADER_STATE_KEY = "table/header-v2"
COLUMN_WIDTHS = [26, 24, 230, 175, 110, 175, 150, 80]
HISTORY_IDLE_MS = 1500  # a search left alone this long goes into the history
NOT_YET = _("Coming in a later version")
# toolbar styles (Settings → Toolbar, or right-click the toolbar): id, label, button style, icon size
# (an invalid size means the style's default, which on Plasma follows System Settings)
TOOLBAR_STYLES = [
    ("system", _("Follow System Settings"), Qt.ToolButtonFollowStyle, QSize()),
    ("under", _("Text Under Icons"), Qt.ToolButtonTextUnderIcon, QSize(24, 24)),
    ("beside", _("Compact: Text Beside Icons"), Qt.ToolButtonTextBesideIcon, QSize(16, 16)),
    ("icons", _("Icons Only"), Qt.ToolButtonIconOnly, QSize(22, 22)),
]


def _age(seconds: int | None) -> str:
    if seconds is None:
        return _("Metadata: unknown age")
    if seconds < 3600:
        return _("Metadata: {minutes} min ago").format(minutes=seconds // 60)
    if seconds < 2 * 86400:
        return _("Metadata: {hours} h {minutes} min ago").format(hours=seconds // 3600, minutes=seconds % 3600 // 60)
    return _("Metadata: {days} d ago").format(days=seconds // 86400)


class MainWindow(QMainWindow):
    catalogLoaded = Signal(object)  # CatalogSnapshot, after every (re)load

    def __init__(self):
        super().__init__()
        self.setWindowTitle(_("Package Manager"))  # Qt appends " — Kram" (the application display name)
        self.resize(1320, 860)

        self.dnf = DnfThread(self)
        self.catalog = Catalog()
        self.snapshot: CatalogSnapshot | None = None
        self.filter: FilterEntry | None = None
        self.history: list[tuple[str, str]] = []  # packages visited via dependency links, for Alt+Left
        self._details_for: tuple[str, str] | None = None
        self.index: SearchIndex | None = None
        self.key_index: dict[tuple[str, str], int] = {}
        self._search_gen = 0                 # drops stale async (provides/file) results
        self._user_sort = (COL_NAME, Qt.AscendingOrder)
        self._last_count = 0
        self._details: PkgDetails | None = None  # details of the current row, once loaded
        self.helper = HelperClient(self)

        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_central()

        self.status = QLabel()
        self.statusBar().addWidget(self.status, 1)
        # enabled repositories that could not be loaded; clicking opens Settings → Repositories
        self.repo_warning = QLabel()
        self.repo_warning.setVisible(False)
        self.repo_warning.linkActivated.connect(lambda _link: self.open_repos())
        self.statusBar().addPermanentWidget(self.repo_warning)
        self.age = QLabel()
        self.statusBar().addPermanentWidget(self.age)

        self._restore_settings()
        self.reload()

    # ---------------------------------------------------------------- construction

    def _action(self, text, icon=None, shortcut=None, slot=None, enabled=True, tip=None) -> QAction:
        a = QAction(QIcon.fromTheme(icon) if icon else QIcon(), text, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        if slot:
            a.triggered.connect(slot)
        a.setEnabled(enabled)
        if tip or not enabled:
            a.setToolTip(tip or NOT_YET)
            a.setStatusTip(tip or NOT_YET)
        self.addAction(a)  # shortcuts work even when the action is only in a menu
        return a

    def _build_actions(self):
        self.act_reload = self._action(_("Reload"), "view-refresh", "Ctrl+R", self.refresh_metadata,
                                       tip=_("Refresh repository metadata and reload the catalog (needs a password)"))
        self.act_reload_cache = self._action(_("Reload from cache"), "view-refresh", "Ctrl+Shift+R", self.reload,
                                             tip=_("Reload the catalog from the local cache, without network or "
                                                   "password"))
        self.act_mark_upgrades = self._action(_("Mark All Upgrades"), None, "Ctrl+U", self.mark_all_upgrades,
                                              tip=_("Mark every package that has a newer version for upgrade"))
        # Breeze's monochrome update glyph matches the other toolbar icons; system-software-update is a colour
        # app icon there, kept as the fallback for themes without update-none
        self.act_mark_upgrades.setIcon(QIcon.fromTheme("update-none", QIcon.fromTheme("system-software-update")))
        self.act_apply = self._action(_("Apply"), "dialog-ok-apply", "Ctrl+P", self.apply,
                                      tip=_("Review and apply the marked changes"))
        self.act_apply.setEnabled(False)
        self.act_unmark_all = self._action(_("Unmark All"), "edit-clear", "Ctrl+Shift+Z", self.unmark_all,
                                           tip=_("Discard all marked changes"))
        self.act_unmark_all.setEnabled(False)
        self.act_properties = self._action(_("Properties"), "document-properties",
                                           slot=lambda: self.details.setCurrentIndex(1))
        self.act_repos = self._action(_("Repositories"), "configure", slot=self.open_repos,
                                      tip=_("Enable or disable software repositories"))
        self.act_filters = self._action(_("Custom Filters…"), "view-filter", slot=lambda: self.edit_filters(),
                                        tip=_("Create and edit your own filters for the sidebar"))
        self.act_new_filter = self._action(_("New Filter from Current View…"), "list-add",
                                           slot=self.new_filter_from_view,
                                           tip=_("A custom filter with the current sidebar selection and search"))
        self.act_copr = self._action(_("COPR"), "folder-cloud", slot=self.open_copr,
                                     tip=_("Manage COPR projects: community repositories"))
        self.act_find = self._action(_("Find"), "edit-find", QKeySequence.Find,
                                     lambda: (self.search.setFocus(), self.search.selectAll()))
        self.act_back = self._action(_("Back"), "go-previous", "Alt+Left", self.go_back,
                                     tip=_("Go back to the previous package (after following a dependency)"))
        self.act_save_marks = self._action(_("Save Markings As…"), "document-save-as", "Ctrl+S", self.save_marks,
                                           tip=_("Save the marked changes to a text file"))
        self.act_save_marks.setEnabled(False)
        self.act_read_marks = self._action(_("Read Markings…"), "document-open", "Ctrl+O", self.read_marks,
                                           tip=_("Mark the changes listed in a saved markings file"))
        self.act_read_marks.setEnabled(False)
        self.act_quit = self._action(_("Quit"), "application-exit", QKeySequence.Quit, self.close)
        self.act_copy_name = self._action(_("Copy Name"), "edit-copy", "Ctrl+C", self.copy_names)
        self.act_copy_nevra = self._action(_("Copy name-version-release.arch"), "edit-copy", "Ctrl+Shift+C",
                                           self.copy_nevras)
        # scoped to the table, so Ctrl+C still copies text in the search field and the detail tabs
        for a in (self.act_copy_name, self.act_copy_nevra):
            self.removeAction(a)
            a.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        self.act_about = self._action(_("About Kram"), "help-about", slot=self.about)
        # package actions are scoped to the table: Del/Ins/Ctrl+Z keep their meaning in the search field
        self.mark_actions: dict[Action, QAction] = {}
        for action, text, icon, shortcut in [
            (Action.INSTALL, _("Mark for Installation"), "list-add", "Ins"),
            (Action.UPGRADE, _("Mark for Upgrade"), "go-up", None),
            (Action.REINSTALL, _("Mark for Reinstallation"), "view-refresh", None),
            (Action.REMOVE, _("Mark for Removal"), "list-remove", "Del"),
            (Action.MARK_USER, _("Mark as Installed by User"), "user-identity", None),
            (Action.MARK_DEP, _("Mark as Dependency"), "link", None),
        ]:
            a = self._action(text, icon, shortcut, lambda _c=False, act=action: self.mark_selected(act), tip=text)
            self.removeAction(a)
            a.setShortcutContext(Qt.WidgetWithChildrenShortcut)
            self.mark_actions[action] = a
        self.downgrade_menu = QMenu(_("Downgrade to Version"), self)
        self.downgrade_menu.setIcon(QIcon.fromTheme("go-down"))
        self.downgrade_menu.aboutToShow.connect(self._fill_downgrade_menu)
        self.act_unmark = self._action(_("Unmark"), "edit-undo", "Ctrl+Z", self.unmark_selected,
                                       tip=_("Unmark the selected packages"))
        self.removeAction(self.act_unmark)
        self.act_unmark.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        self.act_mark_upgrades.setEnabled(False)
        self.toolbar_styles = QActionGroup(self)
        for style_id, label, _button, _size in TOOLBAR_STYLES:
            a = self.toolbar_styles.addAction(label)
            a.setCheckable(True)
            a.setData(style_id)
        self.toolbar_styles.triggered.connect(lambda a: self.set_toolbar_style(a.data()))

    def set_toolbar_style(self, style_id: str) -> None:
        _id, _label, button, size = next((t for t in TOOLBAR_STYLES if t[0] == style_id), TOOLBAR_STYLES[0])
        self.toolbar.setToolButtonStyle(button)
        self.toolbar.setIconSize(size)
        for a in self.toolbar_styles.actions():
            a.setChecked(a.data() == _id)

    def toolbar_style(self) -> str:
        return next((a.data() for a in self.toolbar_styles.actions() if a.isChecked()), TOOLBAR_STYLES[0][0])

    def createPopupMenu(self) -> QMenu:
        # instead of Qt's default "show/hide toolbars" menu: the toolbar can't be hidden, only restyled
        menu = QMenu(self)
        menu.addActions(self.toolbar_styles.actions())
        return menu

    def _package_menu(self, menu: QMenu) -> None:
        menu.addActions(list(self.mark_actions.values()))
        menu.addMenu(self.downgrade_menu)
        menu.addSeparator()
        menu.addAction(self.act_unmark)

    def _build_menus(self):
        mb = self.menuBar()
        m = mb.addMenu(_("&File"))
        m.addActions([self.act_reload, self.act_reload_cache])
        m.addSeparator()
        m.addActions([self.act_read_marks, self.act_save_marks])
        m.addSeparator()
        m.addAction(self.act_quit)
        m = mb.addMenu(_("&Edit"))
        m.addActions([self.act_mark_upgrades, self.act_unmark_all, self.act_apply])
        m.addSeparator()
        m.addActions([self.act_copy_name, self.act_copy_nevra])
        m.addSeparator()
        m.addAction(self.act_find)
        m = mb.addMenu(_("&Package"))
        self._package_menu(m)
        m.addSeparator()
        m.addActions([self.act_properties, self.act_back])
        m = mb.addMenu(_("&Settings"))
        m.addActions([self.act_repos, self.act_copr])
        m.addSeparator()
        m.addActions([self.act_filters, self.act_new_filter])
        m.addSeparator()
        m.addMenu(_("Toolbar")).addActions(self.toolbar_styles.actions())
        m = mb.addMenu(_("&Help"))
        m.addAction(self.act_about)

    def _build_toolbar(self):
        tb = self.toolbar = QToolBar(_("Main toolbar"))
        tb.setObjectName("main-toolbar")
        tb.setMovable(False)
        tb.toggleViewAction().setEnabled(False)  # no way to hide it, so no way to lose it
        self.set_toolbar_style(TOOLBAR_STYLES[0][0])
        tb.addActions([self.act_reload, self.act_mark_upgrades, self.act_apply])
        tb.addSeparator()
        tb.addActions([self.act_repos, self.act_copr])
        spacer = QWidget()
        spacer.setSizePolicy(spacer.sizePolicy().Policy.Expanding, spacer.sizePolicy().Policy.Preferred)
        tb.addWidget(spacer)
        self.search_mode = QComboBox()
        self.search_mode.addItems([MODE_LABELS[m] for m in Mode])
        self.search_mode.setToolTip(
            _("Name / Name + summary / Description: instant ranked search.\n"
              "Provides: packages providing a capability (libvulkan.so.1, python3dist(requests), webbrowser).\n"
              "File: owner of a file (/usr/bin/7z or just 7z; only the main files for packages not installed).\n\n"
              "Several words: all must match. ^start, end$, * and ? are wildcards."))
        self.search_mode.currentIndexChanged.connect(self.apply_filter)
        tb.addWidget(self.search_mode)
        self.search = QLineEdit()
        self.search.setPlaceholderText(_("Search (Ctrl+F)"))
        self.search.setClearButtonEnabled(True)
        # shrinks before anything overflows into the toolbar's ">" menu (where Ctrl+F could not reach it)
        self.search.setMinimumWidth(160)
        self.search.setMaximumWidth(300)
        self.search.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._search_icon = self.search.addAction(QIcon.fromTheme("edit-find"), QLineEdit.LeadingPosition)
        self.search.textChanged.connect(self._update_search_icon)
        tb.addWidget(self.search)
        self.addToolBar(tb)

        self._debounce = QTimer(self, singleShot=True, interval=150)
        self._debounce.timeout.connect(self.apply_filter)
        self.search.textChanged.connect(self._debounce.start)
        self.search.returnPressed.connect(self._on_search_enter)
        self._history_timer = QTimer(self, singleShot=True, interval=HISTORY_IDLE_MS)
        self._history_timer.timeout.connect(self._remember_search)

    def _update_search_icon(self, text: str) -> None:
        """A funnel while the search text filters the list, so it is not missed after switching views."""
        active = bool(text.strip())
        # the theme's own icon (monochrome in Breeze); themes without view-filter keep the magnifier
        self._search_icon.setIcon(QIcon.fromTheme("view-filter" if active and QIcon.hasThemeIcon("view-filter")
                                                  else "edit-find"))
        self._search_icon.setToolTip(_("The list is filtered by the search text") if active else "")

    def _build_central(self):
        self.sidebar = Sidebar()
        self.sidebar.filterChanged.connect(self._on_filter)
        self.sidebar.contextMenuRequested.connect(self._sidebar_menu)
        self.sidebar.entryActivated.connect(
            lambda e: e.id.startswith("custom:") and self.edit_filters(select=e.id.removeprefix("custom:")))

        self.model = PackageTableModel(self)
        self.sidebar.marked = self.model.marks
        self.table = QTreeView()
        self.table.setModel(self.model)
        self.table.setRootIsDecorated(False)
        self.table.setUniformRowHeights(True)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(COL_NAME, Qt.AscendingOrder)
        self.table.header().sortIndicatorChanged.connect(self._on_sort_indicator)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        for col, width in enumerate(COLUMN_WIDTHS):
            self.table.setColumnWidth(col, width)
        self.table.header().setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.header().customContextMenuRequested.connect(self._header_menu)
        self.table.selectionModel().currentRowChanged.connect(self._on_current)
        self.table.selectionModel().selectionChanged.connect(self._update_actions)
        self.table.addActions([self.act_copy_name, self.act_copy_nevra, *self.mark_actions.values(), self.act_unmark])
        self.table.clicked.connect(self._on_table_click)
        self.table.doubleClicked.connect(self._on_double_click)

        self.details = DetailsTabs()
        self.details.linkActivated.connect(self._on_link)

        self.vsplit = QSplitter(Qt.Vertical)
        self.vsplit.addWidget(self.table)
        self.vsplit.addWidget(self.details)
        self.vsplit.setSizes([540, 260])
        self.vsplit.setCollapsible(1, False)  # the details can shrink to their tab bar, not vanish
        self.hsplit = QSplitter(Qt.Horizontal)
        self.hsplit.addWidget(self.sidebar)
        self.hsplit.addWidget(self.vsplit)
        self.hsplit.setStretchFactor(1, 1)
        self.hsplit.setSizes([270, 1050])
        self.setCentralWidget(self.hsplit)

    # ---------------------------------------------------------------- settings

    def _restore_settings(self):
        s = QSettings()
        self.set_toolbar_style(s.value("toolbar/style", TOOLBAR_STYLES[0][0]))
        if geom := s.value("window/geometry"):
            self.restoreGeometry(geom)
        for key, splitter in (("window/hsplit", self.hsplit), ("window/vsplit", self.vsplit)):
            if state := s.value(key):
                splitter.restoreState(state)
        if state := s.value(HEADER_STATE_KEY):
            self.table.header().restoreState(state)
        self.details.setCurrentIndex(int(s.value("details/tab", 0)))
        self.search_mode.setCurrentIndex(int(s.value("search/mode", Mode.NAME)))
        try:
            self.sidebar.history = [tuple(h) for h in json.loads(s.value("search/history", "[]"))]
        except (TypeError, ValueError):
            self.sidebar.history = []
        try:
            self.sidebar.custom = load_filters(json.loads(s.value("filters/custom", "[]")))
        except (TypeError, ValueError):
            self.sidebar.custom = []
        self._restore_filter = (s.value("sidebar/view", "status"), s.value("sidebar/entry", "status:all"))

    def _save_settings(self):
        s = QSettings()
        if self.model.sort_column is None:  # ranked search results: save the user's column sort instead
            self.table.header().setSortIndicator(*self._user_sort)
        s.setValue("search/history", json.dumps(self.sidebar.history, ensure_ascii=False))
        s.setValue("toolbar/style", self.toolbar_style())
        s.setValue("window/geometry", self.saveGeometry())
        s.setValue("window/hsplit", self.hsplit.saveState())
        s.setValue("window/vsplit", self.vsplit.saveState())
        s.setValue(HEADER_STATE_KEY, self.table.header().saveState())
        s.setValue("details/tab", self.details.currentIndex())
        s.setValue("search/mode", self.search_mode.currentIndex())
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
                != QMessageBox.Yes:
            event.ignore()
            return
        self.helper.stop()
        self._save_settings()
        self.dnf.shutdown()
        super().closeEvent(event)

    # ---------------------------------------------------------------- loading and filtering

    def reload(self):
        self.status.setText(_("Loading metadata…"))
        self.act_reload.setEnabled(False)
        self.dnf.submit(self.catalog.load, self._on_loaded, self._on_error)

    def _on_loaded(self, snap: CatalogSnapshot):
        keep = self._current_key()
        self.snapshot = snap
        self.act_reload.setEnabled(True)
        self.model.set_rows(snap.rows, snap.basearch)
        self.index = SearchIndex(snap.rows, snap.descriptions)
        self.key_index = {r.key: i for i, r in enumerate(snap.rows)}
        self._revalidate_marks()
        self.catalogLoaded.emit(snap)
        self.age.setText(_age(snap.metadata_age) + "  ")
        self._show_repo_warning(snap)
        view, entry = self._restore_filter if self.filter is None else (
            self.sidebar.current_view, self.sidebar.current_entry_id)
        self.sidebar.set_snapshot(snap)
        self.sidebar.select(view, entry)  # emits filterChanged -> apply_filter
        if keep:
            self._select_key(keep)

    def _show_repo_warning(self, snap: CatalogSnapshot) -> None:
        missing = snap.unavailable_repos
        self.repo_warning.setVisible(bool(missing))
        if not missing:
            return
        n = len(missing)
        text = ngettext("{n} repository has no metadata", "{n} repositories have no metadata", n).format(n=n)
        self.repo_warning.setText(f"⚠ <a href='repos'>{text}</a>  ")
        self.repo_warning.setToolTip(
            _("Not loaded, so their packages are missing from the list:\n{names}\n\n"
              "Use Reload to download them. If a repository keeps failing (for example it has no packages for "
              "this Fedora release yet), disable it in Settings → Repositories.").format(
                names="\n".join(f"• {r.name} ({r.id})" for r in missing)))

    def _on_error(self, e: BaseException):
        self.act_reload.setEnabled(True)
        self.status.setText(_("Error: {error}").format(error=e))
        QMessageBox.critical(self, "Kram", _("Could not load the package catalog:\n\n{error}").format(error=e))

    def _on_filter(self, entry: FilterEntry):
        self.filter = entry
        if entry.query is not None:  # a search-history entry: re-run that search
            text, mode = entry.query
            for w, setter in ((self.search, lambda: self.search.setText(text)),
                              (self.search_mode, lambda: self.search_mode.setCurrentIndex(mode))):
                w.blockSignals(True)
                setter()
                w.blockSignals(False)
            self.apply_filter()
            self._history_timer.stop()  # already in the history; don't reorder the list under the cursor
            return
        self.apply_filter()

    def apply_filter(self):
        """Sidebar filter, then search. Searches rank their results; an empty search uses the column sort."""
        if not self.snapshot or not self.filter:
            return
        self._debounce.stop()
        t0 = time.perf_counter()
        self._search_gen += 1
        pred = self.filter.predicate
        rows = self.snapshot.rows
        candidates = [i for i, r in enumerate(rows) if pred(r)]
        text = self.search.text().strip()
        mode = Mode(self.search_mode.currentIndex())
        if not text:
            self._history_timer.stop()
            self._show(candidates, ranked=False, ms=(time.perf_counter() - t0) * 1000)
        elif mode.local:
            self._show(self.index.search(text, mode, candidates), ranked=True, ms=(time.perf_counter() - t0) * 1000)
            self._history_timer.start()
        else:
            gen = self._search_gen
            allowed = set(candidates)
            lookup = self.catalog.search_provides if mode is Mode.PROVIDES else self.catalog.search_files
            self.status.setText(_("Searching “{text}” ({mode})…").format(text=text, mode=MODE_LABELS[mode]))

            def done(keys):
                if gen != self._search_gen:
                    return
                found = [i for k in keys if (i := self.key_index.get(k)) is not None and i in allowed]
                self._show(self.index.rank_keys(found), ranked=True, ms=(time.perf_counter() - t0) * 1000)
                self._history_timer.start()
            self.dnf.submit(lambda: lookup(text), done, self._on_error)

    def _show(self, visible: list[int], ranked: bool, ms: float):
        # switch the header between "ranked" (no indicator) and the user's column sort without
        # triggering a sort of the old rows; set_visible sorts the new ones
        header = self.table.header()
        if ranked or self.model.sort_column is None:
            header.blockSignals(True)
            header.setSortIndicator(*((-1, Qt.AscendingOrder) if ranked else self._user_sort))
            header.blockSignals(False)
            self.model.sort(-1) if ranked else self.model.set_sort_column(self._user_sort)
        keep = self._current_key()
        self.model.set_visible(visible, ranked=ranked)
        self._last_count = len(visible)
        self._update_status(len(visible), ms)
        if not visible:
            self.details.clear()
        elif ranked:  # best match first: select it rather than keeping an old selection
            self.table.setCurrentIndex(self.model.index(0, COL_NAME))
            self.table.scrollToTop()
        elif not (keep and self._select_key(keep, scroll=True)):
            self.table.setCurrentIndex(self.model.index(0, COL_NAME))

    def _on_sort_indicator(self, column: int, order):
        if column >= 0:
            self._user_sort = (column, order)

    def _on_search_enter(self):
        self.apply_filter()
        if not Mode(self.search_mode.currentIndex()).local:
            return  # async: remembered when results arrive (timer started in done())
        self._remember_search()

    def _remember_search(self):
        self._history_timer.stop()
        text = self.search.text().strip()
        if text:
            self.sidebar.add_search(text, self.search_mode.currentIndex(), self._last_count)

    def _update_status(self, shown: int | None = None, ms: float | None = None):
        s = self.snapshot
        if s is None:
            return
        if shown is None:
            shown = self.model.rowCount()
        inst, rm = self.model.marks.counts()
        upgrades = ngettext("{n} upgrade", "{n} upgrades", s.n_upgradable).format(n=s.n_upgradable)
        self.status.setText(
            _("{shown} listed, {installed} installed, {upgrades}.").format(
                shown=shown, installed=s.n_installed, upgrades=upgrades) + " "
            + _("{install} to install/upgrade, {remove} to remove.").format(install=inst, remove=rm))
        if ms is None:
            return
        self.status.setToolTip(_("Catalog: {load:.2f} s, filter and search: {ms:.0f} ms").format(load=s.load_seconds, ms=ms))

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
            self.table.scrollTo(idx, QAbstractItemView.PositionAtCenter)
        return True

    def _on_current(self, current, _previous):
        if not current.isValid():
            return
        row = self.model.row_at(current)
        self._details_for = row.key
        self._details = None
        self.dnf.submit(lambda: self.catalog.details(row.key), lambda d: self._show_details(row, d))

    def _show_details(self, row: PkgRow, d):
        if row.key == self._details_for:  # ignore stale results when the cursor moved on
            self._details = d
            self.details.show_package(row, d)

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
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
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
        self._package_menu(m)
        m.addSeparator()
        m.addActions([self.act_copy_name, self.act_copy_nevra])
        m.exec(self.table.viewport().mapToGlobal(pos))

    # ---------------------------------------------------------- custom filters

    def _save_custom_filters(self) -> None:
        QSettings().setValue("filters/custom", json.dumps([f.to_dict() for f in self.sidebar.custom],
                                                          ensure_ascii=False))

    def edit_filters(self, select: str | None = None, new: CustomFilter | None = None) -> None:
        d = FiltersDialog(self.sidebar.custom, self.snapshot, self, select=select, new=new)
        if not d.exec():
            return
        self.sidebar.custom = d.filters()
        self._save_custom_filters()
        name = d.current_name()
        if name is not None:
            self.sidebar.select("custom", f"custom:{name}")
        elif self.sidebar.current_view == "custom":
            self.sidebar.set_view("custom")

    def new_filter_from_view(self) -> None:
        entry_id = self.sidebar.current_entry_id or ""
        text = self.search.text().strip()
        mode = Mode(self.search_mode.currentIndex())
        search_field = {Mode.NAME: Field.NAME, Mode.NAME_SUMMARY: Field.NAME_SUMMARY,
                        Mode.DESCRIPTION: Field.DESCRIPTION}.get(mode)
        conditions = conditions_for_view(entry_id, text, search_field)
        if entry_id.startswith("custom:"):
            base = next((f for f in self.sidebar.custom if f"custom:{f.name}" == entry_id), None)
            if base is not None:
                conditions = list(base.conditions) + conditions
        # named after what it reproduces: "Upgradable", "COPR “term”", …; "All" adds nothing to the name
        from_view = bool(conditions_for_view(entry_id, "", None)) or entry_id.startswith("custom:")
        parts = [self.filter.label if self.filter and from_view else "", f"“{text}”" if text and search_field else ""]
        self.edit_filters(new=CustomFilter(" ".join(p for p in parts if p) or _("New filter"), conditions))

    def delete_filter(self, name: str) -> None:
        if QMessageBox.question(self, _("Custom Filters"), _("Delete the filter “{name}”?").format(name=name)) \
                != QMessageBox.Yes:
            return
        self.sidebar.custom = [f for f in self.sidebar.custom if f.name != name]
        self._save_custom_filters()
        self.sidebar.set_view(self.sidebar.current_view)

    def _header_menu(self, pos) -> None:
        header = self.table.header()
        m = QMenu(self)
        for col in HIDEABLE:
            act = m.addAction(HEADERS[col])
            act.setCheckable(True)
            act.setChecked(not header.isSectionHidden(col))
            act.toggled.connect(lambda on, c=col: header.setSectionHidden(c, not on))
        m.exec(header.viewport().mapToGlobal(pos))

    def _sidebar_menu(self, pos, entry: FilterEntry | None) -> None:
        m = QMenu(self)
        if entry is not None and entry.id.startswith("custom:"):
            name = entry.id.removeprefix("custom:")
            m.addAction(QIcon.fromTheme("document-edit"), _("Edit Filter…"), lambda: self.edit_filters(select=name))
            m.addAction(QIcon.fromTheme("edit-delete"), _("Delete Filter"), lambda: self.delete_filter(name))
            m.addSeparator()
        if self.sidebar.current_view == "search":
            if entry is not None and entry.query is not None:
                text, mode = entry.query
                m.addAction(QIcon.fromTheme("edit-delete"), _("Remove from History"),
                            lambda: self.sidebar.remove_search(text, mode))
            clear = m.addAction(QIcon.fromTheme("edit-clear-history"), _("Clear Search History"),
                                self.sidebar.clear_history)
            clear.setEnabled(bool(self.sidebar.history))
            m.addSeparator()
        m.addAction(self.act_new_filter)
        m.addAction(self.act_filters)
        m.exec(pos)

    def about(self):
        QMessageBox.about(self, _("About Kram"), f"<h3>Kram {__version__}</h3><p>{_('A Synaptic-style package manager for Fedora.')}</p>"
                                           f"<p><a href='{HOMEPAGE}'>{HOMEPAGE}</a></p>"
                                           f"<p>Copyright © 2026 Modo Ltunzher<br>{_('Released under the MIT License.')}</p>")

    # ---------------------------------------------------------------- marking

    def _update_actions(self, *_args):
        rows = self._selected_rows()
        allowed = set()
        for r in rows:
            allowed.update(allowed_actions(r))
        for action, a in self.mark_actions.items():
            a.setEnabled(action in allowed)
        self.downgrade_menu.setEnabled(len(rows) == 1 and rows[0].installed)
        self.act_unmark.setEnabled(any(r.key in self.model.marks for r in rows))
        n = len(self.model.marks)
        self.act_apply.setEnabled(n > 0 and not self.helper.busy)
        self.act_unmark_all.setEnabled(n > 0)
        self.act_save_marks.setEnabled(n > 0)
        self.act_read_marks.setEnabled(self.snapshot is not None)
        self.act_mark_upgrades.setEnabled(bool(self.snapshot and self.snapshot.n_upgradable))

    def _marks_changed(self, keys):
        self.model.marks_changed(keys)
        self._update_actions()
        self._update_status()
        if self.sidebar.current_view == "status":
            self.sidebar.refresh_counts()

    def mark_selected(self, action: Action, evr: str = ""):
        rows = self._selected_rows()
        before = {r.key: self.model.marks.get(r.key) for r in rows}
        changed = [r.key for r in rows if self.model.marks.set(r, action, evr)]
        if changed:
            self._marks_changed(changed)
            if action is Action.REMOVE:
                self._check_removal_dependents(changed, {k: before[k] for k in changed})

    def _check_removal_dependents(self, keys: list, before: dict) -> None:
        """Like Synaptic: packages that depend on the ones just marked for removal must go too; offer to mark them."""
        rows = {r.key: r for r in self.snapshot.rows}
        remove = self.model.marks.request(rows).get("remove", [])

        def done(dependents):
            marks = self.model.marks
            if any((m := marks.get(k)) is None or m.action is not Action.REMOVE for k in keys):
                return  # the marks changed meanwhile
            extra = [rows[k] for k in dependents if k not in marks and k in rows]
            if not extra:
                return
            box = QMessageBox(QMessageBox.Question, "Kram",
                              ngettext("{n} installed package depends on the packages marked for removal and has to be "
                                       "removed as well:",
                                       "{n} installed packages depend on the packages marked for removal and have to be "
                                       "removed as well:", len(extra)).format(n=len(extra)),
                              QMessageBox.Cancel, self)
            box.setInformativeText(", ".join(sorted(r.name for r in extra)))
            mark_btn = box.addButton(_("Mark"), QMessageBox.AcceptRole)
            box.setDefaultButton(mark_btn)
            box.exec()
            if box.clickedButton() is mark_btn:
                for r in extra:
                    marks.set(r, Action.REMOVE)
                self._marks_changed([r.key for r in extra])
            else:  # as in Synaptic, cancelling takes back the removal that needed them
                for k, m in before.items():
                    marks.restore(k, m)
                self._marks_changed(list(before))
        self.dnf.submit(lambda: self.catalog.removal_dependents(remove), done,
                        lambda e: self.status.setText(_("Error: {error}").format(error=e)))

    def unmark_selected(self):
        keys = [r.key for r in self._selected_rows() if r.key in self.model.marks]
        for k in keys:
            self.model.marks.unmark(k)
        self._marks_changed(keys)

    def unmark_all(self):
        self.model.marks.clear()
        self._marks_changed(None)

    def mark_all_upgrades(self):
        if not self.snapshot:
            return
        changed = [r.key for r in self.snapshot.rows
                   if r.status is Status.UPGRADABLE and self.model.marks.set(r, Action.UPGRADE)]
        self._marks_changed(None)
        self.statusBar().showMessage(ngettext("{n} package marked for upgrade", "{n} packages marked for upgrade", len(changed)).format(n=len(changed)), 5000)

    def _markings_dir(self) -> str:
        return QSettings().value("markings/dir", str(Path.home()))

    def save_marks(self):
        path, _filter = QFileDialog.getSaveFileName(self, _("Save Markings"),
                                                    str(Path(self._markings_dir()) / "kram-markings.txt"),
                                                    _("Text files (*.txt);;All files (*)"))
        if not path:
            return
        try:
            Path(path).write_text(dump_marks(self.model.marks), encoding="utf-8")
        except OSError as e:
            QMessageBox.critical(self, _("Save Markings"), _("Could not save {path}:\n\n{error}").format(
                path=path, error=e.strerror or e))
            return
        QSettings().setValue("markings/dir", str(Path(path).parent))
        n = len(self.model.marks)
        self.statusBar().showMessage(ngettext("{n} marking saved to {path}", "{n} markings saved to {path}", n)
                                     .format(n=n, path=path), 5000)

    def read_marks(self):
        path, _filter = QFileDialog.getOpenFileName(self, _("Read Markings"), self._markings_dir(),
                                                    _("Text files (*.txt);;All files (*)"))
        if path:
            self.load_marks_file(path)

    def load_marks_file(self, path: str) -> None:
        """Add the marks from a markings file to the current ones; report what could not be marked."""
        try:
            text = Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            QMessageBox.critical(self, _("Read Markings"), _("Could not read {path}:\n\n{error}").format(
                path=path, error=getattr(e, "strerror", None) or e))
            return
        QSettings().setValue("markings/dir", str(Path(path).parent))
        marks, bad_lines = parse_marks(text)
        rows = {r.key: r for r in self.snapshot.rows}
        skipped = [f"{name}.{arch}" for (name, arch), mark in marks
                   if not ((row := rows.get((name, arch))) and self.model.marks.set(row, mark.action, mark.evr))]
        self._marks_changed(None)
        n = len(marks) - len(skipped)
        self.statusBar().showMessage(ngettext("{n} package marked", "{n} packages marked", n).format(n=n), 5000)
        if skipped or bad_lines:
            problems = []
            if skipped:
                problems.append(ngettext(
                    "{n} marking no longer applies (package not found, already in that state, …):",
                    "{n} markings no longer apply (packages not found, already in that state, …):",
                    len(skipped)).format(n=len(skipped)) + "\n" + ", ".join(skipped))
            if bad_lines:
                problems.append(ngettext("{n} line is not a valid marking: {lines}",
                                         "{n} lines are not valid markings: {lines}", len(bad_lines))
                                .format(n=len(bad_lines), lines=", ".join(map(str, bad_lines))))
            QMessageBox.warning(self, _("Read Markings"),
                                ngettext("{n} package marked.", "{n} packages marked.", n).format(n=n) + "\n\n"
                                + "\n\n".join(problems))

    def _revalidate_marks(self):
        """After a reload, drop marks that no longer apply (package gone, already installed, ...)."""
        rows = {r.key: r for r in self.snapshot.rows}
        for key, mark in list(self.model.marks.items()):
            row = rows.get(key)
            if row is None or not (mark.action is Action.DOWNGRADE and row.installed
                                   or mark.action in allowed_actions(row)):
                self.model.marks.unmark(key)
        self._update_actions()

    def _fill_downgrade_menu(self):
        self.downgrade_menu.clear()
        rows = self._selected_rows()
        d = self._details
        if len(rows) != 1 or d is None or self._details_for != rows[0].key:
            self.downgrade_menu.addAction(_("(loading…)")).setEnabled(False)
            return
        row = rows[0]
        installed = {v.evr for v in d.versions if v.installed}
        older = [v for v in d.versions if not v.installed and v.evr not in installed
                 and evr_cmp(v.evr, row.installed_evr) < 0]
        if not older:
            self.downgrade_menu.addAction(_("No older versions in the repositories")).setEnabled(False)
        for v in older:
            self.downgrade_menu.addAction(f"{v.evr}  ({v.repo_id})",
                                          lambda evr=v.evr: self.mark_selected(Action.DOWNGRADE, evr))

    def _on_table_click(self, index):
        # Synaptic: clicking the status box opens the action menu
        if index.column() == COL_STATUS:
            m = QMenu(self)
            self._package_menu(m)
            m.exec(self.table.viewport().mapToGlobal(self.table.visualRect(index).bottomLeft()))

    def _on_double_click(self, index):
        if index.column() == COL_STATUS:
            return
        row = self.model.row_at(index)
        if row.key in self.model.marks:
            self.model.marks.unmark(row.key)
        else:
            allowed = allowed_actions(row)
            for action in (Action.INSTALL, Action.UPGRADE):
                if action in allowed:
                    self.model.marks.set(row, action)
                    break
        self._marks_changed([row.key])

    # ---------------------------------------------------------------- applying

    def apply(self):
        if not len(self.model.marks) or self.helper.busy:
            return
        rows = {r.key: r for r in self.snapshot.rows}
        request = {"op": "transaction", **self.model.marks.request(rows)}
        self.status.setText(_("Resolving dependencies…"))
        self.dnf.submit(lambda: self.catalog.resolve(request), lambda p: self._on_preview(p, request),
                        lambda e: QMessageBox.critical(self, "Kram", _("Could not resolve the changes:\n\n{error}").format(error=e)))

    def _on_preview(self, preview: TransactionPreview, request: dict):
        self._update_status()
        if not preview.ok:
            box = QMessageBox(QMessageBox.Warning, _("Cannot apply changes"),
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
            self.model.marks.clear()
            self._marks_changed(None)
            self.reload()

    def refresh_metadata(self):
        if self.helper.busy:
            return
        self._run_helper({"op": "refresh"}, _("Refreshing metadata"))
        self.reload()

    def run_helper_and_reload(self, request: dict, title: str) -> bool:
        ok = self._run_helper(request, title)
        self.reload()  # even after a failure: part of the change may have happened
        return ok

    def open_repos(self):
        if not self.snapshot or self.helper.busy:
            return
        self.dnf.submit(self.catalog.repo_package_counts, self._show_repos)

    def _show_repos(self, counts):
        dlg = ReposDialog(self.snapshot.repos, counts, self)
        if dlg.exec() == ReposDialog.Accepted and (changes := dlg.changes()):
            self.run_helper_and_reload({"op": "repo_set_enabled", "repos": changes}, _("Changing repositories"))

    def open_copr(self):
        if not self.snapshot or self.helper.busy:
            return
        dlg = CoprDialog(self.run_helper_and_reload, self)

        def refresh(snap):
            self.dnf.submit(self.catalog.repo_package_counts, lambda counts: dlg.set_catalog(snap, counts))

        def show_packages(repo_id):
            dlg.accept()
            self.search.clear()
            self.sidebar.select("origin", f"repo:{repo_id}")
        refresh(self.snapshot)
        self.catalogLoaded.connect(refresh)
        dlg.showPackages.connect(show_packages)
        dlg.exec()
        self.catalogLoaded.disconnect(refresh)

    def _run_helper(self, request: dict, title: str) -> bool:
        self.act_apply.setEnabled(False)
        self.act_reload.setEnabled(False)
        dlg = ProgressDialog(self.helper, request, title, self)
        dlg.exec()
        self.act_reload.setEnabled(True)
        self._update_actions()
        return dlg.ok
