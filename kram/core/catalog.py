"""libdnf5 access for the GUI process (unprivileged, reads the system metadata cache).

Not thread-safe: every method must be called from the same single worker thread.
"""
import functools
import time

import libdnf5
import rpm

from .model import CatalogSnapshot, ChangelogEntry, PkgDetails, PkgRow, RepoInfo, Status, VersionInfo
from .origin import classify

MAX_CHANGELOG = 30
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
        base.setup()
        base.get_config().cache_only = True
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
        return CatalogSnapshot(rows, n_installed, n_upgradable, time.monotonic() - t0,
                               basearch=basearch, repos=self._repos())

    def _repos(self) -> list[RepoInfo]:
        repos = []
        for r in libdnf5.repo.RepoQuery(self._base):
            if r.get_id().startswith("@"):
                continue
            try:
                age = r.get_age() if r.is_enabled() else None
            except Exception:  # noqa: BLE001 - not loaded / no cache
                age = None
            repos.append(RepoInfo(r.get_id(), r.get_name(), r.is_enabled(), classify(r.get_id()), age))
        repos.sort(key=lambda r: r.id)
        return repos

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
