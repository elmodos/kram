"""Which .repo files Kram may delete. No Qt, no libdnf5; the helper checks the same again (repo_files_to_remove)."""
import os
from collections.abc import Iterable
from enum import Enum

import rpm

REPO_DIR = "/etc/yum.repos.d"  # must match kram_helper.REPO_DIR


class Removal(Enum):
    ALLOWED = "allowed"
    OWNED = "owned"      # a package's file: it comes back with the package's next update
    SYSTEM = "system"    # outside REPO_DIR, e.g. /usr/share/dnf5/repos.d: the distribution's
    NO_FILE = "no-file"  # defined without a file (command line, a plugin)


def file_owners(paths: Iterable[str]) -> dict[str, str]:
    """path -> name of the package that owns it, for the paths a package owns."""
    ts = rpm.TransactionSet()
    owners = {}
    for path in {p for p in paths if p}:
        for header in ts.dbMatch("basenames", path):
            owners[path] = header[rpm.RPMTAG_NAME]
            break
    return owners


def removal(path: str, owner: str | None) -> Removal:
    if not path:
        return Removal.NO_FILE
    if owner:  # wherever it is: removing the package is what removes the repository
        return Removal.OWNED
    if os.path.dirname(os.path.normpath(path)) != REPO_DIR or not path.endswith(".repo"):
        return Removal.SYSTEM
    return Removal.ALLOWED
