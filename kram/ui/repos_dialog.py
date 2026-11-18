"""Settings → Repositories: enable/disable configured repositories, show their packages, remove the user's own."""
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
    QMessageBox,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..core.model import RepoInfo
from ..core.repo_files import Removal, removal
from ..i18n import _, ngettext
from .files import show_in_file_manager
from .icons import ORIGIN_LABEL, origin_icon

COL_ENABLED, COL_ID, COL_NAME, COL_PACKAGES, COL_PRIORITY, COL_ORIGIN, COL_FILE = range(7)
AUX_SUFFIXES = ("-debuginfo", "-source", "-debugsource")
NAME_MIN = 140  # px: the name gives way first, but stays readable
FILE_MIN = 220  # px: the path is cut in the middle below this, to start with
MIN_COLUMN = 40  # px: the least the user can drag a column to
FIT_MARGIN = 24  # px: cell padding on top of the text
COLUMN_PAD = 14  # px added to a column that fits its contents: the measure leaves out an icon's margin


class ReposDialog(QDialog):
    def __init__(self, repos: list[RepoInfo], counts: Counter, parent=None, *, owners: dict[str, str] | None = None,
                 listed: Counter | None = None, installed: Counter | None = None):
        """`counts`: available packages per repo; `owners`: .repo file -> the package that owns it; `listed`: rows
        of the package list per repo (its Origin filter); `installed`: installed packages per repo they came from.

        After exec(), `show_repo` or `remove_repos` says what the user asked for instead of applying changes."""
        super().__init__(parent)
        self.setWindowTitle(_("Repositories"))
        self.resize(1180, 620)
        self._original = {r.id: r.enabled for r in repos}
        self._repos = {r.id: r for r in repos}
        self._owners = owners or {}
        self._listed = listed or Counter()
        self._installed = installed or Counter()
        self.show_repo: str | None = None
        self.remove_repos: list[str] = []

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

        t = self.table = QTableWidget(len(repos), 7)
        t.setHorizontalHeaderLabels([_("Enabled"), _("ID"), _("Name"), _("Packages"), _("Priority"), _("Origin"),
                                     _("File")])
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
        for i, r in enumerate(sorted(repos, key=lambda r: (not r.enabled, r.id))):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            check.setCheckState(Qt.CheckState.Checked if r.enabled else Qt.CheckState.Unchecked)
            check.setData(Qt.ItemDataRole.UserRole, r.id)
            t.setItem(i, COL_ENABLED, check)
            t.setItem(i, COL_ID, self._item(r.id))
            t.setItem(i, COL_NAME, self._item(r.name))
            if r.enabled and r.age_seconds is None:
                packages = QTableWidgetItem("—")
                packages.setToolTip(_("No metadata yet: use Reload"))
            else:
                packages = QTableWidgetItem(str(counts.get(r.id, 0)) if r.enabled else "")
            packages.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            t.setItem(i, COL_PACKAGES, packages)
            prio = QTableWidgetItem(str(r.priority))
            prio.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            t.setItem(i, COL_PRIORITY, prio)
            origin = QTableWidgetItem(origin_icon(r.origin), ORIGIN_LABEL[r.origin])
            t.setItem(i, COL_ORIGIN, origin)
            t.setItem(i, COL_FILE, self._item(r.file_path))
        # the narrow columns fit what they show; the name and the path get their start sizes in _fit_columns
        t.resizeColumnsToContents()
        for col in (COL_ENABLED, COL_ID, COL_PACKAGES, COL_PRIORITY, COL_ORIGIN):
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
        t.itemChanged.connect(self._update_buttons)
        t.itemSelectionChanged.connect(self._update_buttons)
        lay.addWidget(t, 1)

        row = QHBoxLayout()
        self.packages_btn = QPushButton(QIcon.fromTheme("view-list-details"), _("Show packages"))
        # bound methods, not lambdas: a lambda holding self keeps a parentless dialog alive until PySide6's cleanup at
        # exit, which then deletes its widgets in the wrong order and crashes (seen with PySide6 6.12 on rawhide)
        self.packages_btn.clicked.connect(self._show_selected_packages)
        self.remove_btn = QPushButton(QIcon.fromTheme("edit-delete"), _("Remove…"))
        self.remove_btn.clicked.connect(self._remove_selected)
        row.addWidget(self.packages_btn)
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
        others = sum(t.columnWidth(c) for c in (COL_ENABLED, COL_ID, COL_PACKAGES, COL_PRIORITY, COL_ORIGIN))
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
                              lambda: self._show_packages(repo_id))
        show.setEnabled(self._packages_blocker(repo_id) is None)
        remove = menu.addAction(QIcon.fromTheme("edit-delete"), _("Remove Repository…"), lambda: self._remove(repo_id))
        remove.setEnabled(self._removal_blocker(repo_id) is None)
        if path := self._repos[repo_id].file_path:
            menu.addSeparator()
            for text, action in self._file_actions(path):
                menu.addAction(text, action)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------ show packages, remove

    def _selected_id(self) -> str | None:
        rows = self.table.selectionModel().selectedRows()
        return self.table.item(rows[0].row(), COL_ENABLED).data(Qt.ItemDataRole.UserRole) if rows else None

    def _show_selected_packages(self) -> None:
        self._show_packages(self._selected_id())

    def _remove_selected(self) -> None:
        self._remove(self._selected_id())

    def _packages_blocker(self, repo_id: str) -> str | None:
        """Why the repository's packages cannot be shown now; None if they can."""
        if self.changes():
            return _("Apply or undo the changes first.")
        if not self._listed.get(repo_id):
            return _("None of its packages are in the list.")
        return None

    def _removal_blocker(self, repo_id: str) -> str | None:
        """Why the repository cannot be removed; None if it can."""
        if self.changes():
            return _("Apply or undo the changes first.")
        path = self._repos[repo_id].file_path
        match removal(path, self._owners.get(path)):
            case Removal.OWNED:
                return _("The .repo file is part of the installed package {package}.").format(package=self._owners[path])
            case Removal.SYSTEM:
                return _("Configured by the system.")
            case Removal.NO_FILE:
                return _("Not configured in a file.")
        return None

    def _show_packages(self, repo_id: str | None) -> None:
        if repo_id is not None and self._packages_blocker(repo_id) is None:
            self.show_repo = repo_id
            self.reject()  # nothing to apply: the main window shows the packages

    def _remove(self, repo_id: str | None) -> None:
        if repo_id is None or self._removal_blocker(repo_id) is not None:
            return
        path = self._repos[repo_id].file_path
        in_file = sorted((r for r in self._repos.values() if r.file_path == path), key=lambda r: r.id)
        n = sum(self._installed.get(r.id, 0) for r in in_file)
        if len(in_file) == 1:
            text = _("Remove the repository {repo} from the system?").format(repo=repo_id)
            lines = [_("Its file {path} will be deleted.").format(path=path)]
        else:
            text = ngettext("The file {path} configures {n} repository. Remove it from the system?",
                            "The file {path} configures {n} repositories. Remove them all from the system?",
                            len(in_file)).format(path=path, n=len(in_file))
            lines = ["\n".join(f"• {r.id} — {r.name}" for r in in_file)]
        if n:
            lines.append(ngettext(
                "{n} installed package comes from it. It stays installed but will no longer get updates "
                "(it will show as orphaned).",
                "{n} installed packages come from it. They stay installed but will no longer get updates "
                "(they will show as orphaned).", n).format(n=n) if len(in_file) == 1 else ngettext(
                "{n} installed package comes from them. It stays installed but will no longer get updates "
                "(it will show as orphaned).",
                "{n} installed packages come from them. They stay installed but will no longer get updates "
                "(they will show as orphaned).", n).format(n=n))
        box = QMessageBox(QMessageBox.Icon.Question, _("Remove repository"), text, parent=self)
        box.setInformativeText("\n\n".join(lines))
        remove = box.addButton(_("Remove"), QMessageBox.ButtonRole.DestructiveRole)
        show = (box.addButton(_("Show packages"), QMessageBox.ButtonRole.ActionRole)
                if n and self._packages_blocker(repo_id) is None else None)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        if box.clickedButton() is remove:
            self.remove_repos = [r.id for r in in_file]
            self.reject()  # nothing to apply: the main window runs the removal
        elif show is not None and box.clickedButton() is show:
            self._show_packages(repo_id)

    def changes(self) -> dict[str, bool]:
        """Repo id -> new enabled state, only for repos the user toggled."""
        out = {}
        for i in range(self.table.rowCount()):
            item = self.table.item(i, COL_ENABLED)
            repo_id = item.data(Qt.ItemDataRole.UserRole)
            enabled = item.checkState() == Qt.CheckState.Checked
            if enabled != self._original[repo_id]:
                out[repo_id] = enabled
        return out

    def _update_buttons(self, *_args):
        n = len(self.changes())
        self.apply_btn.setEnabled(n > 0)
        repo_id = self._selected_id()
        for button, blocker in ((self.packages_btn, self._packages_blocker), (self.remove_btn, self._removal_blocker)):
            why = blocker(repo_id) if repo_id is not None else None
            button.setEnabled(repo_id is not None and why is None)
            button.setToolTip(why or "")
        self.summary.setText(ngettext("{n} repository will change.", "{n} repositories will change.", n).format(n=n)
                             if n else "")

    def _apply_filter(self, *_args):
        needle = self.filter.text().strip().lower()
        for i in range(self.table.rowCount()):
            repo_id = self.table.item(i, COL_ID).text()
            name = self.table.item(i, COL_NAME).text()
            hidden = (not self.show_aux.isChecked() and repo_id.endswith(AUX_SUFFIXES)
                      or bool(needle) and needle not in repo_id.lower() and needle not in name.lower())
            self.table.setRowHidden(i, hidden)


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
