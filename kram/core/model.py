"""Plain data passed from the libdnf5 thread to the GUI. No libdnf5 objects here."""
from dataclasses import dataclass, field
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


class Reason(Enum):
    """Why an installed package is there (dnf5's install reason). The first three keep it from autoremove."""
    USER = "user"
    GROUP = "group"
    EXTERNAL = "external"    # installed outside dnf, or dnf lost the record: treated as installed by the user
    DEPENDENCY = "dependency"
    WEAK = "weak"            # pulled in by a Recommends/Supplements


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
    from_repo_id: str = ""     # repo it was installed from; "" if not installed
    reason: Reason | None = None  # None if not installed

    @property
    def key(self) -> tuple[str, str]:
        return self.name, self.arch

    @property
    def installed(self) -> bool:
        return bool(self.installed_evr)

    @property
    def origin_repo(self) -> str:
        """The repo `origin` was derived from: where it came from if installed, else where it would come from."""
        return self.from_repo_id or self.repo_id


@dataclass(slots=True)
class RepoInfo:
    id: str
    name: str
    enabled: bool
    origin: Origin
    age_seconds: int | None   # time since metadata was downloaded; None if not loaded
    priority: int = 99
    file_path: str = ""


@dataclass(slots=True)
class GroupInfo:
    """A comps group (Synaptic's "sections"): the package names it lists, of any type."""
    id: str
    name: str                  # translated when the metadata has the current language
    description: str
    installed: bool
    packages: frozenset[str]


@dataclass(slots=True)
class CatalogSnapshot:
    rows: list[PkgRow]
    n_installed: int
    n_upgradable: int
    load_seconds: float
    basearch: str = "x86_64"
    releasever: str = ""
    repos: list[RepoInfo] = field(default_factory=list)
    descriptions: list[str] = field(default_factory=list)   # aligned with rows
    groups: list[GroupInfo] = field(default_factory=list)   # user-visible comps groups, sorted by name
    # (capability, is a glob) -> keys of the packages providing it; only what custom filters asked for (libdnf5 knows
    # the rest, but filters run on the GUI thread)
    provides: dict[tuple[str, bool], frozenset[tuple[str, str]]] = field(default_factory=dict)

    @property
    def unavailable_repos(self) -> list[RepoInfo]:
        """Enabled repos without usable metadata (skipped while loading)."""
        return [r for r in self.repos if r.enabled and r.age_seconds is None]

    @property
    def metadata_age(self) -> int | None:
        """Age of the most recently refreshed enabled repo, i.e. time since the last refresh."""
        ages = [r.age_seconds for r in self.repos if r.enabled and r.age_seconds is not None]
        return min(ages) if ages else None


@dataclass(slots=True)
class VersionInfo:
    evr: str
    repo_id: str
    installed: bool = False
    candidate: bool = False


@dataclass(slots=True)
class ChangelogEntry:
    timestamp: int
    author: str
    text: str


@dataclass(slots=True)
class PkgDetails:
    nevra: str
    summary: str
    description: str
    url: str
    license: str
    vendor: str
    packager: str
    source_rpm: str
    build_time: int
    install_time: int | None
    repo_id: str
    from_repo_id: str
    install_size: int
    download_size: int | None
    user_installed: bool | None
    requires: list[str]
    recommends: list[str]
    suggests: list[str]
    provides: list[str]
    conflicts: list[str]
    obsoletes: list[str]
    required_by: list[tuple[str, str]]   # installed packages that require this one
    files: list[str]
    files_complete: bool                 # False: repo primary metadata only lists some files
    changelog: list[ChangelogEntry]
    versions: list[VersionInfo]


@dataclass(slots=True)
class PreviewItem:
    action: str          # install | upgrade | downgrade | reinstall | remove | reason
    name: str
    arch: str
    evr: str
    old_evr: str         # replaced version for upgrade/downgrade
    repo_id: str
    download_size: int
    install_size: int
    reason: str          # user | dependency | weak | clean (removed as no longer needed) | ""
    rotated: bool = False  # a removal that makes room for a new version of the same package: see mark_rotated


def mark_rotated(items: list[PreviewItem]) -> None:
    """Flag the removals that go with a new version of the same package (name and arch).

    Kernels are installonly: a new one goes next to the old ones, and past `installonly_limit` the oldest is removed.
    That is housekeeping, not a loss: the package stays. An upgrade or downgrade never lists such a removal, because
    libdnf5 reports the old side of those as replaced, so this matches installonly rotation only."""
    arriving = {(i.name, i.arch) for i in items if i.action in ("install", "upgrade", "downgrade", "reinstall")}
    for item in items:
        item.rotated = item.action == "remove" and (item.name, item.arch) in arriving


@dataclass(slots=True)
class Recommendation:
    """A weak dependency the transaction brings in (or would, if the user had not unchecked it)."""
    what: str                    # the Recommends: string, e.g. "(libvirt-daemon-kvm or libvirt-daemon-qemu)",
                                 # or a package name for one pulled in by its own Supplements:
    by: list[str]                # names of the packages in the transaction that recommend it
    direct: bool                 # recommended by a package the user marked, not by a dependency
    brings: list[str]            # names it brings into the transaction now (empty while unchecked)
    excludes: list[str]          # names to put in exclude_weak to uncheck it (every provider)
    needed: list[str] = field(default_factory=list)  # unchecked, but still installed: a hard dependency
    size: int | None = None      # install size it adds; with everything it pulls in when `exact`
    count: int = 0               # packages it adds; likewise
    exact: bool = False

    @property
    def checked(self) -> bool:
        return bool(self.brings)


@dataclass(slots=True)
class TransactionPreview:
    items: list[PreviewItem]
    problems: list[str]          # resolver messages; non-empty means the transaction cannot run
    download_size: int
    size_change: int             # bytes of disk space gained (+) or freed (-)
    recommendations: list[Recommendation] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


@dataclass(slots=True)
class Requirement:
    """One dependency of a package file and what on this system satisfies it."""
    text: str                    # "libX11.so.6()(64bit)", "(gtk3 or gtk4)"
    installed: list[str]         # names of installed packages providing it
    available: list[str]         # names of packages in the repositories providing it
    own: bool = False            # the file provides it itself


@dataclass(slots=True)
class LocalTarget:
    """What installing a package file means for this system."""
    action: str                  # install | upgrade | downgrade | reinstall | alongside (installonly: a kernel)
    installed_evr: str           # newest installed version of the package, "" if none
    repo_evr: str                # best version in the enabled repositories, "" if none has it
    repo_id: str
    # "requires", "recommends", "suggests" -> its dependencies of that kind
    deps: dict[str, list[Requirement]] = field(default_factory=dict)
    repo_newer: bool = False     # the repositories have a newer version than the file: an update replaces it

    @property
    def helper_action(self) -> str:
        """The helper's local_install action: libdnf5 installs a newer file as an upgrade, and an installonly
        package next to the others."""
        return "install" if self.action in ("upgrade", "alongside") else self.action
