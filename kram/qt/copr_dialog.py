"""Settings → COPR (kram.app.copr): the enabled projects, and search/enable new ones via the Copr API."""
from collections import Counter
from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..app.copr import MISSING_BUILD_COLOR, CoprProjects, EnabledProject, ResultLine
from ..core.copr import CoprProject
from ..core.model import CatalogSnapshot
from ..i18n import _
from .qt_loop import post
from .qt_ui import QtUi

RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter


def _item(text: str, align=None) -> QTableWidgetItem:
    it = QTableWidgetItem(text)
    if align is not None:
        it.setTextAlignment(align)
    return it


class CoprDialog(QDialog):
    showPackages = Signal(str)  # repo id: show its packages in the main window

    def __init__(self, run_helper: Callable[[dict, str], bool], parent=None):
        """`run_helper(request, title)` runs a helper request with a progress dialog; True on success."""
        super().__init__(parent)
        self.setWindowTitle(_("COPR repositories"))
        self.resize(940, 680)
        self.copr = CoprProjects(self, QtUi(self), post, run_helper, self.showPackages.emit)

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"<b>{_('Enabled projects')}</b>"))
        t = self.enabled_table = QTableWidget(0, 5)
        t.setHorizontalHeaderLabels([_("Enabled"), _("Project"), _("Hub"), _("Packages"), _("Installed")])
        t.verticalHeader().hide()
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for col, width in ((0, 70), (2, 220), (3, 90), (4, 90)):
            t.setColumnWidth(col, width)
        t.setMaximumHeight(200)
        t.itemSelectionChanged.connect(self._update_buttons)
        lay.addWidget(t)

        row = QHBoxLayout()
        self.enable_btn = QPushButton(QIcon.fromTheme("checkbox"), _("Enable"))
        self.disable_btn = QPushButton(QIcon.fromTheme("dialog-cancel"), _("Disable"))
        self.remove_btn = QPushButton(QIcon.fromTheme("edit-delete"), _("Remove…"))
        self.packages_btn = QPushButton(QIcon.fromTheme("view-list-details"), _("Show packages"))
        self.enable_btn.clicked.connect(lambda: self._with_project(lambda p: self.copr.change(p, "enable")))
        self.disable_btn.clicked.connect(lambda: self._with_project(lambda p: self.copr.change(p, "disable")))
        self.remove_btn.clicked.connect(lambda: self._with_project(self.copr.remove))
        self.packages_btn.clicked.connect(lambda: self._with_project(self.copr.show_packages))
        for b in (self.enable_btn, self.disable_btn, self.remove_btn, self.packages_btn):
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)

        lay.addSpacing(10)
        lay.addWidget(QLabel(f"<b>{_('Add a project')}</b>"))
        row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText(_("owner/project, or words to search for"))
        self.query.setClearButtonEnabled(True)
        self.query.returnPressed.connect(lambda: self.copr.search(self.query.text()))
        self.query.textChanged.connect(self._update_buttons)
        row.addWidget(self.query, 1)
        self.search_btn = QPushButton(QIcon.fromTheme("edit-find"), _("Search Copr"))
        self.search_btn.clicked.connect(lambda: self.copr.search(self.query.text()))
        row.addWidget(self.search_btn)
        lay.addLayout(row)

        r = self.results_table = QTableWidget(0, 3)
        r.setHorizontalHeaderLabels([_("Project"), _("Description"), _("Builds for this system")])
        r.verticalHeader().hide()
        r.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        r.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        r.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        r.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        r.setColumnWidth(0, 260)
        r.setColumnWidth(2, 180)
        r.itemSelectionChanged.connect(self._update_buttons)
        r.doubleClicked.connect(lambda _i: self._enable())
        lay.addWidget(r, 1)

        self.search_status = QLabel()
        lay.addWidget(self.search_status)
        note = QLabel("ⓘ " + _("COPR projects are built by community members and are not reviewed by Fedora."))
        note.setEnabled(False)  # rendered in the palette's dim colour
        lay.addWidget(note)

        buttons = QDialogButtonBox()
        self.add_btn = buttons.addButton(_("Enable selected"), QDialogButtonBox.ButtonRole.ActionRole)
        self.add_btn.setIcon(QIcon.fromTheme("list-add"))
        self.add_btn.clicked.connect(self._enable)
        buttons.addButton(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self._update_buttons()

    def done(self, result: int) -> None:
        self.copr.close()  # deleted after use: results that arrive later are dropped
        super().done(result)

    def set_catalog(self, snap: CatalogSnapshot, counts: Counter) -> None:
        self.copr.set_catalog(snap, counts)

    def _selected_project(self) -> EnabledProject | None:
        rows = self.enabled_table.selectionModel().selectedRows()
        return self.copr.projects[rows[0].row()] if rows else None

    def _with_project(self, fn: Callable[[EnabledProject], None]) -> None:
        if (project := self._selected_project()) is not None:
            fn(project)

    def _selected_result(self) -> CoprProject | None:
        rows = self.results_table.selectionModel().selectedRows()
        results = self.copr.results
        return results[rows[0].row()] if rows and rows[0].row() < len(results) else None

    def _enable(self) -> None:
        self.copr.enable(self._selected_result(), self.query.text())

    def _update_buttons(self) -> None:
        b = self.copr.buttons(self._selected_project(), self._selected_result(), self.query.text())
        self.enable_btn.setEnabled(b.enable)
        self.disable_btn.setEnabled(b.disable)
        self.remove_btn.setEnabled(b.remove)
        self.packages_btn.setEnabled(b.packages)
        self.add_btn.setEnabled(b.add)

    # ---------------------------------------------------------------- CoprView

    def show_projects(self, projects: list[EnabledProject]) -> None:
        t = self.enabled_table
        t.setRowCount(len(projects))
        for i, p in enumerate(projects):
            state = QTableWidgetItem("✓" if p.enabled else "")
            state.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            t.setItem(i, 0, state)
            t.setItem(i, 1, _item(p.project))
            t.setItem(i, 2, _item(p.hub))
            t.setItem(i, 3, _item(p.packages, RIGHT))
            t.setItem(i, 4, _item(p.installed, RIGHT))
        self._update_buttons()

    def show_results(self, results: list[ResultLine]) -> None:
        r = self.results_table
        r.setRowCount(len(results))
        for i, line in enumerate(results):
            r.setItem(i, 0, _item(line.name))
            desc = _item(line.description)
            desc.setToolTip(line.tooltip)
            r.setItem(i, 1, desc)
            state = _item(line.builds)
            if not line.builds_ok:
                state.setForeground(QBrush(QColor(MISSING_BUILD_COLOR)))
                state.setToolTip(line.builds_tip)
            r.setItem(i, 2, state)
        self._update_buttons()

    def show_search_status(self, text: str) -> None:
        self.search_status.setText(text)

    def set_searching(self, on: bool) -> None:
        self.search_btn.setEnabled(not on)

    def select_first_result(self) -> None:
        self.results_table.selectRow(0)
