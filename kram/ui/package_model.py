from functools import cache

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QFont

from ..core.model import PkgRow, Status
from ..core.origin import display_repo
from .icons import ORIGIN_LABEL, origin_icon, status_icon

COL_STATUS, COL_ORIGIN, COL_NAME, COL_INSTALLED, COL_CANDIDATE, COL_REPO, COL_SIZE, COL_SUMMARY = range(8)
HEADERS = ["S", "", "Пакунок", "Встановлена версія", "Остання версія", "Репозиторій", "Розмір", "Опис"]

_STATUS_ORDER = {s: i for i, s in enumerate([
    Status.UPGRADABLE, Status.ORPHAN, Status.NEWER, Status.UNNEEDED, Status.INSTALLED, Status.NOT_INSTALLED])}

SORT_KEYS = {
    COL_STATUS: lambda r: (_STATUS_ORDER[r.status], r.name.lower()),
    COL_ORIGIN: lambda r: (r.origin.value, r.name.lower()),
    COL_NAME: lambda r: (r.name.lower(), r.arch),
    COL_INSTALLED: lambda r: (r.installed_evr == "", r.installed_evr, r.name.lower()),
    COL_CANDIDATE: lambda r: (r.candidate_evr == "", r.candidate_evr, r.name.lower()),
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
    """Table over a flat list of rows; `visible` holds indices into `rows` (filtered and sorted)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list[PkgRow] = []
        self.visible: list[int] = []
        self.basearch = "x86_64"
        self._sort = (COL_NAME, Qt.AscendingOrder)

    def set_rows(self, rows: list[PkgRow], basearch: str) -> None:
        self.beginResetModel()
        self.rows = rows
        self.basearch = basearch
        self.visible = list(range(len(rows)))
        self.endResetModel()

    def set_visible(self, visible: list[int]) -> None:
        self.beginResetModel()
        self.visible = self._sorted(visible)
        self.endResetModel()

    def row_at(self, index: QModelIndex) -> PkgRow:
        return self.rows[self.visible[index.row()]]

    def index_of_key(self, key: tuple[str, str]) -> QModelIndex:
        for pos, i in enumerate(self.visible):
            if self.rows[i].key == key:
                return self.index(pos, COL_NAME)
        return QModelIndex()

    # --- sorting: done on our index list, so no QSortFilterProxyModel overhead on 70k rows

    def sort(self, column: int, order=Qt.AscendingOrder) -> None:
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
        key = SORT_KEYS[column]
        rows = self.rows
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
                return status_icon(r.status)
            if col == COL_ORIGIN:
                return origin_icon(r.origin)
        elif role == Qt.ToolTipRole:
            if col == COL_ORIGIN:
                return f"{ORIGIN_LABEL[r.origin]}: {display_repo(r.origin_repo)}"
            if col == COL_STATUS:
                return STATUS_LABEL[r.status]
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
