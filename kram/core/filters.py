"""Sidebar filters (Synaptic's Status / Origin views) as plain predicates over PkgRow. No Qt."""
from collections import Counter
from collections.abc import Callable, Container
from dataclasses import dataclass

from ..i18n import _
from .model import CatalogSnapshot, Origin, PkgRow, Status
from .origin import classify, display_repo

Predicate = Callable[[PkgRow], bool]


@dataclass(slots=True)
class FilterEntry:
    id: str                    # stable, saved in settings to restore the selection
    label: str
    predicate: Predicate
    count: int | None = None
    origin: Origin | None = None   # for the icon
    indent: int = 0
    query: tuple[str, int] | None = None   # search-history entries: (text, search mode)
    status: Status | None = None   # for the icon (comps groups: installed or not)
    tip: str = ""


def _all(_r: PkgRow) -> bool:
    return True


def _with_counts(entries: list[FilterEntry], rows: list[PkgRow]) -> list[FilterEntry]:
    for e in entries:
        e.count = sum(1 for r in rows if e.predicate(r))
    return entries


def status_filters(snap: CatalogSnapshot, marked: Container[tuple[str, str]] | None = None) -> list[FilterEntry]:
    def status_is(*statuses: Status) -> Predicate:
        return lambda r: r.status in statuses

    installed_like = (Status.INSTALLED, Status.UPGRADABLE, Status.NEWER, Status.ORPHAN, Status.UNNEEDED)
    return _with_counts([
        FilterEntry("status:all", _("All"), _all),
        FilterEntry("status:installed", _("Installed"), status_is(*installed_like)),
        FilterEntry("status:not-installed", _("Not installed"), status_is(Status.NOT_INSTALLED)),
        FilterEntry("status:upgradable", _("Upgradable"), status_is(Status.UPGRADABLE)),
        FilterEntry("status:user", _("Installed by user"), lambda r: r.installed and r.user_installed),
        FilterEntry("status:unneeded", _("Unneeded dependencies"), status_is(Status.UNNEEDED)),
        FilterEntry("status:orphan", _("Orphaned (no repository)"), status_is(Status.ORPHAN)),
        FilterEntry("status:newer", _("Newer than repository"), status_is(Status.NEWER)),
        *([FilterEntry("status:marked", _("Marked"), lambda r: r.key in marked)] if marked is not None else []),
    ], snap.rows)


def origin_filters(snap: CatalogSnapshot) -> list[FilterEntry]:
    rows = snap.rows

    def origin_is(o: Origin) -> Predicate:
        return lambda r: r.origin is o

    def repo_is(repo_id: str) -> Predicate:
        return lambda r: r.origin_repo == repo_id

    per_repo = Counter(r.origin_repo for r in rows)
    repos_by_origin: dict[Origin, list[str]] = {}
    for repo_id in per_repo:
        repos_by_origin.setdefault(classify(repo_id), []).append(repo_id)

    entries = [FilterEntry("origin:all", _("All origins"), _all)]
    groups = [
        (Origin.FEDORA, _("Fedora (official)"), False),
        (Origin.COPR, "COPR", True),
        (Origin.THIRD_PARTY, _("Third-party"), True),
        (Origin.LOCAL, _("Local (@commandline)"), False),
        (Origin.UNKNOWN, _("Unknown (not recorded)"), False),
    ]
    for origin, label, expand in groups:
        if origin not in repos_by_origin:
            continue
        entries.append(FilterEntry(f"origin:{origin.value}", label, origin_is(origin), origin=origin))
        if expand:
            for repo_id in sorted(repos_by_origin[origin], key=lambda rid: (-per_repo[rid], rid)):
                entries.append(FilterEntry(f"repo:{repo_id}", display_repo(repo_id), repo_is(repo_id),
                                           origin=origin, indent=1))
    return _with_counts(entries, rows)


def group_filters(snap: CatalogSnapshot) -> list[FilterEntry]:
    def in_group(names: frozenset[str]) -> Predicate:
        return lambda r: r.name in names

    entries = [FilterEntry("group:all", _("All groups"), _all)]
    entries += [FilterEntry(f"group:{g.id}", g.name, in_group(g.packages), tip=g.description,
                            status=Status.INSTALLED if g.installed else Status.NOT_INSTALLED)
                for g in snap.groups]
    return _with_counts(entries, snap.rows)


def custom_filter_entries(snap: CatalogSnapshot, filters: list) -> list[FilterEntry]:
    """Entries for the user's custom filters (kram.core.custom_filters.CustomFilter), in their order."""
    return _with_counts([FilterEntry(f"custom:{f.name}", f.name, f.compile(snap)) for f in filters], snap.rows)
