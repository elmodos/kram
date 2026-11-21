"""The package list's columns: their headers, what each cell shows, and how each column sorts.

Toolkit-free: a front end asks for a cell's text, tooltip, icon reference and style, and draws them its own way.
The functions are split by aspect (`cell_text`, `cell_tooltip`, `cell_icon`, `cell_style`) because Qt asks for one
aspect at a time, many times a second while the list scrolls; `cell` puts them together for a toolkit that wants
them all at once.
"""
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cache

from ..core.evr import evr_ranks
from ..core.marks import ACTION_LABELS, Action, MarkSet
from ..core.model import PkgRow, Reason, Status
from ..core.origin import display_repo
from ..i18n import _, pgettext
from .icons import ORIGIN_LABEL, IconRef, status_icon_ref

# new columns come last (the update type at logical index 9, the download size at 10) so that saved header states
# keep their columns; the window shows them where they belong: the update type after the latest version, the
# download size after the installed size
(COL_STATUS, COL_ORIGIN, COL_NAME, COL_INSTALLED, COL_REASON, COL_CANDIDATE, COL_REPO, COL_SIZE, COL_SUMMARY,
 COL_ADVISORY, COL_DOWNLOAD) = range(11)
# TRANSLATORS: "S" is the narrow status column (Synaptic convention); keep it one letter
HEADERS = [_("S"), "", _("Package"), _("Installed version"), _("Reason"), _("Latest version"), _("Repository"),
           _("Installed size"), _("Summary"), _("Update type"), _("Download size")]
# the tooltips of the headers that show no title
HEADER_TIPS = {COL_STATUS: _("Status"), COL_ORIGIN: _("Origin")}
# columns the header's context menu can hide (the first three identify the row), in the order it lists them
HIDEABLE = (COL_INSTALLED, COL_REASON, COL_CANDIDATE, COL_ADVISORY, COL_REPO, COL_SIZE, COL_DOWNLOAD, COL_SUMMARY)
ALIGN_RIGHT = frozenset((COL_SIZE, COL_DOWNLOAD))

# kram.core.model.ADVISORY_LEVELS
ADVISORY_LABEL = {
    "critical": _("Security: critical"),
    "important": _("Security: important"),
    "moderate": _("Security: moderate"),
    "low": _("Security: low"),
    "security": _("Security"),
    "bugfix": _("Bug fix"),
    "enhancement": _("Enhancement"),
    "other": pgettext("update type", "Other"),
}


def shown_advisories(r: PkgRow) -> tuple:
    """The advisories of the upgrade, or else of the upgrade the version lock holds back."""
    return r.advisories or r.held_advisories


def advisory_tip(r: PkgRow) -> str | None:
    """The advisories of an upgrade, one per line: "Security: important — FEDORA-2026-… — title"."""
    if not (found := shown_advisories(r)):
        return None
    return "\n".join(" — ".join(filter(None, (ADVISORY_LABEL[a.level], a.id, a.title))) for a in found)


def held_tip(r: PkgRow) -> str:
    return _("Version {version} is held back by the version lock").format(version=r.held_evr)


def lock_tip(r: PkgRow) -> str:
    """The lock's entries, one per line: "Version locked: evr = 3.6a-1.fc44"."""
    return "\n".join(_("Version locked: {conditions}").format(conditions=lock.conditions) for lock in r.locks)


REASON_LABEL = {
    Reason.USER: _("user"),
    Reason.GROUP: _("group"),
    Reason.EXTERNAL: _("not recorded"),
    Reason.DEPENDENCY: _("dependency"),
    Reason.WEAK: _("weak dependency"),
}
REASON_TIP = {
    Reason.USER: _("Installed by the user: autoremove keeps it"),
    Reason.GROUP: _("Installed with a package group: autoremove keeps it"),
    Reason.EXTERNAL: _("Installed outside dnf, or dnf lost the record: treated as installed by the user,\n"
                       "so autoremove keeps it. Mark it as a dependency if something else pulled it in."),
    Reason.DEPENDENCY: _("Installed as a dependency: autoremove removes it once nothing needs it"),
    Reason.WEAK: _("Installed as a weak dependency (recommended by another package):\n"
                   "autoremove removes it once nothing needs it"),
}
_REASON_ORDER = {r: i for i, r in enumerate(Reason)}

STATUS_LABEL = {
    Status.NOT_INSTALLED: pgettext("package status", "Not installed"),
    Status.INSTALLED: pgettext("package status", "Installed"),
    Status.UPGRADABLE: _("Installed, upgrade available"),
    Status.NEWER: _("Installed version is newer than the repository"),
    Status.ORPHAN: _("Installed, no repository provides it"),
    Status.UNNEEDED: _("Installed as a dependency, no longer needed"),
}
STATUS_ORDER = {s: i for i, s in enumerate([
    Status.UPGRADABLE, Status.ORPHAN, Status.NEWER, Status.UNNEEDED, Status.INSTALLED, Status.NOT_INSTALLED])}


@cache
def blocked_tip(reason: str) -> str:
    """Two lines: that the upgrade cannot be installed, and the root cause from the resolver's message, as dnf says
    it in the user's language (its last line, such as "nothing provides liboapv.so.11()(64bit) needed by
    ffmpeg-libs-9.0.2-4.fc45.x86_64 from rpmfusion-free-updates")."""
    lines = [line.strip().removeprefix("- ") for line in reason.splitlines() if line.strip()]
    cause = lines[-1] if lines else ""
    return "\n".join(filter(None, (_("The upgrade cannot be installed now"), cause)))


def latest_evr(r: PkgRow) -> str:
    """The Latest version column: the candidate, or the newer version the version lock holds back."""
    return r.held_evr or r.candidate_evr


def human_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    for unit in ("kB", "MB", "GB"):
        n /= 1024
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}"


def repo_text(r: PkgRow) -> str:
    """Where the latest version comes from; for an installed package that came from another repository, that one
    first: "elmodos/Kram → updates"."""
    if r.from_repo_id and r.from_repo_id != r.repo_id:
        return f"{display_repo(r.from_repo_id)} → {display_repo(r.repo_id)}"
    return display_repo(r.repo_id)


# ---------------------------------------------------------------- cells

@dataclass
class CellContext:
    """What a cell shows besides its row. `blocked`: upgradable packages whose upgrade cannot be installed now, with
    the resolver's reason; `optional`: the selected comps group's optional package names."""
    basearch: str = "x86_64"
    marks: MarkSet = field(default_factory=MarkSet)
    blocked: dict[tuple[str, str], str] = field(default_factory=dict)
    optional: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class CellStyle:
    bold: bool = False
    italic: bool = False
    dimmed: bool = False  # in the disabled text colour


PLAIN = CellStyle()
_BOLD, _ITALIC = CellStyle(bold=True), CellStyle(italic=True)
_DIMMED, _DIMMED_ITALIC = CellStyle(dimmed=True), CellStyle(italic=True, dimmed=True)


@dataclass(frozen=True, slots=True)
class Cell:
    text: str
    tooltip: str | None
    icon: IconRef | None
    style: CellStyle
    align_right: bool


def cell_text(r: PkgRow, col: int, ctx: CellContext) -> str | None:
    match col:
        case 2: return r.name if r.arch in ("noarch", ctx.basearch) else f"{r.name}.{r.arch}"
        case 3: return r.installed_evr
        case 4: return REASON_LABEL.get(r.reason, "")
        case 5:
            if r.held_evr:
                return r.held_evr
            return f"{r.candidate_evr} ({r.candidate_arch})" if r.candidate_arch else r.candidate_evr
        case 6: return repo_text(r)
        case 7: return human_size(r.size)
        case 8: return r.summary
        case 9: return ADVISORY_LABEL[found[0].level] if (found := shown_advisories(r)) else ""
        case 10: return "" if r.download_size is None else human_size(r.download_size)
    return None


def cell_icon(r: PkgRow, col: int, ctx: CellContext) -> IconRef | None:
    if col == COL_STATUS:
        mark = ctx.marks.get(r.key)
        return status_icon_ref(r.status, r.locked, r.installed, mark.action if mark else None)
    if col == COL_ORIGIN:
        return ("origin", r.origin)
    if col == COL_CANDIDATE:  # a blank one without an advisory, so that the versions line up
        if r.key in ctx.blocked:  # until the repository fixes it, this matters more than the advisory
            return ("blocked",)
        if r.held_evr and r.held_advisories:
            return ("held", r.held_advisories[0].level)
        return ("advisory", r.advisory.level if r.advisories else None)
    return None


def cell_tooltip(r: PkgRow, col: int, ctx: CellContext) -> str | None:
    if col in (COL_CANDIDATE, COL_ADVISORY):
        if r.key in ctx.blocked:
            return "\n\n".join(filter(None, (blocked_tip(ctx.blocked[r.key]), advisory_tip(r))))
        if r.held_evr:
            return "\n\n".join(filter(None, (held_tip(r), advisory_tip(r))))
        return advisory_tip(r)
    if col == COL_ORIGIN:
        return f"{ORIGIN_LABEL[r.origin]}: {display_repo(r.origin_repo)}"
    if col == COL_NAME and r.name in ctx.optional:
        return _("Optional in this group: installing the group brings it only with optional packages")
    if col == COL_REASON:
        return REASON_TIP.get(r.reason)
    if col == COL_REPO and r.from_repo_id and r.from_repo_id != r.repo_id:
        return _("Installed from {installed}; the latest version comes from {latest}").format(
            installed=display_repo(r.from_repo_id), latest=display_repo(r.repo_id))
    if col == COL_STATUS:
        mark = ctx.marks.get(r.key)
        label = STATUS_LABEL[r.status]
        if r.locked:
            label += "\n" + lock_tip(r)
        if r.held_evr:
            label += "\n" + held_tip(r)
        if r.key in ctx.blocked:
            label += "\n" + _("The upgrade cannot be installed now")
        if mark:
            target = f" {mark.evr}" if mark.evr else ""
            label += "\n" + _("Marked: {action}").format(action=ACTION_LABELS[mark.action] + target)
        return label + "\n\n" + _("Click for actions")
    return None


def cell_style(r: PkgRow, col: int, ctx: CellContext) -> CellStyle:
    """Bold upgradable versions; italic held-back versions and a group's optional packages; dimmed versions that
    cannot be installed now or are held back, and the update type of a held-back upgrade."""
    if col == COL_NAME:
        return _ITALIC if r.name in ctx.optional else PLAIN
    if col == COL_CANDIDATE:
        if r.held_evr:
            return _DIMMED_ITALIC
        if r.key in ctx.blocked:
            return _DIMMED
        return _BOLD if r.status is Status.UPGRADABLE else PLAIN
    if col == COL_ADVISORY and r.held_evr and not r.advisories:
        return _DIMMED
    return PLAIN


def row_tint(r: PkgRow, marks: MarkSet) -> Action | None:
    """A marked row is tinted in its action's colour (kram.app.icons.MARK_BACKGROUND)."""
    mark = marks.get(r.key)
    return mark.action if mark else None


def cell(r: PkgRow, col: int, ctx: CellContext) -> Cell:
    return Cell(cell_text(r, col, ctx) or "", cell_tooltip(r, col, ctx), cell_icon(r, col, ctx),
                cell_style(r, col, ctx), col in ALIGN_RIGHT)


# ---------------------------------------------------------------- sorting

SORT_KEYS = {
    COL_STATUS: lambda r: (STATUS_ORDER[r.status], r.name.lower()),
    COL_ORIGIN: lambda r: (r.origin.value, r.name.lower()),
    COL_NAME: lambda r: (r.name.lower(), r.arch),
    COL_REASON: lambda r: (r.reason is None, _REASON_ORDER.get(r.reason, 0), r.name.lower()),
    COL_REPO: lambda r: (repo_text(r).lower(), r.name.lower()),
    COL_SIZE: lambda r: (r.size, r.name.lower()),
    COL_DOWNLOAD: lambda r: (r.download_size is not None, r.download_size or 0, r.name.lower()),
    COL_SUMMARY: lambda r: (r.summary.lower(), r.name.lower()),
}
_NO_ADVISORY = len(ADVISORY_LABEL)


def version_ranks(rows: list[PkgRow]) -> dict[str, int]:
    """The rank of every installed and latest version among each other, for sorting the version columns."""
    return evr_ranks([r.installed_evr for r in rows] + [latest_evr(r) for r in rows])


def sorted_positions(rows: list[PkgRow], visible: list[int], column: int, descending: bool,
                     ranks: Callable[[], dict[str, int]]) -> list[int]:
    """`visible` (indices into `rows`) sorted by `column`. `ranks` gives `version_ranks(rows)`, worked out by the
    caller once per list of rows and only when a version column is sorted."""
    if column in (COL_INSTALLED, COL_CANDIDATE):
        rank = ranks()
        version = (lambda r: r.installed_evr) if column == COL_INSTALLED else latest_evr

        def key(r):
            evr = version(r)
            # empty versions go last in both directions
            return (evr == "") != descending, rank.get(evr, -1), r.name.lower()
    elif column == COL_ADVISORY:
        def key(r):
            a = (shown_advisories(r) or (None,))[0]
            # the most important first when ascending; packages without an advisory last in both directions
            level = a.rank if a else _NO_ADVISORY
            return (a is None) != descending, level, r.name.lower()
    else:
        key = SORT_KEYS[column]
    return sorted(visible, key=lambda i: key(rows[i]), reverse=descending)
