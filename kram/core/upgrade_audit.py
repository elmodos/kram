"""What would moving to another Fedora release do? Resolved as the normal user, never run.

A separate libdnf5 Base with another `releasever` and its own cache: the system and the catalog's cache stay as they
are. Call it on the dnf thread. The metadata is deleted as soon as the answer is known.
"""
import os
import re
import shutil
import threading
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

import libdnf5

Report = Callable[[str, dict], None]  # (message key, its parameters); called on the thread that runs the simulation
PROGRESS_INTERVAL = 0.25  # s between progress reports
QUIET_INTERVAL = 5  # s of silence in the log before it says what is still being waited for
MAX_NAMED_DOWNLOADS = 3
INBOUND = ("Install", "Upgrade", "Downgrade", "Reinstall")
OUTBOUND = ("Remove", "Replaced")
HASHED_REPO_ID = re.compile(r"^[0-9a-f]{32}$")  # dnf5 records some packages under an id nobody can read


@dataclass(slots=True)
class AuditResult:
    target: str
    resolved: bool                                  # some way of doing the upgrade exists
    blockers: list[str] = field(default_factory=list)  # why it does not work without removing packages
    upgrades: int = 0
    installs: int = 0
    removed: list[str] = field(default_factory=list)
    # removed name -> what it requires that the target does not provide
    removal_needs: dict[str, list[str]] = field(default_factory=dict)
    downgrades: list[str] = field(default_factory=list)  # "name 1.2-3 → 1.1-9"
    replaced: list[str] = field(default_factory=list)   # "name → the package taking over"
    orphaned: list[str] = field(default_factory=list)   # no package of that name in the target, nothing takes over
    empty_repos: list[str] = field(default_factory=list)
    download: int = 0
    needed: int = 0                                 # download plus what the installed system grows by
    free: int = 0


class Cancelled(Exception):
    pass


class _Downloads(libdnf5.repo.DownloadCallbacks):
    """libdnf5 tells about every transfer and asks whether to go on: what is reported, and how Cancel works."""

    def __init__(self, cancel: threading.Event, report: Report):
        super().__init__()
        self._cancel = cancel
        self._report = report
        self._names: dict[int, str] = {}
        self._sizes: dict[int, int] = {}
        self._done: dict[int, int] = {}
        self._open: set[int] = set()
        self._last_said = time.monotonic()
        self._last_progress = 0.0

    def _say(self, key: str, **params) -> None:
        if key != "progress":
            self._last_said = time.monotonic()
        try:
            self._report(key, params)
        except Exception:  # noqa: BLE001 - an exception leaving a SWIG callback aborts the whole process
            pass

    def add_new_download(self, _user_data, description, _total):
        handle = len(self._names) + 1
        self._names[handle] = description or "?"
        self._open.add(handle)
        self._say("downloading", name=self._names[handle])
        return handle

    def progress(self, handle, total, downloaded):
        if total > 0:
            self._sizes[handle] = int(total)
            self._done[handle] = int(downloaded)
        self._tick()  # libdnf5 keeps calling this about once a second even when a server sends nothing
        return self.ABORT if self._cancel.is_set() else self.OK

    def _tick(self) -> None:
        now = time.monotonic()
        total = sum(self._sizes.values())
        if total and now - self._last_progress >= PROGRESS_INTERVAL:
            self._last_progress = now
            self._say("progress", done=sum(self._done.values()), total=total)
        if self._open and now - self._last_said >= QUIET_INTERVAL:
            largest = sorted(self._open, key=lambda h: self._sizes.get(h, 0), reverse=True)[:MAX_NAMED_DOWNLOADS]
            self._say("still_downloading", items=[(self._names[h], self._done.get(h, 0), self._sizes.get(h, 0))
                                                  for h in largest])

    def end(self, handle, status, message):
        self._open.discard(handle)
        if handle in self._sizes:
            self._done[handle] = self._sizes[handle]
        if self._cancel.is_set():
            return self.OK
        name = self._names.get(handle, "?")
        if status == self.TransferStatus_ERROR:
            self._say("download_failed", error=f"{name}: {message}")
        else:
            self._say("downloaded", name=name, size=self._sizes.get(handle, 0))
        return self.OK

    def mirror_failure(self, _handle, message, url, _metadata):
        if self._cancel.is_set():
            return self.ABORT
        self._say("mirror_failure", url=url, error=message)
        return self.OK


def cache_dir() -> str:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, "kram", "upgrade-audit")


def simulate(target: str, cancel: threading.Event | None = None, report: Report | None = None) -> AuditResult:
    """Raises Cancelled once `cancel` is set and the transfers have stopped. `report` follows what is going on."""
    cancel = cancel or threading.Event()
    report = report or (lambda _key, _params: None)
    cache = cache_dir()
    shutil.rmtree(cache, ignore_errors=True)  # left behind if Kram was killed during a check
    os.makedirs(cache, exist_ok=True)
    try:
        result = _simulate(target, cache, cancel, report)
    except Exception:
        if cancel.is_set():  # however the aborted transfers surfaced
            raise Cancelled from None
        raise
    else:
        if cancel.is_set():
            raise Cancelled
        return result
    finally:  # the Base is gone by now: nothing has these files open
        shutil.rmtree(cache, ignore_errors=True)


def _simulate(target: str, cache: str, cancel: threading.Event, report: Report) -> AuditResult:
    base = libdnf5.base.Base()
    base.load_config()
    base.get_config().cachedir = cache
    base.get_vars().set("releasever", target)
    base.setup()
    downloads = _Downloads(cancel, report)  # stays referenced: libdnf5 only owns the C++ side
    base.set_download_callbacks(libdnf5.repo.DownloadCallbacksUniquePtr(downloads))
    sack = base.get_repo_sack()
    sack.create_repos_from_system_configuration()
    for repo in libdnf5.repo.RepoQuery(base):
        repo.get_config().skip_if_unavailable = True  # one repo without this release is a finding, not an error
    sack.load_repos()
    if cancel.is_set():
        raise Cancelled

    result = AuditResult(target, resolved=False, free=shutil.disk_usage("/var").free)
    installed = libdnf5.rpm.PackageQuery(base)
    installed.filter_installed()
    available = libdnf5.rpm.PackageQuery(base)
    available.filter_available()
    without_target = _without_target(installed, available)
    packages_per_repo = Counter(p.get_repo_id() for p in available)
    if not packages_per_repo:  # otherwise "nothing to do" would read as "the upgrade works"
        raise RuntimeError(f"no enabled repository has packages for Fedora {target}")
    result.empty_repos = sorted(r.get_id() for r in libdnf5.repo.RepoQuery(base)
                                if r.is_enabled() and r.get_id() != "@System" and not packages_per_repo[r.get_id()])

    report("resolving", {})
    transaction = _resolve(base, allow_erasing=False)
    if not _ok(transaction):
        result.blockers = list(transaction.get_resolve_logs_as_strings())
        report("retry_erasing", {})
        transaction = _resolve(base, allow_erasing=True)
    if _ok(transaction):
        result.resolved = True
        _describe(transaction, installed, available, without_target, result)
    else:
        result.orphaned = sorted(without_target.values())
    report("cleanup", {})
    return result


def _resolve(base, allow_erasing: bool):
    goal = libdnf5.base.Goal(base)
    goal.add_rpm_distro_sync()
    goal.set_allow_erasing(allow_erasing)
    return goal.resolve()


def _ok(transaction) -> bool:
    return transaction.get_problems() == libdnf5.base.GoalProblem_NO_PROBLEM


def _without_target(installed, available) -> dict[str, str]:
    """Installed packages whose name the target does not have (name -> how to show it). By name, not by arch: a package
    that only changes arch, noarch to x86_64 say, is an ordinary upgrade."""
    known = {p.get_name() for p in available}
    # the repo a package came from is one of the running release's, misleading in a list about the target
    return {p.get_name(): f"{p.get_name()} (@commandline)" if p.get_from_repo_id() == "@commandline" else p.get_name()
            for p in installed if p.get_name() not in known and p.get_name() != "gpg-pubkey"}


def sort_out(without_target: dict[str, str], removed: list[str],
             successors: dict[str, set[str]]) -> tuple[list[str], list[str]]:
    """What really happens to the packages the target has no package of that name for: (replaced, staying as they
    are). The removed ones are reported as removed."""
    replaced = [f"{name} → {', '.join(sorted(successors[name]))}"
                for name in sorted(without_target) if name in successors]
    staying = [label for name, label in sorted(without_target.items())
               if name not in successors and name not in removed]
    return replaced, staying


def _unmet(package, installed, available) -> list[str]:
    """What `package` requires that the target does not provide: why it cannot stay. Its own capabilities do not
    count, nor do file paths and rich dependencies, which this query cannot judge."""
    unmet = []
    for requirement in map(str, package.get_requires()):
        if requirement.startswith(("rpmlib(", "/", "(")):
            continue
        provided = libdnf5.rpm.PackageQuery(available)
        provided.filter_provides([requirement])
        own = libdnf5.rpm.PackageQuery(installed)
        own.filter_name([package.get_name()])
        own.filter_provides([requirement])
        if provided.empty() and own.empty():
            unmet.append(requirement)
    return unmet


def _describe(transaction, installed, available, without_target: dict[str, str], result: AuditResult) -> None:
    to_string = libdnf5.base.transaction.transaction_item_action_to_string
    versions = {p.get_name(): p.get_evr() for p in installed}
    packages = list(transaction.get_transaction_packages())
    items = [(to_string(tp.get_action()), tp.get_package()) for tp in packages]
    counts = Counter(action for action, _package in items)
    result.upgrades, result.installs = counts["Upgrade"], counts["Install"]
    result.download = sum(p.get_download_size() for action, p in items if action in INBOUND)
    growth = sum(p.get_install_size() for action, p in items if action in INBOUND) \
        - sum(p.get_install_size() for action, p in items if action in OUTBOUND)
    result.needed = result.download + max(growth, 0)
    # the rotation of old kernels is a removal too, but that package stays
    staying = {p.get_name() for action, p in items if action in INBOUND}
    result.removed = sorted({p.get_name() for action, p in items if action == "Remove"} - staying)
    successors: dict[str, set[str]] = {}
    for tp in packages:
        for old in tp.get_replaces():
            if old.get_name() != tp.get_package().get_name():
                successors.setdefault(old.get_name(), set()).add(tp.get_package().get_name())
    result.removal_needs = {p.get_name(): needs for action, p in items
                            if action == "Remove" and p.get_name() in result.removed
                            and (needs := _unmet(p, installed, available))}
    result.replaced, result.orphaned = sort_out(without_target, result.removed, successors)
    result.downgrades = sorted(f"{p.get_name()} {versions.get(p.get_name(), '?')} → {p.get_evr()}"
                               for action, p in items if action == "Downgrade")
