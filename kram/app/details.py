"""The detail tabs of the selected package: what each tab says, as documents (kram.app.doc) written once for every
front end; which tab is selected; and the loader that fetches the details once the cursor rests on a package."""
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from ..core.catalog import Catalog
from ..core.model import PkgDetails, PkgRow
from ..core.origin import display_repo
from ..core.worker import DnfWorker
from ..i18n import _, ngettext, pgettext
from .columns import ADVISORY_LABEL, blocked_tip, held_tip, human_size, shown_advisories
from .doc import BR, Doc, Heading, Inline, Rule, Section, Span, Table, bold, italic, joined, lines, link, para, small
from .icons import ORIGIN_LABEL
from .scheduler import Scheduler

# items of one section of the Dependencies tab: its rich text takes ~0.02 s for 1000 lines, but grows faster than
# the list, and kernel-core provides some 16000 (8 s, with the window frozen)
MAX_DEP_ITEMS = 1000

# the tabs, in their order, by the names the settings keep
TABS = ("description", "general", "advisories", "dependencies", "files", "versions", "changelog")


def tab_titles() -> dict[str, str]:
    return {"description": _("Description"), "general": _("General"), "advisories": _("Advisories"),
            "dependencies": _("Dependencies"), "files": _("Files"), "versions": _("Versions"),
            "changelog": _("Changelog")}


def date_text(ts: int | None) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else "—"


def reference(kind: str, ref_id: str) -> str:
    """A bug or CVE an advisory fixes: "CVE-2026-1234", Red Hat's Bugzilla as "RHBZ#2369081"."""
    return f"RHBZ#{ref_id}" if kind == "bugzilla" and ref_id.isdigit() else ref_id


def advisories_doc(row: PkgRow) -> Doc:
    """The advisories of an upgrade: what it fixes, with links to the advisory and to the bugs and CVEs. For an
    upgrade the version lock holds back, that comes first."""
    blocks = []
    if not row.advisories and row.held_evr:
        blocks += [para(bold(held_tip(row)), BR,
                        _("These fixes stay out until the lock is removed (Package → Unlock Version).")), Rule()]
    for a in shown_advisories(row):
        name: Span = link("web", a.url, a.id) if a.url else a.id
        spans: list[Span] = [bold(name), f" — {ADVISORY_LABEL[a.level]}"]
        if a.issued:
            spans.append(" — " + date_text(a.issued)[:10])
        if a.title:
            spans += [BR, a.title]
        blocks.append(para(*spans))
        if a.description:
            blocks.append(para(*lines(a.description)))
        refs: list[list[Span]] = [[link("web", url, reference(kind, ref_id) or url) if url else reference(kind, ref_id)]
                                  for kind, ref_id, url in a.references]
        if refs:
            blocks.append(para(_("References:") + " ", *joined(refs, [", "])))
    return Doc(blocks)


def blocked_doc(reason: str) -> Doc:
    """Above the dependencies of an upgrade that cannot be installed: the root cause, then the resolver's message."""
    title, _nl, cause = blocked_tip(reason).partition("\n")
    message = reason.strip()
    blocks = [para(bold(title), role="error")]
    if cause:
        blocks.append(para(bold(cause)))
    blocks.append(para(_("The repository has to fix it. Until then Mark All Upgrades leaves this package out.")))
    # no message while it is looked up, or none from the resolver: the title still says it cannot be installed
    if message:
        blocks.append(para(message, role="mono"))
    blocks.append(Rule())
    return Doc(blocks)


def description_doc(d: PkgDetails) -> Doc:
    return Doc([Heading((d.summary,)), *(para(p) for p in d.description.split("\n\n") if p.strip())])


def general_doc(row: PkgRow, d: PkgDetails) -> Doc:
    def row_(label: str, *value: Span):
        return (label,), value

    reason = {True: _("by the user"), False: _("as a dependency"), None: "—"}[d.user_installed]
    locks: list[Span] = joined([[lock.conditions, *([" ", small(f"({lock.comment})")] if lock.comment else [])]
                                for lock in row.locks], [BR])
    rows = [
        row_(_("Package"), d.nevra),
        row_(_("Origin"), f"{ORIGIN_LABEL[row.origin]} — {display_repo(row.origin_repo)}"),
        row_(_("Candidate repository"), display_repo(d.repo_id) or "—"),
        row_(_("License"), d.license),
        row_(_("Website"), link("web", d.url, d.url) if d.url else "—"),
        row_(_("Vendor"), d.vendor or "—"),
        row_(_("Packager"), d.packager or "—"),
        row_(_("Source package"), d.source_rpm),
        row_(_("Built"), date_text(d.build_time)),
        row_(pgettext("install date", "Installed"), date_text(d.install_time)),
        row_(_("Install reason"), reason),
        *([row_(_("Version lock"), *locks)] if row.locked else []),
        row_(_("Installed size"), human_size(d.install_size)),
        row_(_("Download size"), human_size(d.download_size) if d.download_size else "—"),
    ]
    return Doc([Table(tuple(rows))])


def dependencies_doc(d: PkgDetails) -> Doc:
    def section(title: str, items: list, kind: str = "dep") -> list[Section]:
        if not items:
            return []
        shown = items[:MAX_DEP_ITEMS]
        if kind == "pkg":
            entries = tuple((link("pkg", f"{n}.{a}", f"{n}.{a}"),) for n, a in shown)
        else:
            entries = tuple((link("dep", i, i),) for i in shown)
        rest = len(items) - len(shown)
        more = ngettext("…and {n} more", "…and {n} more", rest).format(n=rest) if rest > 0 else ""
        return [Section(title, len(items), entries, more)]

    blocks = [
        *section(_("Requires"), d.requires),
        *section(_("Recommends"), d.recommends),
        *section(_("Suggests"), d.suggests),
        *section(_("Required by installed packages"), d.required_by, "pkg"),
        *section(_("Conflicts"), d.conflicts),
        *section(_("Obsoletes"), d.obsoletes),
        *section(_("Provides"), d.provides),
    ]
    return Doc(blocks or [Inline((italic(_("No dependencies")),))])


def changelog_doc(d: PkgDetails) -> Doc:
    if not d.changelog:
        return Doc([Inline((italic(_("The changelog is available for installed packages only "
                                     "(dnf5 does not download it for repositories by default).")),))])
    return Doc([para(bold(date_text(c.timestamp)[:10]), f" — {c.author}", BR, *lines(c.text)) for c in d.changelog])


@dataclass(frozen=True)
class VersionRow:
    evr: str
    repo: str
    state: str
    bold: bool      # installed or the candidate
    dimmed: bool    # excluded by the version lock


def version_rows(d: PkgDetails) -> list[VersionRow]:
    return [VersionRow(v.evr, display_repo(v.repo_id),
                       pgettext("version state", "installed") if v.installed else _("candidate") if v.candidate
                       else _("excluded by the version lock") if v.locked_out else "",
                       v.installed or v.candidate, v.locked_out)
            for v in d.versions]


def advisories_tab_tip(row: PkgRow) -> str:
    """The advisories tab's tooltip: the most important level, and why the fixes are held back if they are."""
    found = shown_advisories(row)
    held = not row.advisories
    return "\n".join(filter(None, (ADVISORY_LABEL[found[0].level], held and held_tip(row))))


def advisories_tab_icon(row: PkgRow):
    """The advisories tab's icon (kram.app.icons.IconRef), None when the tab is not shown."""
    if not (found := shown_advisories(row)):
        return None
    return ("held" if not row.advisories else "advisory", found[0].level)


# ---------------------------------------------------------------- loading

# libdnf5 holds Python's lock while it looks the details up, so the window would stop for each row the cursor only
# passes (typing, holding an arrow key)
DETAILS_DELAY_MS = 120


class DetailsSink(Protocol):
    """What the detail tabs of a front end do with what the loader finds."""

    def show_advisories(self, row: PkgRow | None) -> None: ...

    def show_blocked(self, reason: str | None) -> None: ...

    def show_package(self, row: PkgRow, d: PkgDetails) -> None: ...

    def clear(self) -> None: ...


class TabChoice:
    """Which detail tab is selected, around the advisories tab that comes and goes with the selected package: when
    the user picked it, it is selected again for the next package that has one, and meanwhile the tab the user had
    before stands in for it. Tabs by name (TABS)."""

    def __init__(self) -> None:
        self.wants_advisories = False
        self.other = "general"

    def user_selected(self, name: str) -> None:
        self.wants_advisories = name == "advisories"
        if not self.wants_advisories:
            self.other = name

    def saved_name(self, current: str) -> str:
        """The tab to keep in the settings."""
        return "advisories" if self.wants_advisories else current

    def to_select(self, name: str, advisories_shown: bool) -> str | None:
        """The tab to select for a saved or asked-for `name`; None: the advisories tab, once a package has one."""
        if name == "advisories" and not advisories_shown:
            self.wants_advisories = True
            return None
        return name if name in TABS else "description"

    def instead_of_advisories(self) -> str:
        return self.other


class DetailsLoader:
    """Loads the details of the package under the cursor for the detail tabs (a `DetailsSink`), once the cursor rests
    on it."""

    def __init__(self, tabs: "DetailsSink", catalog: Catalog, dnf: DnfWorker,
                 blocked: Callable[[tuple[str, str]], str | None],
                 set_reason: Callable[[tuple[str, str], str], None], scheduler: Scheduler):
        """`blocked`: why the upgrade of a package cannot be installed now, or None; "" when it is not known yet.
        `set_reason`: keeps a reason looked up for the cursor's row."""
        self._tabs, self._catalog, self._dnf, self._blocked = tabs, catalog, dnf, blocked
        self._set_reason = set_reason
        # blocked keys whose reason was asked for since the blocked upgrades last arrived: the cursor's rests and
        # the arrival do not ask twice, nor again for one the resolver gives no reason for
        self._asked: set[tuple[str, str]] = set()
        self._row: PkgRow | None = None
        self._details: PkgDetails | None = None  # of `_row`, once loaded
        self.timer = scheduler.timer(DETAILS_DELAY_MS, self.load)

    def follow(self, row: PkgRow) -> None:
        """The cursor is on `row`: its advisories at once (they come with the row), the rest once it rests there."""
        self._row = row
        self._details = None
        self._tabs.show_advisories(row)
        self._tabs.show_blocked(self._blocked(row.key))
        self.timer.start()

    def refresh_blocked(self) -> None:
        """The blocked upgrades arrived (they are resolved after the list is up)."""
        self._asked.clear()
        if self._row is not None:
            self._tabs.show_blocked(self._blocked(self._row.key))
            self._fetch_reason(self._row)

    def clear(self) -> None:
        """Nothing is listed."""
        self.timer.stop()
        self._row = self._details = None
        self._tabs.clear()

    def details_of(self, key: tuple[str, str]) -> PkgDetails | None:
        """The details of the package under the cursor, if that is `key` and they have arrived."""
        return self._details if self._row is not None and self._row.key == key else None

    def _is_current(self, row: PkgRow) -> bool:
        return self._row is not None and self._row.key == row.key

    def load(self) -> None:
        row = self._row
        if row is None:
            return
        # skipped on the dnf thread when the cursor moved on while it waited its turn
        self._dnf.submit(lambda: self._catalog.details(row.key) if self._is_current(row) else None,
                         lambda d: self._show(row, d), lambda _e: None)  # the panel stays empty
        self._fetch_reason(row)

    def _fetch_reason(self, row: PkgRow) -> None:
        """A blocked upgrade whose reason the resolve of the whole upgrade did not give: asked for on its own."""
        if self._blocked(row.key) == "" and row.key not in self._asked:
            self._asked.add(row.key)
            self._dnf.submit(lambda: self._catalog.blocked_reason(row.key) if self._is_current(row) else None,
                             lambda reason: self._show_reason(row, reason),
                             lambda _e: self._asked.discard(row.key))  # asked again when the cursor comes back

    def _show_reason(self, row: PkgRow, reason: str | None) -> None:
        if reason is None:  # skipped on the dnf thread, the cursor had moved on: to be asked again
            self._asked.discard(row.key)
            return
        self._set_reason(row.key, reason)  # kept for the list's tooltip even when the cursor moved on
        if self._is_current(row):
            self._tabs.show_blocked(self._blocked(row.key))

    def _show(self, row: PkgRow, d: PkgDetails | None) -> None:
        if d is not None and self._is_current(row):  # ignore stale results when the cursor moved on
            self._details = d
            self._tabs.show_package(row, d)
