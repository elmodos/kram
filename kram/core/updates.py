"""What the system cache says about upgrades, without root and without network.

Shared by the catalog (the "Upgradable" filter) and the tray update checker, so both count the same packages.
"""
from dataclasses import dataclass

import libdnf5

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
    types = advisory_types(base)
    security = sum(1 for key in upgradable if "security" in types.get(key, ()))
    bugfix = any("bugfix" in types.get(key, ()) for key in upgradable)
    severity = HIGH if security else MEDIUM if bugfix else LOW
    ages = [r.get_age() for r in libdnf5.repo.RepoQuery(base)
            if not r.get_id().startswith("@") and r.is_enabled() and r.get_timestamp() != -1]
    return UpdateSummary(len(upgradable), severity, security, min(ages) if ages else None)


def advisory_types(base) -> dict[tuple[str, str], set[str]]:
    """(name, arch) of each upgrade -> the types of the advisories that list its newest version ("security",
    "bugfix", "enhancement", …). Counted per package: one advisory often covers many packages (dnf5 and its
    libraries), and an advisory count next to a package count would compare apples and pears."""
    upgrades = libdnf5.rpm.PackageQuery(base)
    upgrades.filter_upgrades()
    upgrades.filter_latest_evr()
    query = libdnf5.advisory.AdvisoryQuery(base)
    query.filter_packages(upgrades)
    types: dict[tuple[str, str], set[str]] = {}
    for package in query.get_advisory_packages_sorted(upgrades):
        types.setdefault((package.get_name(), package.get_arch()), set()).add(package.get_advisory().get_type())
    return types
