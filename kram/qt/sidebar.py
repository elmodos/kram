"""Left panel: one filter list whose content is chosen by the buttons below it, as in Synaptic; a view over
kram.app.sidebar.SidebarModel. A tree: nested entries (an origin's repositories, an environment's groups) are
children of the entry above them."""
from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QButtonGroup,
    QHeaderView,
    QPushButton,
    QStyle,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..app.sidebar import VIEW_ICONS, VIEWS, Listing, SidebarModel, entry_font, entry_icon, entry_text
from ..core.filters import FilterEntry
from .icons import icon
from .qt_loop import QtScheduler

INDEX_ROLE = Qt.ItemDataRole.UserRole + 1  # the item's position in the model's entries


class Sidebar(QWidget):
    """`filterChanged(entry)` is the model's; the context menu and double clicks are the widget's own."""
    contextMenuRequested = Signal(QPoint, object)  # global position, FilterEntry under the cursor or None
    entryActivated = Signal(object)  # FilterEntry, on double click

    def __init__(self, parent=None, model: SidebarModel | None = None):
        super().__init__(parent)
        self.model = model if model is not None else SidebarModel(QtScheduler(self))
        self.model.listed.connect(self._draw)
        self.model.entry_changed.connect(self._redraw_entry)
        self.filterChanged = self.model.filter_changed
        self._items: list[QTreeWidgetItem] = []  # aligned with the model's entries
        self._view = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.list = _Tree()
        self.list.setHeaderHidden(True)
        self.list.setUniformRowHeights(True)
        # one step puts a child's icon under its parent's text, as the old flat list's indent did
        style = self.list.style()
        self._indent = style.pixelMetric(QStyle.PixelMetric.PM_SmallIconSize) + 2 * (
            style.pixelMetric(QStyle.PixelMetric.PM_FocusFrameHMargin) + 1)
        self.list.currentItemChanged.connect(lambda item, _prev: self.model.chosen(self._index_of(item)))
        self.list.itemExpanded.connect(lambda item: self._fold(item, True))
        self.list.itemCollapsed.connect(lambda item: self._fold(item, False))
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(
            lambda pos: self.contextMenuRequested.emit(self.list.viewport().mapToGlobal(pos), self._entry_at(pos)))
        self.list.itemDoubleClicked.connect(
            lambda item, _col: (e := self._entry_of(item)) and self.entryActivated.emit(e))
        lay.addWidget(self.list, 1)

        self._buttons = QButtonGroup(self)
        for view_id, label, _builder in VIEWS:
            btn = QPushButton(QIcon.fromTheme(VIEW_ICONS[view_id]), label)
            btn.setCheckable(True)
            btn.setChecked(view_id == self.model.current_view)
            btn.clicked.connect(lambda _checked, v=view_id: self.set_view(v))
            self._buttons.addButton(btn)
            lay.addWidget(btn)

    # ---------------------------------------------------------------- the model's state, as the window knows it

    def __getattr__(self, name):
        # set_snapshot, select, add_search, remove_search, clear_history, refresh_counts, refresh_marked_count
        if name in _FORWARDED:
            return getattr(self.model, name)
        raise AttributeError(name)

    history = property(lambda self: self.model.history, lambda self, v: setattr(self.model, "history", v))
    marked = property(lambda self: self.model.marked, lambda self, v: setattr(self.model, "marked", v))
    blocked = property(lambda self: self.model.blocked, lambda self, v: setattr(self.model, "blocked", v))
    custom = property(lambda self: self.model.custom, lambda self, v: setattr(self.model, "custom", v))
    current_view = property(lambda self: self.model.current_view)
    current_entry_id = property(lambda self: self.model.current_entry_id)

    def set_view(self, view_id: str) -> None:
        self.model.set_view(view_id)

    def item_of(self, entry_id: str) -> QTreeWidgetItem | None:
        return next((item for e, item in zip(self.model.entries, self._items, strict=True) if e.id == entry_id), None)

    # ---------------------------------------------------------------- drawing

    def _draw(self, listing: Listing) -> None:
        for btn, (vid, _label, _b) in zip(self._buttons.buttons(), VIEWS, strict=True):
            btn.setChecked(vid == listing.view)
        tree = self.list
        tree.blockSignals(True)
        tree.clear()
        tree.setRootIsDecorated(listing.collapsible)
        tree.setItemsExpandable(listing.collapsible)
        tree.setIndentation(self._indent)
        self._items = []
        current = None
        for i, e in enumerate(listing.entries):
            item = QTreeWidgetItem([entry_text(e)])
            item.setData(0, INDEX_ROLE, i)
            if (ref := entry_icon(e)) is not None:
                item.setIcon(0, icon(ref))
            if e.tip:
                item.setToolTip(0, e.tip)
            bold, italic = entry_font(e)
            if bold or italic:
                f = QFont(item.font(0))
                f.setBold(bold)
                f.setItalic(italic)
                item.setFont(0, f)
            parent = listing.parents[i]
            if parent is not None:
                self._items[parent].addChild(item)
            else:
                tree.addTopLevelItem(item)
            self._items.append(item)
            if e.id == listing.current:
                current = item
        if listing.placeholder:
            placeholder = QTreeWidgetItem([listing.placeholder])
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            tree.addTopLevelItem(placeholder)
        if listing.collapsible:
            for e, item in zip(listing.entries, self._items, strict=True):
                item.setExpanded(e.id in listing.expanded)
        else:
            tree.expandAll()
        tree.setCurrentItem(current)
        tree.blockSignals(False)

    def _redraw_entry(self, index: int, entry: FilterEntry) -> None:
        if 0 <= index < len(self._items):
            self._items[index].setText(0, entry_text(entry))

    def _index_of(self, item: QTreeWidgetItem | None) -> int | None:
        return item.data(0, INDEX_ROLE) if item is not None else None

    def _entry_of(self, item: QTreeWidgetItem | None) -> FilterEntry | None:
        return self.model.entry(self._index_of(item))

    def _entry_at(self, pos) -> FilterEntry | None:
        return self._entry_of(self.list.itemAt(pos))

    def _fold(self, item: QTreeWidgetItem, expanded: bool) -> None:
        if (i := self._index_of(item)) is not None:
            self.model.folded(i, expanded)


_FORWARDED = {"set_snapshot", "select", "add_search", "remove_search", "clear_history", "refresh_counts",
              "refresh_marked_count"}


class _Tree(QTreeWidget):
    """The sidebar's tree: its one column is as wide as the longest entry, scrolled sideways as the flat list was
    (a stretched column elides instead), and never narrower than the view, so the selection spans the whole row."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.header().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.header().setStretchLastSection(False)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # ResizeToContents never goes below the minimum section size
        self.header().setMinimumSectionSize(self.viewport().width())
