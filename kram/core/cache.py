"""Sizes of the package caches (Settings → Package Cache). Counting needs no root; the helper does the cleaning."""
import os
import stat
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass

import libdnf5

from ..helper import kram_helper
from ..i18n import N_

# why the helper refuses to clean PackageKit's cache (kram_helper.packagekit_blocker)
PACKAGEKIT_BLOCKED = {
    "offline": N_("An offline update is prepared. Install or cancel it first."),
    "transaction": N_("PackageKit is working right now. Try again when it has finished."),
}


@dataclass(frozen=True)
class Usage:
    size: int = 0
    files: int = 0


@dataclass(frozen=True)
class CacheReport:
    """One field per cache; None when this system does not have that cache."""
    dnf_packages: Usage | None
    dnf_metadata: Usage | None
    user: Usage | None
    packagekit: Usage | None
    packagekit_blocker: str | None
    dnf_dir: str = ""
    user_dir: str = ""
    packagekit_release: str = ""  # its only release folder; empty when there are several

    def locations(self) -> dict[str, tuple[str, str]]:
        """Field name -> (where its files are, the folder to open). The packages are spread over a folder per
        repository, and the path says so."""
        pk = kram_helper.PACKAGEKIT_CACHE
        if self.packagekit_release:
            metadata = os.path.join(pk, self.packagekit_release, "metadata")
            packagekit = (os.path.join(metadata, "*", "packages"), metadata)
        else:
            packagekit = (os.path.join(pk, "*", "metadata", "*", "packages"), pk)
        return {
            "dnf_packages": (os.path.join(self.dnf_dir, "*", "packages"), self.dnf_dir),
            "dnf_metadata": (self.dnf_dir, self.dnf_dir),
            "user": (self.user_dir, self.user_dir),
            "packagekit": packagekit,
        }


def _files(root: str) -> Iterator[tuple[str, int]]:
    """(path, size) of the regular files below `root`; what this user cannot read is skipped."""
    for directory, _subdirs, names in os.walk(root):
        for name in names:
            path = os.path.join(directory, name)
            try:
                st = os.lstat(path)
            except OSError:
                continue
            if stat.S_ISREG(st.st_mode):
                yield path, st.st_size


def _usage(sizes: list[int]) -> Usage:
    return Usage(sum(sizes), len(sizes))


def scan_dnf(cachedir: str) -> tuple[Usage | None, Usage | None]:
    """(downloaded packages, everything else) of a libdnf5 cache: packages live in <cachedir>/<repo>/packages/."""
    if not os.path.isdir(cachedir):
        return None, None
    packages, other = [], []
    for path, size in _files(cachedir):
        parts = os.path.relpath(path, cachedir).split(os.sep)
        (packages if len(parts) > 2 and parts[1] == "packages" else other).append(size)
    return _usage(packages), _usage(other)


def scan_tree(root: str) -> Usage | None:
    return _usage([size for _path, size in _files(root)]) if os.path.isdir(root) else None


def scan_packagekit() -> Usage | None:
    if not os.path.isdir(kram_helper.PACKAGEKIT_CACHE):
        return None
    return _usage([size for _path, size in kram_helper.packagekit_rpms()])


def packagekit_release() -> str:
    """The name of PackageKit's only release folder ("44"), "" if there is none or several (after a system upgrade)."""
    try:
        with os.scandir(kram_helper.PACKAGEKIT_CACHE) as entries:
            folders = [entry.name for entry in entries if entry.is_dir(follow_symlinks=False)]
    except OSError:
        return ""
    return folders[0] if len(folders) == 1 else ""


def measure() -> CacheReport:
    config_base = libdnf5.base.Base()
    config_base.load_config()
    config = config_base.get_config()
    packages, metadata = scan_dnf(config.system_cachedir)
    # root has one cache, the system one: the "user" row would clean the same files with other words
    user = None if config.cachedir == config.system_cachedir else scan_tree(config.cachedir)
    return CacheReport(packages, metadata, user, scan_packagekit(), kram_helper.packagekit_blocker(),
                       config.system_cachedir, config.cachedir, packagekit_release())


def clean_user_cache() -> None:
    """Empty ~/.cache/libdnf5. Run as the normal user, so `dnf5 clean` works on that cache and needs no root."""
    proc = subprocess.run(["dnf5", "clean", "all"], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                          check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"dnf5 clean: exit code {proc.returncode}")
