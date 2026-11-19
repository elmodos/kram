"""The package list: a QTableView set up to look and behave like the QTreeView it replaces.

QTreeView rebuilds an internal item for every row on each model reset: 240 ms for 68k rows here (three times that
on a ThinkPad X220), on every search keystroke that changes the row set and every time a search is cleared.
QTableView keeps nothing per row (its row heights are one uniform size): 40 ms, whatever the number of rows.
"""
from PySide6.QtCore import QEvent, QSettings, Qt, Signal
from PySide6.QtGui import QCursor, QPalette, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QMenu,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
)

from .package_model import COL_ADVISORY, COL_CANDIDATE, COL_DOWNLOAD, COL_SIZE, HEADERS, HIDEABLE

# bumped when columns change: an old saved state would put widths and hidden flags on the wrong columns
HEADER_STATE_KEY = "table/header-v2"
SIZE_COLUMN_WIDTH = 100
COLUMN_WIDTHS = [26, 24, 230, 175, 110, 175, 150, SIZE_COLUMN_WIDTH]
ADVISORY_COLUMN_WIDTH = 150
# set once the update type column has been moved next to the latest version: a header state saved before 0.7 has
# it at the end, after the summary that stretches over the spare width
ADVISORY_COLUMN_KEY = "table/advisory-column"
# the same for the download size (hidden until the user shows it), which a header state saved before it lacks:
# restoring one shows it at the end
DOWNLOAD_COLUMN_KEY = "table/download-column"


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
    emptyLinkActivated = Signal(str)  # a link in the text shown while the list is empty

    def __init__(self, parent=None):
        super().__init__(parent)
        # why the list is empty, in the middle of it: kram.ui.empty_list
        self._empty = QLabel(self.viewport())
        self._empty.setWordWrap(True)
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setTextFormat(Qt.TextFormat.RichText)
        self._empty.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse
                                            | Qt.TextInteractionFlag.LinksAccessibleByKeyboard)
        self._empty.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        self._empty.linkActivated.connect(self.emptyLinkActivated)
        self._empty.hide()
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

    # ---------------------------------------------------------------- the empty list

    def set_empty_text(self, text: str) -> None:
        """Rich text shown while the list has no rows."""
        self._empty.setText(text)
        self._sync_empty()

    def empty_text(self) -> str:
        """What the empty list shows now, "" while it has rows."""
        return self._empty.text() if self._empty.isVisibleTo(self) else ""

    def _sync_empty(self) -> None:
        model = self.model()
        show = bool(self._empty.text()) and (model is None or model.rowCount() == 0)
        if show:
            self._place_empty()
        self._empty.setVisible(show)

    def _place_empty(self) -> None:
        area = self.viewport().rect()
        width = max(1, min(area.width() - 32, 520))
        height = self._empty.heightForWidth(width)
        self._empty.setGeometry(area.center().x() - width // 2, max(16, area.height() // 4 - height // 2),
                                width, height)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._empty.isVisible():
            self._place_empty()

    def header(self) -> QHeaderView:
        """QTreeView's name for it, which the window uses throughout."""
        return self.horizontalHeader()

    def setModel(self, model) -> None:
        super().setModel(model)
        model.modelReset.connect(self._fit_row_height)
        for signal in (model.modelReset, model.rowsInserted, model.rowsRemoved, model.layoutChanged):
            signal.connect(self._sync_empty)
        for col, width in enumerate(COLUMN_WIDTHS):
            self.setColumnWidth(col, width)
        self.setColumnWidth(COL_ADVISORY, ADVISORY_COLUMN_WIDTH)
        self._place_advisory_column()
        self._place_download_column()
        header = self.header()
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._header_menu)

    # ---------------------------------------------------------------- columns

    def _place_advisory_column(self) -> None:
        header = self.header()
        header.moveSection(header.visualIndex(COL_ADVISORY), header.visualIndex(COL_CANDIDATE) + 1)

    def _place_download_column(self) -> None:
        """Hidden, after the installed size, as wide as it."""
        header = self.header()
        header.moveSection(header.visualIndex(COL_DOWNLOAD), header.visualIndex(COL_SIZE) + 1)
        self.setColumnWidth(COL_DOWNLOAD, SIZE_COLUMN_WIDTH)
        header.setSectionHidden(COL_DOWNLOAD, True)

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
        if not (state := settings.value(HEADER_STATE_KEY)):
            return
        if settings.value(DOWNLOAD_COLUMN_KEY, False, type=bool):
            self.header().restoreState(state)
        else:
            self._restore_older(state, COL_DOWNLOAD)
            if not settings.value(ADVISORY_COLUMN_KEY, False, type=bool):
                self.setColumnWidth(COL_ADVISORY, ADVISORY_COLUMN_WIDTH)
                self._place_advisory_column()
            if not settings.value(DOWNLOAD_COLUMN_KEY, False, type=bool):
                self._place_download_column()
                # "Size" became "Installed size": the old default width cuts the title short
                self.setColumnWidth(COL_SIZE, max(self.columnWidth(COL_SIZE), SIZE_COLUMN_WIDTH))

    def _restore_older(self, state, count: int) -> None:
        """A header state saved with the first `count` columns only. Qt restores one into a header with more, but
        the state it saves afterwards is one it then refuses to restore; so read it with a header of its own size
        and take the order, widths, hidden columns and sort column over by hand."""
        old = QHeaderView(Qt.Orientation.Horizontal)
        old.setModel(QStandardItemModel(0, count, old))
        if not old.restoreState(state):
            return
        header = self.header()
        for visual, logical in enumerate(sorted(range(count), key=old.visualIndex)):
            header.moveSection(header.visualIndex(logical), visual)
        for logical in range(count):
            header.resizeSection(logical, old.sectionSize(logical))
            header.setSectionHidden(logical, old.isSectionHidden(logical))
        header.setSortIndicator(old.sortIndicatorSection(), old.sortIndicatorOrder())

    def save_columns(self, settings: QSettings) -> None:
        settings.setValue(HEADER_STATE_KEY, self.header().saveState())
        settings.setValue(ADVISORY_COLUMN_KEY, True)
        settings.setValue(DOWNLOAD_COLUMN_KEY, True)

    def _fit_row_height(self) -> None:
        """Rows as tall as the tree view made them: what the delegate asks for (text, status and origin icons), not
        the vertical header's own default, which styles make taller. Measured once, on the first rows."""
        if self._row_height_fitted or self.model().rowCount() == 0:
            return
        self.verticalHeader().setDefaultSectionSize(self.sizeHintForRow(0))
        self._row_height_fitted = True
