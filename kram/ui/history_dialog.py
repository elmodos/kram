"""File → Transaction History: dnf's transactions (`dnf5 history`), their packages, and marking the changes that undo
one of them. A window of its own, not modal: a package of a transaction opens in the main window."""
from datetime import datetime

from PySide6.QtCore import QSettings, Qt, QTimer, Signal
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

from ..core.catalog import Catalog
from ..core.history import (
    Change,
    HistoryRow,
    HistoryTransaction,
    change_counts,
    changes_comps,
    command_label,
    history_rows,
    user_name,
)
from ..core.marks import Action
from ..core.model import ENVIRONMENT_PREFIX, Reason
from ..core.worker import DnfWorker
from ..i18n import _, ngettext, pgettext
from .group_icons import group_icon
from .icons import mark_icon
from .package_model import REASON_LABEL

CHUNK = 25  # transactions whose packages one worker job reads (~5 ms each): other jobs get their turn in between
COL_ID, COL_DATE, COL_CHANGES, COL_USER, COL_COMMAND = range(5)  # the command line can be long: last
COL_ACTION, COL_PACKAGE, COL_VERSION, COL_REPO, COL_REASON = range(5)
ROLE_ID = Qt.ItemDataRole.UserRole
GEOMETRY_KEY = "history/geometry"
SPLITTER_KEY = "history/splitter"

UNDO_TIP = _("Mark the changes that take the packages of this transaction back to where they were. Review them in "
             "the Marked list, then apply them.")
CHANGE_LABEL = {
    Change.INSTALL: pgettext("history", "Install"),
    Change.UPGRADE: pgettext("history", "Upgrade"),
    Change.DOWNGRADE: pgettext("history", "Downgrade"),
    Change.REINSTALL: pgettext("history", "Reinstall"),
    Change.REMOVE: pgettext("history", "Remove"),
    Change.OBSOLETED: pgettext("history", "Obsoleted"),
    Change.REASON: pgettext("history", "Reason change"),
}
# "3 installed, 12 upgraded": the counts of the Changes column
CHANGE_COUNT = {
    Change.INSTALL: _("{n} installed"),
    Change.UPGRADE: _("{n} upgraded"),
    Change.DOWNGRADE: _("{n} downgraded"),
    Change.REINSTALL: _("{n} reinstalled"),
    Change.REMOVE: _("{n} removed"),
    Change.OBSOLETED: _("{n} obsoleted"),
    Change.REASON: _("{n} reasons changed"),
}
CHANGE_ICON_ACTION = {
    Change.INSTALL: Action.INSTALL, Change.UPGRADE: Action.UPGRADE, Change.DOWNGRADE: Action.DOWNGRADE,
    Change.REINSTALL: Action.REINSTALL, Change.REMOVE: Action.REMOVE, Change.OBSOLETED: Action.REMOVE,
}


def counts_text(rows: list[HistoryRow]) -> str:
    """"1 environment, 16 groups; 1042 installed, 5 upgraded"."""
    counts = change_counts(rows)
    envs = sum(1 for r in rows if r.comps == "environment")
    groups = sum(1 for r in rows if r.comps == "group")
    comps = ", ".join(filter(None, (
        ngettext("{n} environment", "{n} environments", envs).format(n=envs) if envs else "",
        ngettext("{n} group", "{n} groups", groups).format(n=groups) if groups else "")))
    packages = ", ".join(CHANGE_COUNT[c].format(n=counts[c]) for c in Change if c in counts)
    if not packages:
        return comps or _("no package changes")
    return f"{comps}; {packages}" if comps else packages


def comps_key(row: HistoryRow) -> str:
    """The GroupInfo.key of a comps row, for its icon."""
    return ENVIRONMENT_PREFIX + row.arch if row.comps == "environment" else row.arch


def change_icon(row: HistoryRow) -> QIcon:
    if row.change is Change.REASON:
        return mark_icon(Action.MARK_USER if row.reason is Reason.USER else Action.MARK_DEP)
    return mark_icon(CHANGE_ICON_ACTION[row.change])


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
        self._dnf, self._catalog = dnf, catalog
        self._transactions: list[HistoryTransaction] = []
        self._rows: dict[int, list[HistoryRow]] = {}   # transaction id -> its packages, as they load
        self._items: dict[int, QTreeWidgetItem] = {}
        self._pending: list[int] = []                  # ids whose packages are still to load
        self._generation = 0                           # drops what a load started before a reload delivers
        self._busy = False                             # Kram is applying changes: no undo meanwhile
        self._can_mark = False                         # the main window has a catalog to mark in

        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.filter = QLineEdit(placeholderText=_("Filter by package name"), clearButtonEnabled=True)
        self.filter.textChanged.connect(self._on_filter_text)
        top.addWidget(self.filter, 1)
        self.state = QLabel()
        top.addWidget(self.state)
        lay.addLayout(top)

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.list = self._tree([_("ID"), _("Date"), _("Changes"), _("User"), _("Command")])
        self.list.currentItemChanged.connect(self._on_current)
        self.packages = self._tree([_("Action"), _("Package"), _("Version"), _("Repository"), _("Reason")])
        self.packages.itemDoubleClicked.connect(self._on_package_double_click)
        self.packages.setToolTip(_("Double-click a package to close the history and show the package in the list"))
        self.splitter.addWidget(self.list)
        self.splitter.addWidget(self.packages)
        lay.addWidget(self.splitter, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        self.undo = QPushButton(QIcon.fromTheme("edit-undo"), _("Mark Changes to Undo"))
        self.undo.setToolTip(UNDO_TIP)
        self.undo.clicked.connect(lambda: self.undoRequested.emit(self._current_id()))
        buttons.addButton(self.undo, QDialogButtonBox.ButtonRole.ActionRole)
        lay.addWidget(buttons)

        settings = QSettings()
        if geometry := settings.value(GEOMETRY_KEY):
            self.restoreGeometry(geometry)
        if sizes := settings.value(SPLITTER_KEY):
            self.splitter.restoreState(sizes)
        else:
            self.splitter.setSizes([400, 300])
        self._update_undo()

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

    # ---------------------------------------------------------------- loading

    def reload(self) -> None:
        """Read the transactions again (after a change was applied, or the first time)."""
        self._generation += 1
        gen = self._generation
        self.state.setText(_("Loading…"))
        self._dnf.submit(self._catalog.history, lambda found: self._on_transactions(gen, found), self._on_error)

    def _on_error(self, error: BaseException) -> None:
        self.state.setText(_("Could not read the history: {error}").format(error=error))

    def _on_transactions(self, gen: int, found: list[HistoryTransaction]) -> None:
        if gen != self._generation:
            return
        current = self._current_id()
        self._transactions = found
        self._rows = {}
        self._items = {}
        self.list.clear()
        users: dict[int, str] = {}
        for t in found:
            if t.user_id not in users:
                users[t.user_id] = user_name(t.user_id)
            item = QTreeWidgetItem([str(t.id), datetime.fromtimestamp(t.start).strftime("%Y-%m-%d %H:%M"), "…",
                                    users[t.user_id], command_label(t.command)])
            item.setData(COL_ID, ROLE_ID, t.id)
            item.setTextAlignment(COL_ID, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            item.setToolTip(COL_COMMAND, "\n\n".join(filter(None, (t.command, t.comment))))
            if not t.ok:
                item.setIcon(COL_ID, QIcon.fromTheme("dialog-error"))
                item.setToolTip(COL_ID, _("The transaction failed or did not finish"))
            self._items[t.id] = item
        self.list.addTopLevelItems(list(self._items.values()))
        for col, width in ((COL_ID, 70), (COL_DATE, 140), (COL_CHANGES, 300), (COL_USER, 90)):
            self.list.setColumnWidth(col, width)
        self._pending = [t.id for t in found]
        target = self._items.get(current) or self.list.topLevelItem(0)
        if target is not None:
            self.list.setCurrentItem(target)
        self._load_next(gen)

    def _load_next(self, gen: int) -> None:
        """Read the packages of the next chunk of transactions, the newest first."""
        if gen != self._generation:
            return
        self._pending = [i for i in self._pending if i not in self._rows]
        if not self._pending:
            self._update_state()
            return
        chunk = self._pending[:CHUNK]
        self._update_state()
        self._dnf.submit(lambda: self._catalog.history_items(chunk), lambda items: self._on_items(gen, items, True),
                         self._on_error)

    def _on_items(self, gen: int, items: dict, chained: bool) -> None:
        if gen != self._generation:
            return
        for tid, found in items.items():
            rows = self._rows[tid] = history_rows(found)
            self._items[tid].setText(COL_CHANGES, counts_text(rows))
        if (cur := self._current_id()) in items:
            self._show_packages(cur)
        self._apply_filter()
        if chained:
            QTimer.singleShot(0, lambda: self._load_next(gen))

    def _update_state(self) -> None:
        left = len([i for i in self._pending if i not in self._rows])
        if left:
            self.state.setText(_("Reading packages: {done} of {total} transactions").format(
                done=len(self._transactions) - left, total=len(self._transactions)))
        elif not self._transactions:
            self.state.setText(_("No transactions recorded"))
        elif self.filter.text().strip():
            shown = sum(1 for item in self._items.values() if not item.isHidden())
            self.state.setText(ngettext("{shown} of {n} transaction", "{shown} of {n} transactions",
                                    len(self._transactions)).format(shown=shown, n=len(self._transactions)))
        else:
            self.state.setText(ngettext("{n} transaction", "{n} transactions", len(self._transactions)).format(
                n=len(self._transactions)))

    # ---------------------------------------------------------------- showing

    def _current_id(self) -> int | None:
        item = self.list.currentItem()
        return item.data(COL_ID, ROLE_ID) if item is not None else None

    def _on_current(self, *_args) -> None:
        tid = self._current_id()
        if tid is not None and tid not in self._rows:
            gen = self._generation
            self._dnf.submit(lambda: self._catalog.history_items([tid]),
                             lambda items: self._on_items(gen, items, False), self._on_error)
        self._show_packages(tid)

    def _show_packages(self, tid: int | None) -> None:
        self.packages.clear()
        rows = self._rows.get(tid, [])
        needle = self.filter.text().strip().lower()
        bold = QFont(self.packages.font())
        bold.setBold(True)
        items = []
        for r in sorted(rows, key=lambda r: (not r.comps, r.comps != "environment")):  # comps first
            if r.comps:
                kind = _("environment") if r.comps == "environment" else _("group")
                item = QTreeWidgetItem([CHANGE_LABEL[r.change], f"{r.name} ({kind})", "", "",
                                        REASON_LABEL.get(r.reason, "")])
                item.setIcon(COL_PACKAGE, group_icon(comps_key(r)))
                item.setToolTip(COL_PACKAGE, r.arch)
                items.append(item)
                continue
            version = f"{r.old_evr} → {r.evr}" if r.old_evr else r.evr
            item = QTreeWidgetItem([CHANGE_LABEL[r.change], f"{r.name}.{r.arch}", version,
                                    r.repo_id, REASON_LABEL.get(r.reason, "")])
            item.setIcon(COL_ACTION, change_icon(r))
            item.setData(COL_ACTION, ROLE_ID, r.key)
            if needle and needle in r.name.lower():
                for col in range(5):
                    item.setFont(col, bold)
            items.append(item)
        self.packages.addTopLevelItems(items)
        for col, width in ((COL_ACTION, 130), (COL_PACKAGE, 300), (COL_VERSION, 300), (COL_REPO, 200)):
            self.packages.setColumnWidth(col, width)
        self._update_undo()

    def _on_filter_text(self) -> None:
        self._apply_filter()
        self._show_packages(self._current_id())  # in bold, the packages that match

    def _apply_filter(self) -> None:
        """Leave the transactions that changed a package whose name contains the text; while their packages are
        still loading, the ones not read yet are hidden."""
        needle = self.filter.text().strip().lower()
        for tid, item in self._items.items():
            rows = self._rows.get(tid)
            item.setHidden(bool(needle) and (rows is None or not any(needle in r.name.lower() for r in rows)))
        current = self.list.currentItem()
        if current is not None and current.isHidden():
            visible = next((i for i in self._items.values() if not i.isHidden()), None)
            self.list.setCurrentItem(visible)
        self._update_state()

    def rows_of(self, tid: int) -> list[HistoryRow] | None:
        """The packages of a transaction, once read."""
        return self._rows.get(tid)

    def show_package_name(self, name: str) -> None:
        """Filter the list by a package's name (Package → Show in History)."""
        self.filter.setText(name)

    def _on_package_double_click(self, item: QTreeWidgetItem, _col: int) -> None:
        self.showPackage.emit(item.data(COL_ACTION, ROLE_ID))

    # ---------------------------------------------------------------- undo

    def set_marking(self, can_mark: bool, busy: bool) -> None:
        """`can_mark`: the main window has a catalog; `busy`: it is applying changes."""
        self._can_mark, self._busy = can_mark, busy
        self._update_undo()

    def _update_undo(self) -> None:
        tid = self._current_id()
        t = next((t for t in self._transactions if t.id == tid), None)
        rows = self._rows.get(tid)
        self.undo.setEnabled(bool(t and t.ok and rows) and self._can_mark and not self._busy)
        if rows and changes_comps(rows):
            self.undo.setText(_("Undo Transaction…"))
            self.undo.setToolTip(_("The transaction changed groups or environments: it is undone as "
                                   "“dnf5 history undo” does, packages and groups together. Kram shows what that "
                                   "does before it runs."))
        else:
            self.undo.setText(_("Mark Changes to Undo"))
            self.undo.setToolTip(UNDO_TIP)

    def closeEvent(self, event) -> None:
        settings = QSettings()
        settings.setValue(GEOMETRY_KEY, self.saveGeometry())
        settings.setValue(SPLITTER_KEY, self.splitter.saveState())
        super().closeEvent(event)
