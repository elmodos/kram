"""Plain data passed from the libdnf5 thread to the GUI. No libdnf5 objects here."""
from dataclasses import dataclass
from enum import Enum


class Origin(Enum):
    FEDORA = "fedora"
    COPR = "copr"
    THIRD_PARTY = "third"
    LOCAL = "local"
    UNKNOWN = "unknown"


class Status(Enum):
    NOT_INSTALLED = "none"
    INSTALLED = "installed"
    UPGRADABLE = "upgradable"
    NEWER = "newer"          # installed EVR is higher than anything in enabled repos
    ORPHAN = "orphan"        # installed, no enabled repo provides it
    UNNEEDED = "unneeded"    # installed as a dependency, nothing needs it any more


@dataclass(slots=True)
class PkgRow:
    name: str
    arch: str
    summary: str
    installed_evr: str        # "" if not installed
    candidate_evr: str        # best available, "" if none
    repo_id: str              # candidate's repo, or the repo it was installed from
    size: int                 # installed size (of installed pkg if any, else of candidate)
    origin: Origin
    status: Status
    user_installed: bool = False

    @property
    def key(self) -> tuple[str, str]:
        return self.name, self.arch

    @property
    def installed(self) -> bool:
        return bool(self.installed_evr)


@dataclass(slots=True)
class CatalogSnapshot:
    rows: list[PkgRow]
    n_installed: int
    n_upgradable: int
    load_seconds: float
