"""Sidebar filters (Synaptic's Status / Origin views) as plain predicates over PkgRow. No Qt."""
from collections import Counter
from collections.abc import Callable, Container
from dataclasses import dataclass

from ..i18n import _
from .model import HIGH_SECURITY_LEVELS, CatalogSnapshot, Origin, PkgRow, Status
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
    group: str | None = None   # comps group id for its themed icon ("" for all groups)
    bold: bool = False   # comps groups: installed
    tip: str = ""
    hide_empty: bool = False   # left out of the sidebar while it matches nothing


def _all(_r: PkgRow) -> bool:
    return True


def _with_counts(entries: list[FilterEntry], rows: list[PkgRow]) -> list[FilterEntry]:
    for e in entries:
        e.count = sum(1 for r in rows if e.predicate(r))
    return entries


def visible_entries(entries: list[FilterEntry], keep: str | None = None) -> list[FilterEntry]:
    """Entries to show: hide_empty ones with no matches are left out, except `keep` (the selected one), so the
    selection does not jump away from the filter the package list shows."""
    return [e for e in entries if not (e.hide_empty and e.count == 0 and e.id != keep)]


def has_update_type(kind: str) -> Predicate:
    """An upgrade with an advisory of that type ("security", "bugfix", "enhancement")."""
    return lambda r: any(a.type == kind for a in r.advisories)


# the ways to mark upgrades by their advisories, besides all of them: security fixes, only those rated critical or
# important, security and bug fixes (everything but enhancements)
UPGRADES_SECURITY, UPGRADES_SECURITY_HIGH, UPGRADES_FIXES = "security", "security_high", "fixes"


def upgrades_by_kind(rows: list[PkgRow]) -> dict[str, list[PkgRow]]:
    """The upgradable rows of each UPGRADES_* kind. Upgrades without advisories are in none of them."""
    kinds: dict[str, list[PkgRow]] = {UPGRADES_SECURITY: [], UPGRADES_SECURITY_HIGH: [], UPGRADES_FIXES: []}
    for r in rows:
        if r.status is not Status.UPGRADABLE or not r.advisories:
            continue
        types = {a.type for a in r.advisories}
        if "security" in types:
            kinds[UPGRADES_SECURITY].append(r)
            if any(a.level in HIGH_SECURITY_LEVELS for a in r.advisories):
                kinds[UPGRADES_SECURITY_HIGH].append(r)
        if types & {"security", "bugfix"}:
            kinds[UPGRADES_FIXES].append(r)
    return kinds


def status_filters(snap: CatalogSnapshot, marked: Container[tuple[str, str]] | None = None) -> list[FilterEntry]:
    def status_is(*statuses: Status) -> Predicate:
        return lambda r: r.status in statuses

    installed_like = (Status.INSTALLED, Status.UPGRADABLE, Status.NEWER, Status.ORPHAN, Status.UNNEEDED)
    return _with_counts([
        FilterEntry("status:all", _("All"), _all),
        FilterEntry("status:installed", _("Installed"), status_is(*installed_like)),
        FilterEntry("status:not-installed", _("Not installed"), status_is(Status.NOT_INSTALLED)),
        FilterEntry("status:upgradable", _("Upgradable"), status_is(Status.UPGRADABLE)),
        FilterEntry("status:security", _("Security updates"), has_update_type("security"), indent=1,
                    tip=_("Upgrades that fix a security issue, by their advisories"), hide_empty=True),
        FilterEntry("status:bugfix", _("Bug fix updates"), has_update_type("bugfix"), indent=1,
                    tip=_("Upgrades that fix bugs, by their advisories"), hide_empty=True),
        FilterEntry("status:user", _("Installed by user"), lambda r: r.installed and r.user_installed),
        # what dnf autoremove removes, orphaned and upgradable ones included
        FilterEntry("status:unneeded", _("Unneeded dependencies"), lambda r: r.unneeded),
        FilterEntry("status:orphan", _("Orphaned (no repository)"), status_is(Status.ORPHAN)),
        FilterEntry("status:newer", _("Newer than repository"), status_is(Status.NEWER)),
        # shown even while empty: it tells that packages can be locked (Package → Lock Version)
        FilterEntry("status:locked", _("Locked versions"), lambda r: r.locked,
                    tip=_("Packages dnf's version lock keeps at their version")),
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
        (Origin.FEDORA, _("Fedora (official)"), True),
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

    entries = [FilterEntry("group:all", _("All groups"), _all, group="")]
    entries += [FilterEntry(f"group:{g.id}", g.name, in_group(g.packages), tip=g.description,
                            group=g.id, bold=g.installed)
                for g in snap.groups]
    return _with_counts(entries, snap.rows)


def custom_filter_entries(snap: CatalogSnapshot, filters: list) -> list[FilterEntry]:
    """Entries for the user's custom filters (kram.core.custom_filters.CustomFilter), in their order."""
    return _with_counts([FilterEntry(f"custom:{f.name}", f.name, f.compile(snap)) for f in filters], snap.rows)
