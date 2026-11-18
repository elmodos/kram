"""The package list: a QTableView set up to look and behave like the QTreeView it replaces.

QTreeView rebuilds an internal item for every row on each model reset: 240 ms for 68k rows here (three times that
on a ThinkPad X220), on every search keystroke that changes the row set and every time a search is cleared.
QTableView keeps nothing per row (its row heights are one uniform size): 40 ms, whatever the number of rows.
"""
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
)


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

    def _fit_row_height(self) -> None:
        """Rows as tall as the tree view made them: what the delegate asks for (text, status and origin icons), not
        the vertical header's own default, which styles make taller. Measured once, on the first rows."""
        if self._row_height_fitted or self.model().rowCount() == 0:
            return
        self.verticalHeader().setDefaultSectionSize(self.sizeHintForRow(0))
        self._row_height_fitted = True
