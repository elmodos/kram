"""Main window: Synaptic layout — browse, mark, preview, apply."""
import json
import time

from PySide6.QtCore import QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QGuiApplication, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSplitter,
    QToolBar,
    QTreeView,
    QWidget,
)

from .. import HOMEPAGE
from ..core.catalog import Catalog
from ..core.evr import evr_cmp
from ..core.filters import FilterEntry
from ..core.marks import Action, allowed_actions
from ..core.model import CatalogSnapshot, PkgDetails, PkgRow, Status, TransactionPreview
from ..core.search import MODE_LABELS, Mode, SearchIndex
from ..ipc.client import HelperClient
from .apply_dialog import ApplyDialog
from .details import DetailsTabs
from .dnf_thread import DnfThread
from .package_model import COL_NAME, COL_STATUS, PackageTableModel
from .progress_dialog import ProgressDialog
from .sidebar import Sidebar

COLUMN_WIDTHS = [26, 24, 230, 175, 175, 150, 80]
HISTORY_IDLE_MS = 1500  # a search left alone this long goes into the history
NOT_YET = "Буде в наступних версіях"


def _age(seconds: int | None) -> str:
    if seconds is None:
        return "Метадані: невідомо"
    if seconds < 3600:
        return f"Метадані: {seconds // 60} хв тому"
    if seconds < 2 * 86400:
        return f"Метадані: {seconds // 3600} год {seconds % 3600 // 60} хв тому"
    return f"Метадані: {seconds // 86400} дн тому"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Kram — менеджер пакунків")
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
        self.act_reload = self._action("Перечитати", "view-refresh", "Ctrl+R", self.refresh_metadata,
                                       tip="Оновити метадані репозиторіїв і перечитати каталог (потрібен пароль)")
        self.act_reload_cache = self._action("Перечитати з кешу", "view-refresh", "Ctrl+Shift+R", self.reload,
                                             tip="Перечитати каталог із локального кешу, без мережі та пароля")
        self.act_mark_upgrades = self._action("Позначити всі оновлення", "system-software-update", "Ctrl+U",
                                              self.mark_all_upgrades, tip="Позначити для оновлення всі пакунки, "
                                                                          "що мають новіші версії")
        self.act_apply = self._action("Застосувати", "dialog-ok-apply", "Ctrl+P", self.apply,
                                      tip="Переглянути й застосувати позначені зміни")
        self.act_apply.setEnabled(False)
        self.act_unmark_all = self._action("Зняти всі позначки", "edit-clear", "Ctrl+Shift+Z", self.unmark_all,
                                           tip="Скасувати всі позначені зміни")
        self.act_unmark_all.setEnabled(False)
        self.act_properties = self._action("Властивості", "document-properties", "Alt+Return",
                                           lambda: self.details.setCurrentIndex(1))
        self.act_repos = self._action("Репозиторії", "configure", enabled=False)
        self.act_find = self._action("Знайти", "edit-find", QKeySequence.Find,
                                     lambda: (self.search.setFocus(), self.search.selectAll()))
        self.act_back = self._action("Назад", "go-previous", "Alt+Left", self.go_back,
                                     tip="Повернутися до попереднього пакунка (після переходу за залежністю)")
        self.act_quit = self._action("Вихід", "application-exit", QKeySequence.Quit, self.close)
        self.act_copy_name = self._action("Копіювати назву", "edit-copy", "Ctrl+C", self.copy_names)
        self.act_copy_nevra = self._action("Копіювати name-version-release.arch", "edit-copy", "Ctrl+Shift+C",
                                           self.copy_nevras)
        # scoped to the table, so Ctrl+C still copies text in the search field and the detail tabs
        for a in (self.act_copy_name, self.act_copy_nevra):
            self.removeAction(a)
            a.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        self.act_about = self._action("Про Kram", "help-about", slot=self.about)
        # package actions are scoped to the table: Del/Ins/Ctrl+Z keep their meaning in the search field
        self.mark_actions: dict[Action, QAction] = {}
        for action, text, icon, shortcut in [
            (Action.INSTALL, "Позначити для встановлення", "list-add", "Ins"),
            (Action.UPGRADE, "Позначити для оновлення", "go-up", None),
            (Action.REINSTALL, "Позначити для перевстановлення", "view-refresh", None),
            (Action.REMOVE, "Позначити для видалення", "list-remove", "Del"),
            (Action.MARK_USER, "Позначити як встановлений вручну", "user-identity", None),
            (Action.MARK_DEP, "Позначити як залежність", "link", None),
        ]:
            a = self._action(text, icon, shortcut, lambda _c=False, act=action: self.mark_selected(act), tip=text)
            self.removeAction(a)
            a.setShortcutContext(Qt.WidgetWithChildrenShortcut)
            self.mark_actions[action] = a
        self.downgrade_menu = QMenu("Понизити до версії", self)
        self.downgrade_menu.setIcon(QIcon.fromTheme("go-down"))
        self.downgrade_menu.aboutToShow.connect(self._fill_downgrade_menu)
        self.act_unmark = self._action("Зняти позначку", "edit-undo", "Ctrl+Z", self.unmark_selected,
                                       tip="Зняти позначку з вибраних пакунків")
        self.removeAction(self.act_unmark)
        self.act_unmark.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        self.act_mark_upgrades.setEnabled(False)

    def _package_menu(self, menu: QMenu) -> None:
        menu.addActions(list(self.mark_actions.values()))
        menu.addMenu(self.downgrade_menu)
        menu.addSeparator()
        menu.addAction(self.act_unmark)

    def _build_menus(self):
        mb = self.menuBar()
        m = mb.addMenu("&Файл")
        m.addActions([self.act_reload, self.act_reload_cache])
        m.addSeparator()
        m.addAction(self.act_quit)
        m = mb.addMenu("&Правка")
        m.addActions([self.act_mark_upgrades, self.act_unmark_all, self.act_apply])
        m.addSeparator()
        m.addActions([self.act_copy_name, self.act_copy_nevra])
        m.addSeparator()
        m.addAction(self.act_find)
        m = mb.addMenu("Па&кунок")
        self._package_menu(m)
        m.addSeparator()
        m.addActions([self.act_properties, self.act_back])
        m = mb.addMenu("&Налаштування")
        m.addAction(self.act_repos)
        m = mb.addMenu("&Довідка")
        m.addAction(self.act_about)

    def _build_toolbar(self):
        tb = QToolBar("Головна панель")
        tb.setObjectName("main-toolbar")
        tb.setMovable(False)
        tb.setIconSize(QSize(24, 24))
        tb.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        tb.addActions([self.act_reload, self.act_mark_upgrades, self.act_apply])
        tb.addSeparator()
        tb.addActions([self.act_properties, self.act_repos])
        spacer = QWidget()
        spacer.setSizePolicy(spacer.sizePolicy().Policy.Expanding, spacer.sizePolicy().Policy.Preferred)
        tb.addWidget(spacer)
        self.search_mode = QComboBox()
        self.search_mode.addItems([MODE_LABELS[m] for m in Mode])
        self.search_mode.setToolTip(
            "Назва / Назва + опис / Повний опис — миттєвий пошук із ранжуванням.\n"
            "Provides — пакунки, що надають можливість (libvulkan.so.1, python3dist(requests), webbrowser).\n"
            "Файл — власник файлу (/usr/bin/7z або просто 7z; для невстановлених — лише основні файли).\n\n"
            "Кілька слів — усі мають збігтися. ^на початку, в кінці$, * і ? — шаблони.")
        self.search_mode.currentIndexChanged.connect(self.apply_filter)
        tb.addWidget(self.search_mode)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Пошук (Ctrl+F)")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(300)
        self.search.addAction(QIcon.fromTheme("edit-find"), QLineEdit.LeadingPosition)
        tb.addWidget(self.search)
        self.addToolBar(tb)

        self._debounce = QTimer(self, singleShot=True, interval=150)
        self._debounce.timeout.connect(self.apply_filter)
        self.search.textChanged.connect(self._debounce.start)
        self.search.returnPressed.connect(self._on_search_enter)
        self._history_timer = QTimer(self, singleShot=True, interval=HISTORY_IDLE_MS)
        self._history_timer.timeout.connect(self._remember_search)

    def _build_central(self):
        self.sidebar = Sidebar()
        self.sidebar.filterChanged.connect(self._on_filter)

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
        self.hsplit = QSplitter(Qt.Horizontal)
        self.hsplit.addWidget(self.sidebar)
        self.hsplit.addWidget(self.vsplit)
        self.hsplit.setStretchFactor(1, 1)
        self.hsplit.setSizes([270, 1050])
        self.setCentralWidget(self.hsplit)

    # ---------------------------------------------------------------- settings

    def _restore_settings(self):
        s = QSettings()
        if geom := s.value("window/geometry"):
            self.restoreGeometry(geom)
        for key, splitter in (("window/hsplit", self.hsplit), ("window/vsplit", self.vsplit)):
            if state := s.value(key):
                splitter.restoreState(state)
        if state := s.value("table/header"):
            self.table.header().restoreState(state)
        self.details.setCurrentIndex(int(s.value("details/tab", 0)))
        self.search_mode.setCurrentIndex(int(s.value("search/mode", Mode.NAME)))
        try:
            self.sidebar.history = [tuple(h) for h in json.loads(s.value("search/history", "[]"))]
        except (TypeError, ValueError):
            self.sidebar.history = []
        self._restore_filter = (s.value("sidebar/view", "status"), s.value("sidebar/entry", "status:all"))

    def _save_settings(self):
        s = QSettings()
        if self.model.sort_column is None:  # ranked search results: save the user's column sort instead
            self.table.header().setSortIndicator(*self._user_sort)
        s.setValue("search/history", json.dumps(self.sidebar.history, ensure_ascii=False))
        s.setValue("window/geometry", self.saveGeometry())
        s.setValue("window/hsplit", self.hsplit.saveState())
        s.setValue("window/vsplit", self.vsplit.saveState())
        s.setValue("table/header", self.table.header().saveState())
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
                self, "Kram", f"Є {len(self.model.marks)} позначених змін, які не застосовано. Вийти?") \
                != QMessageBox.Yes:
            event.ignore()
            return
        self.helper.stop()
        self._save_settings()
        self.dnf.shutdown()
        super().closeEvent(event)

    # ---------------------------------------------------------------- loading and filtering

    def reload(self):
        self.status.setText("Завантаження метаданих…")
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
        self.age.setText(_age(snap.metadata_age) + "  ")
        view, entry = self._restore_filter if self.filter is None else (
            self.sidebar.current_view, self.sidebar.current_entry_id)
        self.sidebar.set_snapshot(snap)
        self.sidebar.select(view, entry)  # emits filterChanged -> apply_filter
        if keep:
            self._select_key(keep)

    def _on_error(self, e: BaseException):
        self.act_reload.setEnabled(True)
        self.status.setText(f"Помилка: {e}")
        QMessageBox.critical(self, "Kram", f"Не вдалося завантажити каталог пакунків:\n\n{e}")

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
            self.status.setText(f"Пошук «{text}» ({MODE_LABELS[mode]})…")

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
        self.status.setText(
            f"{shown} показано, {s.n_installed} встановлено, {s.n_upgradable} оновлень. "
            f"{inst} до встановлення/оновлення, {rm} до видалення.")
        if ms is None:
            return
        self.status.setToolTip(f"Каталог: {s.load_seconds:.2f} с, фільтр і пошук: {ms:.0f} мс")

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
                                f"Нічого не надає «{value}»", 5000))

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
            self.statusBar().showMessage(f"Пакунок {key[0]}.{key[1]} не знайдено в каталозі", 5000)

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
        m.addSeparator()
        m.addAction(self.act_properties)
        m.exec(self.table.viewport().mapToGlobal(pos))

    def about(self):
        QMessageBox.about(self, "Про Kram", f"<h3>Kram</h3><p>Менеджер пакунків для Fedora в дусі Synaptic.</p>"
                                           f"<p><a href='{HOMEPAGE}'>{HOMEPAGE}</a></p>")

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
        self.act_mark_upgrades.setEnabled(bool(self.snapshot and self.snapshot.n_upgradable))

    def _marks_changed(self, keys):
        self.model.marks_changed(keys)
        self._update_actions()
        self._update_status()
        if self.sidebar.current_view == "status":
            self.sidebar.refresh_counts()

    def mark_selected(self, action: Action, evr: str = ""):
        changed = [r.key for r in self._selected_rows() if self.model.marks.set(r, action, evr)]
        if changed:
            self._marks_changed(changed)

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
        self.statusBar().showMessage(f"Позначено для оновлення: {len(changed)}", 5000)

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
            self.downgrade_menu.addAction("(завантаження…)").setEnabled(False)
            return
        row = rows[0]
        installed = {v.evr for v in d.versions if v.installed}
        older = [v for v in d.versions if not v.installed and v.evr not in installed
                 and evr_cmp(v.evr, row.installed_evr) < 0]
        if not older:
            self.downgrade_menu.addAction("Старіших версій у репозиторіях немає").setEnabled(False)
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
        self.status.setText("Розрахунок залежностей…")
        self.dnf.submit(lambda: self.catalog.resolve(request), lambda p: self._on_preview(p, request),
                        lambda e: QMessageBox.critical(self, "Kram", f"Не вдалося розрахувати зміни:\n\n{e}"))

    def _on_preview(self, preview: TransactionPreview, request: dict):
        self._update_status()
        if not preview.ok:
            box = QMessageBox(QMessageBox.Warning, "Неможливо застосувати зміни",
                              "Позначені зміни неможливо виконати. Зніміть або змініть позначки.", parent=self)
            box.setInformativeText(preview.problems[0][:500])
            box.setDetailedText("\n".join(preview.problems))
            box.exec()
            return
        dlg = ApplyDialog(preview, request, self.snapshot.basearch, self)
        if dlg.exec() != ApplyDialog.Accepted:
            return
        download_only = dlg.download_only.isChecked()
        if download_only:
            request = {**request, "download_only": True}
        if self._run_helper(request, "Застосування змін") and not download_only:
            self.model.marks.clear()
            self._marks_changed(None)
            self.reload()

    def refresh_metadata(self):
        if self.helper.busy:
            return
        self._run_helper({"op": "refresh"}, "Оновлення метаданих")
        self.reload()

    def _run_helper(self, request: dict, title: str) -> bool:
        self.act_apply.setEnabled(False)
        self.act_reload.setEnabled(False)
        dlg = ProgressDialog(self.helper, request, title, self)
        dlg.exec()
        self.act_reload.setEnabled(True)
        self._update_actions()
        return dlg.ok
