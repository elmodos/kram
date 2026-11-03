from functools import cache

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QFont

from ..core.model import PkgRow, Status
from ..core.origin import display_repo
from .icons import ORIGIN_LABEL, origin_icon, status_icon

COL_STATUS, COL_ORIGIN, COL_NAME, COL_INSTALLED, COL_CANDIDATE, COL_REPO, COL_SIZE, COL_SUMMARY = range(8)
HEADERS = ["S", "", "Пакунок", "Встановлена версія", "Остання версія", "Репозиторій", "Розмір", "Опис"]


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
    """Table over a flat list of rows; `visible` holds indices into `rows` (filter result)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list[PkgRow] = []
        self.visible: list[int] = []

    def set_rows(self, rows: list[PkgRow]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.visible = list(range(len(rows)))
        self.endResetModel()

    def set_visible(self, visible: list[int]) -> None:
        self.beginResetModel()
        self.visible = visible
        self.endResetModel()

    def row_at(self, index: QModelIndex) -> PkgRow:
        return self.rows[self.visible[index.row()]]

    def rowCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(self.visible)

    def columnCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return HEADERS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        r = self.rows[self.visible[index.row()]]
        col = index.column()
        if role == Qt.DisplayRole:
            match col:
                case 2: return r.name if r.arch in ("noarch", "x86_64") else f"{r.name}.{r.arch}"
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
        elif role == Qt.ToolTipRole and col == COL_ORIGIN:
            return ORIGIN_LABEL[r.origin]
        elif role == Qt.TextAlignmentRole and col == COL_SIZE:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        elif role == Qt.FontRole and col == COL_CANDIDATE and r.status is Status.UPGRADABLE:
            return _bold()
        return None
