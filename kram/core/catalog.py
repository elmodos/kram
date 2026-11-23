"""libdnf5 access for the GUI process (unprivileged, reads the system metadata cache).

Not thread-safe: every method must be called from the same single worker thread.
"""
import functools
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterable

import libdnf5
import rpm

from ..helper.kram_helper import build_goal, cmdline_package, local_goal, transaction_space
from ..i18n import language
from . import capabilities
from .evr import split_evr
from .history import (
    ITEM_REASONS,
    HistoryItem,
    HistoryTransaction,
    PackageState,
    comps_install_times,
    read_items,
    read_transactions,
)
from .model import (
    ENVIRONMENT_PREFIX,
    CatalogSnapshot,
    ChangelogEntry,
    GroupInfo,
    LocalTarget,
    PkgDetails,
    PkgRow,
    PreviewGroup,
    PreviewItem,
    Reason,
    Recommendation,
    RepoInfo,
    Requirement,
    Status,
    TransactionPreview,
    VersionInfo,
    mark_rotated,
)
from .origin import classify
from .session import current_session
from .updates import (
    advisories_up_to,
    installable_upgrades,
    open_system_base,
    upgradable_keys,
    upgrade_advisories,
    waiting_for_lock,
)
from .versionlock import excluded_versions, held_back, locks_for, newest_excluded, read_locks

MAX_CHANGELOG = 30
# a substring of one or two characters matches most of what packages provide: no use as a search
MIN_SUBSTRING_QUERY = 3
# not-installed debug packages are noise in a package list (TODO: make it a setting)
HIDDEN_SUFFIXES = ("-debuginfo", "-debugsource")
# what a recommendation adds with everything it pulls in costs one more resolve (~0.4 s) each
MAX_SIZED_RECOMMENDATIONS = 10
# blocked upgrades whose reason is resolved one by one (0.1-0.3 s each) with the list; the others get theirs when
# the row is selected (Catalog.blocked_reason)
MAX_BLOCKED_REASONS = 20


def _option(option, default=""):
    """A libdnf5 option's value; `default` when the option is not set (`get_value` raises then)."""
    try:
        return option.get_value()
    except libdnf5.exception.OptionValueNotSetError:
        return default


def _evr_tuple(pkg):
    return pkg.get_epoch() or "0", pkg.get_version(), pkg.get_release()


_evr_cmp_key = functools.cmp_to_key(rpm.labelCompare)


def _evr_sort_key(pkg):
    return _evr_cmp_key(_evr_tuple(pkg))


def _reldeps(reldep_list) -> list[str]:
    return [r.to_string() for r in reldep_list]


def _own_deps(reldep_list) -> list:
    """Without duplicates (/bin/sh for each scriptlet) and rpmlib() features, which rpm itself provides."""
    seen, out = set(), []
    for r in reldep_list:
        text = r.to_string()
        if text not in seen and not text.startswith("rpmlib("):
            seen.add(text)
            out.append(r)
    return out


def skipped_changes(tr) -> list[str]:
    """What the resolver left out of a transaction that has no problems: the marked upgrades (or installs) it could
    not carry out because best=False lets it drop them, such as a new version that needs a library no repository
    has. Already installed packages and the like are not reported: nothing is missing there."""
    strict = libdnf5.base.GoalProblem_SOLVER_PROBLEM_STRICT_RESOLVEMENT
    return [ev.to_string() for ev in tr.get_resolve_logs() if ev.get_problem() == strict]


class Catalog:
    def __init__(self) -> None:
        self._base = None
        # (name, arch) -> (installed pkg | None, candidate pkg | None); lives only on the worker thread
        self._pkgs: dict[tuple[str, str], tuple[object, object]] = {}
        self._capabilities: dict[str, set[tuple[str, str]]] | None = None  # built on first use, see search_provides
        self._required: set[str] | None = None  # built on first use, see details
        self._user_installed: set[tuple[str, str]] = set()
        self._system_base = None
        self._local: dict[str, object] = {}  # package file path -> its Package in @commandline

    def load(self, provides: Iterable[tuple[str, bool]] = (),
             on_wait: Callable[[], None] | None = None, cancel: threading.Event | None = None) -> CatalogSnapshot:
        """`provides`: the (capability, is a glob) questions of the custom filters, answered in the snapshot.
        `on_wait`: called (on this thread) when another package manager holds the system repo lock. `cancel`: set
        when the application closes, which ends such a wait (Cancelled)."""
        t0 = time.monotonic()
        base = open_system_base(on_wait, cancel)
        self._base = base
        self._system_base = None  # built on first use, see removal_dependents
        self._local = {}
        self._capabilities = None
        self._required = None

        basearch = base.get_vars().get_value("basearch")
        arches = [basearch, "noarch"]

        # all arches here, so installed multilib (i686) packages still find their candidate
        candidates = libdnf5.rpm.PackageQuery(base)
        candidates.filter_available()
        candidates.filter_latest_evr()
        cand_by_key = {(p.get_name(), p.get_arch()): p for p in candidates}

        # installonly packages (kernel) have several installed versions: keep the newest
        installed = libdnf5.rpm.PackageQuery(base)
        installed.filter_installed()
        installed.filter_latest_evr()

        def keys(query_setup):
            q = libdnf5.rpm.PackageQuery(base)
            q.filter_installed()
            query_setup(q)
            return {(p.get_name(), p.get_arch()) for p in q}

        upgradable = upgradable_keys(base)  # the tray update checker counts with the same functions
        advisories = upgrade_advisories(base, upgradable)
        arch_changes = self._arch_changes(base, installed, cand_by_key, upgradable, arches)
        for new in arch_changes.values():  # one row per package: the new arch is that row's candidate
            cand_by_key.pop((new.get_name(), new.get_arch()), None)
        orphans = keys(lambda q: q.filter_extras())
        unneeded = keys(lambda q: q.filter_unneeded())
        user_installed = keys(lambda q: q.filter_userinstalled())
        locks = read_locks(base)
        excluded = newest_excluded(base) if locks else {}

        T = libdnf5.transaction
        reasons = {T.TransactionItemReason_USER: Reason.USER, T.TransactionItemReason_GROUP: Reason.GROUP,
                   T.TransactionItemReason_EXTERNAL_USER: Reason.EXTERNAL,
                   T.TransactionItemReason_DEPENDENCY: Reason.DEPENDENCY,
                   T.TransactionItemReason_WEAK_DEPENDENCY: Reason.WEAK}
        rows: list[PkgRow] = []
        pkgs: dict[tuple[str, str], tuple[object, object]] = {}
        n_upgradable = 0

        for p in installed:
            key = (p.get_name(), p.get_arch())
            cand = cand_by_key.pop(key, None)
            cand = arch_changes.get(key, cand)
            from_repo = p.get_from_repo_id()
            if key in upgradable and cand is not None:
                status = Status.UPGRADABLE
                n_upgradable += 1
            elif key in orphans or cand is None:
                status = Status.ORPHAN
            elif key in unneeded:
                status = Status.UNNEEDED
            elif p.get_evr() != cand.get_evr() and rpm.labelCompare(_evr_tuple(p), _evr_tuple(cand)) > 0:
                status = Status.NEWER
            else:
                status = Status.INSTALLED
            rows.append(PkgRow(
                name=key[0], arch=key[1], summary=p.get_summary(),
                installed_evr=p.get_evr(), candidate_evr=cand.get_evr() if cand else "",
                repo_id=cand.get_repo_id() if cand else from_repo,
                size=p.get_install_size(), origin=classify(from_repo), status=status,
                user_installed=key in user_installed, from_repo_id=from_repo, reason=reasons.get(p.get_reason()),
                candidate_arch=cand.get_arch() if key in arch_changes else "",
                advisories=advisories.get(key, ()) if status is Status.UPGRADABLE else (),
                unneeded=key in unneeded, download_size=cand.get_download_size() if cand else None,
                **self._lock_fields(locks, excluded, key, p, cand),
            ))
            pkgs[key] = (p, cand)

        n_installed = len(rows)
        for key, cand in cand_by_key.items():
            if key[1] not in arches or key[0].endswith(HIDDEN_SUFFIXES):
                continue
            repo_id = cand.get_repo_id()
            rows.append(PkgRow(
                name=key[0], arch=key[1], summary=cand.get_summary(),
                installed_evr="", candidate_evr=cand.get_evr(), repo_id=repo_id,
                size=cand.get_install_size(), origin=classify(repo_id), status=Status.NOT_INSTALLED,
                download_size=cand.get_download_size(),
                **self._lock_fields(locks, excluded, key, None, cand),
            ))
            pkgs[key] = (None, cand)

        held = {r.key: r for r in rows if r.held_evr and r.installed}
        if held:
            ceilings = {key: _evr_tuple(excluded[key]) for key in held}
            for key, found in advisories_up_to(base, ceilings).items():
                held[key].held_advisories = found
        rows.sort(key=lambda r: (r.name.lower(), r.arch))
        self._pkgs = pkgs
        self._user_installed = user_installed
        # ~0.1 s for 70k packages; cheap enough to make full-description search instant
        descriptions = [(pkgs[r.key][0] or pkgs[r.key][1]).get_description() for r in rows]
        groups, environments = self._groups()
        # read the rpmdb for the session's packages here, on this thread: librpm is not documented as thread-safe,
        # and the review dialog would otherwise make this first (cached) call on the GUI thread
        current_session()
        return CatalogSnapshot(rows, n_installed, n_upgradable, time.monotonic() - t0,
                               basearch=basearch, releasever=base.get_vars().get_value("releasever"),
                               repos=self._repos(), descriptions=descriptions, groups=groups, environments=environments,
                               provides={q: self.provides_keys(*q) for q in provides},
                               fastestmirror=bool(base.get_config().get_fastestmirror_option().get_value()))

    @staticmethod
    def _lock_fields(locks, excluded, key, installed, cand) -> dict:
        """PkgRow's version lock fields: the entries for the name, and the upgrade they hold back."""
        if not locks:
            return {}
        held = held_back(excluded, key, installed, cand)
        return {"locks": locks_for(locks, key[0]), "held_evr": held.get_evr() if held else ""}

    @staticmethod
    def _arch_changes(base, installed, cand_by_key, upgradable, arches) -> dict[tuple[str, str], object]:
        """(name, arch) of an installed package -> its upgrade of another arch, for the upgradable packages whose
        own arch has nothing newer: libdnf5 counts noarch -> x86_64 (a package that gained compiled code) and back
        as an upgrade of the same package."""
        installed_keys = {(p.get_name(), p.get_arch()) for p in installed}
        stuck = {}
        for p in installed:
            key = (p.get_name(), p.get_arch())
            same = cand_by_key.get(key)
            if key in upgradable and (same is None or rpm.labelCompare(_evr_tuple(same), _evr_tuple(p)) <= 0):
                stuck[key] = p
        if not stuck:
            return {}
        upgrades = libdnf5.rpm.PackageQuery(base)
        upgrades.filter_upgrades()
        upgrades.filter_name(sorted({name for name, _arch in stuck}))
        upgrades.filter_latest_evr()
        changes = {}
        for key in stuck:
            other = [u for u in upgrades if u.get_name() == key[0] and u.get_arch() != key[1]
                     and u.get_arch() in arches and (u.get_name(), u.get_arch()) not in installed_keys]
            if other:
                changes[key] = max(other, key=_evr_sort_key)
        return changes

    def _groups(self) -> tuple[list[GroupInfo], list[GroupInfo]]:
        """(groups, environments), each sorted by name. Groups: the user-visible ones and the hidden ones an
        environment installs ("core", "standard"), which the Environments view lists under it."""
        lang = language() or ""

        def text(x, name: bool) -> str:
            if name:
                return (x.get_translated_name(lang) if lang else "") or x.get_name()
            return (x.get_translated_description(lang) if lang else "") or x.get_description()

        # an installed group or environment shows up twice (system state + repo metadata): merge by id
        envs: dict[str, GroupInfo] = {}
        for e in libdnf5.comps.EnvironmentQuery(self._base):
            eid = e.get_environmentid()
            if eid in envs:
                envs[eid].installed |= e.get_installed()
                continue
            # what `dnf5 group install` installs: the mandatory and the default groups (libdnf5 5.2, Fedora 43, has
            # no default groups: they are among the optional ones there)
            defaults = e.get_default_groups() if hasattr(e, "get_default_groups") else ()
            envs[eid] = GroupInfo(eid, text(e, True), text(e, False), e.get_installed(), frozenset(),
                                  environment=True, groups=tuple(dict.fromkeys((*e.get_groups(), *defaults))),
                                  optional_groups=tuple(e.get_optional_groups()))
        in_envs = {gid for env in envs.values() for gid in (*env.groups, *env.optional_groups)}
        optional = libdnf5.comps.PackageType_OPTIONAL
        groups: dict[str, GroupInfo] = {}
        for g in libdnf5.comps.GroupQuery(self._base):
            gid = g.get_groupid()
            if gid in groups:
                groups[gid].installed |= g.get_installed()
                continue
            visible = g.get_uservisible()
            if not (visible or gid in in_envs):
                continue
            packages = g.get_packages()
            groups[gid] = GroupInfo(
                gid, text(g, True), text(g, False), g.get_installed(), frozenset(p.get_name() for p in packages),
                optional=frozenset(p.get_name() for p in packages if p.get_type() == optional), visible=visible)
        for env in envs.values():
            mine = [groups[gid] for gid in env.groups if gid in groups]
            env.packages = frozenset().union(*(g.packages for g in mine))
            env.optional = frozenset().union(*(g.optional for g in mine)) - frozenset().union(
                *(g.packages - g.optional for g in mine))

        def by_name(items):
            return sorted(items, key=lambda g: g.name.lower())
        return by_name(groups.values()), by_name(envs.values())

    def upgradable_groups(self, keys: Iterable[str]) -> set[str]:
        """The installed groups and environments (GroupInfo.key) that `dnf5 group upgrade` would change: one dry-run
        resolve each (~0.1 s)."""
        found = set()
        for key in keys:
            env, _prefix, eid = key.partition(ENVIRONMENT_PREFIX)
            req = {"environment_upgrade": [eid]} if not env and eid else {"group_upgrade": [key]}
            tr = self._resolve_goal(lambda _extra, req=req: build_goal(self._base, req), [])
            if tr.get_problems() == libdnf5.base.GoalProblem_NO_PROBLEM and len(tr.get_transaction_packages()):
                found.add(key)
        return found

    def _repos(self) -> list[RepoInfo]:
        repos = []
        for r in libdnf5.repo.RepoQuery(self._base):
            if r.get_id().startswith("@"):
                continue
            # get_timestamp() is -1 when the repo has no loaded metadata (get_age() is then meaningless)
            age = r.get_age() if r.is_enabled() and r.get_timestamp() != -1 else None
            conf = r.get_config()
            repos.append(RepoInfo(r.get_id(), r.get_name(), r.is_enabled(), classify(r.get_id()), age,
                                  priority=r.get_priority(), file_path=r.get_repo_file_path(),
                                  metalink=_option(conf.get_metalink_option()),
                                  mirrorlist=_option(conf.get_mirrorlist_option()),
                                  baseurls=tuple(_option(conf.get_baseurl_option(), ()))))
        repos.sort(key=lambda r: r.id)
        return repos

    def repo_package_counts(self) -> Counter[str]:
        """Distinct packages (name.arch, as the package list's rows) available in each enabled repo: a COPR project
        keeps every build, so counting versions would say 60 for a single package."""
        q = libdnf5.rpm.PackageQuery(self._base)
        q.filter_available()
        return Counter(repo for repo, _name, _arch in {(p.get_repo_id(), p.get_name(), p.get_arch()) for p in q})

    def details(self, key: tuple[str, str]) -> PkgDetails:
        inst, cand = self._pkgs[key]
        p = inst or cand

        required_by: list[tuple[str, str]] = []
        if inst is not None:
            # only the capabilities somebody asks for: libdnf5 checks each one against every installed package, and
            # kernel-core provides 16k kernel symbols (6.7 s with the window frozen; 0.03 s like this)
            asked = self._required_names()
            wanted = libdnf5.rpm.ReldepList(self._base)
            for reldep in inst.get_provides():
                if reldep.get_name() in asked:
                    wanted.add(reldep)
            if not wanted.empty():
                q = libdnf5.rpm.PackageQuery(self._base)
                q.filter_installed()
                q.filter_requires(wanted)
                required_by = sorted({(x.get_name(), x.get_arch()) for x in q if x.get_name() != inst.get_name()})

        # every installed version: installonly packages (kernel) keep several side by side
        q = libdnf5.rpm.PackageQuery(self._base)
        # an upgrade that changes the arch (noarch -> x86_64): both arches are versions of this package
        arches = sorted({key[1], cand.get_arch()} if cand else {key[1]})
        q.filter_installed()
        q.filter_name([key[0]])
        q.filter_arch(arches)
        versions = [VersionInfo(x.get_evr(), "@System", installed=True)
                    for x in sorted(q, key=_evr_sort_key, reverse=True)]
        q = libdnf5.rpm.PackageQuery(self._base)
        q.filter_available()
        q.filter_name([key[0]])
        q.filter_arch(arches)
        avail = sorted(q, key=_evr_sort_key, reverse=True)
        cand_evr = cand.get_evr() if cand else None
        available = [VersionInfo(x.get_evr(), x.get_repo_id(), candidate=x.get_evr() == cand_evr) for x in avail]
        # the versions the lock excludes are no longer in any query; listed all the same, as what it holds back
        available += [VersionInfo(x.get_evr(), x.get_repo_id(), locked_out=True)
                      for x in excluded_versions(self._base, key[0], arches) if not x.is_installed()]
        versions += sorted(available, key=lambda v: _evr_cmp_key(split_evr(v.evr)), reverse=True)

        changelog = [ChangelogEntry(c.get_timestamp(), c.get_author(), c.get_text())
                     for c in list(p.get_changelogs())[:MAX_CHANGELOG]]

        return PkgDetails(
            nevra=p.get_nevra(), summary=p.get_summary(), description=p.get_description(),
            url=p.get_url(), license=p.get_license(), vendor=p.get_vendor(), packager=p.get_packager(),
            source_rpm=p.get_sourcerpm(), build_time=p.get_build_time(),
            install_time=inst.get_install_time() if inst else None,
            repo_id=cand.get_repo_id() if cand else "", from_repo_id=inst.get_from_repo_id() if inst else "",
            install_size=p.get_install_size(), download_size=cand.get_download_size() if cand else None,
            user_installed=(key in self._user_installed) if inst else None,
            requires=_reldeps(p.get_requires()), recommends=_reldeps(p.get_recommends()),
            suggests=_reldeps(p.get_suggests()), provides=_reldeps(p.get_provides()),
            conflicts=_reldeps(p.get_conflicts()), obsoletes=_reldeps(p.get_obsoletes()),
            required_by=required_by,
            files=list(p.get_files()), files_complete=inst is not None,
            changelog=changelog, versions=versions,
        )

    def search_provides(self, text: str) -> list[tuple[str, str]]:
        """Packages providing a capability. Plain words match the capability exactly (libdnf5, which also knows
        versions: "python(abi) = 3.14"), falling back to part of a capability name; globs match whole names. Those
        two go through the capability index, built on the first such search."""
        text = text.strip()
        if not text:
            return []
        if capabilities.is_glob(text):
            return sorted(capabilities.match(self._capability_index(), text))
        exact = self._keys(lambda q: q.filter_provides([text]))
        if exact or len(text) < MIN_SUBSTRING_QUERY or any(c in text for c in " <>="):
            return exact
        return sorted(capabilities.match(self._capability_index(), text))

    def _required_names(self) -> set[str]:
        """Every capability name an installed package requires; ~0.2 s for 3000 packages, once per load."""
        if self._required is None:
            q = libdnf5.rpm.PackageQuery(self._base)
            q.filter_installed()
            names: set[str] = set()
            for pkg in q:
                for reldep in pkg.get_requires():
                    text = str(reldep)
                    if text.startswith("("):
                        names |= capabilities.dependency_names(text)
                    else:
                        names.add(reldep.get_name())
            self._required = names
        return self._required

    @property
    def capabilities_ready(self) -> bool:
        """Whether a Provides search by part of a name runs at once, or first builds the index (read from any
        thread)."""
        return self._capabilities is not None

    def _capability_index(self) -> dict[str, set[tuple[str, str]]]:
        """~1.6 s and ~160 MB for 70k packages here. Short libdnf5 calls, so the window keeps running meanwhile.
        Only the versions the catalog shows (installed and candidate) count: an older build in another repository
        that provided something the current one dropped is no answer to "what provides it"."""
        if self._capabilities is None:
            index: dict[str, set[tuple[str, str]]] = {}
            for key, versions in self._pkgs.items():
                for pkg in versions:
                    if pkg is not None:
                        for reldep in pkg.get_provides():
                            index.setdefault(reldep.get_name(), set()).add(key)
            self._capabilities = index
        return self._capabilities

    def provides_keys(self, capability: str, glob: bool) -> frozenset[tuple[str, str]]:
        """Keys of the packages providing exactly `capability`, or a capability matching it as a glob."""
        if glob:
            return frozenset(self._keys(lambda q: q.filter_provides([capability], libdnf5.common.QueryCmp_GLOB)))
        return frozenset(self._keys(lambda q: q.filter_provides([capability])))

    def search_files(self, text: str) -> list[tuple[str, str]]:
        """Packages owning a file. "/usr/bin/7z" is exact, "7z" means any path ending in /7z, globs pass through.
        Not-installed packages are searched in primary metadata only (binaries, /etc, ...)."""
        text = text.strip()
        if not text:
            return []
        if any(c in text for c in "*?["):
            pattern = text if text.startswith(("/", "*")) else f"*/{text}"
            return self._keys(lambda q: q.filter_file([pattern], libdnf5.common.QueryCmp_GLOB))
        if text.startswith("/"):
            return self._keys(lambda q: q.filter_file([text]))
        if len(text) < 2:
            return []
        return self._keys(lambda q: q.filter_file([f"*/{text}"], libdnf5.common.QueryCmp_GLOB))

    def _keys(self, setup) -> list[tuple[str, str]]:
        q = libdnf5.rpm.PackageQuery(self._base)
        try:
            setup(q)
        except Exception:  # noqa: BLE001 - malformed capability strings raise
            return []
        # several versions of one package collapse into its catalog row
        return sorted({k for k in ((x.get_name(), x.get_arch()) for x in q) if k in self._pkgs})

    def blocked_upgrades(self) -> dict[tuple[str, str], str]:
        """Upgradable packages whose upgrade `dnf5 upgrade` would leave out now (see installable_upgrades), as
        (name, arch) -> the resolver's reason ("" past MAX_BLOCKED_REASONS). Run after `load`, apart from it: it
        resolves a full upgrade, a few tenths of a second the list does not have to wait for."""
        upgradable = upgradable_keys(self._base)
        blocked = sorted(upgradable - installable_upgrades(self._base, upgradable))
        reasons = {}
        for n, key in enumerate(blocked):
            if n >= MAX_BLOCKED_REASONS:
                reasons[key] = ""
                continue
            reasons[key] = self.blocked_reason(key)
        return reasons

    def blocked_reason(self, key: tuple[str, str]) -> str:
        """Why the upgrade of one package cannot be installed now, as the resolver's messages ("" when it gives
        none). blocked_upgrades explains the first MAX_BLOCKED_REASONS with it, the selected row the others."""
        goal = libdnf5.base.Goal(self._base)
        goal.add_upgrade(f"{key[0]}.{key[1]}")
        tr = goal.resolve()
        skipped = skipped_changes(tr)
        if not skipped and tr.get_problems() != libdnf5.base.GoalProblem_NO_PROBLEM:
            skipped = list(tr.get_resolve_logs_as_strings())  # it fails outright instead of leaving it out
        return "\n".join(skipped)

    def removal_dependents(self, remove: list[str]) -> list[tuple[str, str]]:
        """Installed packages that depend on `remove` (specs), at any depth, and would have to be removed with
        them, as keys. The real goal does not allow erasing, so these have to be marked too.

        Resolved like `dnf5 remove`: allow_erasing on a base with only the installed packages. With the
        repositories loaded, allow_erasing would also let the solver downgrade or swap packages instead."""
        if self._system_base is None:
            def load():
                base = libdnf5.base.Base()
                base.load_config()
                base.setup()
                base.get_repo_sack().load_repos(libdnf5.repo.Repo.Type_SYSTEM)
                return base
            self._system_base = waiting_for_lock(load)
        goal = libdnf5.base.Goal(self._system_base)
        for s in remove:
            goal.add_remove(s)
        goal.set_allow_erasing(True)
        tr = goal.resolve()
        if tr.get_problems() != libdnf5.base.GoalProblem_NO_PROBLEM:
            return []  # the preview will show the resolver's own message
        T = libdnf5.transaction
        found = {(tp.get_package().get_name(), tp.get_package().get_arch()) for tp in tr.get_transaction_packages()
                 if tp.get_action() == T.TransactionItemAction_REMOVE
                 and tp.get_reason() == T.TransactionItemReason_DEPENDENCY}
        return sorted(k for k in found if k in self._pkgs)

    def conflict_removals(self, request: dict) -> list[tuple[str, str]]:
        """Installed packages that stand in the way of `request` (marked changes that do not resolve), as keys: the
        ones `dnf5 install --allowerasing` would remove although they are not marked. Like Synaptic, Kram offers to
        mark them, so that switching kram-qt for kram-gtk or ffmpeg-free for ffmpeg can be done by marking.

        Only when the request resolves with them marked for removal and without allow_erasing: allowed to erase,
        the solver may also swap or downgrade packages, and that is not what is offered. [] otherwise."""
        excluded = list(request.get("exclude_weak", ()))

        def erasing(extra: list[str]):
            goal = build_goal(self._base, {**request, "exclude_weak": [*excluded, *extra]})
            goal.set_allow_erasing(True)
            return goal
        tr = self._resolve_goal(erasing, [])
        if tr.get_problems() != libdnf5.base.GoalProblem_NO_PROBLEM:
            return []
        T = libdnf5.transaction
        marked = set(request.get("remove", ()))
        # not the dependencies nothing needs any more (clean_requirements_on_remove): removing a package takes those
        # anyway, they do not stand in the way
        found = sorted({(p.get_name(), p.get_arch()) for tp in tr.get_transaction_packages()
                        if tp.get_action() == T.TransactionItemAction_REMOVE
                        and tp.get_reason() != T.TransactionItemReason_CLEAN
                        and (p := tp.get_package()).get_nevra() not in marked
                        and f"{p.get_name()}.{p.get_arch()}" not in marked and p.get_name() not in marked})
        found = [k for k in found if k in self._pkgs]
        if not found:
            return []
        with_them = {**request, "remove": [*request.get("remove", ()), *(f"{n}.{a}" for n, a in found)]}

        def plain(extra: list[str]):
            return build_goal(self._base, {**with_them, "exclude_weak": [*excluded, *extra]})
        if self._resolve_goal(plain, []).get_problems() != libdnf5.base.GoalProblem_NO_PROBLEM:
            return []
        return found

    def resolve(self, request: dict, sizes: bool = True) -> TransactionPreview:
        """Dry-run the transaction the helper would run (same goal builder), without root or downloads.

        With `sizes`, what each recommendation of a marked package adds with everything it pulls in is
        resolved too (a few more resolves); the others get their own size."""
        excluded = list(request.get("exclude_weak", ()))

        def goal(extra: list[str]):
            return build_goal(self._base, {**request, "exclude_weak": [*excluded, *extra]})
        return self._resolve_preview(goal, set(excluded), self._marked_names(request), sizes)

    def open_local(self, path: str) -> LocalTarget:
        """Add a package file to the catalog's base (until `forget_local`) and say what installing it means.
        Raises LocalFileError for a file libdnf5 cannot read as a package."""
        package = self._local.get(path)
        if package is None:
            package = self._local[path] = cmdline_package(self._base, path)
        q = libdnf5.rpm.PackageQuery(self._base)
        q.filter_installed()
        q.filter_name([package.get_name()])
        # noarch <-> arch changes between versions still count as the same package
        same_arch = [x for x in q if x.get_arch() == package.get_arch()]
        installed = sorted(same_arch or list(q), key=_evr_sort_key)
        # kernels and the like: another version goes next to the installed ones (installonlypkgs)
        only = libdnf5.rpm.PackageQuery(self._base)
        only.filter_repo_id(["@commandline"])
        only.filter_installonly()
        installonly = any(x.get_package_path() == package.get_package_path() for x in only)
        action, installed_evr = "install", ""
        if installed:
            newest = installed[-1]
            installed_evr = newest.get_evr()
            order = rpm.labelCompare(_evr_tuple(package), _evr_tuple(newest))
            if any(x.get_evr() == package.get_evr() and x.get_arch() == package.get_arch() for x in installed):
                action = "reinstall"
            elif installonly:
                action = "alongside"
            else:
                action = "upgrade" if order > 0 else "downgrade"
        q = libdnf5.rpm.PackageQuery(self._base)
        q.filter_available()
        q.filter_name([package.get_name()])
        q.filter_repo_id(["@commandline"], libdnf5.common.QueryCmp_NEQ)
        repo = sorted(q, key=_evr_sort_key)
        deps = {"requires": package.get_requires(), "recommends": package.get_recommends(),
                "suggests": package.get_suggests()}
        return LocalTarget(action, installed_evr, repo[-1].get_evr() if repo else "",
                           repo[-1].get_repo_id() if repo else "",
                           {kind: [self._requirement(package, r) for r in _own_deps(reldeps)]
                            for kind, reldeps in deps.items()},
                           repo_newer=bool(repo) and rpm.labelCompare(_evr_tuple(repo[-1]), _evr_tuple(package)) > 0)

    def _requirement(self, package, reldep) -> Requirement:
        """What provides `reldep`: ~1 ms each, rich "(a or b)" dependencies included."""
        q = libdnf5.rpm.PackageQuery(self._base)
        q.filter_provides(reldep)
        installed, available, own = set(), set(), False
        for x in q:
            if x.get_repo_id() == "@commandline":
                own |= x.get_package_path() == package.get_package_path()
            elif x.is_installed():
                installed.add(x.get_name())
            else:
                available.add(x.get_name())
        return Requirement(reldep.to_string(), sorted(installed), sorted(available), own)

    def resolve_local(self, path: str, action: str, exclude_weak: list[str], sizes: bool = True) -> TransactionPreview:
        """Like `resolve`, for a file from `open_local`; `action` is the helper's (install, reinstall, downgrade)."""
        package = self._local[path]

        def goal(extra: list[str]):
            return local_goal(self._base, package, action, [*exclude_weak, *extra])
        return self._resolve_preview(goal, set(exclude_weak), {package.get_name()}, sizes)

    def forget_local(self) -> None:
        """Hide the added package files again: they must not turn up as candidates for the marks."""
        q = libdnf5.rpm.PackageQuery(self._base)
        q.filter_repo_id(["@commandline"])
        if not q.empty():
            self._base.get_rpm_package_sack().add_user_excludes(q)
        self._local = {}

    def _resolve_preview(self, make_goal, excluded: set[str], marked: set[str], sizes: bool) -> TransactionPreview:
        tr = self._resolve_goal(make_goal, [])
        if (problems := tr.get_problems()) != libdnf5.base.GoalProblem_NO_PROBLEM:
            logs = list(tr.get_resolve_logs_as_strings())
            # the problem of a requested version that only the lock excludes has its own flag; the solver's own
            # problems name the lock in their text ("... is filtered out by versionlock")
            locked = bool(problems & libdnf5.base.GoalProblem_EXCLUDED_VERSIONLOCK) or any(
                "versionlock" in text for text in logs)
            return TransactionPreview([], logs, 0, 0, versionlock=locked)
        preview = self._preview(tr)
        preview.skipped = skipped_changes(tr)
        preview.recommendations = self._recommendations(tr, excluded, marked)
        own = {i.name: i.install_size for i in preview.items}
        sized = 0
        for rec in sorted(preview.recommendations, key=lambda r: not r.direct):
            if not rec.checked:
                continue
            if sizes and rec.direct and sized < MAX_SIZED_RECOMMENDATIONS:
                sized += 1
                without = self._resolve_goal(make_goal, rec.excludes)
                if without.get_problems() == libdnf5.base.GoalProblem_NO_PROBLEM:
                    less = self._preview(without)
                    rec.size, rec.count, rec.exact = (preview.size_change - less.size_change,
                                                      len(preview.items) - len(less.items), True)
                    continue
            rec.size, rec.count = sum(own.get(n, 0) for n in rec.brings), len(rec.brings)
        return preview

    def _resolve_goal(self, make_goal, extra_excludes: list[str]):
        # the goal builders add exclude_weak to the base's config; this base lives on, so put it back
        config = self._base.get_config()
        configured = config.exclude_from_weak
        try:
            return make_goal(list(extra_excludes)).resolve()
        finally:
            config.exclude_from_weak = configured

    def _preview(self, tr) -> TransactionPreview:
        T = libdnf5.transaction
        actions = {T.TransactionItemAction_INSTALL: "install", T.TransactionItemAction_UPGRADE: "upgrade",
                   T.TransactionItemAction_DOWNGRADE: "downgrade", T.TransactionItemAction_REINSTALL: "reinstall",
                   T.TransactionItemAction_REMOVE: "remove", T.TransactionItemAction_REASON_CHANGE: "reason"}
        reasons = {T.TransactionItemReason_USER: "user", T.TransactionItemReason_DEPENDENCY: "dependency",
                   T.TransactionItemReason_WEAK_DEPENDENCY: "weak", T.TransactionItemReason_GROUP: "group",
                   T.TransactionItemReason_CLEAN: "clean"}
        items, download, change = [], 0, 0
        for tp in tr.get_transaction_packages():
            p = tp.get_package()
            act = tp.get_action()
            if act == T.TransactionItemAction_REPLACED:  # the old side of an upgrade/downgrade
                change -= p.get_install_size()
                continue
            if act not in actions:
                continue
            old = [r.get_evr() for r in tp.get_replaces()]
            kind = actions[act]
            if kind in ("install", "upgrade", "downgrade", "reinstall"):
                download += p.get_download_size()
                change += p.get_install_size()
            elif kind == "remove":
                change -= p.get_install_size()
            items.append(PreviewItem(
                action=kind, name=p.get_name(), arch=p.get_arch(), evr=p.get_evr(), old_evr=old[0] if old else "",
                repo_id=p.get_repo_id() if kind != "remove" else p.get_from_repo_id(),
                download_size=p.get_download_size() if kind != "remove" else 0,
                install_size=p.get_install_size(), reason=reasons.get(tp.get_reason(), ""),
            ))
        items.sort(key=lambda i: (i.action, i.reason != "user", i.name))
        mark_rotated(items)
        self._mark_older_than_groups(tr, items)
        # the helper downloads into the system cache; this base, as a user, has a cache of its own
        config = self._base.get_config()
        mine, system = config.cachedir, config.system_cachedir
        to_download, _change = transaction_space(
            tr, lambda path: system + path.removeprefix(mine) if path.startswith(mine) else path)
        return TransactionPreview(items, [], download, change, groups=self._preview_groups(tr, actions),
                                  to_download=to_download, cache_dir=system)

    def _mark_older_than_groups(self, tr, items: list[PreviewItem]) -> None:
        """Set PreviewItem.before on the removals a removed group or environment takes although the package was
        installed before it: `dnf5 group remove` takes the packages of the group, whoever brought them."""
        T = libdnf5.transaction
        removed_groups = [tg.get_group() for tg in tr.get_transaction_groups()
                          if tg.get_action() == T.TransactionItemAction_REMOVE]
        if not removed_groups:
            return
        lang = language() or ""

        def name(x) -> str:
            return (x.get_translated_name(lang) if lang else "") or x.get_name()
        times = comps_install_times(self._base)
        # a package is taken by the removed groups that list it; an environment removed with them counts for its groups
        envs = {}
        for te in tr.get_transaction_environments():
            if te.get_action() == T.TransactionItemAction_REMOVE:
                e = te.get_environment()
                for gid in (*e.get_groups(), *(e.get_default_groups() if hasattr(e, "get_default_groups") else ())):
                    envs.setdefault(gid, []).append((ENVIRONMENT_PREFIX + e.get_environmentid(), name(e)))
        owners: dict[str, list[tuple[str, str]]] = {}
        for g in removed_groups:
            for p in g.get_packages():
                owners.setdefault(p.get_name(), []).extend(
                    [(g.get_groupid(), name(g)), *envs.get(g.get_groupid(), [])])
        installed_at = {}
        for tp in tr.get_transaction_packages():
            if tp.get_action() == T.TransactionItemAction_REMOVE:
                p = tp.get_package()
                installed_at[(p.get_name(), p.get_arch())] = p.get_install_time()
        for i in items:
            if i.action != "remove" or i.name not in owners or (i.name, i.arch) not in installed_at:
                continue
            known = [(times[key], label) for key, label in owners[i.name] if key in times]
            if known:
                since, label = max(known)
                if installed_at[(i.name, i.arch)] < since:
                    i.before = label

    @staticmethod
    def _preview_groups(tr, actions: dict) -> list[PreviewGroup]:
        lang = language() or ""
        groups = []
        for tg in tr.get_transaction_groups():
            if (kind := actions.get(tg.get_action())) not in ("install", "upgrade", "remove"):
                continue
            g = tg.get_group()
            groups.append(PreviewGroup(kind, g.get_groupid(),
                                       (g.get_translated_name(lang) if lang else "") or g.get_name()))
        for te in tr.get_transaction_environments():
            if (kind := actions.get(te.get_action())) not in ("install", "upgrade", "remove"):
                continue
            e = te.get_environment()
            groups.append(PreviewGroup(kind, ENVIRONMENT_PREFIX + e.get_environmentid(),
                                       (e.get_translated_name(lang) if lang else "") or e.get_name()))
        return sorted(groups, key=lambda g: (g.action, g.name.lower()))

    def _marked_names(self, request: dict) -> set[str]:
        marked = set()
        for field in ("install", "upgrade", "reinstall", "downgrade"):
            for spec in request.get(field, ()):
                q = libdnf5.rpm.PackageQuery(self._base)
                if q.resolve_pkg_spec(spec, libdnf5.base.ResolveSpecSettings(), False)[0]:
                    marked |= {x.get_name() for x in q}
        return marked

    def _recommendations(self, tr, excluded: set[str], marked: set[str]) -> list[Recommendation]:
        """The recommendations that bring packages into `tr`, plus the ones the user unchecked (`excluded`).
        Those of the `marked` packages are direct."""
        T = libdnf5.transaction
        installing = (T.TransactionItemAction_INSTALL, T.TransactionItemAction_UPGRADE,
                      T.TransactionItemAction_DOWNGRADE, T.TransactionItemAction_REINSTALL)
        pkgs, weak, hard = [], set(), set()
        for tp in tr.get_transaction_packages():
            if tp.get_action() in installing:
                p = tp.get_package()
                pkgs.append(p)
                (weak if tp.get_reason() == T.TransactionItemReason_WEAK_DEPENDENCY else hard).add(p.get_name())
        recs: dict[str, Recommendation] = {}
        for p in pkgs:
            name = p.get_name()
            for reldep in p.get_recommends():
                q = libdnf5.rpm.PackageQuery(self._base)
                q.filter_provides(reldep)
                providers = sorted({x.get_name() for x in q})
                brings = [n for n in providers if n in weak]
                if not brings and not excluded.intersection(providers):
                    continue  # already installed, or the solver did not want it
                if not brings:
                    q.filter_installed()
                    if not q.empty():
                        continue  # satisfied by an installed package anyway
                what = reldep.to_string()
                if what in recs:
                    recs[what].by.append(name)
                    recs[what].direct |= name in marked
                else:
                    recs[what] = Recommendation(what, [name], name in marked, brings, providers,
                                                needed=[n for n in providers if n in hard] if not brings else [])
        # pulled in by their own Supplements: (language packs, plugins), not by anything's Recommends:
        covered = {n for r in recs.values() for n in r.brings}
        for n in sorted(weak - covered):
            recs[n] = Recommendation(n, [], False, [n], [n])
        # unchecked ones whose recommending package left with them stay listed, so they can be checked again
        listed = {n for r in recs.values() for n in r.excludes}
        for n in sorted(excluded - listed):
            recs[n] = Recommendation(n, [], False, [], [n], needed=[n] if n in hard else [])
        return sorted(recs.values(), key=lambda r: (not r.direct, r.what.lstrip("(").lower()))

    def find_provider(self, reldep: str) -> tuple[str, str] | None:
        """Best package in the catalog that satisfies a requirement string: installed first, then candidate."""
        q = libdnf5.rpm.PackageQuery(self._base)
        try:
            q.filter_provides([reldep])
        except Exception:  # noqa: BLE001 - rich deps like "(a if b)" are not plain provides
            return None
        found = [(x.get_name(), x.get_arch()) for x in q]
        installed = [k for k in found if k in self._pkgs and self._pkgs[k][0] is not None]
        known = [k for k in found if k in self._pkgs]
        return (installed or known or [None])[0]

    # ---------------------------------------------------------------- history

    def history(self) -> list[HistoryTransaction]:
        """dnf's transactions, the newest first, without their packages."""
        return read_transactions(self._base)

    def history_items(self, ids: list[int]) -> dict[int, tuple[HistoryItem, ...]]:
        return read_items(self._base, ids)

    def package_states(self, keys: Iterable[tuple[str, str]]) -> dict[tuple[str, str], PackageState]:
        """What the system has now of these name.arch: for planning an undo, see `plan_undo`."""
        keys = set(keys)
        names = sorted({name for name, _arch in keys})
        installed: dict[tuple[str, str], list] = {}
        available: dict[tuple[str, str], set[str]] = {}
        q = libdnf5.rpm.PackageQuery(self._base)
        q.filter_name(names)
        only = libdnf5.rpm.PackageQuery(self._base)
        only.filter_installonly()
        installonly_names = {p.get_name() for p in only}
        for p in q:
            key = p.get_name(), p.get_arch()
            if key not in keys:
                continue
            if p.is_installed():
                installed.setdefault(key, []).append(p)
            else:
                available.setdefault(key, set()).add(p.get_evr())
        states = {}
        for key in keys:
            have = sorted(installed.get(key, []), key=_evr_sort_key)
            cand = self._pkgs.get(key, (None, None))[1]
            states[key] = PackageState(tuple(p.get_evr() for p in have), frozenset(available.get(key, ())),
                                       cand.get_evr() if cand is not None and not cand.is_installed() else "",
                                       ITEM_REASONS.get(have[-1].get_reason()) if have else None,
                                       installonly=key[0] in installonly_names)
        return states
