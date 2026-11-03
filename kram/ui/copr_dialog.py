"""Settings → COPR: the enabled projects, and search/enable new ones via the Copr API."""
import json
from collections import Counter
from collections.abc import Callable

from PySide6.QtCore import Qt, QUrl, QUrlQuery, Signal
from PySide6.QtGui import QBrush, QColor, QIcon
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..core.copr import DEFAULT_HUB, PROJECT_RE, SEARCH_URL, CoprProject, parse_repo_id, parse_search, rank
from ..core.model import CatalogSnapshot
from ..i18n import _, ngettext

# the Copr search API routinely takes 10-20 s to answer, whatever the result size
SEARCH_TIMEOUT_MS = 60000
SEARCH_LIMIT = 50


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
        self._run_helper = run_helper
        self._snap: CatalogSnapshot | None = None
        self._projects: list[tuple[str, str, str]] = []  # (repo id, hub, project) for the top table
        self._results: list[CoprProject] = []
        self._net = QNetworkAccessManager(self)
        self._reply: QNetworkReply | None = None

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"<b>{_('Enabled projects')}</b>"))
        t = self.enabled_table = QTableWidget(0, 5)
        t.setHorizontalHeaderLabels([_("Enabled"), _("Project"), _("Hub"), _("Packages"), _("Installed")])
        t.verticalHeader().hide()
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setSelectionMode(QAbstractItemView.SingleSelection)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
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
        self.enable_btn.clicked.connect(lambda: self._change_selected("enable"))
        self.disable_btn.clicked.connect(lambda: self._change_selected("disable"))
        self.remove_btn.clicked.connect(self._remove_selected)
        self.packages_btn.clicked.connect(self._show_selected_packages)
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
        self.query.returnPressed.connect(self._search)
        self.query.textChanged.connect(self._update_buttons)
        row.addWidget(self.query, 1)
        self.search_btn = QPushButton(QIcon.fromTheme("edit-find"), _("Search Copr"))
        self.search_btn.clicked.connect(self._search)
        row.addWidget(self.search_btn)
        lay.addLayout(row)

        r = self.results_table = QTableWidget(0, 3)
        r.setHorizontalHeaderLabels([_("Project"), _("Description"), _("Builds for this system")])
        r.verticalHeader().hide()
        r.setSelectionBehavior(QAbstractItemView.SelectRows)
        r.setSelectionMode(QAbstractItemView.SingleSelection)
        r.setEditTriggers(QAbstractItemView.NoEditTriggers)
        r.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        r.setColumnWidth(0, 260)
        r.setColumnWidth(2, 180)
        r.itemSelectionChanged.connect(self._update_buttons)
        r.doubleClicked.connect(lambda _i: self._enable_result())
        lay.addWidget(r, 1)

        self.search_status = QLabel()
        lay.addWidget(self.search_status)
        note = QLabel("ⓘ " + _("COPR projects are built by community members and are not reviewed by Fedora."))
        note.setEnabled(False)  # rendered in the palette's dim colour
        lay.addWidget(note)

        buttons = QDialogButtonBox()
        self.add_btn = buttons.addButton(_("Enable selected"), QDialogButtonBox.ActionRole)
        self.add_btn.setIcon(QIcon.fromTheme("list-add"))
        self.add_btn.clicked.connect(self._enable_result)
        buttons.addButton(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self._update_buttons()

    # ---------------------------------------------------------------- enabled projects

    def set_catalog(self, snap: CatalogSnapshot, counts: Counter) -> None:
        self._snap = snap
        installed = Counter(r.origin_repo for r in snap.rows if r.installed)
        coprs = []
        for repo in snap.repos:
            ref = parse_repo_id(repo.id)
            if ref is not None:
                coprs.append((repo, ref))
        coprs.sort(key=lambda c: c[1].project.lower())
        self._projects = [(repo.id, ref.hub, ref.project) for repo, ref in coprs]
        t = self.enabled_table
        t.setRowCount(len(coprs))
        right = Qt.AlignRight | Qt.AlignVCenter
        for i, (repo, ref) in enumerate(coprs):
            state = QTableWidgetItem("✓" if repo.enabled else "")
            state.setTextAlignment(Qt.AlignCenter)
            t.setItem(i, 0, state)
            t.setItem(i, 1, _item(ref.project))
            t.setItem(i, 2, _item(ref.hub))
            t.setItem(i, 3, _item(str(counts.get(repo.id, 0)) if repo.enabled else "", right))
            t.setItem(i, 4, _item(str(installed.get(repo.id, 0)), right))
        self._update_buttons()
        self._fill_results()  # "already enabled" markers depend on the projects list

    def _selected_project(self) -> tuple[str, str, str] | None:
        rows = self.enabled_table.selectionModel().selectedRows()
        return self._projects[rows[0].row()] if rows else None

    def _installed_from(self, repo_id: str) -> int:
        return sum(1 for r in self._snap.rows if r.installed and r.origin_repo == repo_id) if self._snap else 0

    def _change_selected(self, action: str) -> None:
        sel = self._selected_project()
        if sel:
            _repo_id, hub, project = sel
            self._copr(action, project, hub)

    def _remove_selected(self) -> None:
        sel = self._selected_project()
        if not sel:
            return
        repo_id, hub, project = sel
        n = self._installed_from(repo_id)
        box = QMessageBox(QMessageBox.Question, _("Remove COPR project"),
                          _("Remove the {project} repository from the system?").format(project=project), parent=self)
        if n:
            box.setInformativeText(ngettext(
                "{n} installed package comes from it. It stays installed but will no longer get updates "
                "(it will show as orphaned).",
                "{n} installed packages come from it. They stay installed but will no longer get updates "
                "(they will show as orphaned).", n).format(n=n))
        remove = box.addButton(_("Remove"), QMessageBox.DestructiveRole)
        show = box.addButton(_("Show packages"), QMessageBox.ActionRole) if n else None
        box.addButton(QMessageBox.Cancel)
        box.exec()
        if box.clickedButton() is remove:
            self._copr("remove", project, hub)
        elif show is not None and box.clickedButton() is show:
            self.showPackages.emit(repo_id)

    def _show_selected_packages(self) -> None:
        sel = self._selected_project()
        if sel:
            self.showPackages.emit(sel[0])

    def _copr(self, action: str, project: str, hub: str) -> None:
        titles = {"enable": _("Enabling {project}"), "disable": _("Disabling {project}"),
                  "remove": _("Removing {project}")}
        request = {"op": "copr", "action": action, "project": project}
        if hub != DEFAULT_HUB:
            request["hub"] = hub
        self._run_helper(request, titles[action].format(project=project))

    # ---------------------------------------------------------------- search

    def _search(self) -> None:
        text = self.query.text().strip()
        if not text:
            return
        if self._reply is not None:
            self._reply.abort()
        url = QUrl(SEARCH_URL.format(hub=DEFAULT_HUB))
        q = QUrlQuery()
        q.addQueryItem("query", text)
        q.addQueryItem("limit", str(SEARCH_LIMIT))
        url.setQuery(q)
        req = QNetworkRequest(url)
        req.setTransferTimeout(SEARCH_TIMEOUT_MS)
        self.search_status.setText(_("Searching… Copr can take up to a minute to answer."))
        self.search_btn.setEnabled(False)
        reply = self._reply = self._net.get(req)
        reply.finished.connect(lambda: self._on_search_done(reply, text))

    def _on_search_done(self, reply: QNetworkReply, text: str) -> None:
        reply.deleteLater()
        if reply is not self._reply:  # superseded by a newer search
            return
        self._reply = None
        self.search_btn.setEnabled(True)
        if reply.error() != QNetworkReply.NoError:
            if reply.error() != QNetworkReply.OperationCanceledError:
                self.search_status.setText(_("Search failed: {error}").format(error=reply.errorString()))
            return
        try:
            results = parse_search(json.loads(bytes(reply.readAll())))
        except (ValueError, AttributeError):
            self.search_status.setText(_("Search failed: unexpected answer from Copr"))
            return
        self._results = results = rank(results, text)
        self._fill_results()
        n = len(results)
        self.search_status.setText(ngettext("{n} project found.", "{n} projects found.", n).format(n=n))
        if results:
            self.results_table.selectRow(0)

    def _fill_results(self) -> None:
        if self._snap is None:
            return
        enabled = {project.lower() for _id, hub, project in self._projects if hub == DEFAULT_HUB}
        chroot = f"fedora-{self._snap.releasever}-{self._snap.basearch}"
        r = self.results_table
        r.setRowCount(len(self._results))
        for i, p in enumerate(self._results):
            name = _item(p.full_name)
            if p.full_name.lower() in enabled:
                name.setText(p.full_name + "  " + _("(enabled)"))
            r.setItem(i, 0, name)
            desc = _item(p.description)
            desc.setToolTip(p.description + (f"\n\n{p.homepage}" if p.homepage else ""))
            r.setItem(i, 1, desc)
            ok = p.has_chroot(self._snap.releasever, self._snap.basearch)
            state = _item(("✓ " if ok else "✗ ") + chroot)
            if not ok:
                state.setForeground(QBrush(QColor("#c03030")))
                state.setToolTip(_("Builds exist for: {chroots}").format(chroots=", ".join(p.chroots) or "—"))
            r.setItem(i, 2, state)
        self._update_buttons()

    def _selected_result(self) -> CoprProject | None:
        rows = self.results_table.selectionModel().selectedRows()
        return self._results[rows[0].row()] if rows and rows[0].row() < len(self._results) else None

    def _enable_result(self) -> None:
        p = self._selected_result()
        if p is None:
            text = self.query.text().strip()  # allow enabling a typed owner/project without searching
            if PROJECT_RE.match(text):
                self._copr("enable", text, DEFAULT_HUB)
            return
        snap = self._snap
        if snap and not p.has_chroot(snap.releasever, snap.basearch) and QMessageBox.question(
                self, _("No builds for this system"),
                _("{project} has no builds for Fedora {release} ({arch}). Enable it anyway?").format(
                    project=p.full_name, release=snap.releasever, arch=snap.basearch)) != QMessageBox.Yes:
            return
        self._copr("enable", p.full_name, DEFAULT_HUB)

    def _update_buttons(self) -> None:
        sel = self._selected_project()
        enabled = bool(sel) and self.enabled_table.item(
            self.enabled_table.selectionModel().selectedRows()[0].row(), 0).text() == "✓"
        self.enable_btn.setEnabled(bool(sel) and not enabled)
        self.disable_btn.setEnabled(bool(sel) and enabled)
        self.remove_btn.setEnabled(bool(sel))
        self.packages_btn.setEnabled(bool(sel))
        typed = bool(PROJECT_RE.match(self.query.text().strip()))
        self.add_btn.setEnabled(self._selected_result() is not None or typed)
