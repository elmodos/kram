from functools import cache

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette

from ..core.evr import evr_ranks
from ..core.marks import ACTION_LABELS, MarkSet
from ..core.model import PkgRow, Reason, Status
from ..core.origin import display_repo
from ..i18n import _, pgettext
from .icons import (
    MARK_BACKGROUND,
    ORIGIN_LABEL,
    advisory_icon,
    blocked_icon,
    held_advisory_icon,
    locked_icon,
    mark_icon,
    origin_icon,
    status_icon,
)

# new columns come last (the update type at logical index 9, the download size at 10) so that saved header states
# keep their columns; the window shows them where they belong: the update type after the latest version, the
# download size after the installed size
(COL_STATUS, COL_ORIGIN, COL_NAME, COL_INSTALLED, COL_REASON, COL_CANDIDATE, COL_REPO, COL_SIZE, COL_SUMMARY,
 COL_ADVISORY, COL_DOWNLOAD) = range(11)
# TRANSLATORS: "S" is the narrow status column (Synaptic convention); keep it one letter
HEADERS = [_("S"), "", _("Package"), _("Installed version"), _("Reason"), _("Latest version"), _("Repository"),
           _("Installed size"), _("Summary"), _("Update type"), _("Download size")]
# columns the header's context menu can hide (the first three identify the row), in the order it lists them
HIDEABLE = (COL_INSTALLED, COL_REASON, COL_CANDIDATE, COL_ADVISORY, COL_REPO, COL_SIZE, COL_DOWNLOAD, COL_SUMMARY)

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

_STATUS_ORDER = {s: i for i, s in enumerate([
    Status.UPGRADABLE, Status.ORPHAN, Status.NEWER, Status.UNNEEDED, Status.INSTALLED, Status.NOT_INSTALLED])}

SORT_KEYS = {
    COL_STATUS: lambda r: (_STATUS_ORDER[r.status], r.name.lower()),
    COL_ORIGIN: lambda r: (r.origin.value, r.name.lower()),
    COL_NAME: lambda r: (r.name.lower(), r.arch),
    COL_REASON: lambda r: (r.reason is None, _REASON_ORDER.get(r.reason, 0), r.name.lower()),
    COL_REPO: lambda r: (repo_text(r).lower(), r.name.lower()),
    COL_SIZE: lambda r: (r.size, r.name.lower()),
    COL_DOWNLOAD: lambda r: (r.download_size is not None, r.download_size or 0, r.name.lower()),
    COL_SUMMARY: lambda r: (r.summary.lower(), r.name.lower()),
}
_NO_ADVISORY = len(ADVISORY_LABEL)


@cache
def blocked_tip(reason: str) -> str:
    """Two lines: that the upgrade cannot be installed, and the root cause from the resolver's message, as dnf says
    it in the user's language (its last line, such as "nothing provides liboapv.so.11()(64bit) needed by
    ffmpeg-libs-9.0.2-4.fc45.x86_64 from rpmfusion-free-updates")."""
    lines = [line.strip().removeprefix("- ") for line in reason.splitlines() if line.strip()]
    cause = lines[-1] if lines else ""
    return "\n".join(filter(None, (_("The upgrade cannot be installed now"), cause)))


def _bold() -> QFont:
    f = QFont()
    f.setBold(True)
    return f


def _italic() -> QFont:
    f = QFont()
    f.setItalic(True)
    return f


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


class PackageTableModel(QAbstractTableModel):
    """Table over a flat list of rows; `visible` holds indices into `rows` (filtered and sorted).

    Two orderings: by a column (`sort`), or "ranked" — the order search produced, kept as is until the user
    clicks a column header.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list[PkgRow] = []
        self.visible: list[int] = []
        self.basearch = "x86_64"
        self._sort: tuple[int, Qt.SortOrder] | None = (COL_NAME, Qt.SortOrder.AscendingOrder)
        self._evr_rank: dict[str, int] | None = None
        self.marks = MarkSet()
        # upgradable packages whose upgrade cannot be installed now -> the resolver's reason; see
        # Catalog.blocked_upgrades. Filled after each load, so it may lag the rows by a moment. Always this one dict,
        # changed in place: the sidebar's "Cannot be upgraded now" entry reads it
        self.blocked: dict[tuple[str, str], str] = {}
        # the selected comps group's optional package names: in italics, as installing the group leaves them out
        self.optional: frozenset[str] = frozenset()

    def set_rows(self, rows: list[PkgRow], basearch: str) -> None:
        self.beginResetModel()
        self.rows = rows
        self.basearch = basearch
        self.blocked.clear()
        self.visible = list(range(len(rows)))
        self._evr_rank = None
        self.endResetModel()

    def set_blocked(self, blocked: dict[tuple[str, str], str]) -> None:
        self.blocked.clear()
        self.blocked.update(blocked)
        if self.visible:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.visible) - 1, self.columnCount() - 1))

    def set_blocked_reason(self, key: tuple[str, str], reason: str) -> None:
        """The reason of one blocked row, looked up for the selected row after the list was filled."""
        if key not in self.blocked:
            return
        self.blocked[key] = reason
        index = self.index_of_key(key)
        if index.isValid():
            self.dataChanged.emit(self.index(index.row(), 0), self.index(index.row(), self.columnCount() - 1))

    def set_visible(self, visible: list[int], ranked: bool = False) -> None:
        """`ranked`: keep the given order (search relevance) instead of the column sort."""
        self.beginResetModel()
        self.visible = visible if ranked or self._sort is None else self._sorted(visible)
        self.endResetModel()

    def set_sort_column(self, sort: tuple[int, Qt.SortOrder]) -> None:
        """Change the column sort without re-sorting now; the next set_visible applies it."""
        self._sort = sort

    @property
    def sort_column(self) -> tuple[int, Qt.SortOrder] | None:
        return self._sort

    def marks_changed(self, keys=None) -> None:
        """Repaint rows whose marks changed (all visible rows if keys is None)."""
        if not self.visible:
            return
        if keys is None:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.visible) - 1, len(HEADERS) - 1))
            return
        for key in keys:
            idx = self.index_of_key(key)
            if idx.isValid():
                self.dataChanged.emit(self.index(idx.row(), 0), self.index(idx.row(), len(HEADERS) - 1))

    def row_at(self, index: QModelIndex) -> PkgRow:
        return self.rows[self.visible[index.row()]]

    def index_of_key(self, key: tuple[str, str]) -> QModelIndex:
        for pos, i in enumerate(self.visible):
            if self.rows[i].key == key:
                return self.index(pos, COL_NAME)
        return QModelIndex()

    # --- sorting: done on our index list, so no QSortFilterProxyModel overhead on 70k rows

    def sort(self, column: int, order=Qt.SortOrder.AscendingOrder) -> None:
        if column < 0:  # sort indicator cleared: keep the current (ranked) order
            self._sort = None
            return
        self._sort = (column, order)
        self.layoutAboutToBeChanged.emit()
        old = {pos: i for pos, i in enumerate(self.visible)}
        self.visible = self._sorted(self.visible)
        new_pos = {i: pos for pos, i in enumerate(self.visible)}
        for idx in self.persistentIndexList():
            if idx.isValid():
                self.changePersistentIndex(idx, self.index(new_pos[old[idx.row()]], idx.column()))
        self.layoutChanged.emit()

    def _sorted(self, visible: list[int]) -> list[int]:
        column, order = self._sort
        rows = self.rows
        if column in (COL_INSTALLED, COL_CANDIDATE):
            if self._evr_rank is None:
                self._evr_rank = evr_ranks([r.installed_evr for r in rows] + [latest_evr(r) for r in rows])
            ranks = self._evr_rank
            version = (lambda r: r.installed_evr) if column == COL_INSTALLED else latest_evr

            def key(r):
                evr = version(r)
                # empty versions go last in both directions
                return (evr == "") != (order == Qt.SortOrder.DescendingOrder), ranks.get(evr, -1), r.name.lower()
        elif column == COL_ADVISORY:
            def key(r):
                a = (shown_advisories(r) or (None,))[0]
                # the most important first when ascending; packages without an advisory last in both directions
                rank = a.rank if a else _NO_ADVISORY
                return (a is None) != (order == Qt.SortOrder.DescendingOrder), rank, r.name.lower()
        else:
            key = SORT_KEYS[column]
        return sorted(visible, key=lambda i: key(rows[i]), reverse=order == Qt.SortOrder.DescendingOrder)

    # --- Qt model API

    def rowCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(self.visible)

    def columnCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return HEADERS[section]
        if (orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.ToolTipRole
                and section in (COL_STATUS, COL_ORIGIN)):
            return _("Status") if section == COL_STATUS else _("Origin")
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        r = self.rows[self.visible[index.row()]]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            match col:
                case 2: return r.name if r.arch in ("noarch", self.basearch) else f"{r.name}.{r.arch}"
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
        elif role == Qt.ItemDataRole.DecorationRole:
            if col == COL_STATUS:
                mark = self.marks.get(r.key)
                if mark:
                    return mark_icon(mark.action)
                return locked_icon(r.installed) if r.locked else status_icon(r.status)
            if col == COL_ORIGIN:
                return origin_icon(r.origin)
            if col == COL_CANDIDATE:  # a blank one without an advisory, so that the versions line up
                if r.key in self.blocked:  # until the repository fixes it, this matters more than the advisory
                    return blocked_icon()
                if r.held_evr and r.held_advisories:
                    return held_advisory_icon(r.held_advisories[0].level)
                return advisory_icon(r.advisory.level if r.advisories else None)
        elif role == Qt.ItemDataRole.ToolTipRole:
            if col in (COL_CANDIDATE, COL_ADVISORY):
                if r.key in self.blocked:
                    return "\n\n".join(filter(None, (blocked_tip(self.blocked[r.key]), advisory_tip(r))))
                if r.held_evr:
                    return "\n\n".join(filter(None, (held_tip(r), advisory_tip(r))))
                return advisory_tip(r)
            if col == COL_ORIGIN:
                return f"{ORIGIN_LABEL[r.origin]}: {display_repo(r.origin_repo)}"
            if col == COL_NAME and r.name in self.optional:
                return _("Optional in this group: installing the group brings it only with optional packages")
            if col == COL_REASON:
                return REASON_TIP.get(r.reason)
            if col == COL_REPO and r.from_repo_id and r.from_repo_id != r.repo_id:
                return _("Installed from {installed}; the latest version comes from {latest}").format(
                    installed=display_repo(r.from_repo_id), latest=display_repo(r.repo_id))
            if col == COL_STATUS:
                mark = self.marks.get(r.key)
                label = STATUS_LABEL[r.status]
                if r.locked:
                    label += "\n" + lock_tip(r)
                if r.held_evr:
                    label += "\n" + held_tip(r)
                if r.key in self.blocked:
                    label += "\n" + _("The upgrade cannot be installed now")
                if mark:
                    target = f" {mark.evr}" if mark.evr else ""
                    label += "\n" + _("Marked: {action}").format(action=ACTION_LABELS[mark.action] + target)
                return label + "\n\n" + _("Click for actions")
        elif role == Qt.ItemDataRole.BackgroundRole:
            mark = self.marks.get(r.key)
            if mark:
                return QColor(*MARK_BACKGROUND[mark.action])
        elif role == Qt.ItemDataRole.TextAlignmentRole and col in (COL_SIZE, COL_DOWNLOAD):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        elif role == Qt.ItemDataRole.FontRole and col == COL_NAME and r.name in self.optional:
            return _italic()
        elif role == Qt.ItemDataRole.FontRole and col == COL_CANDIDATE:
            if r.held_evr:
                return _italic()
            if r.status is Status.UPGRADABLE:
                return None if r.key in self.blocked else _bold()
        elif role == Qt.ItemDataRole.ForegroundRole and (
                col == COL_CANDIDATE and (r.key in self.blocked or r.held_evr)
                or col == COL_ADVISORY and r.held_evr and not r.advisories):
            return QGuiApplication.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)
        return None


def repo_text(r: PkgRow) -> str:
    """Where the latest version comes from; for an installed package that came from another repository, that one
    first: "elmodos/Kram → updates"."""
    if r.from_repo_id and r.from_repo_id != r.repo_id:
        return f"{display_repo(r.from_repo_id)} → {display_repo(r.repo_id)}"
    return display_repo(r.repo_id)


STATUS_LABEL = {
    Status.NOT_INSTALLED: pgettext("package status", "Not installed"),
    Status.INSTALLED: pgettext("package status", "Installed"),
    Status.UPGRADABLE: _("Installed, upgrade available"),
    Status.NEWER: _("Installed version is newer than the repository"),
    Status.ORPHAN: _("Installed, no repository provides it"),
    Status.UNNEEDED: _("Installed as a dependency, no longer needed"),
}
