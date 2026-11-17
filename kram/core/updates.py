"""What the system cache says about upgrades, without root and without network.

Shared by the catalog (the "Upgradable" filter) and the tray update checker, so both count the same packages.
"""
from dataclasses import dataclass

import libdnf5
import rpm

from .model import Advisory

# severities, from the highest advisory type among the upgrades
LOW, MEDIUM, HIGH = "low", "medium", "high"


def open_system_base() -> libdnf5.base.Base:
    """A Base over the system metadata cache (/var/cache/libdnf5), read-only, every repo loaded that can be."""
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


@dataclass(frozen=True)
class UpdateSummary:
    count: int
    severity: str               # LOW, MEDIUM or HIGH
    security: int               # how many of the `count` packages fix a security advisory
    metadata_age: int | None    # seconds since the newest repository refresh; None: no metadata at all


def summarize(base) -> UpdateSummary:
    upgradable = upgradable_keys(base)
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
    installed = libdnf5.rpm.PackageQuery(base)
    installed.filter_installed()
    installed.filter_latest_evr()
    newest = libdnf5.rpm.PackageQuery(base)
    newest.filter_upgrades()
    newest.filter_latest_evr()
    newest_evr: dict[tuple[str, str], tuple[str, str, str]] = {}
    for p in newest:
        key = p.get_name(), p.get_arch()
        if key not in newest_evr or rpm.labelCompare(_evr(p), newest_evr[key]) > 0:
            newest_evr[key] = _evr(p)
    query = libdnf5.advisory.AdvisoryQuery(base)
    query.filter_packages(installed, libdnf5.common.QueryCmp_GT)
    seen: dict[int, Advisory] = {}  # libdnf5's advisory id -> its data, read once for all its packages
    found: dict[tuple[str, str], dict[str, Advisory]] = {}
    for package in query.get_advisory_packages_sorted(installed, libdnf5.common.QueryCmp_GT):
        key = package.get_name(), package.get_arch()
        # an advisory for a version the repositories do not have (yet): its update is not available here
        if key not in upgradable or key not in newest_evr or rpm.labelCompare(_evr(package), newest_evr[key]) > 0:
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
