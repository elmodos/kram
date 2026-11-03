"""libdnf5 access for the GUI process (unprivileged, reads the system metadata cache).

Not thread-safe: every method must be called from the same single worker thread.
"""
import time

import libdnf5
import rpm

from .model import CatalogSnapshot, PkgRow, Status
from .origin import classify


def _evr_tuple(pkg):
    return pkg.get_epoch() or "0", pkg.get_version(), pkg.get_release()


class Catalog:
    def __init__(self) -> None:
        self._base = None
        # (name, arch) -> (installed pkg | None, candidate pkg | None); lives only on the worker thread
        self._pkgs: dict[tuple[str, str], tuple[object, object]] = {}

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
                user_installed=key in user_installed,
            ))
            pkgs[key] = (p, cand)

        n_installed = len(rows)
        for key, cand in cand_by_key.items():
            if key[1] not in arches:
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
        return CatalogSnapshot(rows, n_installed, n_upgradable, time.monotonic() - t0)

    def details(self, key: tuple[str, str]) -> dict:
        inst, cand = self._pkgs[key]
        p = inst or cand
        return {
            "nevra": p.get_nevra(),
            "summary": p.get_summary(),
            "description": p.get_description(),
            "url": p.get_url(),
            "license": p.get_license(),
            "requires": [r.to_string() for r in p.get_requires()],
            "recommends": [r.to_string() for r in p.get_recommends()],
            "provides": [r.to_string() for r in p.get_provides()],
        }
