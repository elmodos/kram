"""M0 main window: table + quick name filter + description pane. Full Synaptic layout comes in M1."""
import html
import time

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QSplitter,
    QTextBrowser,
    QToolBar,
    QTreeView,
    QWidget,
)

from ..core.catalog import Catalog
from ..core.model import CatalogSnapshot
from .dnf_thread import DnfThread
from .package_model import COL_NAME, PackageTableModel

COLUMN_WIDTHS = [26, 24, 230, 175, 175, 150, 80]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Менеджер пакунків — dnf-gui")
        self.resize(1320, 860)

        self.dnf = DnfThread(self)
        self.catalog = Catalog()
        self.snapshot: CatalogSnapshot | None = None

        tb = QToolBar()
        tb.setMovable(False)
        tb.setIconSize(QSize(24, 24))
        tb.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        reload_ = tb.addAction(QIcon.fromTheme("view-refresh"), "Перечитати")
        reload_.setShortcut(QKeySequence("Ctrl+R"))
        reload_.triggered.connect(self.reload)
        spacer = QWidget()
        spacer.setSizePolicy(spacer.sizePolicy().Policy.Expanding, spacer.sizePolicy().Policy.Preferred)
        tb.addWidget(spacer)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Пошук за назвою (Ctrl+F)")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(300)
        self.search.addAction(QIcon.fromTheme("edit-find"), QLineEdit.LeadingPosition)
        tb.addWidget(self.search)
        self.addToolBar(tb)
        find = self.addAction("find")
        find.setShortcut(QKeySequence.Find)
        find.triggered.connect(lambda: (self.search.setFocus(), self.search.selectAll()))

        self._debounce = QTimer(self, singleShot=True, interval=150)
        self._debounce.timeout.connect(self.apply_filter)
        self.search.textChanged.connect(self._debounce.start)

        self.model = PackageTableModel(self)
        self.table = QTreeView()
        self.table.setModel(self.model)
        self.table.setRootIsDecorated(False)
        self.table.setUniformRowHeights(True)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        for col, width in enumerate(COLUMN_WIDTHS):
            self.table.setColumnWidth(col, width)
        self.table.selectionModel().currentRowChanged.connect(self.show_details)

        self.details = QTextBrowser()
        self.details.setOpenLinks(False)

        split = QSplitter(Qt.Vertical)
        split.addWidget(self.table)
        split.addWidget(self.details)
        split.setSizes([560, 240])
        self.setCentralWidget(split)

        self.status = QLabel()
        self.statusBar().addWidget(self.status, 1)
        self.reload()

    def reload(self):
        self.status.setText("Завантаження метаданих…")
        self.dnf.submit(self.catalog.load, self.on_loaded, self.on_error)

    def on_loaded(self, snap: CatalogSnapshot):
        self.snapshot = snap
        self.model.set_rows(snap.rows)
        self.apply_filter()

    def on_error(self, e: BaseException):
        self.status.setText(f"Помилка: {e}")

    def apply_filter(self):
        if not self.snapshot:
            return
        t0 = time.perf_counter()
        needle = self.search.text().strip().lower()
        rows = self.snapshot.rows
        if needle:
            # M0 placeholder; ranked multi-field search is M2
            visible = [i for i, r in enumerate(rows) if needle in r.name]
        else:
            visible = list(range(len(rows)))
        self.model.set_visible(visible)
        ms = (time.perf_counter() - t0) * 1000
        s = self.snapshot
        self.status.setText(
            f"{len(visible)} показано, {s.n_installed} встановлено, {s.n_upgradable} оновлень. "
            f"Каталог: {s.load_seconds:.2f} с, фільтр: {ms:.0f} мс")
        if visible:
            self.table.setCurrentIndex(self.model.index(0, COL_NAME))

    def show_details(self, current, _previous):
        if not current.isValid():
            self.details.clear()
            return
        row = self.model.row_at(current)
        self.dnf.submit(lambda: self.catalog.details(row.key), self._render_details)

    def _render_details(self, d: dict):
        e = html.escape
        desc = "".join(f"<p>{e(p)}</p>" for p in d["description"].split("\n\n"))
        reqs = "".join(f"<li>{e(r)}</li>" for r in d["requires"][:40])
        self.details.setHtml(
            f"<h3>{e(d['summary'])}</h3>{desc}"
            f"<p><b>{e(d['nevra'])}</b> · {e(d['license'])} · {e(d['url'])}</p>"
            f"<b>Залежить від:</b><ul>{reqs}</ul>")

    def closeEvent(self, event):
        self.dnf.shutdown()
        super().closeEvent(event)
