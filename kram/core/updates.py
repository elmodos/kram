"""What the system cache says about upgrades, without root and without network.

Shared by the catalog (the "Upgradable" filter) and the tray update checker, so both count the same packages.
"""
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

import libdnf5
import rpm

from .model import Advisory

# severities, from the highest advisory type among the upgrades
LOW, MEDIUM, HIGH = "low", "medium", "high"


# how long to wait for another package manager to release the system repo lock before giving up
LOCK_WAIT = 120.0
LOCK_POLL = 1.0


def is_lock_error(e: BaseException) -> bool:
    """libdnf5 could not lock the system repo (the rpm database): another package manager holds it.

    libdnf5 raises a plain libdnf5.exception.Error; its message is not translated."""
    return "system repo lock" in str(e)


class Cancelled(Exception):
    """A wait was cancelled because the application is closing."""


def waiting_for_lock[T](load: Callable[[], T], on_wait: Callable[[], None] | None = None,
                        timeout: float = LOCK_WAIT, poll: float = LOCK_POLL,
                        sleep: Callable[[float], None] = time.sleep,
                        cancel: threading.Event | None = None) -> T:
    """Run `load` (it builds a fresh Base and loads its repos) again while the system repo lock is taken.

    Another package manager holds the lock while it changes the rpm database: right after Kram's own transaction
    that is often akmods installing the kmods it built for a new kernel. `on_wait` is called once, on the first
    wait. After `timeout` seconds the last lock error is raised. `cancel` set: Cancelled, at once instead of after the
    next poll, so that the application does not wait for the lock when it closes."""
    waited = 0.0
    while True:
        try:
            return load()
        except Exception as e:  # only the lock error is retried
            if not is_lock_error(e) or waited >= timeout:
                raise
        if waited == 0.0 and on_wait is not None:
            on_wait()
        if cancel is not None:
            if cancel.wait(poll):
                raise Cancelled()
        else:
            sleep(poll)
        waited += poll


def open_system_base(on_wait: Callable[[], None] | None = None,
                     cancel: threading.Event | None = None) -> libdnf5.base.Base:
    """A Base over the system metadata cache (/var/cache/libdnf5), read-only, every repo loaded that can be.

    Waits while another package manager holds the system repo lock, see waiting_for_lock."""
    return waiting_for_lock(_open_system_base, on_wait, cancel=cancel)


def _open_system_base() -> libdnf5.base.Base:
    base = libdnf5.base.Base()
    base.load_config()
    # read the system cache (/var/cache/libdnf5), which the root helper refreshes; for a normal user libdnf5
    # would otherwise use ~/.cache/libdnf5, which nothing here updates, so "Reload" would seem to do nothing
    config = base.get_config()
    config.cachedir = config.system_cachedir
    # and never write to it: after `dnf makecache` (e.g. dnf-makecache.timer) the .solv files are stale, and
    # libdnf5 would try to rebuild them in a root-owned directory ("cannot create temporary file: (13)").
    # Without them it parses the XML metadata instead, a few seconds slower until the next root refresh.
    config.build_cache = False
    # only read what the helper downloaded: never fetch metadata as the normal user (it would fail with
    # "Failed to set up metadata download" for a repo that has no cache yet)
    config.cacheonly = "all"
    base.setup()
    repo_sack = base.get_repo_sack()
    repo_sack.create_repos_from_system_configuration()
    # a repo without usable metadata (no build for this release yet, server down) must not hide every other
    # package: skip it whatever its .repo file says; the snapshot lists it as unavailable
    for repo in libdnf5.repo.RepoQuery(base):
        repo.get_config().skip_if_unavailable = True
    repo_sack.load_repos()
    return base


def upgradable_keys(base) -> set[tuple[str, str]]:
    """(name, arch) of the installed packages that a repository has a newer version of."""
    q = libdnf5.rpm.PackageQuery(base)
    q.filter_installed()
    q.filter_upgradable()
    return {(p.get_name(), p.get_arch()) for p in q}


def installable_upgrades(base, upgradable: set[tuple[str, str]]) -> set[tuple[str, str]]:
    """The part of `upgradable` that `dnf5 upgrade` would really upgrade now, as a resolve of it says.

    With best=False (Fedora's default) the resolver leaves out an upgrade whose newer versions cannot be installed,
    such as a build that needs a library no repository has yet; such an upgrade is not one the user can do. The
    upgraded packages, and those an obsoleting package replaces, count; so do installonly packages (kernel), whose
    new version is installed next to the old one, not as its upgrade. If the resolve fails as a whole, all of
    `upgradable` is kept: the upgrade dialog shows that problem."""
    if not upgradable:
        return set()
    goal = libdnf5.base.Goal(base)
    goal.add_rpm_upgrade()
    tr = goal.resolve()
    if tr.get_problems() != libdnf5.base.GoalProblem_NO_PROBLEM:
        return set(upgradable)
    T = libdnf5.transaction
    done = set()
    for tp in tr.get_transaction_packages():
        # an installed name.arch that gets an install is installonly: the old versions stay, or the oldest goes
        if tp.get_action() in (T.TransactionItemAction_UPGRADE, T.TransactionItemAction_INSTALL):
            done.add((tp.get_package().get_name(), tp.get_package().get_arch()))
        for old in tp.get_replaces():
            done.add((old.get_name(), old.get_arch()))
    return upgradable & done


@dataclass(frozen=True)
class UpdateSummary:
    count: int
    severity: str               # LOW, MEDIUM or HIGH
    security: int               # how many of the `count` packages fix a security advisory
    metadata_age: int | None    # seconds since the newest repository refresh; None: no metadata at all


def summarize(base) -> UpdateSummary:
    """What the tray shows: only the upgrades that can be installed now, see installable_upgrades."""
    upgradable = installable_upgrades(base, upgradable_keys(base))
    advisories = upgrade_advisories(base, upgradable)
    types = [{a.type for a in found} for found in advisories.values()]
    security = sum(1 for t in types if "security" in t)
    bugfix = any("bugfix" in t for t in types)
    severity = HIGH if security else MEDIUM if bugfix else LOW
    ages = [r.get_age() for r in libdnf5.repo.RepoQuery(base)
            if not r.get_id().startswith("@") and r.is_enabled() and r.get_timestamp() != -1]
    return UpdateSummary(len(upgradable), severity, security, min(ages) if ages else None)


def _evr(p) -> tuple[str, str, str]:
    return p.get_epoch() or "0", p.get_version(), p.get_release()


def upgrade_advisories(base, upgradable: set[tuple[str, str]]) -> dict[tuple[str, str], tuple[Advisory, ...]]:
    """(name, arch) of each upgradable package -> the advisories of the versions an upgrade brings: newer than the
    installed one, up to the newest available, the most important first. As `dnf5 advisory list --updates`, so a
    security fix in an intermediate version counts when the newest version is only a bug fix. Keyed per package:
    one advisory often covers many packages (dnf5 and its libraries), and an advisory count next to a package count
    would compare apples and pears."""
    if not upgradable:
        return {}
    newest = libdnf5.rpm.PackageQuery(base)
    newest.filter_upgrades()
    newest.filter_latest_evr()
    newest_evr: dict[tuple[str, str], tuple[str, str, str]] = {}
    for p in newest:
        key = p.get_name(), p.get_arch()
        if key in upgradable and (key not in newest_evr or rpm.labelCompare(_evr(p), newest_evr[key]) > 0):
            newest_evr[key] = _evr(p)
    return advisories_up_to(base, newest_evr)


def advisories_up_to(base, newest_evr: dict[tuple[str, str], tuple[str, str, str]]
                     ) -> dict[tuple[str, str], tuple[Advisory, ...]]:
    """(name, arch) of installed packages -> the advisories of their versions newer than the installed one, up to
    `newest_evr` of that key (epoch, version, release), the most important first. See upgrade_advisories; the
    version lock's held-back upgrades are counted the same way."""
    if not newest_evr:
        return {}
    installed = libdnf5.rpm.PackageQuery(base)
    installed.filter_installed()
    installed.filter_latest_evr()
    query = libdnf5.advisory.AdvisoryQuery(base)
    query.filter_packages(installed, libdnf5.common.QueryCmp_GT)
    seen: dict[int, Advisory] = {}  # libdnf5's advisory id -> its data, read once for all its packages
    found: dict[tuple[str, str], dict[str, Advisory]] = {}
    for package in query.get_advisory_packages_sorted(installed, libdnf5.common.QueryCmp_GT):
        key = package.get_name(), package.get_arch()
        # an advisory for a version the repositories do not have (yet): its update is not available here
        if key not in newest_evr or rpm.labelCompare(_evr(package), newest_evr[key]) > 0:
            continue
        advisory_id = package.get_advisory_id().id
        if (advisory := seen.get(advisory_id)) is None:
            advisory = seen[advisory_id] = _advisory(package.get_advisory())
        found.setdefault(key, {})[advisory.id] = advisory
    return {key: tuple(sorted(by_id.values(), key=lambda a: (a.rank, -a.issued)))
            for key, by_id in found.items()}


def _advisory(a) -> Advisory:
    severity = (a.get_severity() or "").lower()
    return Advisory(
        id=a.get_name(), type=(a.get_type() or "").lower(), severity="" if severity == "none" else severity,
        title=a.get_title() or "", issued=a.get_buildtime() or 0, description=(a.get_description() or "").strip(),
        references=tuple((r.get_type_cstring() or "", r.get_id() or "", r.get_url() or "")
                         for r in a.get_references()))
