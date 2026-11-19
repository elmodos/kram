"""dnf's version lock (`dnf5 versionlock`, /etc/dnf/versionlock.toml), as libdnf5 reads it. No Qt.

libdnf5 applies the lock itself while loading: the versions it excludes are left out of every query, so a locked
package has no upgrade and its candidate is the locked version. What the lock holds back is only seen through
`get_versionlock_excludes`."""
import fnmatch
import re

import rpm

from .model import VersionLock

# package names a versionlock request may carry; must match kram.helper.kram_helper.LOCK_NAME_RE. The first
# character is never "-", so a name cannot be read as an option of dnf5 or rpm
NAME_RE = re.compile(r"^[A-Za-z0-9_+][A-Za-z0-9_.+~^-]{0,255}$")


def read_locks(base) -> dict[str, tuple[VersionLock, ...]]:
    """The entries of the lock configuration by package name (which may be a glob). Empty without a configuration,
    or when dnf cannot read it (dnf itself then reports it)."""
    try:
        # keep the config referenced while reading: its entries point into it, and once SWIG frees it their
        # strings read as garbage
        config = base.get_rpm_package_sack().get_versionlock_config()
        entries = config.get_packages()
    except Exception:  # noqa: BLE001 - a broken file raises libdnf5's VersionlockParseError
        return {}
    found: dict[str, list[VersionLock]] = {}
    for entry in entries:
        conditions = ", ".join(c.to_string(False) for c in entry.get_conditions())
        found.setdefault(entry.get_name(), []).append(VersionLock(conditions, entry.get_comment() or ""))
    del config
    return {name: tuple(locks) for name, locks in found.items()}


def locks_for(locks: dict[str, tuple[VersionLock, ...]], name: str) -> tuple[VersionLock, ...]:
    """The entries that apply to a package name: its own, then those of matching globs ("kernel*")."""
    own = locks.get(name, ())
    globs = tuple(lock for pattern, entries in locks.items()
                  if pattern != name and any(c in pattern for c in "*?[") and fnmatch.fnmatchcase(name, pattern)
                  for lock in entries)
    return own + globs


def _evr(p) -> tuple[str, str, str]:
    return p.get_epoch() or "0", p.get_version(), p.get_release()


def newest_excluded(base) -> dict[tuple[str, str], object]:
    """(name, arch) -> the newest package of it that the lock excludes."""
    newest: dict[tuple[str, str], object] = {}
    for p in base.get_rpm_package_sack().get_versionlock_excludes():
        key = p.get_name(), p.get_arch()
        if key not in newest or rpm.labelCompare(_evr(p), _evr(newest[key])) > 0:
            newest[key] = p
    return newest


def excluded_versions(base, name: str, arches: list[str]) -> list:
    """The packages of `name` in `arches` that the lock excludes. Picked out by hand: a PackageQuery made from the
    set would apply the excludes again and come out empty."""
    return [p for p in base.get_rpm_package_sack().get_versionlock_excludes()
            if p.get_name() == name and p.get_arch() in arches]


def held_back(newest: dict[tuple[str, str], object], key: tuple[str, str], *current) -> object | None:
    """The package the lock holds back for `key`: its newest excluded one, if newer than each of the `current`
    packages (the installed one and the candidate; None ones are skipped)."""
    p = newest.get(key)
    if p is None or any(c is not None and rpm.labelCompare(_evr(p), _evr(c)) <= 0 for c in current):
        return None
    return p
