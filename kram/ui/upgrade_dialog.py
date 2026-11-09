"""The toolbar's "Fedora N" button: what moving to that release would do. Kram itself never upgrades the system."""
import html
import json
import os
import threading

from PySide6.QtCore import QProcess, QUrl, QUrlQuery
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from .. import __version__
from ..core import copr, distro, upgrade_audit
from ..core.model import CatalogSnapshot
from ..core.upgrade_audit import AuditResult
from ..i18n import _
from .package_model import human_size

COPR_TIMEOUT_MS = 30000


def api_request(url: QUrl, timeout_ms: int) -> QNetworkRequest:
    """A request that says what it is. Qt's default User-Agent, "Mozilla/5.0", looks like a browser, and Bodhi answers
    browsers with an HTML bot check instead of JSON."""
    request = QNetworkRequest(url)
    request.setTransferTimeout(timeout_ms)
    request.setHeader(QNetworkRequest.UserAgentHeader, f"Kram/{__version__}")
    request.setRawHeader(b"Accept", b"application/json")
    return request


class UpgradeDialog(QDialog):
    """Kept by the main window for the session, so a finished check is not repeated when it is opened again."""

    def __init__(self, target: int, running: int, running_eol: str, snapshot: CatalogSnapshot, dnf, parent=None):
        super().__init__(parent)
        self.target = target
        self.setWindowTitle(f"Fedora {target}")
        self.resize(760, 600)
        self._dnf = dnf
        self._net = QNetworkAccessManager(self)
        self._waiting = 0
        self._copr_missing: list[str] = []
        self._copr_failed: list[str] = []
        self._copr_total = 0
        self._result_items: list[QTreeWidgetItem] = []
        self.running_check = False
        self._cancel = threading.Event()

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("<b>" + html.escape(_("Fedora {version} is available").format(version=target)) + "</b>"))
        have = _("You have Fedora {version}, supported until {date}.").format(version=running, date=running_eol) \
            if running_eol else _("You have Fedora {version}.").format(version=running)
        info = QLabel(have + " " + _("Kram does not upgrade the system itself."))
        info.setWordWrap(True)
        lay.addWidget(info)

        row = QHBoxLayout()
        notes = html.escape(distro.RELEASE_NOTES_URL.format(version=target), quote=True)
        guide = html.escape(distro.UPGRADE_GUIDE_URL, quote=True)
        links = QLabel(f"<a href='{notes}'>{html.escape(_('Release notes'))}</a> &nbsp; "
                       f"<a href='{guide}'>{html.escape(_('Upgrade guide'))}</a>")
        links.setOpenExternalLinks(True)
        row.addWidget(links, 1)
        self.program = distro.upgrade_program(os.environ.get("XDG_CURRENT_DESKTOP", ""))
        self.open_program = None
        if self.program is not None:
            self.open_program = QPushButton(_("Open {program}").format(program=self.program.name))
            self.open_program.clicked.connect(self._launch_program)
            row.addWidget(self.open_program)
        lay.addLayout(row)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(QAbstractItemView.NoSelection)
        self.copr_item = QTreeWidgetItem(self.tree, [_("COPR projects: checking…")])
        lay.addWidget(self.tree, 1)

        self._intro = _("Check simulates the upgrade and changes nothing on this system. It downloads the "
                        "package lists of Fedora {version} (about 80 MB).").format(version=target)
        self.status = QLabel(self._intro)
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.busy = QProgressBar()
        self.busy.setRange(0, 0)
        self.busy.hide()
        lay.addWidget(self.busy)

        buttons = QDialogButtonBox(QDialogButtonBox.Close | QDialogButtonBox.Cancel)
        self.close_button = buttons.button(QDialogButtonBox.Close)
        self.cancel_button = buttons.button(QDialogButtonBox.Cancel)
        self.cancel_button.hide()
        self.cancel_button.clicked.connect(self.cancel_check)
        self.check = buttons.addButton(_("Check"), QDialogButtonBox.ActionRole)
        self.check.clicked.connect(self.start_check)
        buttons.rejected.connect(self.reject)  # no effect during a check, see done()
        lay.addWidget(buttons)

        self._ask_copr(snapshot)

    def done(self, result: int) -> None:
        if not self.running_check:  # Esc and the window's close button too: a check is left with Cancel
            super().done(result)

    def _launch_program(self) -> None:
        QProcess.startDetached(self.program.argv[0], list(self.program.argv[1:]))

    # ---------------------------------------------------------------- COPR

    def _ask_copr(self, snapshot: CatalogSnapshot) -> None:
        arch = snapshot.basearch
        installed = {}
        for r in snapshot.rows:
            if r.installed and r.from_repo_id:
                installed[r.from_repo_id] = installed.get(r.from_repo_id, 0) + 1
        for repo in snapshot.repos:
            ref = copr.parse_repo_id(repo.id) if repo.enabled else None
            if ref is None:
                continue
            self._copr_total += 1
            self._waiting += 1
            owner, _slash, name = ref.project.partition("/")
            url = QUrl(copr.PROJECT_URL.format(hub=ref.hub))
            query = QUrlQuery()
            query.addQueryItem("ownername", owner)
            query.addQueryItem("projectname", name)
            url.setQuery(query)
            reply = self._net.get(api_request(url, COPR_TIMEOUT_MS))
            label = _("{project} ({n} installed)").format(project=ref.project, n=installed.get(repo.id, 0))
            reply.finished.connect(lambda r=reply, chroot=f"fedora-{self.target}-{arch}", text=label:
                                   self._on_copr(r, chroot, text))
        if not self._waiting:
            self._show_copr()

    def _on_copr(self, reply: QNetworkReply, chroot: str, label: str) -> None:
        reply.deleteLater()
        self._waiting -= 1
        try:
            if reply.error() != QNetworkReply.NoError:
                raise ValueError(reply.errorString())
            if chroot not in copr.parse_chroots(json.loads(bytes(reply.readAll()))):
                self._copr_missing.append(label)
        except ValueError:
            self._copr_failed.append(label)
        if not self._waiting:
            self._show_copr()

    def _show_copr(self) -> None:
        if self._copr_missing:
            self.copr_item.setText(0, _("COPR projects without a build for Fedora {version}: {n}").format(
                version=self.target, n=len(self._copr_missing)))
            self._children(self.copr_item, self._copr_missing)
        elif not self._copr_total:
            self.copr_item.setText(0, _("No COPR projects are enabled."))
        elif not self._copr_failed:
            self.copr_item.setText(0, _("Every enabled COPR project has a build for Fedora {version}.").format(
                version=self.target))
        else:
            self.copr_item.setText(0, _("COPR projects: the rest have a build for Fedora {version}.").format(
                version=self.target))
        if self._copr_failed:
            failed = QTreeWidgetItem(self.tree, [_("COPR projects that could not be checked: {n}").format(
                n=len(self._copr_failed))])
            self._children(failed, self._copr_failed)

    @staticmethod
    def _children(parent: QTreeWidgetItem, lines: list[str]) -> None:
        for line in lines:
            QTreeWidgetItem(parent, [line])
        parent.setExpanded(True)

    # ---------------------------------------------------------------- simulation

    def start_check(self) -> None:
        if self.running_check:
            return
        self.running_check = True
        self._cancel.clear()
        self.check.setEnabled(False)
        self.close_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.cancel_button.show()
        self.busy.show()
        self.status.setText(_("Downloading the package lists of Fedora {version}. This can take a while…").format(
            version=self.target))
        version = str(self.target)
        cancel = self._cancel
        self._dnf.submit(lambda: upgrade_audit.simulate(version, cancel), self._show_result, self._on_failed)

    def cancel_check(self) -> None:
        if self.running_check:
            self._cancel.set()
            self.cancel_button.setEnabled(False)
            self.status.setText(_("Cancelling…"))

    def _finished(self) -> None:
        self.running_check = False
        self.check.setEnabled(True)
        self.close_button.setEnabled(True)
        self.cancel_button.hide()
        self.busy.hide()

    def _on_failed(self, error: BaseException) -> None:
        self._finished()
        if isinstance(error, upgrade_audit.Cancelled):
            self.status.setText(self._intro)
            return
        self.status.setText(_("Could not check: {error}").format(error=error))

    def _show_result(self, r: AuditResult) -> None:
        self._finished()
        for item in self._result_items:
            self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(item))
        self._result_items = []
        version = self.target
        self._category(_("Problems that stop the upgrade: {n}"), r.blockers, expanded=True)
        self._category(_("Would be removed: {n}"), r.removed, expanded=True)
        self._category(_("Installed, with no version in Fedora {version}: {n}"), r.orphaned, expanded=False)
        self._category(_("Would be downgraded: {n}"), r.downgrades, expanded=False)
        self._category(_("Repositories with nothing for Fedora {version}: {n}"), r.empty_repos, expanded=True)

        if not r.resolved:
            self.status.setText(_("The upgrade to Fedora {version} cannot be worked out as things are.").format(
                version=version))
            return
        verdict = _("The upgrade works only if packages are removed.") if r.blockers else _("The upgrade works.")
        details = _("Upgrades: {upgrades}, new packages: {installs}. To download: {download}. Needs {needed}, "
                    "free: {free}.").format(upgrades=r.upgrades, installs=r.installs, download=human_size(r.download),
                                            needed=human_size(r.needed), free=human_size(r.free))
        warning = " ⚠ " + _("Not enough free disk space.") if r.free < r.needed else ""
        self.status.setText(f"{verdict} {details}{warning}")

    def _category(self, title: str, lines: list[str], expanded: bool) -> None:
        if not lines:
            return
        item = QTreeWidgetItem(self.tree, [title.format(n=len(lines), version=self.target)])
        self._result_items.append(item)
        for line in lines:
            QTreeWidgetItem(item, [line])
        item.setExpanded(expanded)
