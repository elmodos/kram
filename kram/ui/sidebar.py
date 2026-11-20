"""Left panel: one filter list whose content is chosen by the buttons below it, as in Synaptic. A tree: nested
entries (an origin's repositories, an environment's groups) are children of the entry above them."""
from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QFont
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

from ..core.filters import (
    FilterEntry,
    custom_filter_entries,
    environment_filters,
    group_filters,
    origin_filters,
    status_filters,
    visible_entries,
)
from ..core.model import CatalogSnapshot
from ..core.search import MODE_LABELS, Mode
from ..i18n import _
from .group_icons import group_icon
from .icons import origin_icon, status_filter_icon

MAX_HISTORY = 30
INDEX_ROLE = Qt.ItemDataRole.UserRole + 1  # the item's position in Sidebar._entries
COLLAPSIBLE = {"environments"}  # views whose parents fold, with the style's arrows; the others stay open

# (id, label, builder); "search" and "custom" are built from the sidebar's own history / custom filters
VIEWS = [
    ("status", _("Status"), status_filters),
    ("origin", _("Origin"), origin_filters),
    ("groups", _("Groups"), group_filters),
    ("environments", _("Environments"), environment_filters),
    ("search", _("Search results"), "history"),
    ("custom", _("Custom filters"), "custom"),
]


class Sidebar(QWidget):
    filterChanged = Signal(object)  # FilterEntry
    contextMenuRequested = Signal(QPoint, object)  # global position, FilterEntry under the cursor or None
    entryActivated = Signal(object)  # FilterEntry, on double click

    def __init__(self, parent=None):
        super().__init__(parent)
        self._snap: CatalogSnapshot | None = None
        self._entries: list[FilterEntry] = []
        self._items: list[QTreeWidgetItem] = []  # aligned with _entries
        self._view = "status"
        self._selected: dict[str, str] = {}  # view -> selected entry id
        self._expanded: set[str] = set()  # ids of the unfolded entries of the collapsible views
        self.history: list[tuple[str, int, int]] = []  # (text, mode, result count), newest first
        self.marked = None  # the MarkSet: marked keys for the "Marked" status entry
        self.blocked = None  # the upgrades that cannot be installed now, for "Cannot be upgraded now"
        self.custom: list = []  # kram.core.custom_filters.CustomFilter, in sidebar order

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.list = _Tree()
        self.list.setHeaderHidden(True)
        self.list.setUniformRowHeights(True)
        # one step puts a child's icon under its parent's text, as the old flat list's indent did
        style = self.list.style()
        self._indent = style.pixelMetric(QStyle.PixelMetric.PM_SmallIconSize) + 2 * (
            style.pixelMetric(QStyle.PixelMetric.PM_FocusFrameHMargin) + 1)
        self.list.currentItemChanged.connect(lambda item, _prev: self._on_item(item))
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
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(view_id == self._view)
            btn.clicked.connect(lambda _checked, v=view_id: self.set_view(v))
            self._buttons.addButton(btn)
            lay.addWidget(btn)

    def set_snapshot(self, snap: CatalogSnapshot) -> None:
        self._snap = snap
        self._rebuild()

    def set_view(self, view_id: str) -> None:
        self._view = view_id
        for btn, (vid, _label, _b) in zip(self._buttons.buttons(), VIEWS, strict=True):
            btn.setChecked(vid == view_id)
        self._rebuild()

    def select(self, view_id: str, entry_id: str) -> None:
        self._selected[view_id] = entry_id
        self.set_view(view_id)

    def add_search(self, text: str, mode: int, count: int) -> None:
        """Remember a search; when the search view is open, select it without re-emitting."""
        self.history = [(text, mode, count)] + [h for h in self.history if h[:2] != (text, mode)]
        del self.history[MAX_HISTORY:]
        self._selected["search"] = _history_id(text, mode)
        if self._view == "search":
            self._rebuild(emit=False)

    def remove_search(self, text: str, mode: int) -> None:
        self._drop_history([h for h in self.history if h[:2] != (text, mode)])

    def clear_history(self) -> None:
        self._drop_history([])

    def _drop_history(self, history: list[tuple[str, int, int]]) -> None:
        """Replace the history; the list re-filters only if the selected search went away."""
        self.history = history
        if self._view == "search":
            kept = any(_history_id(text, mode) == self._selected.get("search") for text, mode, _c in history)
            self._rebuild(emit=not kept)

    def _history_entries(self) -> list[FilterEntry]:
        return [FilterEntry(_history_id(text, mode), _("“{text}” — {mode}").format(text=text, mode=MODE_LABELS[Mode(mode)].lower()),
                            lambda _r: True, count, query=(text, mode))
                for text, mode, count in self.history]

    def refresh_counts(self) -> None:
        """Recount entries (e.g. after marking) without changing the selection or re-filtering."""
        self._rebuild(emit=False)

    def refresh_marked_count(self) -> None:
        """After marking: only the "Marked" entry's count changes. Recounting every status filter over the whole
        catalog on each mark made marking slow."""
        for e, item in zip(self._entries, self._items, strict=True):
            if e.id == "status:marked":
                e.count = len(self.marked) if self.marked is not None else 0
                item.setText(0, f"{e.label}   ({e.count})")
                return

    @property
    def current_view(self) -> str:
        return self._view

    @property
    def current_entry_id(self) -> str | None:
        e = self._entry_of(self.list.currentItem())
        return e.id if e is not None else None

    def item_of(self, entry_id: str) -> QTreeWidgetItem | None:
        return next((item for e, item in zip(self._entries, self._items, strict=True) if e.id == entry_id), None)

    def _rebuild(self, emit: bool = True) -> None:
        if self._snap is None:
            return
        builder = next(b for vid, _l, b in VIEWS if vid == self._view)
        if builder == "history":
            self._entries = self._history_entries()
        elif builder == "custom":
            self._entries = custom_filter_entries(self._snap, self.custom)
        elif builder is status_filters:
            self._entries = visible_entries(status_filters(self._snap, self.marked, self.blocked), self._selected.get(self._view))
        else:
            self._entries = builder(self._snap)
        collapsible = self._view in COLLAPSIBLE
        tree = self.list
        tree.blockSignals(True)
        tree.clear()
        tree.setRootIsDecorated(collapsible)
        tree.setItemsExpandable(collapsible)
        tree.setIndentation(self._indent)
        self._items = []
        want = self._selected.get(self._view)
        current = None
        parent = None
        for i, e in enumerate(self._entries):
            item = QTreeWidgetItem([e.label + (f"   ({e.count})" if e.count is not None else "")])
            item.setData(0, INDEX_ROLE, i)
            if e.origin is not None:
                item.setIcon(0, origin_icon(e.origin))
            elif e.group is not None:
                item.setIcon(0, group_icon(e.group))
            elif (icon := status_filter_icon(e.id)) is not None:
                item.setIcon(0, icon)
            if e.tip:
                item.setToolTip(0, e.tip)
            # an "All …" entry heads the view; installed groups; an environment's optional groups in italics
            if e.bold or e.dim or e.id.endswith(":all"):
                f = QFont(item.font(0))
                f.setBold(e.bold or e.id.endswith(":all"))
                f.setItalic(e.dim)
                item.setFont(0, f)
            if e.indent and parent is not None:
                parent.addChild(item)
            else:
                tree.addTopLevelItem(item)
                parent = item
            self._items.append(item)
            if e.id == want:
                current = item
        if not self._entries:
            placeholder = QTreeWidgetItem([_("Search history is empty") if self._view == "search" else
                                           _("No custom filters yet.\nRight-click to create one.")])
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            tree.addTopLevelItem(placeholder)
        if collapsible:
            for e, item in zip(self._entries, self._items, strict=True):
                item.setExpanded(e.id in self._expanded)
            if current is not None and current.parent() is not None:  # a selected child shows
                current.parent().setExpanded(True)
                self._expanded.add(self._entry_of(current.parent()).id)
        else:
            tree.expandAll()
        if current is None and self._items:
            current = self._items[0]
        tree.setCurrentItem(current)
        tree.blockSignals(False)
        if emit:
            self._on_item(current)

    def _entry_of(self, item: QTreeWidgetItem | None) -> FilterEntry | None:
        i = item.data(0, INDEX_ROLE) if item is not None else None
        return self._entries[i] if i is not None and 0 <= i < len(self._entries) else None

    def _entry_at(self, pos) -> FilterEntry | None:
        return self._entry_of(self.list.itemAt(pos))

    def _fold(self, item: QTreeWidgetItem, expanded: bool) -> None:
        if (e := self._entry_of(item)) is not None:
            (self._expanded.add if expanded else self._expanded.discard)(e.id)

    def _on_item(self, item: QTreeWidgetItem | None) -> None:
        if (e := self._entry_of(item)) is not None:
            left = self._selected.get(self._view)
            self._selected[self._view] = e.id
            self.filterChanged.emit(e)
            # an empty entry that stayed only because it was selected (a restored "Cannot be upgraded now"): gone once
            # the selection leaves it. After this signal, not in the middle of the tree's own selection change
            if left != e.id and any(x.id == left and x.hide_empty and x.count == 0 for x in self._entries):
                QTimer.singleShot(0, lambda: self._rebuild(emit=False))
        elif not self._entries:
            self.filterChanged.emit(FilterEntry("empty", "", lambda _r: True))


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


def _history_id(text: str, mode: int) -> str:
    return f"search:{mode}:{text}"
