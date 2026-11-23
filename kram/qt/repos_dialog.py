"""Settings → Repositories (kram.app.repos): enable/disable configured repositories, show their packages, remove the user's own."""
from collections import Counter

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFontMetrics, QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..app.repos import Repos, ReposData, matches
from ..core.model import RepoInfo
from ..i18n import _
from .files import show_in_file_manager
from .icons import icon
from .qt_ui import QtUi

COL_ENABLED, COL_ID, COL_NAME, COL_PACKAGES, COL_PRIORITY, COL_ORIGIN, COL_MIRROR, COL_FILE = range(8)
NAME_MIN = 140  # px: the name gives way first, but stays readable
FILE_MIN = 220  # px: the path is cut in the middle below this, to start with
MIN_COLUMN = 40  # px: the least the user can drag a column to
FIT_MARGIN = 24  # px: cell padding on top of the text
COLUMN_PAD = 14  # px added to a column that fits its contents: the measure leaves out an icon's margin


class ReposDialog(QDialog):
    def __init__(self, repos: list[RepoInfo], counts: Counter, parent=None, *, owners: dict[str, str] | None = None,
                 listed: Counter | None = None, installed: Counter | None = None,
                 variables: dict[str, str] | None = None, on_remove=None, on_mirrors=None):
        """The arguments are those of kram.app.repos.ReposData; `on_remove` and `on_mirrors` those of Repos: they run
        while the dialog stays open, and `set_data` then shows the new state. After exec(), `show_repo` says whether
        the user asked to see a repository's packages instead of applying changes."""
        super().__init__(parent)
        self.setWindowTitle(_("Repositories"))
        self.resize(1300, 620)
        self.repos = Repos(repos, counts, QtUi(self), self, owners=owners, listed=listed, installed=installed,
                           variables=variables, on_remove=on_remove, on_mirrors=on_mirrors)

        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.filter = QLineEdit()
        self.filter.setPlaceholderText(_("Filter…"))
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._apply_filter)
        top.addWidget(self.filter, 1)
        self.show_aux = QCheckBox(_("Show debuginfo and source repositories"))
        self.show_aux.toggled.connect(self._apply_filter)
        top.addWidget(self.show_aux)
        lay.addLayout(top)

        t = self.table = QTableWidget(0, 8)
        t.setHorizontalHeaderLabels([_("Enabled"), _("ID"), _("Name"), _("Packages"), _("Priority"), _("Origin"),
                                     _("Mirror"), _("File")])
        t.verticalHeader().hide()
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setSortingEnabled(False)
        middle = _MiddleElide(t)  # a long id or path keeps both its start and its end
        for col in (COL_ID, COL_NAME, COL_FILE):
            t.setItemDelegateForColumn(col, middle)
        t.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        t.customContextMenuRequested.connect(self._context_menu)
        self._fill()
        # the narrow columns fit what they show; the name and the path get their start sizes in _fit_columns
        t.resizeColumnsToContents()
        for col in (COL_ENABLED, COL_ID, COL_PACKAGES, COL_PRIORITY, COL_ORIGIN, COL_MIRROR):
            t.setColumnWidth(col, t.columnWidth(col) + COLUMN_PAD)
        # every column can be dragged, and what does not fit scrolls sideways; the sizes below are only a start: they
        # follow the window until the user resizes a column himself, and are then left alone
        header = t.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(MIN_COLUMN)
        t.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._fitting = False
        self._user_sized = False
        header.sectionResized.connect(self._section_resized)
        t.itemChanged.connect(self._on_item_changed)
        t.itemSelectionChanged.connect(self._update_buttons)
        lay.addWidget(t, 1)

        row = QHBoxLayout()
        self.packages_btn = QPushButton(QIcon.fromTheme("view-list-details"), _("Show packages"))
        # bound methods, not lambdas: a lambda holding self keeps a parentless dialog alive until PySide6's cleanup at
        # exit, which then deletes its widgets in the wrong order and crashes (seen with PySide6 6.12 on rawhide)
        self.packages_btn.clicked.connect(self._show_selected_packages)
        self.remove_btn = QPushButton(QIcon.fromTheme("edit-delete"), _("Remove…"))
        self.remove_btn.clicked.connect(self._remove_selected)
        self.mirrors_btn = QPushButton(QIcon.fromTheme("network-server"), _("Mirrors…"))
        self.mirrors_btn.clicked.connect(self._show_selected_mirrors)
        row.addWidget(self.packages_btn)
        row.addWidget(self.mirrors_btn)
        row.addWidget(self.remove_btn)
        row.addStretch()
        lay.addLayout(row)

        self.summary = QLabel()
        lay.addWidget(self.summary)
        self.buttons = QDialogButtonBox()
        self.apply_btn = self.buttons.addButton(_("Apply changes"), QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.addButton(QDialogButtonBox.StandardButton.Close)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)
        self._apply_filter()
        self._update_buttons()

    def _fill(self) -> None:
        t = self.table
        t.blockSignals(True)  # no itemChanged while the checkboxes are filled
        t.setRowCount(0)
        lines = self.repos.lines()
        t.setRowCount(len(lines))
        for i, line in enumerate(lines):
            r = line.repo
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            check.setCheckState(Qt.CheckState.Checked if r.enabled else Qt.CheckState.Unchecked)
            check.setData(Qt.ItemDataRole.UserRole, r.id)
            t.setItem(i, COL_ENABLED, check)
            t.setItem(i, COL_ID, self._item(r.id))
            t.setItem(i, COL_NAME, self._item(r.name))
            packages = QTableWidgetItem(line.packages)
            if line.packages_tip:
                packages.setToolTip(line.packages_tip)
            packages.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            t.setItem(i, COL_PACKAGES, packages)
            prio = QTableWidgetItem(line.priority)
            prio.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            t.setItem(i, COL_PRIORITY, prio)
            t.setItem(i, COL_ORIGIN, QTableWidgetItem(icon(line.origin_icon), line.origin))
            mirror = self._item(line.mirror)
            if line.mirror_tip:
                mirror.setToolTip(line.mirror_tip)
            t.setItem(i, COL_MIRROR, mirror)
            t.setItem(i, COL_FILE, self._item(r.file_path))
        t.blockSignals(False)

    def set_data(self, data: ReposData) -> None:
        """Show the repositories as they are now: after a removal or a mirror change made from the dialog."""
        selected = self._selected_id()
        self.repos.update(data)
        self._fill()
        for i in range(self.table.rowCount()):
            if self.table.item(i, COL_ENABLED).data(Qt.ItemDataRole.UserRole) == selected:
                self.table.selectRow(i)
        self._apply_filter()
        self._update_buttons()

    @staticmethod
    def _item(text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setToolTip(text)  # in full, whatever is left of it on screen
        return item

    def _section_resized(self, _column: int, _old: int, _new: int) -> None:
        if not self._fitting:
            self._user_sized = True

    def _fit_columns(self) -> None:
        """A start that needs no scrolling: the path is as wide as its longest path, or as wide as the window leaves
        it (never under FILE_MIN), and the name gets the rest. Not once the user has resized a column."""
        if self._user_sized:
            return
        t = self.table
        wanted = t.sizeHintForColumn(COL_FILE) + FIT_MARGIN
        others = sum(t.columnWidth(c) for c in (COL_ENABLED, COL_ID, COL_PACKAGES, COL_PRIORITY, COL_ORIGIN, COL_MIRROR))
        free = t.viewport().width() - others
        path = max(FILE_MIN, min(wanted, free - NAME_MIN))
        self._fitting = True
        try:
            t.setColumnWidth(COL_FILE, path)
            t.setColumnWidth(COL_NAME, max(NAME_MIN, free - path))
        finally:
            self._fitting = False

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._fit_columns()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # after the layout has given the table its new size; tied to the dialog, so it does not outlive it
        QTimer.singleShot(0, self, self._fit_columns)

    # ------------------------------------------------------------ the path's menu

    def _file_actions(self, path: str) -> list[tuple[str, object]]:
        return [(_("Copy Path"), lambda: QGuiApplication.clipboard().setText(path)),
                (_("Show in File Manager"), lambda: show_in_file_manager(path))]

    def _context_menu(self, pos) -> None:
        item = self.table.itemAt(pos)
        if item is None:
            return
        repo_id = self.table.item(item.row(), COL_ENABLED).data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        show = menu.addAction(QIcon.fromTheme("view-list-details"), _("Show Packages"),
                              lambda: self.repos.show_packages(repo_id))
        show.setEnabled(self.repos.packages_blocker(repo_id) is None)
        mirrors = menu.addAction(QIcon.fromTheme("network-server"), _("Mirrors…"),
                                 lambda: self.repos.show_mirrors(repo_id))
        mirrors.setEnabled(self.repos.mirrors_action(repo_id).enabled)
        remove = menu.addAction(QIcon.fromTheme("edit-delete"), _("Remove Repository…"),
                                lambda: self.repos.remove(repo_id))
        remove.setEnabled(self.repos.removal_blocker(repo_id) is None)
        if path := self.repos.repos[repo_id].file_path:
            menu.addSeparator()
            for text, action in self._file_actions(path):
                menu.addAction(text, action)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------ show packages, remove

    def _selected_id(self) -> str | None:
        rows = self.table.selectionModel().selectedRows()
        return self.table.item(rows[0].row(), COL_ENABLED).data(Qt.ItemDataRole.UserRole) if rows else None

    def _show_selected_packages(self) -> None:
        self.repos.show_packages(self._selected_id())

    def _remove_selected(self) -> None:
        self.repos.remove(self._selected_id())

    def _show_selected_mirrors(self) -> None:
        self.repos.show_mirrors(self._selected_id())

    # the choice the dialog closed with, for the main window
    show_repo = property(lambda self: self.repos.show_repo)
    remove_repos = property(lambda self: self.repos.remove_repos)  # the last removal asked for
    mirror_repo = property(lambda self: self.repos.mirror_repo)    # the last repository whose mirrors were asked for

    def changes(self) -> dict[str, bool]:
        """Repo id -> new enabled state, only for repos the user toggled."""
        return self.repos.changes()

    def close_with_choice(self) -> None:
        self.reject()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() == COL_ENABLED:
            self.repos.set_enabled(item.data(Qt.ItemDataRole.UserRole), item.checkState() == Qt.CheckState.Checked)
        self._update_buttons()

    def _update_buttons(self, *_args):
        self.apply_btn.setEnabled(bool(self.repos.changes()))
        packages, remove = self.repos.actions(self._selected_id())
        mirrors = self.repos.mirrors_action(self._selected_id())
        for button, state in ((self.packages_btn, packages), (self.remove_btn, remove), (self.mirrors_btn, mirrors)):
            button.setEnabled(state.enabled)
            button.setToolTip(state.tooltip)
        self.summary.setText(self.repos.summary())

    def _apply_filter(self, *_args):
        needle, aux = self.filter.text(), self.show_aux.isChecked()
        for i in range(self.table.rowCount()):
            repo_id = self.table.item(i, COL_ENABLED).data(Qt.ItemDataRole.UserRole)
            self.table.setRowHidden(i, not matches(self.repos.repos[repo_id], needle, aux))


def elide_middle(text: str, width: int, metrics: QFontMetrics) -> str:
    """`text` cut in the middle to fit `width` px: "/etc/yum.repos.d/_cop…nightly.repo".

    Qt's own middle elision of a table cell breaks a long unspaced path at its first "/" and drops the end."""
    return metrics.elidedText(text, Qt.TextElideMode.ElideMiddle, max(width, 0))


class _MiddleElide(QStyledItemDelegate):
    def paint(self, painter, option, index) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        widget = option.widget
        style = widget.style() if widget else QApplication.style()
        # the style pads the text on both sides once more when it draws it
        padding = 2 * (style.pixelMetric(QStyle.PixelMetric.PM_FocusFrameHMargin, opt, widget) + 1)
        room = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, opt, widget).width() - padding
        opt.text = elide_middle(opt.text, room, opt.fontMetrics)
        opt.textElideMode = Qt.TextElideMode.ElideNone  # already done, whole
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)
