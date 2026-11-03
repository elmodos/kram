"""Settings → Repositories: enable/disable configured repositories."""
from collections import Counter

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..core.model import RepoInfo
from ..i18n import _, ngettext
from .icons import ORIGIN_LABEL, origin_icon

COL_ENABLED, COL_ID, COL_NAME, COL_PACKAGES, COL_PRIORITY, COL_ORIGIN, COL_FILE = range(7)
AUX_SUFFIXES = ("-debuginfo", "-source", "-debugsource")


class ReposDialog(QDialog):
    def __init__(self, repos: list[RepoInfo], counts: Counter, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Repositories"))
        self.resize(1180, 620)
        self._original = {r.id: r.enabled for r in repos}

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
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setSortingEnabled(False)
        for i, r in enumerate(sorted(repos, key=lambda r: (not r.enabled, r.id))):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            check.setCheckState(Qt.Checked if r.enabled else Qt.Unchecked)
            check.setData(Qt.UserRole, r.id)
            t.setItem(i, COL_ENABLED, check)
            t.setItem(i, COL_ID, QTableWidgetItem(r.id))
            t.setItem(i, COL_NAME, QTableWidgetItem(r.name))
            if r.enabled and r.age_seconds is None:
                packages = QTableWidgetItem("—")
                packages.setToolTip(_("No metadata yet: use Reload"))
            else:
                packages = QTableWidgetItem(str(counts.get(r.id, 0)) if r.enabled else "")
            packages.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            t.setItem(i, COL_PACKAGES, packages)
            prio = QTableWidgetItem(str(r.priority))
            prio.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            t.setItem(i, COL_PRIORITY, prio)
            origin = QTableWidgetItem(origin_icon(r.origin), ORIGIN_LABEL[r.origin])
            t.setItem(i, COL_ORIGIN, origin)
            t.setItem(i, COL_FILE, QTableWidgetItem(r.file_path))
        header = t.horizontalHeader()
        header.setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        for col, width in ((COL_ENABLED, 70), (COL_ID, 290), (COL_PACKAGES, 80), (COL_PRIORITY, 70),
                           (COL_ORIGIN, 120), (COL_FILE, 260)):
            t.setColumnWidth(col, width)
        t.itemChanged.connect(self._update_buttons)
        lay.addWidget(t, 1)

        self.summary = QLabel()
        lay.addWidget(self.summary)
        self.buttons = QDialogButtonBox()
        self.apply_btn = self.buttons.addButton(_("Apply changes"), QDialogButtonBox.AcceptRole)
        self.buttons.addButton(QDialogButtonBox.Close)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)
        self._apply_filter()
        self._update_buttons()

    def changes(self) -> dict[str, bool]:
        """Repo id -> new enabled state, only for repos the user toggled."""
        out = {}
        for i in range(self.table.rowCount()):
            item = self.table.item(i, COL_ENABLED)
            repo_id = item.data(Qt.UserRole)
            enabled = item.checkState() == Qt.Checked
            if enabled != self._original[repo_id]:
                out[repo_id] = enabled
        return out

    def _update_buttons(self, *_args):
        n = len(self.changes())
        self.apply_btn.setEnabled(n > 0)
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
