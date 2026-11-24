"""Main window: Synaptic layout — browse, mark, preview, apply. A view of kram.app.browser.Browser, which holds the
state and the flows; this builds the widgets, wires them to it and shows its dialogs."""
from collections.abc import Callable
from pathlib import Path

from PySide6 import __version__ as pyside_version
from PySide6.QtCore import QSettings, QStandardPaths, Qt, qVersion
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QMainWindow,
    QMenu,
    QSplitter,
    QToolButton,
    QWidget,
)

from .. import HOMEPAGE, __version__
from ..app import preferences
from ..app.actions import ActionState, DynamicItem, table_menu
from ..app.browser import Browser, ReposChoice, rpm_path
from ..app.custom_filters import CustomFilters
from ..app.details import DETAILS_TAB_KEY
from ..app.doc import Doc
from ..app.files import FILES_VIEW_KEY
from ..app.mirrors import MirrorChoice
from ..app.package_list import Sort
from ..core.model import CatalogSnapshot, PkgRow, TransactionPreview
from ..core.settings import store as settings
from ..i18n import _
from .about_dialog import AboutDialog
from .actions import WindowActions, fill_dynamic
from .apply_dialog import ApplyDialog
from .cache_dialog import CacheDialog
from .copr_dialog import CoprDialog
from .custom_filters import edit_dialog
from .details import DetailsTabs
from .history_dialog import HistoryDialog
from .install_dialog import InstallDialog
from .mirrors_dialog import MirrorsDialog
from .notifier_dialog import NotifierDialog
from .package_model import COL_NAME, COL_STATUS, PackageTableModel
from .package_view import PackageView
from .progress_dialog import ProgressDialog
from .qt_loop import QtScheduler, post
from .qt_ui import QtUi
from .release_watch import ReleaseWatcher
from .repos_dialog import ReposDialog
from .search_bar import SearchBar
from .sidebar import Sidebar
from .status_bar import MainStatusBar
from .toolbar import MainToolBar
from .upgrade_dialog import UpgradeDialog


def _order(descending: bool) -> Qt.SortOrder:
    return Qt.SortOrder.DescendingOrder if descending else Qt.SortOrder.AscendingOrder



def toolkit_versions() -> str:
    """The toolkit this front end runs on, for About: Qt's and PySide6's versions."""
    return f"Qt {qVersion()}, PySide6 {pyside_version}"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(_("Package Manager"))  # Qt appends " — Kram" (the application display name)
        self.resize(1320, 860)

        self.status = MainStatusBar()
        self.setStatusBar(self.status)
        self.ui = QtUi(self, self.status.showMessage)
        self.details = DetailsTabs()
        self.browser = b = Browser(self, self.ui, QtScheduler(self), self.details, post,
                                       front_package="kram-qt")
        self.dnf, self.catalog, self.helper, self.marker = b.dnf, b.catalog, b.helper, b.marker
        self.details_loader = b.details_loader
        self.catalogLoaded = b.catalog_loaded
        self.status.reposClicked.connect(b.open_repos)
        self.releases = ReleaseWatcher(self)
        self.releases.act_upgrade.triggered.connect(self.open_upgrade)
        b.refreshed.connect(self.releases.check)
        self._upgrade_dialog: UpgradeDialog | None = None
        self._history_dialog: HistoryDialog | None = None
        self.search = SearchBar(self, b.search)

        self._build_central()
        self._connect_actions()
        self.table.addActions(self.acts.table_actions())
        self._build_toolbar()
        self.acts.fill_menu_bar(self.menuBar())
        self.acts.watch_releases.toggled.connect(lambda _on: self.releases.update_button())

        self.setAcceptDrops(True)  # an .rpm file dropped anywhere on the window opens the installer
        self._restore_settings()
        self.reload()

    # ---------------------------------------------------------------- construction

    def _connect_actions(self):
        acts = self.acts = WindowActions(self)
        b = self.browser
        for action, slot in [
            (acts.reload, b.refresh_metadata), (acts.reload_cache, self.reload),
            (acts.mark_upgrades, self.marker.mark_all_upgrades), (acts.mark_unneeded, self.marker.mark_unneeded),
            (acts.apply, b.apply), (acts.unmark_all, self.marker.unmark_all),
            (acts.properties, lambda: self.details.select_name("general")),
            (acts.repos, b.open_repos), (acts.copr, self.open_copr), (acts.cache, self.open_cache),
            (acts.notifications, self.open_notifications), (acts.history, lambda: self.open_history()),
            (acts.show_in_history, self.show_in_history),
            (acts.why_blocked, lambda: self.details.select_name("dependencies")),
            (acts.filters, lambda: self.custom_filters.edit()), (acts.new_filter, self.new_filter_from_view),
            (acts.find, self.search.focus), (acts.back, b.go_back),
            (acts.save_marks, b.save_marks), (acts.read_marks, b.read_marks), (acts.export_csv, b.export_csv),
            (acts.open_file, lambda: self.open_package_file()), (acts.quit, self.close), (acts.about, self.about),
            (acts.copy_name, b.copy_names), (acts.copy_nevra, b.copy_nevras), (acts.unmark, b.unmark_selected),
            (acts.lock, lambda: b.set_version_lock(True)), (acts.unlock, lambda: b.set_version_lock(False)),
        ]:
            action.triggered.connect(slot)
        for kind, action in acts.mark_upgrades_of_kind.items():
            action.triggered.connect(lambda _on=False, k=kind: self.marker.mark_upgrades(k))
        for mark, action in acts.mark.items():
            action.triggered.connect(lambda _on=False, m=mark: b.mark_selected(m))
        acts.downgrade_menu.aboutToShow.connect(self._fill_downgrade_menu)

    def createPopupMenu(self) -> QMenu:
        # instead of Qt's default "show/hide toolbars" menu: the toolbar can't be hidden, only restyled
        menu = QMenu(self)
        menu.addActions(self.toolbar.styles.actions())
        return menu

    def _build_toolbar(self):
        tb = self.toolbar = MainToolBar(self.acts.toolbar_styles)
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
        b = self.browser
        self.sidebar = Sidebar(model=b.sidebar)
        self.sidebar.contextMenuRequested.connect(self._sidebar_menu)
        self.custom_filters = b.custom_filters = CustomFilters(b.sidebar, self.catalog, self.dnf, lambda: b.snapshot,
                                                               b.ui, edit_dialog(self))
        self.sidebar.entryActivated.connect(self.custom_filters.activated)
        self.model = PackageTableModel(self, b.packages)
        self.table = PackageView()
        self.table.setModel(self.model)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(COL_NAME, Qt.SortOrder.AscendingOrder)
        self.table.header().sortIndicatorChanged.connect(
            lambda column, order: b.user_sorted(column, order == Qt.SortOrder.DescendingOrder))
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.selectionModel().currentRowChanged.connect(
            lambda current, _previous: b.current_changed(self.model.row_at(current) if current.isValid() else None))
        self.table.selectionModel().selectionChanged.connect(b.update_actions)
        self.table.clicked.connect(self._on_table_click)
        self.table.doubleClicked.connect(self._on_double_click)
        self.table.emptyLinkActivated.connect(b.empty_link)
        self.details.linkActivated.connect(b.follow_link)

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

    # ---------------------------------------------------------------- settings and lifetime

    def _restore_settings(self):
        s = QSettings()  # the settings only Qt can read; the others are in `settings`
        self.releases.update_button()
        if geom := s.value("window/geometry"):
            self.restoreGeometry(geom)
        for key, splitter in (("window/hsplit", self.hsplit), ("window/vsplit", self.vsplit)):
            if state := s.value(key):
                splitter.restoreState(state)
        self.table.restore_columns(s)
        if name := settings.get(DETAILS_TAB_KEY):
            self.details.select_name(name)
        else:  # saved before 0.7 by position, from the tabs before the advisories tab came
            old = ("description", "general", "dependencies", "files", "versions", "changelog")
            self.details.select_name(old[min(max(settings.get("details/tab", 0), 0), len(old) - 1)])
        self.details.files.tree_mode = settings.get(FILES_VIEW_KEY, "tree") != "list"
        self.browser.restore_settings()
        self.custom_filters.restore()

    def _save_settings(self):
        if self.model.sort_column is None:  # ranked search results: save the user's column sort instead
            column, descending = self.browser.user_sort
            self.table.header().setSortIndicator(column, _order(descending))
        settings.set(DETAILS_TAB_KEY, self.details.current_name())
        settings.set(FILES_VIEW_KEY, "tree" if self.details.files.tree_mode else "list")
        # Browser.shutdown saves the rest; then QSettings reads the file they changed before it writes its own keys
        s = QSettings()
        s.setValue("window/geometry", self.saveGeometry())
        s.setValue("window/hsplit", self.hsplit.saveState())
        s.setValue("window/vsplit", self.vsplit.saveState())
        self.table.save_columns(s)

    def reload(self) -> None:
        self.browser.reload()

    def show_view(self, view: str) -> None:
        self.browser.show_view(view)

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

    def closeEvent(self, event):
        answer = []
        self.browser.can_close(answer.append)  # Qt's questions are modal: answered by now
        if not (answer and answer[0]):
            event.ignore()
            return
        self._save_settings()
        self.browser.shutdown()
        super().closeEvent(event)

    def quit(self) -> None:
        """BrowserView: a transaction removed this front end."""
        if self.close():
            QApplication.quit()

    # ---------------------------------------------------------------- BrowserView: the package list

    def current_key(self) -> tuple[str, str] | None:
        idx = self.table.currentIndex()
        return self.model.row_at(idx).key if idx.isValid() else None

    def select_key(self, key: tuple[str, str], scroll: bool = True) -> bool:
        idx = self.model.index_of_key(key)
        if not idx.isValid():
            return False
        self.table.setCurrentIndex(idx)
        if scroll:
            self.table.scrollTo(idx, QAbstractItemView.ScrollHint.PositionAtCenter)
        return True

    def select_first(self, to_top: bool) -> None:
        self.table.setCurrentIndex(self.model.index(0, COL_NAME))
        if to_top:
            self.table.scrollToTop()

    def selected_rows(self) -> list[PkgRow]:
        return [self.model.row_at(i) for i in self.table.selectionModel().selectedRows()]

    def show_sort(self, sort: Sort | None) -> None:
        header = self.table.header()
        header.blockSignals(True)
        if sort is None:
            header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        else:
            header.setSortIndicator(sort[0], _order(sort[1]))
        header.blockSignals(False)

    def set_empty(self, doc: Doc) -> None:
        self.table.set_empty_doc(doc)

    def focus_list(self) -> None:
        self.activateWindow()
        self.table.setFocus()

    # ---------------------------------------------------------------- BrowserView: status and actions

    def set_status(self, text: str) -> None:
        self.status.set_text(text)

    def status_text(self) -> str:
        return self.status.text()

    def show_catalog(self, snap: CatalogSnapshot) -> None:
        self.status.show_catalog(snap)

    def show_counts(self, snap, shown, to_install, to_remove, ms) -> None:
        self.status.show_counts(snap, shown, to_install, to_remove, ms)

    def show_error(self, error: BaseException) -> None:
        self.status.show_error(error)

    def apply_actions(self, state: ActionState, catalog: bool, busy: bool) -> None:
        self.acts.apply_state(state, {"upgrade": self.releases.act_upgrade})
        if self._history_dialog is not None:
            self._history_dialog.set_marking(catalog, busy)

    def set_reload_enabled(self, on: bool) -> None:
        self.acts.reload.setEnabled(on)
        self.acts.reload_cache.setEnabled(on)

    def set_apply_enabled(self, on: bool) -> None:
        self.acts.apply.setEnabled(on)

    # ---------------------------------------------------------------- BrowserView: dialogs

    def review_changes(self, preview: TransactionPreview, request: dict, basearch: str, resolve,
                       done: Callable[[dict | None], None]) -> None:
        dlg = ApplyDialog(preview, request, basearch, self, resolve=resolve)
        accepted = dlg.exec() == ApplyDialog.Accepted
        result = dlg.review.result()  # with the recommendations the user unchecked, and download only if chosen
        dlg.deleteLater()  # every dialog is deleted after use: as a child of the window it would live until exit
        done(result if accepted else None)

    def run_helper(self, request: dict, title: str, done: Callable[[dict | None], None]) -> None:
        # a child of the dialog that started it (COPR, Package Cache): as a sibling, that one could be raised over it
        dlg = ProgressDialog(self.helper, request, title, QApplication.activeModalWidget() or self)
        dlg.exec()
        result = dlg.result if dlg.ok else None
        dlg.deleteLater()  # with its whole log
        done(result)

    def show_repos(self, data, done: Callable[[ReposChoice | None], None]) -> None:
        b = self.browser
        dlg = ReposDialog(data.repos, data.counts, self, owners=data.owners, listed=data.listed,
                          installed=data.installed, variables=data.variables, on_remove=b.remove_repos,
                          on_mirrors=b.open_mirrors)
        shown = [True]

        def refresh(snap) -> None:  # after a removal or a mirror change made from it: it stays open
            b.repos_data(snap, lambda new: shown[0] and dlg.set_data(new))
        b.catalog_loaded.connect(refresh)
        accepted = dlg.exec() == ReposDialog.Accepted
        shown[0] = False  # data read for it later is dropped
        b.catalog_loaded.disconnect(refresh)
        choice = ReposChoice(dlg.show_repo, dlg.changes() if accepted else None)
        dlg.deleteLater()
        done(choice)

    def show_mirrors(self, repo, source, fastestmirror: bool, apply: Callable[[MirrorChoice], None]) -> None:
        # over the Repositories dialog that asked for it, which stays open behind it; a choice is applied while this one
        # stays open too, and the reload shows it the new state
        b = self.browser
        dlg = MirrorsDialog(repo, source, fastestmirror, QApplication.activeModalWidget() or self, on_choice=apply)
        shown = [True]

        def refresh(snap) -> None:
            if shown[0] and (state := b.mirror_state(snap, repo.id)) is not None:
                dlg.set_state(*state)
        b.catalog_loaded.connect(refresh)
        dlg.exec()
        shown[0] = False
        b.catalog_loaded.disconnect(refresh)
        dlg.deleteLater()

    def run_helper_and_reload(self, request: dict, title: str) -> bool:
        ok = []
        self.browser.run_helper_and_reload(request, title, ok.append)
        return bool(ok and ok[0])

    # ---------------------------------------------------------------- menus and clicks

    def _fill_menu(self, menu: QMenu, items: list[DynamicItem | str | None]) -> None:
        for item in items:
            if item is None:
                menu.addSeparator()
            elif isinstance(item, str):
                menu.addAction(self.acts.by_id[item])
            else:
                fill_dynamic(menu, [item])

    def _context_menu(self, pos):
        if not self.table.indexAt(pos).isValid():
            return
        m = QMenu(self)
        self.acts.fill(m, table_menu().items)
        m.exec(self.table.viewport().mapToGlobal(pos))

    def _sidebar_menu(self, pos, entry) -> None:
        m = QMenu(self)
        m.setToolTipsVisible(True)
        self._fill_menu(m, self.browser.sidebar_menu(entry))
        m.exec(pos)

    def _fill_downgrade_menu(self):
        self.acts.downgrade_menu.clear()
        fill_dynamic(self.acts.downgrade_menu, self.browser.downgrade_items())

    def _on_table_click(self, index):
        # Synaptic: clicking the status box opens the action menu, or marks the likely action if the user chose that
        if index.column() == COL_STATUS:
            if preferences.value(preferences.STATUS_CLICK) and self.marker.toggle_likely(self.model.row_at(index)):
                return
            m = QMenu(self)
            self.acts.fill_package_menu(m)
            m.exec(self.table.viewport().mapToGlobal(self.table.visualRect(index).bottomLeft()))

    def _on_double_click(self, index):
        if index.column() != COL_STATUS:
            self.marker.toggle_likely(self.model.row_at(index))

    def new_filter_from_view(self) -> None:
        self.custom_filters.new_from_view(self.browser.filter, self.search.text(), self.search.mode())

    def about(self):
        dlg = AboutDialog(f"<h3>Kram · Qt {__version__}</h3><p>{toolkit_versions()}</p>"
                          f"<p>{_('A Synaptic-style package manager for Fedora.')}</p>"
                          f"<p><a href='{HOMEPAGE}'>{HOMEPAGE}</a></p>"
                          f"<p>Copyright © 2026 Modo Ltunzher<br>{_('Released under the MIT License.')}</p>",
                          self.windowIcon().pixmap(64, 64), self)
        dlg.exec()
        dlg.deleteLater()

    # ---------------------------------------------------------------- the other dialogs

    def open_copr(self):
        b = self.browser
        if not b.snapshot or b.busy():
            return
        dlg = CoprDialog(self.run_helper_and_reload, self)

        def refresh(snap):
            self.dnf.submit(self.catalog.repo_package_counts, lambda counts: dlg.set_catalog(snap, counts),
                            lambda _e: None)  # the dialog keeps the counts it has

        def show_packages(repo_id):
            dlg.accept()
            b.show_repo_packages(repo_id)
        refresh(b.snapshot)
        b.catalog_loaded.connect(refresh)
        dlg.showPackages.connect(show_packages)
        dlg.exec()
        b.catalog_loaded.disconnect(refresh)
        dlg.deleteLater()

    def open_cache(self):
        b = self.browser
        if not b.snapshot or b.busy():
            return
        dlg = CacheDialog(self.dnf, b.clean_cache, self, helper=b.run_helper)
        dlg.exec()
        dlg.deleteLater()

    def open_history(self, name: str | None = None) -> None:
        """File → Transaction History; with a package name, filtered by it (Package → Show in History)."""
        b = self.browser
        if b.snapshot is None:
            return
        dlg = self._history_dialog
        if dlg is None:
            dlg = self._history_dialog = HistoryDialog(self.dnf, self.catalog, self)
            dlg.showPackage.connect(self._show_from_history)
            dlg.undoRequested.connect(lambda tid: b.undo_transaction(tid, dlg.rows_of(tid), dlg.close))
            # after Apply the new transaction shows; a closed window reads the history again when it opens
            b.catalog_loaded.connect(lambda _snap: dlg.isVisible() and dlg.reload())
        if not dlg.isVisible():
            dlg.reload()
        if name is not None:
            dlg.show_package_name(name)
        dlg.set_marking(b.snapshot is not None, b.busy())
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _show_from_history(self, key: tuple[str, str]) -> None:
        """A package double-clicked in the history: the user wants it, so the history closes and the package list
        gets the focus (selected behind the window, it was easy to miss)."""
        if self._history_dialog is not None:
            self._history_dialog.close()
        self.browser.navigate(key)
        self.focus_list()

    def show_in_history(self) -> None:
        rows = self.selected_rows()
        if len(rows) == 1:
            self.open_history(rows[0].name)

    def open_notifications(self):
        dlg = NotifierDialog(self)
        dlg.exec()
        dlg.deleteLater()

    def open_upgrade(self) -> None:
        target = self.releases.target()
        snap = self.browser.snapshot
        if target is None or snap is None:
            return
        if self._upgrade_dialog is None or self._upgrade_dialog.target != target:
            self._upgrade_dialog = UpgradeDialog(target, self.releases.running, self.releases.running_eol(),
                                                 snap, self.dnf, self)
        self._upgrade_dialog.exec()

    # ---------------------------------------------------------------- package files

    @staticmethod
    def _dropped_rpm(mime) -> str | None:
        urls = mime.urls() if mime.hasUrls() else []
        return rpm_path([u.toLocalFile() for u in urls]) if all(u.isLocalFile() for u in urls) else None

    def dragEnterEvent(self, event):
        if self._dropped_rpm(event.mimeData()) and self.browser.can_open_file():
            event.acceptProposedAction()

    def dropEvent(self, event):
        if (path := self._dropped_rpm(event.mimeData())) and self.browser.can_open_file():
            event.acceptProposedAction()
            # after the drop returns: a modal dialog inside a drop handler blocks the drag source
            QtScheduler(self).later(lambda: self.open_package_file(path))

    def open_package_file(self, path: str | None = None) -> None:
        b = self.browser
        if not b.can_open_file():
            return
        if not path:
            downloads = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
            chosen = []
            self.ui.choose_open_file(_("Open Package File"), settings.get("install/dir", downloads),
                                     _("RPM packages (*.rpm)"), chosen.append)
            if not chosen or not chosen[0]:
                return
            path = chosen[0]
            settings.set("install/dir", str(Path(path).parent))
            if not b.can_open_file():
                return
        dlg = InstallDialog(path, self.catalog, self.dnf, self.helper, b.snapshot.basearch,
                            marks=len(self.model.marks), parent=self)
        dlg.exec()
        changed = dlg.changed_system
        dlg.deleteLater()
        if changed:
            b.reload()
        b.update_actions()
