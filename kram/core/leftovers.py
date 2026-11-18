"""rpm's leftover copies of configuration files (.rpmnew, .rpmsave, .rpmorig), for Settings → Cleanup.

A normal user searches what it can read; the helper searches the rest and deletes."""
import difflib
import os
from dataclasses import dataclass
from enum import Enum

from ..helper import kram_helper
from .repo_files import file_owners


class Kind(Enum):
    ORPHAN = "orphan"  # the file it is a copy of is gone: nothing uses it, safe to delete
    SAVED = "saved"    # .rpmsave/.rpmorig: the user's earlier version, put aside when a package replaced the file
    NEW = "new"        # .rpmnew: a package's new default, not applied because the user changed the file


@dataclass(frozen=True)
class Leftover:
    path: str
    size: int
    mtime: int
    kind: Kind
    package: str = ""  # the package that owns the current file, "" if none does

    @property
    def current(self) -> str:
        """The file this is a copy of."""
        return os.path.splitext(self.path)[0]

    @property
    def comparable(self) -> bool:
        return self.kind is not Kind.ORPHAN and os.access(self.path, os.R_OK) and os.access(self.current, os.R_OK)


@dataclass(frozen=True)
class LeftoverReport:
    files: list[Leftover]
    unreadable: int  # folders the search could not read: 0 once the helper has searched


def classify(found: list[dict], unreadable: int) -> LeftoverReport:
    """`found`: kram_helper.find_leftover_files() records, from either search."""
    owners = file_owners(os.path.splitext(f["path"])[0] for f in found if f["current"])
    files = []
    for f in found:
        current = os.path.splitext(f["path"])[0]
        if not f["current"]:
            kind = Kind.ORPHAN
        else:
            kind = Kind.NEW if f["path"].endswith(".rpmnew") else Kind.SAVED
        files.append(Leftover(f["path"], f["size"], f["mtime"], kind, owners.get(current, "")))
    return LeftoverReport(files, unreadable)


def scan(root: str = kram_helper.LEFTOVER_ROOT) -> LeftoverReport:
    return classify(*kram_helper.find_leftover_files(root))


def diff(leftover: Leftover) -> str:
    """The unified diff from the current file to the leftover copy."""
    def lines(path: str) -> list[str]:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.readlines()
    return "".join(difflib.unified_diff(lines(leftover.current), lines(leftover.path), leftover.current,
                                        leftover.path))
