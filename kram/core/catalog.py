"""libdnf5 access for the GUI process (unprivileged, reads the system metadata cache).

Not thread-safe: every method must be called from the same single worker thread.
"""
import functools
import time
from collections import Counter

import libdnf5
import rpm

from ..helper.kram_helper import build_goal
from ..i18n import language
from .model import (
    CatalogSnapshot,
    ChangelogEntry,
    GroupInfo,
    PkgDetails,
    PkgRow,
    PreviewItem,
    RepoInfo,
    Status,
    TransactionPreview,
    VersionInfo,
)
from .origin import classify

MAX_CHANGELOG = 30
# libdnf5 glob scans take ~0.3-0.9 s and can't be cancelled; too-short patterns would block the worker for
# nothing useful
MIN_SUBSTRING_QUERY = 3
# not-installed debug packages are noise in a package list (TODO: make it a setting)
HIDDEN_SUFFIXES = ("-debuginfo", "-debugsource")


def _evr_tuple(pkg):
    return pkg.get_epoch() or "0", pkg.get_version(), pkg.get_release()


_evr_cmp_key = functools.cmp_to_key(rpm.labelCompare)


def _evr_sort_key(pkg):
    return _evr_cmp_key(_evr_tuple(pkg))


def _reldeps(reldep_list) -> list[str]:
    return [r.to_string() for r in reldep_list]


class Catalog:
    def __init__(self) -> None:
        self._base = None
        # (name, arch) -> (installed pkg | None, candidate pkg | None); lives only on the worker thread
        self._pkgs: dict[tuple[str, str], tuple[object, object]] = {}
        self._user_installed: set[tuple[str, str]] = set()

    def load(self) -> CatalogSnapshot:
        t0 = time.monotonic()
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
        base.setup()
        config.cache_only = True
        repo_sack = base.get_repo_sack()
        repo_sack.create_repos_from_system_configuration()
        repo_sack.load_repos()
        self._base = base

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

        upgradable = keys(lambda q: q.filter_upgradable())
        orphans = keys(lambda q: q.filter_extras())
        unneeded = keys(lambda q: q.filter_unneeded())
        user_installed = keys(lambda q: q.filter_userinstalled())

        rows: list[PkgRow] = []
        pkgs: dict[tuple[str, str], tuple[object, object]] = {}
        n_upgradable = 0

        for p in installed:
            key = (p.get_name(), p.get_arch())
            cand = cand_by_key.pop(key, None)
            from_repo = p.get_from_repo_id()
            if key in orphans or cand is None:
                status = Status.ORPHAN
            elif key in upgradable:
                status = Status.UPGRADABLE
                n_upgradable += 1
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
                user_installed=key in user_installed, from_repo_id=from_repo,
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
            ))
            pkgs[key] = (None, cand)

        rows.sort(key=lambda r: (r.name.lower(), r.arch))
        self._pkgs = pkgs
        self._user_installed = user_installed
        # ~0.1 s for 70k packages; cheap enough to make full-description search instant
        descriptions = [(pkgs[r.key][0] or pkgs[r.key][1]).get_description() for r in rows]
        return CatalogSnapshot(rows, n_installed, n_upgradable, time.monotonic() - t0,
                               basearch=basearch, releasever=base.get_vars().get_value("releasever"),
                               repos=self._repos(), descriptions=descriptions, groups=self._groups())

    def _groups(self) -> list[GroupInfo]:
        # an installed group shows up twice (system state + repo metadata): merge by id
        lang = language() or ""
        groups: dict[str, GroupInfo] = {}
        for g in libdnf5.comps.GroupQuery(self._base):
            gid = g.get_groupid()
            if gid in groups:
                groups[gid].installed |= g.get_installed()
                continue
            if not g.get_uservisible():
                continue
            groups[gid] = GroupInfo(
                gid, (g.get_translated_name(lang) if lang else "") or g.get_name(),
                (g.get_translated_description(lang) if lang else "") or g.get_description(),
                g.get_installed(), frozenset(p.get_name() for p in g.get_packages()))
        return sorted(groups.values(), key=lambda g: g.name.lower())

    def _repos(self) -> list[RepoInfo]:
        repos = []
        for r in libdnf5.repo.RepoQuery(self._base):
            if r.get_id().startswith("@"):
                continue
            try:
                age = r.get_age() if r.is_enabled() else None
            except Exception:  # noqa: BLE001 - not loaded / no cache
                age = None
            repos.append(RepoInfo(r.get_id(), r.get_name(), r.is_enabled(), classify(r.get_id()), age,
                                  priority=r.get_priority(), file_path=r.get_repo_file_path()))
        repos.sort(key=lambda r: r.id)
        return repos

    def repo_package_counts(self) -> Counter[str]:
        """Available packages (all versions) per enabled repo."""
        q = libdnf5.rpm.PackageQuery(self._base)
        q.filter_available()
        return Counter(p.get_repo_id() for p in q)

    def details(self, key: tuple[str, str]) -> PkgDetails:
        inst, cand = self._pkgs[key]
        p = inst or cand

        required_by: list[tuple[str, str]] = []
        if inst is not None:
            q = libdnf5.rpm.PackageQuery(self._base)
            q.filter_installed()
            q.filter_requires(inst.get_provides())
            required_by = sorted({(x.get_name(), x.get_arch()) for x in q if x.get_name() != inst.get_name()})

        # every installed version: installonly packages (kernel) keep several side by side
        q = libdnf5.rpm.PackageQuery(self._base)
        q.filter_installed()
        q.filter_name([key[0]])
        q.filter_arch([key[1]])
        versions = [VersionInfo(x.get_evr(), "@System", installed=True)
                    for x in sorted(q, key=_evr_sort_key, reverse=True)]
        q = libdnf5.rpm.PackageQuery(self._base)
        q.filter_available()
        q.filter_name([key[0]])
        q.filter_arch([key[1]])
        avail = sorted(q, key=_evr_sort_key, reverse=True)
        cand_evr = cand.get_evr() if cand else None
        versions += [VersionInfo(x.get_evr(), x.get_repo_id(), candidate=x.get_evr() == cand_evr) for x in avail]

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
        """Packages providing a capability. Plain words match the capability name exactly, falling back to
        *word*; globs are passed through."""
        text = text.strip()
        if not text:
            return []
        if any(c in text for c in "*?["):
            return self._keys(lambda q: q.filter_provides([text], libdnf5.common.QueryCmp_GLOB))
        exact = self._keys(lambda q: q.filter_provides([text]))
        if exact or len(text) < MIN_SUBSTRING_QUERY:
            return exact
        return self._keys(lambda q: q.filter_provides([f"*{text}*"], libdnf5.common.QueryCmp_GLOB))

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

    def resolve(self, request: dict) -> TransactionPreview:
        """Dry-run the transaction the helper would run (same goal builder), without root or downloads."""
        tr = build_goal(self._base, request).resolve()
        if tr.get_problems() != libdnf5.base.GoalProblem_NO_PROBLEM:
            return TransactionPreview([], list(tr.get_resolve_logs_as_strings()), 0, 0)

        T = libdnf5.transaction
        actions = {T.TransactionItemAction_INSTALL: "install", T.TransactionItemAction_UPGRADE: "upgrade",
                   T.TransactionItemAction_DOWNGRADE: "downgrade", T.TransactionItemAction_REINSTALL: "reinstall",
                   T.TransactionItemAction_REMOVE: "remove", T.TransactionItemAction_REASON_CHANGE: "reason"}
        reasons = {T.TransactionItemReason_USER: "user", T.TransactionItemReason_DEPENDENCY: "dependency",
                   T.TransactionItemReason_WEAK_DEPENDENCY: "weak", T.TransactionItemReason_CLEAN: "clean"}
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
        return TransactionPreview(items, [], download, change)

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
