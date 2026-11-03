"""Main window: Synaptic layout. M1 is read-only — marking and applying arrive in M3."""
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
from ..core.filters import FilterEntry
from ..core.model import CatalogSnapshot, PkgRow
from .details import DetailsTabs
from .dnf_thread import DnfThread
from .package_model import COL_NAME, PackageTableModel
from .sidebar import Sidebar

COLUMN_WIDTHS = [26, 24, 230, 175, 175, 150, 80]
SEARCH_NAME, SEARCH_NAME_SUMMARY = range(2)
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
        self.act_reload = self._action("Перечитати", "view-refresh", "Ctrl+R", self.reload,
                                       tip="Перечитати каталог із кешу (оновлення метаданих — у M3)")
        self.act_mark_upgrades = self._action("Позначити всі оновлення", "system-software-update", "Ctrl+U",
                                              enabled=False)
        self.act_apply = self._action("Застосувати", "dialog-ok-apply", "Ctrl+P", enabled=False)
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
        self.pkg_actions = [
            self._action(text, icon, shortcut, enabled=False) for text, icon, shortcut in [
                ("Позначити для встановлення", "list-add", "Ins"),
                ("Позначити для перевстановлення", "view-refresh", None),
                ("Позначити для оновлення", "go-up", None),
                ("Позначити для видалення", "list-remove", "Del"),
                ("Понизити до версії…", "go-down", None),
                ("Зняти позначку", "edit-undo", "Ctrl+Z"),
            ]
        ]

    def _build_menus(self):
        mb = self.menuBar()
        m = mb.addMenu("&Файл")
        m.addAction(self.act_reload)
        m.addSeparator()
        m.addAction(self.act_quit)
        m = mb.addMenu("&Правка")
        m.addActions([self.act_mark_upgrades, self.act_apply])
        m.addSeparator()
        m.addActions([self.act_copy_name, self.act_copy_nevra])
        m.addSeparator()
        m.addAction(self.act_find)
        m = mb.addMenu("Па&кунок")
        m.addActions(self.pkg_actions)
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
        self.search_mode.addItems(["Назва", "Назва + опис"])
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
        self.search.returnPressed.connect(self.apply_filter)

    def _build_central(self):
        self.sidebar = Sidebar()
        self.sidebar.filterChanged.connect(self._on_filter)

        self.model = PackageTableModel(self)
        self.table = QTreeView()
        self.table.setModel(self.model)
        self.table.setRootIsDecorated(False)
        self.table.setUniformRowHeights(True)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(COL_NAME, Qt.AscendingOrder)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        for col, width in enumerate(COLUMN_WIDTHS):
            self.table.setColumnWidth(col, width)
        self.table.selectionModel().currentRowChanged.connect(self._on_current)
        self.table.addActions([self.act_copy_name, self.act_copy_nevra])

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
        self.search_mode.setCurrentIndex(int(s.value("search/mode", SEARCH_NAME)))
        self._restore_filter = (s.value("sidebar/view", "status"), s.value("sidebar/entry", "status:all"))

    def _save_settings(self):
        s = QSettings()
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
        self.apply_filter()

    def apply_filter(self):
        if not self.snapshot or not self.filter:
            return
        t0 = time.perf_counter()
        keep = self._current_key()
        pred = self.filter.predicate
        words = self.search.text().lower().split()
        rows = self.snapshot.rows
        if not words:
            visible = [i for i, r in enumerate(rows) if pred(r)]
        elif self.search_mode.currentIndex() == SEARCH_NAME:
            # every word must match (AND); ranked search is M2
            visible = [i for i, r in enumerate(rows) if all(w in r.name.lower() for w in words) and pred(r)]
        else:
            visible = [i for i, r in enumerate(rows)
                       if all(w in r.name.lower() or w in r.summary.lower() for w in words) and pred(r)]
        self.model.set_visible(visible)
        self._update_status(len(visible), (time.perf_counter() - t0) * 1000)
        if not (keep and self._select_key(keep, scroll=True)) and visible:
            self.table.setCurrentIndex(self.model.index(0, COL_NAME))
        elif not visible:
            self.details.clear()

    def _update_status(self, shown: int, ms: float):
        s = self.snapshot
        self.status.setText(
            f"{shown} показано, {s.n_installed} встановлено, {s.n_upgradable} оновлень. "
            f"0 до встановлення/оновлення, 0 до видалення.")
        self.status.setToolTip(f"Каталог: {s.load_seconds:.2f} с, фільтр: {ms:.0f} мс")

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
        self.dnf.submit(lambda: self.catalog.details(row.key), lambda d: self._show_details(row, d))

    def _show_details(self, row: PkgRow, d):
        if row.key == self._details_for:  # ignore stale results when the cursor moved on
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
        m.addActions(self.pkg_actions)
        m.addSeparator()
        m.addActions([self.act_copy_name, self.act_copy_nevra])
        m.addSeparator()
        m.addAction(self.act_properties)
        m.exec(self.table.viewport().mapToGlobal(pos))

    def about(self):
        QMessageBox.about(self, "Про Kram", f"<h3>Kram</h3><p>Менеджер пакунків для Fedora в дусі Synaptic.</p>"
                                           f"<p><a href='{HOMEPAGE}'>{HOMEPAGE}</a></p>")
