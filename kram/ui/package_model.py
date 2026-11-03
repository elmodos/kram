from functools import cache

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor, QFont

from ..core.evr import evr_ranks
from ..core.marks import ACTION_LABELS, MarkSet
from ..core.model import PkgRow, Status
from ..core.origin import display_repo
from .icons import MARK_BACKGROUND, ORIGIN_LABEL, mark_icon, origin_icon, status_icon

COL_STATUS, COL_ORIGIN, COL_NAME, COL_INSTALLED, COL_CANDIDATE, COL_REPO, COL_SIZE, COL_SUMMARY = range(8)
HEADERS = ["S", "", "Пакунок", "Встановлена версія", "Остання версія", "Репозиторій", "Розмір", "Опис"]

_STATUS_ORDER = {s: i for i, s in enumerate([
    Status.UPGRADABLE, Status.ORPHAN, Status.NEWER, Status.UNNEEDED, Status.INSTALLED, Status.NOT_INSTALLED])}

SORT_KEYS = {
    COL_STATUS: lambda r: (_STATUS_ORDER[r.status], r.name.lower()),
    COL_ORIGIN: lambda r: (r.origin.value, r.name.lower()),
    COL_NAME: lambda r: (r.name.lower(), r.arch),
    COL_REPO: lambda r: (display_repo(r.repo_id).lower(), r.name.lower()),
    COL_SIZE: lambda r: (r.size, r.name.lower()),
    COL_SUMMARY: lambda r: (r.summary.lower(), r.name.lower()),
}


@cache
def _bold() -> QFont:
    f = QFont()
    f.setBold(True)
    return f


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
        self._sort: tuple[int, Qt.SortOrder] | None = (COL_NAME, Qt.AscendingOrder)
        self._evr_rank: dict[str, int] | None = None
        self.marks = MarkSet()

    def set_rows(self, rows: list[PkgRow], basearch: str) -> None:
        self.beginResetModel()
        self.rows = rows
        self.basearch = basearch
        self.visible = list(range(len(rows)))
        self._evr_rank = None
        self.endResetModel()

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

    def sort(self, column: int, order=Qt.AscendingOrder) -> None:
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
                self._evr_rank = evr_ranks([r.installed_evr for r in rows] + [r.candidate_evr for r in rows])
            ranks = self._evr_rank
            attr = "installed_evr" if column == COL_INSTALLED else "candidate_evr"

            def key(r):
                evr = getattr(r, attr)
                # empty versions go last in both directions
                return (evr == "") != (order == Qt.DescendingOrder), ranks.get(evr, -1), r.name.lower()
        else:
            key = SORT_KEYS[column]
        return sorted(visible, key=lambda i: key(rows[i]), reverse=order == Qt.DescendingOrder)

    # --- Qt model API

    def rowCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(self.visible)

    def columnCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return HEADERS[section]
        if orientation == Qt.Horizontal and role == Qt.ToolTipRole and section in (COL_STATUS, COL_ORIGIN):
            return "Статус" if section == COL_STATUS else "Походження"
        return None

    def data(self, index, role=Qt.DisplayRole):
        r = self.rows[self.visible[index.row()]]
        col = index.column()
        if role == Qt.DisplayRole:
            match col:
                case 2: return r.name if r.arch in ("noarch", self.basearch) else f"{r.name}.{r.arch}"
                case 3: return r.installed_evr
                case 4: return r.candidate_evr
                case 5: return display_repo(r.repo_id)
                case 6: return human_size(r.size)
                case 7: return r.summary
        elif role == Qt.DecorationRole:
            if col == COL_STATUS:
                mark = self.marks.get(r.key)
                return mark_icon(mark.action) if mark else status_icon(r.status)
            if col == COL_ORIGIN:
                return origin_icon(r.origin)
        elif role == Qt.ToolTipRole:
            if col == COL_ORIGIN:
                return f"{ORIGIN_LABEL[r.origin]}: {display_repo(r.origin_repo)}"
            if col == COL_STATUS:
                mark = self.marks.get(r.key)
                label = STATUS_LABEL[r.status]
                if mark:
                    target = f" {mark.evr}" if mark.evr else ""
                    label += f"\nПозначено: {ACTION_LABELS[mark.action]}{target}"
                return label + "\n\nКлік — меню дій"
        elif role == Qt.BackgroundRole:
            mark = self.marks.get(r.key)
            if mark:
                return QColor(*MARK_BACKGROUND[mark.action])
        elif role == Qt.TextAlignmentRole and col == COL_SIZE:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        elif role == Qt.FontRole and col == COL_CANDIDATE and r.status is Status.UPGRADABLE:
            return _bold()
        return None


STATUS_LABEL = {
    Status.NOT_INSTALLED: "Не встановлено",
    Status.INSTALLED: "Встановлено",
    Status.UPGRADABLE: "Встановлено, є оновлення",
    Status.NEWER: "Встановлена версія новіша за репозиторій",
    Status.ORPHAN: "Встановлено, жоден репозиторій його не надає",
    Status.UNNEEDED: "Встановлено як залежність, більше не потрібен",
}
