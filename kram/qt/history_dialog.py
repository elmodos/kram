"""File → Transaction History (kram.app.history): a window of its own, not modal: a package of a transaction opens
in the main window."""
from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..app.history import History, PackageLine, TransactionLine, UndoButton, failed_tip, undo_tip
from ..core.catalog import Catalog
from ..core.history import HistoryRow
from ..core.worker import DnfWorker
from ..i18n import _
from .icons import icon
from .qt_loop import QtScheduler

COL_ID, COL_DATE, COL_CHANGES, COL_USER, COL_COMMAND = range(5)  # the command line can be long: last
COL_ACTION, COL_PACKAGE, COL_VERSION, COL_REPO, COL_REASON = range(5)
ROLE_ID = Qt.ItemDataRole.UserRole
GEOMETRY_KEY = "history/geometry"
SPLITTER_KEY = "history/splitter"


class HistoryDialog(QDialog):
    """`showPackage`: open this name.arch in the main window. `undoRequested`: mark the changes that undo the
    transaction with this id."""

    showPackage = Signal(object)
    undoRequested = Signal(int)

    def __init__(self, dnf: DnfWorker, catalog: Catalog, parent: QWidget):
        super().__init__(parent)
        self.setWindowTitle(_("Transaction History"))
        self.setWindowFlag(Qt.WindowType.WindowMinMaxButtonsHint)
        self.resize(1100, 720)
        self.history = History(dnf, catalog, QtScheduler(self), self)
        self._items: dict[int, QTreeWidgetItem] = {}

        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.filter = QLineEdit(placeholderText=_("Filter by package name"), clearButtonEnabled=True)
        self.filter.textChanged.connect(self.history.set_filter)
        top.addWidget(self.filter, 1)
        self.state = QLabel()
        top.addWidget(self.state)
        lay.addLayout(top)

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.list = self._tree([_("ID"), _("Date"), _("Changes"), _("User"), _("Command")])
        self.list.currentItemChanged.connect(lambda *_args: self.history.current_changed(self._current_id()))
        self.packages = self._tree([_("Action"), _("Package"), _("Version"), _("Repository"), _("Reason")])
        self.packages.itemDoubleClicked.connect(self._on_package_double_click)
        self.packages.setToolTip(_("Double-click a package to close the history and show the package in the list"))
        self.splitter.addWidget(self.list)
        self.splitter.addWidget(self.packages)
        lay.addWidget(self.splitter, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        self.undo = QPushButton(QIcon.fromTheme("edit-undo"), _("Mark Changes to Undo"))
        self.undo.setToolTip(undo_tip())
        self.undo.clicked.connect(lambda: self.undoRequested.emit(self.history.current))
        buttons.addButton(self.undo, QDialogButtonBox.ButtonRole.ActionRole)
        lay.addWidget(buttons)

        settings = QSettings()
        if geometry := settings.value(GEOMETRY_KEY):
            self.restoreGeometry(geometry)
        if sizes := settings.value(SPLITTER_KEY):
            self.splitter.restoreState(sizes)
        else:
            self.splitter.setSizes([400, 300])
        self.show_undo(self.history.undo_button())

    @staticmethod
    def _tree(headers: list[str]) -> QTreeWidget:
        t = QTreeWidget()
        t.setHeaderLabels(headers)
        t.setRootIsDecorated(False)
        t.setUniformRowHeights(True)
        t.setAlternatingRowColors(True)
        t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        t.header().setStretchLastSection(True)
        t.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        return t

    def reload(self) -> None:
        """Read the transactions again (after a change was applied, or the first time)."""
        self.history.reload()

    def rows_of(self, tid: int) -> list[HistoryRow] | None:
        return self.history.rows_of(tid)

    def show_package_name(self, name: str) -> None:
        """Filter the list by a package's name (Package → Show in History)."""
        self.filter.setText(name)

    def set_marking(self, can_mark: bool, busy: bool) -> None:
        self.history.set_marking(can_mark, busy)

    def _current_id(self) -> int | None:
        item = self.list.currentItem()
        return item.data(COL_ID, ROLE_ID) if item is not None else None

    def _on_package_double_click(self, item: QTreeWidgetItem, _col: int) -> None:
        key = item.data(COL_ACTION, ROLE_ID)
        if key is None:  # a group or environment: it is not a package the list can show
            return
        self.showPackage.emit(key)

    # ---------------------------------------------------------------- HistoryView

    def show_transactions(self, lines: list[TransactionLine]) -> None:
        self._items = {}
        self.list.clear()
        for t in lines:
            item = QTreeWidgetItem([str(t.id), t.date, t.changes, t.user, t.command])
            item.setData(COL_ID, ROLE_ID, t.id)
            item.setTextAlignment(COL_ID, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            item.setToolTip(COL_COMMAND, t.tooltip)
            if t.failed:
                item.setIcon(COL_ID, QIcon.fromTheme("dialog-error"))
                item.setToolTip(COL_ID, failed_tip())
            self._items[t.id] = item
        self.list.addTopLevelItems(list(self._items.values()))
        for col, width in ((COL_ID, 70), (COL_DATE, 140), (COL_CHANGES, 300), (COL_USER, 90)):
            self.list.setColumnWidth(col, width)

    def set_changes(self, tid: int, text: str) -> None:
        self._items[tid].setText(COL_CHANGES, text)

    def set_current(self, tid: int | None) -> None:
        self.list.setCurrentItem(self._items.get(tid))

    def show_packages(self, lines: list[PackageLine]) -> None:
        self.packages.clear()
        bold = QFont(self.packages.font())
        bold.setBold(True)
        items = []
        for line in lines:
            item = QTreeWidgetItem([line.action, line.package, line.version, line.repo, line.reason])
            if line.icon is not None:
                item.setIcon(COL_ACTION if line.key is not None else COL_PACKAGE, icon(line.icon))
            if line.tooltip:
                item.setToolTip(COL_PACKAGE, line.tooltip)
            if line.key is not None:
                item.setData(COL_ACTION, ROLE_ID, line.key)
            if line.bold:
                for col in range(5):
                    item.setFont(col, bold)
            items.append(item)
        self.packages.addTopLevelItems(items)
        for col, width in ((COL_ACTION, 130), (COL_PACKAGE, 300), (COL_VERSION, 300), (COL_REPO, 200)):
            self.packages.setColumnWidth(col, width)

    def set_hidden(self, hidden: set[int]) -> None:
        for tid, item in self._items.items():
            item.setHidden(tid in hidden)

    def show_state(self, text: str) -> None:
        self.state.setText(text)

    def show_undo(self, button: UndoButton) -> None:
        self.undo.setEnabled(button.enabled)
        self.undo.setText(button.text)
        self.undo.setToolTip(button.tooltip)

    def closeEvent(self, event) -> None:
        settings = QSettings()
        settings.setValue(GEOMETRY_KEY, self.saveGeometry())
        settings.setValue(SPLITTER_KEY, self.splitter.saveState())
        super().closeEvent(event)
