"""What would moving to another Fedora release do? Resolved as the normal user, never run.

A separate libdnf5 Base with another `releasever` and its own cache: the system and the catalog's cache stay as they
are. Call it on the dnf thread. The metadata is deleted as soon as the answer is known.
"""
import os
import re
import shutil
from collections import Counter
from dataclasses import dataclass, field

import libdnf5

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
    downgrades: list[str] = field(default_factory=list)  # "name 1.2-3 → 1.1-9"
    orphaned: list[str] = field(default_factory=list)   # installed, no version in the target; "name (repo)"
    empty_repos: list[str] = field(default_factory=list)
    download: int = 0
    needed: int = 0                                 # download plus what the installed system grows by
    free: int = 0


def cache_dir() -> str:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, "kram", "upgrade-audit")


def simulate(target: str) -> AuditResult:
    cache = cache_dir()
    shutil.rmtree(cache, ignore_errors=True)  # left behind if Kram was killed during a check
    os.makedirs(cache, exist_ok=True)
    try:
        return _simulate(target, cache)
    finally:  # the Base is gone by now: nothing has these files open
        shutil.rmtree(cache, ignore_errors=True)


def _simulate(target: str, cache: str) -> AuditResult:
    base = libdnf5.base.Base()
    base.load_config()
    base.get_config().cachedir = cache
    base.get_vars().set("releasever", target)
    base.setup()
    sack = base.get_repo_sack()
    sack.create_repos_from_system_configuration()
    for repo in libdnf5.repo.RepoQuery(base):
        repo.get_config().skip_if_unavailable = True  # one repo without this release is a finding, not an error
    sack.load_repos()

    result = AuditResult(target, resolved=False, free=shutil.disk_usage("/var").free)
    installed = libdnf5.rpm.PackageQuery(base)
    installed.filter_installed()
    available = libdnf5.rpm.PackageQuery(base)
    available.filter_available()
    result.orphaned = _orphaned(installed, available)
    packages_per_repo = Counter(p.get_repo_id() for p in available)
    if not packages_per_repo:  # otherwise "nothing to do" would read as "the upgrade works"
        raise RuntimeError(f"no enabled repository has packages for Fedora {target}")
    result.empty_repos = sorted(r.get_id() for r in libdnf5.repo.RepoQuery(base)
                                if r.is_enabled() and r.get_id() != "@System" and not packages_per_repo[r.get_id()])

    transaction = _resolve(base, allow_erasing=False)
    if not _ok(transaction):
        result.blockers = list(transaction.get_resolve_logs_as_strings())
        transaction = _resolve(base, allow_erasing=True)
    if _ok(transaction):
        result.resolved = True
        _describe(transaction, installed, result)
    return result


def _resolve(base, allow_erasing: bool):
    goal = libdnf5.base.Goal(base)
    goal.add_rpm_distro_sync()
    goal.set_allow_erasing(allow_erasing)
    return goal.resolve()


def _ok(transaction) -> bool:
    return transaction.get_problems() == libdnf5.base.GoalProblem_NO_PROBLEM


def _orphaned(installed, available) -> list[str]:
    known = {(p.get_name(), p.get_arch()) for p in available}
    found = set()
    for p in installed:
        if (p.get_name(), p.get_arch()) not in known and p.get_name() != "gpg-pubkey":
            repo = p.get_from_repo_id()
            found.add(p.get_name() if not repo or HASHED_REPO_ID.match(repo) else f"{p.get_name()} ({repo})")
    return sorted(found)


def _describe(transaction, installed, result: AuditResult) -> None:
    to_string = libdnf5.base.transaction.transaction_item_action_to_string
    versions = {p.get_name(): p.get_evr() for p in installed}
    items = [(to_string(tp.get_action()), tp.get_package()) for tp in transaction.get_transaction_packages()]
    counts = Counter(action for action, _package in items)
    result.upgrades, result.installs = counts["Upgrade"], counts["Install"]
    result.download = sum(p.get_download_size() for action, p in items if action in INBOUND)
    growth = sum(p.get_install_size() for action, p in items if action in INBOUND) \
        - sum(p.get_install_size() for action, p in items if action in OUTBOUND)
    result.needed = result.download + max(growth, 0)
    # the rotation of old kernels is a removal too, but that package stays
    staying = {p.get_name() for action, p in items if action in INBOUND}
    result.removed = sorted({p.get_name() for action, p in items if action == "Remove"} - staying)
    result.downgrades = sorted(f"{p.get_name()} {versions.get(p.get_name(), '?')} → {p.get_evr()}"
                               for action, p in items if action == "Downgrade")
