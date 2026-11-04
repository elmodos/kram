"""Left panel: one filter list whose content is chosen by the buttons below it, as in Synaptic."""
from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QButtonGroup, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget

from ..core.filters import FilterEntry, custom_filter_entries, group_filters, origin_filters, status_filters
from ..core.model import CatalogSnapshot
from ..core.search import MODE_LABELS, Mode
from ..i18n import _
from .icons import origin_icon, status_icon

MAX_HISTORY = 30

# (id, label, builder); "search" and "custom" are built from the sidebar's own history / custom filters
VIEWS = [
    ("status", _("Status"), status_filters),
    ("origin", _("Origin"), origin_filters),
    ("groups", _("Groups"), group_filters),
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
        self._view = "status"
        self._selected: dict[str, str] = {}  # view -> selected entry id
        self.history: list[tuple[str, int, int]] = []  # (text, mode, result count), newest first
        self.marked = None  # container of marked keys, for the "Marked" status entry
        self.custom: list = []  # kram.core.custom_filters.CustomFilter, in sidebar order

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._on_row)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(
            lambda pos: self.contextMenuRequested.emit(self.list.viewport().mapToGlobal(pos), self._entry_at(pos)))
        self.list.itemDoubleClicked.connect(
            lambda item: (e := self._entry_at(self.list.visualItemRect(item).center())) and self.entryActivated.emit(e))
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

    def _history_entries(self) -> list[FilterEntry]:
        return [FilterEntry(_history_id(text, mode), _("“{text}” — {mode}").format(text=text, mode=MODE_LABELS[Mode(mode)].lower()),
                            lambda _r: True, count, query=(text, mode))
                for text, mode, count in self.history]

    def refresh_counts(self) -> None:
        """Recount entries (e.g. after marking) without changing the selection or re-filtering."""
        self._rebuild(emit=False)

    @property
    def current_view(self) -> str:
        return self._view

    @property
    def current_entry_id(self) -> str | None:
        row = self.list.currentRow()
        return self._entries[row].id if 0 <= row < len(self._entries) else None

    def _rebuild(self, emit: bool = True) -> None:
        if self._snap is None:
            return
        builder = next(b for vid, _l, b in VIEWS if vid == self._view)
        if builder == "history":
            self._entries = self._history_entries()
        elif builder == "custom":
            self._entries = custom_filter_entries(self._snap, self.custom)
        elif builder is status_filters:
            self._entries = status_filters(self._snap, self.marked)
        else:
            self._entries = builder(self._snap)
        self.list.blockSignals(True)
        self.list.clear()
        want = self._selected.get(self._view)
        current = 0
        for i, e in enumerate(self._entries):
            item = QListWidgetItem("    " * e.indent + e.label + (f"   ({e.count})" if e.count is not None else ""))
            if e.origin is not None:
                item.setIcon(origin_icon(e.origin))
            elif e.status is not None:
                item.setIcon(status_icon(e.status))
            if e.tip:
                item.setToolTip(e.tip)
            if i == 0 and e.query is None:
                f = QFont(item.font())
                f.setBold(True)
                item.setFont(f)
            self.list.addItem(item)
            if e.id == want:
                current = i
        if not self._entries:
            placeholder = QListWidgetItem(_("Search history is empty") if self._view == "search" else
                                          _("No custom filters yet.\nRight-click to create one."))
            placeholder.setFlags(Qt.NoItemFlags)
            self.list.addItem(placeholder)
        self.list.setCurrentRow(current)
        self.list.blockSignals(False)
        if emit:
            self._on_row(current)

    def _entry_at(self, pos) -> FilterEntry | None:
        row = self.list.indexAt(pos).row()
        return self._entries[row] if 0 <= row < len(self._entries) else None

    def _on_row(self, row: int) -> None:
        if 0 <= row < len(self._entries):
            e = self._entries[row]
            self._selected[self._view] = e.id
            self.filterChanged.emit(e)
        elif not self._entries:
            self.filterChanged.emit(FilterEntry("empty", "", lambda _r: True))


def _history_id(text: str, mode: int) -> str:
    return f"search:{mode}:{text}"
