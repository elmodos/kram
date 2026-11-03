"""Left panel: one filter list whose content is chosen by the buttons below it, as in Synaptic."""
from PySide6.QtCore import Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QButtonGroup, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget

from ..core.filters import FilterEntry, origin_filters, status_filters
from ..core.model import CatalogSnapshot
from .icons import origin_icon

# (id, label, builder or None if not implemented yet)
VIEWS = [
    ("status", "Статус", status_filters),
    ("origin", "Походження", origin_filters),
    ("groups", "Групи", None),
    ("search", "Результати пошуку", None),
    ("custom", "Власні фільтри", None),
]


class Sidebar(QWidget):
    filterChanged = Signal(object)  # FilterEntry

    def __init__(self, parent=None):
        super().__init__(parent)
        self._snap: CatalogSnapshot | None = None
        self._entries: list[FilterEntry] = []
        self._view = "status"
        self._selected: dict[str, str] = {}  # view -> selected entry id

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._on_row)
        lay.addWidget(self.list, 1)

        self._buttons = QButtonGroup(self)
        for view_id, label, builder in VIEWS:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(view_id == self._view)
            btn.setEnabled(builder is not None)
            if builder is None:
                btn.setToolTip("Буде в наступних версіях")
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

    @property
    def current_view(self) -> str:
        return self._view

    @property
    def current_entry_id(self) -> str | None:
        row = self.list.currentRow()
        return self._entries[row].id if 0 <= row < len(self._entries) else None

    def _rebuild(self) -> None:
        if self._snap is None:
            return
        builder = next(b for vid, _l, b in VIEWS if vid == self._view)
        self._entries = builder(self._snap)
        self.list.blockSignals(True)
        self.list.clear()
        want = self._selected.get(self._view)
        current = 0
        for i, e in enumerate(self._entries):
            item = QListWidgetItem("    " * e.indent + e.label + (f"   ({e.count})" if e.count is not None else ""))
            if e.origin is not None:
                item.setIcon(origin_icon(e.origin))
            if i == 0:
                f = QFont(item.font())
                f.setBold(True)
                item.setFont(f)
            self.list.addItem(item)
            if e.id == want:
                current = i
        self.list.blockSignals(False)
        self.list.setCurrentRow(current)
        self._on_row(current)

    def _on_row(self, row: int) -> None:
        if 0 <= row < len(self._entries):
            e = self._entries[row]
            self._selected[self._view] = e.id
            self.filterChanged.emit(e)
