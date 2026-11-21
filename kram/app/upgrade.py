"""The "Fedora N" button's dialog: what moving to that release would do. Kram itself never upgrades the system.

Two checks: at once, whether every enabled COPR project builds for the new release (Copr's API, through core.net);
on the user's word, a simulation of the whole upgrade on the dnf thread (kram.core.upgrade_audit), which can be
cancelled. The front end draws what `UpgradeCheck` tells its `UpgradeView`."""
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from ..core import copr, net, upgrade_audit
from ..core.mainloop import Post
from ..core.model import CatalogSnapshot
from ..core.upgrade_audit import AuditResult
from ..core.worker import DnfWorker
from ..i18n import N_, _
from .columns import human_size
from .icons import ERROR, INFO, OK, WARN
from .ports import view_ref
from .progress import Bar

COPR_TIMEOUT_S = 30
MAX_SHOWN_NEEDS = 3
# keys of the simulation's reports (upgrade_audit.Report)
AUDIT_MESSAGES = {
    "downloading": N_("Downloading {name}"),
    "downloaded": N_("Downloaded {name} ({size})"),
    "download_failed": N_("Download failed: {error}"),
    "mirror_failure": N_("Mirror unavailable: {url}: {error}"),
    "resolving": N_("Working out the upgrade…"),
    "retry_erasing": N_("It does not work as it is. Trying again with removing packages allowed…"),
    "cleanup": N_("Deleting the downloaded package lists…"),
}




@dataclass(frozen=True)
class Finding:
    """A line of the findings, with its mark (kram.app.icons OK / WARN / ERROR / INFO) and the lines under it."""
    kind: str | None
    title: str
    lines: tuple[str, ...] = ()
    expanded: bool = True


class UpgradeView(Protocol):
    def show_copr(self, finding: Finding, failed: Finding | None) -> None:
        """The COPR line (it replaces "checking…"), and the projects that could not be asked."""
        ...

    def show_findings(self, findings: list[Finding]) -> None:
        """The simulation's findings, under the COPR lines; they replace those of an earlier check."""
        ...

    def show_status(self, text: str) -> None: ...

    def set_running(self, running: bool) -> None:
        """A check runs: Cancel instead of Check, Close off, the busy bar and the log shown (and the log cleared
        when it starts)."""
        ...

    def set_cancelling(self) -> None:
        """Cancel was pressed: it is off now."""
        ...

    def show_progress(self, bar: Bar) -> None: ...

    def append_log(self, line: str) -> None: ...


def intro(target: int) -> str:
    return _("Check simulates the upgrade and changes nothing on this system. It downloads the package lists of "
             "Fedora {version} (about 80 MB).").format(version=target)


def have_text(running: int, running_eol: str) -> str:
    have = _("You have Fedora {version}, supported until {date}.").format(version=running, date=running_eol) \
        if running_eol else _("You have Fedora {version}.").format(version=running)
    return have + " " + _("Kram does not upgrade the system itself.")


class UpgradeCheck:
    def __init__(self, target: int, dnf: DnfWorker, post: Post, view: UpgradeView,
                 now: Callable[[], datetime] = datetime.now):
        self.target = target
        self._dnf, self._post, self._view, self._now = dnf, post, view_ref(view), now
        self._waiting = 0
        self._copr_missing: list[str] = []
        self._copr_failed: list[str] = []
        self._copr_total = 0
        self.running = False
        self._cancel = threading.Event()

    # ---------------------------------------------------------------- COPR

    def ask_copr(self, snapshot: CatalogSnapshot) -> None:
        arch = snapshot.basearch
        installed: dict[str, int] = {}
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
            label = _("{project} ({n} installed)").format(project=ref.project, n=installed.get(repo.id, 0))
            chroot = f"fedora-{self.target}-{arch}"
            net.fetch_json(copr.PROJECT_URL.format(hub=ref.hub), params={"ownername": owner, "projectname": name},
                           timeout_s=COPR_TIMEOUT_S, post=self._post,
                           done=lambda payload, c=chroot, text=label: self.on_copr(c, text, payload),
                           failed=lambda error, c=chroot, text=label: self.on_copr(c, text, error))
        if not self._waiting:
            self._show_copr()

    def on_copr(self, chroot: str, label: str, answer: object) -> None:
        """`answer`: the project's JSON, or the net.NetError that came instead."""
        self._waiting -= 1
        try:
            if isinstance(answer, net.NetError):
                raise ValueError(str(answer))
            if chroot not in copr.parse_chroots(answer):
                self._copr_missing.append(label)
        except ValueError:
            self._copr_failed.append(label)
        if not self._waiting:
            self._show_copr()

    def _show_copr(self) -> None:
        version = self.target
        if self._copr_missing:
            finding = Finding(WARN, _("COPR projects without a build for Fedora {version}: {n}").format(
                version=version, n=len(self._copr_missing)), tuple(self._copr_missing))
        elif not self._copr_total:
            finding = Finding(INFO, _("No COPR projects are enabled."))
        elif not self._copr_failed:
            finding = Finding(OK, _("Every enabled COPR project has a build for Fedora {version}.").format(
                version=version))
        else:
            finding = Finding(OK, _("COPR projects: the rest have a build for Fedora {version}.").format(
                version=version))
        failed = Finding(WARN, _("COPR projects that could not be checked: {n}").format(n=len(self._copr_failed)),
                         tuple(self._copr_failed)) if self._copr_failed else None
        self._view.show_copr(finding, failed)

    # ---------------------------------------------------------------- simulation

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self._cancel.clear()
        self._view.set_running(True)
        self._view.show_progress(Bar(0, 0))
        self._view.show_status(_("Downloading the package lists of Fedora {version}. This can take a while…").format(
            version=self.target))
        version = str(self.target)
        cancel = self._cancel
        post = self._post

        def report(key: str, params: dict) -> None:  # from the dnf thread
            post(lambda: self._on_report(key, params))
        self._dnf.submit(lambda: upgrade_audit.simulate(version, cancel, report), self._show_result, self._on_failed)

    def cancel(self) -> None:
        if self.running:
            self._cancel.set()
            self._view.set_cancelling()
            self._view.show_status(_("Cancelling…"))
            self._append(_("Cancelling…"))

    def _append(self, text: str) -> None:
        self._view.append_log(f"{self._now():%H:%M:%S}  {text}")

    def _on_report(self, key: str, params: dict) -> None:
        if key == "progress":  # not a line of the log
            self._view.show_progress(Bar(int(1000 * params["done"] / params["total"]),
                                         0 if params["done"] >= params["total"] else 1000))
            return
        if key == "still_downloading":
            items = "; ".join(
                _("{name}: {done} of {total}").format(name=name, done=human_size(done), total=human_size(size))
                if size else name for name, done, size in params["items"])
            self._append(_("Still downloading: {items}").format(items=items))
            return
        values = {**params, "size": human_size(params["size"])} if "size" in params else params
        self._append(_(AUDIT_MESSAGES[key]).format(**values))

    def _finished(self) -> None:
        self.running = False
        self._view.set_running(False)

    def _on_failed(self, error: BaseException) -> None:
        self._finished()
        if isinstance(error, upgrade_audit.Cancelled):
            self._view.show_status(intro(self.target))
            return
        text = _("Could not check: {error}").format(error=error)
        self._view.show_status(text)
        self._append(text)

    def _show_result(self, r: AuditResult) -> None:
        self._finished()
        self._append(_("Done."))
        version = self.target
        findings = []

        def finding(kind, title, lines, expanded):
            if lines:
                findings.append(Finding(kind, title.format(n=len(lines), version=version), tuple(lines), expanded))
        finding(ERROR, _("Problems that stop the upgrade: {n}"), r.blockers, True)
        finding(WARN, _("Would be removed: {n}"), [removal_line(name, r) for name in r.removed], True)
        finding(WARN, _("Stay as they are, with no updates from Fedora {version}: {n}"), r.orphaned, True)
        finding(INFO, _("Replaced by other packages: {n}"), r.replaced, False)
        finding(INFO, _("Would be downgraded: {n}"), r.downgrades, False)
        finding(WARN, _("Repositories with nothing for Fedora {version}: {n}"), r.empty_repos, True)
        self._view.show_findings(findings)

        if not r.resolved:
            self._view.show_status(_("The upgrade to Fedora {version} cannot be worked out as things are.").format(
                version=version))
            return
        verdict = _("The upgrade works only if packages are removed.") if r.blockers else _("The upgrade works.")
        details = _("Upgrades: {upgrades}, new packages: {installs}. To download: {download}. Needs {needed}, "
                    "free: {free}.").format(upgrades=r.upgrades, installs=r.installs, download=human_size(r.download),
                                            needed=human_size(r.needed), free=human_size(r.free))
        warning = " ⚠ " + _("Not enough free disk space.") if r.free < r.needed else ""
        self._view.show_status(f"{verdict} {details}{warning}")


def removal_line(name: str, r: AuditResult) -> str:
    needs = r.removal_needs.get(name)
    if not needs:
        return name
    what = ", ".join(needs[:MAX_SHOWN_NEEDS]) + (", …" if len(needs) > MAX_SHOWN_NEEDS else "")
    return _("{name} — needs {what}").format(name=name, what=what)

