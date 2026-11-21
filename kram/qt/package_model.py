"""The package list's Qt model: an adapter over `kram.app.columns`, which decides what every cell shows."""
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette

from ..app.columns import (
    ALIGN_RIGHT,
    COL_ADVISORY,
    COL_CANDIDATE,
    COL_DOWNLOAD,
    COL_INSTALLED,
    COL_NAME,
    COL_ORIGIN,
    COL_REASON,
    COL_REPO,
    COL_SIZE,
    COL_STATUS,
    COL_SUMMARY,
    HEADER_TIPS,
    HEADERS,
    HIDEABLE,
    REASON_LABEL,
    cell_icon,
    cell_style,
    cell_text,
    cell_tooltip,
    human_size,
    row_tint,
)
from ..app.icons import MARK_BACKGROUND
from ..app.package_list import PackageList
from ..core.marks import MarkSet
from ..core.model import PkgRow
from .icons import icon

__all__ = ["COL_ADVISORY", "COL_CANDIDATE", "COL_DOWNLOAD", "COL_INSTALLED", "COL_NAME", "COL_ORIGIN", "COL_REASON",
           "COL_REPO", "COL_SIZE", "COL_STATUS", "COL_SUMMARY", "HEADERS", "HIDEABLE", "REASON_LABEL",
           "PackageTableModel", "human_size"]


def _bold() -> QFont:
    f = QFont()
    f.setBold(True)
    return f


def _italic() -> QFont:
    f = QFont()
    f.setItalic(True)
    return f


class PackageTableModel(QAbstractTableModel):
    """The Qt view of a kram.app.package_list.PackageList: forwards its signals as Qt's model signals and asks
    kram.app.columns what each cell shows."""

    def __init__(self, parent=None, packages: PackageList | None = None):
        super().__init__(parent)
        self.packages = packages if packages is not None else PackageList()
        self.packages.about_to_reset.connect(self.beginResetModel)
        self.packages.reset.connect(self.endResetModel)
        self.packages.about_to_sort.connect(self.layoutAboutToBeChanged.emit)
        self.packages.sorted.connect(self._on_sorted)
        self.packages.rows_changed.connect(self._on_rows_changed)
        self._ctx = self.packages.ctx

    def _on_sorted(self, moved: list[int]) -> None:
        for idx in self.persistentIndexList():
            if idx.isValid():
                self.changePersistentIndex(idx, self.index(moved[idx.row()], idx.column()))
        self.layoutChanged.emit()

    def _on_rows_changed(self, positions: list[int] | None) -> None:
        last = len(HEADERS) - 1
        if positions is None:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.packages) - 1, last))
            return
        for pos in positions:
            self.dataChanged.emit(self.index(pos, 0), self.index(pos, last))

    # --- the list's state, under the names the window has always used

    @property
    def rows(self) -> list[PkgRow]:
        return self.packages.rows

    @property
    def visible(self) -> list[int]:
        return self.packages.visible

    @property
    def marks(self) -> MarkSet:
        return self.packages.marks

    @marks.setter
    def marks(self, marks: MarkSet) -> None:
        self.packages.marks = marks

    @property
    def blocked(self) -> dict[tuple[str, str], str]:
        return self.packages.blocked

    @property
    def basearch(self) -> str:
        return self.packages.basearch

    @property
    def optional(self) -> frozenset[str]:
        return self.packages.optional

    @optional.setter
    def optional(self, names: frozenset[str]) -> None:
        self.packages.optional = names

    def set_rows(self, rows: list[PkgRow], basearch: str) -> None:
        self.packages.set_rows(rows, basearch)

    def set_blocked(self, blocked: dict[tuple[str, str], str]) -> None:
        self.packages.set_blocked(blocked)

    def set_blocked_reason(self, key: tuple[str, str], reason: str) -> None:
        self.packages.set_blocked_reason(key, reason)

    def set_visible(self, visible: list[int], ranked: bool = False) -> None:
        self.packages.set_visible(visible, ranked)

    def set_sort_column(self, sort: tuple[int, Qt.SortOrder]) -> None:
        """Change the column sort without re-sorting now; the next set_visible applies it."""
        column, order = sort
        self.packages.set_sort_column((column, order == Qt.SortOrder.DescendingOrder))

    @property
    def sort_column(self) -> tuple[int, Qt.SortOrder] | None:
        if (sort := self.packages.sort_column) is None:
            return None
        column, descending = sort
        return column, Qt.SortOrder.DescendingOrder if descending else Qt.SortOrder.AscendingOrder

    def marks_changed(self, keys=None) -> None:
        """Repaint rows whose marks changed (all visible rows if keys is None)."""
        self.packages.marks_changed(keys)

    def row_at(self, index: QModelIndex) -> PkgRow:
        return self.packages.row(index.row())

    def index_of_key(self, key: tuple[str, str]) -> QModelIndex:
        pos = self.packages.position_of(key)
        return self.index(pos, COL_NAME) if pos is not None else QModelIndex()

    def sort(self, column: int, order=Qt.SortOrder.AscendingOrder) -> None:
        """Header clicks: sorted on the list's index list, so no QSortFilterProxyModel overhead on 70k rows."""
        self.packages.sort(column, order == Qt.SortOrder.DescendingOrder)

    # --- Qt model API

    def rowCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(self.packages.visible)

    def columnCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return HEADERS[section]
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.ToolTipRole:
            return HEADER_TIPS.get(section)
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        r = self.packages.row(index.row())
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return cell_text(r, col, self._ctx)
        if role == Qt.ItemDataRole.DecorationRole:
            ref = cell_icon(r, col, self._ctx)
            return icon(ref) if ref is not None else None
        if role == Qt.ItemDataRole.ToolTipRole:
            return cell_tooltip(r, col, self._ctx)
        if role == Qt.ItemDataRole.BackgroundRole:
            action = row_tint(r, self.marks)
            return QColor(*MARK_BACKGROUND[action]) if action is not None else None
        if role == Qt.ItemDataRole.TextAlignmentRole and col in ALIGN_RIGHT:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.FontRole and col in (COL_NAME, COL_CANDIDATE):
            style = cell_style(r, col, self._ctx)
            return _bold() if style.bold else _italic() if style.italic else None
        if role == Qt.ItemDataRole.ForegroundRole and col in (COL_CANDIDATE, COL_ADVISORY):
            if cell_style(r, col, self._ctx).dimmed:
                return QGuiApplication.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)
        return None
