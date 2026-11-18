"""The package list: a QTableView set up to look and behave like the QTreeView it replaces.

QTreeView rebuilds an internal item for every row on each model reset: 240 ms for 68k rows here (three times that
on a ThinkPad X220), on every search keystroke that changes the row set and every time a search is cleared.
QTableView keeps nothing per row (its row heights are one uniform size): 40 ms, whatever the number of rows.
"""
from PySide6.QtCore import QEvent, QSettings, Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QMenu,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
)

from .package_model import COL_ADVISORY, COL_CANDIDATE, HEADERS, HIDEABLE

# bumped when columns change: an old saved state would put widths and hidden flags on the wrong columns
HEADER_STATE_KEY = "table/header-v2"
COLUMN_WIDTHS = [26, 24, 230, 175, 110, 175, 150, 80]
ADVISORY_COLUMN_WIDTH = 150
# set once the update type column has been moved next to the latest version: a header state saved before 0.7 has
# it at the end, after the summary that stretches over the spare width
ADVISORY_COLUMN_KEY = "table/advisory-column"


class RowDelegate(QStyledItemDelegate):
    """Highlights every cell of the row under the mouse, as QTreeView highlights the row: QTableView marks only the
    cell under the mouse. Each cell draws its own hover frame, as the style makes it."""

    def __init__(self, view: "PackageView"):
        super().__init__(view)
        self._view = view

    def initStyleOption(self, option: QStyleOptionViewItem, index) -> None:
        super().initStyleOption(option, index)
        if index.row() == self._view.hover_row:
            option.state |= QStyle.StateFlag.State_MouseOver
        else:
            option.state &= ~QStyle.StateFlag.State_MouseOver


class PackageView(QTableView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setTabKeyNavigation(False)  # Tab leaves the list, as it did
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        rows = self.verticalHeader()
        rows.hide()
        rows.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        rows.setMinimumSectionSize(1)
        # the tree view's header: left-aligned titles, movable columns, the last one taking the spare width, and no
        # bold title for the column of the current cell
        columns = self.horizontalHeader()
        columns.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        columns.setSectionsMovable(True)
        columns.setStretchLastSection(True)
        columns.setHighlightSections(False)
        self._row_height_fitted = False
        self.hover_row = -1
        self.setMouseTracking(True)
        self.setItemDelegate(RowDelegate(self))

    def _set_hover_row(self, row: int) -> None:
        if row == self.hover_row:
            return
        old, self.hover_row = self.hover_row, row
        width = self.viewport().width()
        for r in (old, row):
            if r >= 0:
                self.viewport().update(0, self.rowViewportPosition(r), width, self.rowHeight(r))

    def mouseMoveEvent(self, event) -> None:
        self._set_hover_row(self.rowAt(event.position().toPoint().y()))
        super().mouseMoveEvent(event)

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        super().scrollContentsBy(dx, dy)
        if dy and self.hover_row >= 0:  # the wheel brings another row under the mouse
            pos = self.viewport().mapFromGlobal(QCursor.pos())
            self._set_hover_row(self.rowAt(pos.y()) if self.viewport().rect().contains(pos) else -1)

    def viewportEvent(self, event) -> bool:
        if event.type() in (QEvent.Type.Leave, QEvent.Type.HoverLeave):
            self._set_hover_row(-1)
        return super().viewportEvent(event)

    def header(self) -> QHeaderView:
        """QTreeView's name for it, which the window uses throughout."""
        return self.horizontalHeader()

    def setModel(self, model) -> None:
        super().setModel(model)
        model.modelReset.connect(self._fit_row_height)
        for col, width in enumerate(COLUMN_WIDTHS):
            self.setColumnWidth(col, width)
        self.setColumnWidth(COL_ADVISORY, ADVISORY_COLUMN_WIDTH)
        self._place_advisory_column()
        header = self.header()
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._header_menu)

    # ---------------------------------------------------------------- columns

    def _place_advisory_column(self) -> None:
        header = self.header()
        header.moveSection(header.visualIndex(COL_ADVISORY), header.visualIndex(COL_CANDIDATE) + 1)

    def _header_menu(self, pos) -> None:
        """Right-click on the column titles: show or hide the columns that may be hidden."""
        header = self.header()
        m = QMenu(self)
        for col in HIDEABLE:
            act = m.addAction(HEADERS[col])
            act.setCheckable(True)
            act.setChecked(not header.isSectionHidden(col))
            act.toggled.connect(lambda on, c=col: header.setSectionHidden(c, not on))
        m.exec(header.viewport().mapToGlobal(pos))

    def restore_columns(self, settings: QSettings) -> None:
        """Widths, order and hidden columns as the user left them."""
        if state := settings.value(HEADER_STATE_KEY):
            self.header().restoreState(state)
            if not settings.value(ADVISORY_COLUMN_KEY, False, type=bool):
                self.setColumnWidth(COL_ADVISORY, ADVISORY_COLUMN_WIDTH)
                self._place_advisory_column()

    def save_columns(self, settings: QSettings) -> None:
        settings.setValue(HEADER_STATE_KEY, self.header().saveState())
        settings.setValue(ADVISORY_COLUMN_KEY, True)

    def _fit_row_height(self) -> None:
        """Rows as tall as the tree view made them: what the delegate asks for (text, status and origin icons), not
        the vertical header's own default, which styles make taller. Measured once, on the first rows."""
        if self._row_height_fitted or self.model().rowCount() == 0:
            return
        self.verticalHeader().setDefaultSectionSize(self.sizeHintForRow(0))
        self._row_height_fitted = True
