"""Left panel: one filter list whose content is chosen by the buttons below it, as in Synaptic."""
from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import (
    QButtonGroup,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from ..core.filters import (
    FilterEntry,
    custom_filter_entries,
    group_filters,
    origin_filters,
    status_filters,
    visible_entries,
)
from ..core.marks import ACTION_LABELS
from ..core.model import CatalogSnapshot
from ..core.search import MODE_LABELS, Mode
from ..i18n import _
from .group_icons import group_icon
from .icons import MARK_BACKGROUND, mark_icon, origin_icon, status_filter_icon

MAX_HISTORY = 30
INDENT_ROLE = Qt.ItemDataRole.UserRole + 1  # FilterEntry.indent: nesting level of the row

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
        self.marked = None  # the MarkSet: marked keys for the "Marked" status entry, marked comps groups
        self.custom: list = []  # kram.core.custom_filters.CustomFilter, in sidebar order

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.setItemDelegate(_IndentDelegate(self.list))
        self.list.currentRowChanged.connect(self._on_row)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
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
            self._entries = visible_entries(status_filters(self._snap, self.marked), self._selected.get(self._view))
        else:
            self._entries = builder(self._snap)
        self.list.blockSignals(True)
        self.list.clear()
        want = self._selected.get(self._view)
        current = 0
        for i, e in enumerate(self._entries):
            item = QListWidgetItem(e.label + (f"   ({e.count})" if e.count is not None else ""))
            item.setData(INDENT_ROLE, e.indent)
            tip = e.tip
            if e.origin is not None:
                item.setIcon(origin_icon(e.origin))
            elif e.group and self.marked is not None and (action := self.marked.group(e.group)) is not None:
                # like a marked package row: the mark's box and tint instead of the group's icon
                item.setIcon(mark_icon(action))
                item.setBackground(QColor(*MARK_BACKGROUND[action]))
                marked = _("Marked: {action}").format(action=ACTION_LABELS[action])
                tip = f"{tip}\n{marked}" if tip else marked
            elif e.group is not None:
                item.setIcon(group_icon(e.group))
            elif (icon := status_filter_icon(e.id)) is not None:
                item.setIcon(icon)
            if tip:
                item.setToolTip(tip)
            if e.bold or (i == 0 and e.query is None):
                f = QFont(item.font())
                f.setBold(True)
                item.setFont(f)
            self.list.addItem(item)
            if e.id == want:
                current = i
        if not self._entries:
            placeholder = QListWidgetItem(_("Search history is empty") if self._view == "search" else
                                          _("No custom filters yet.\nRight-click to create one."))
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
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


class _IndentDelegate(QStyledItemDelegate):
    """Shifts a nested row's icon and text right; the selection and the row's tint stay full width."""

    def _shift(self, option: QStyleOptionViewItem, index) -> int:
        level = index.data(INDENT_ROLE) or 0
        if not level:
            return 0
        style = option.widget.style() if option.widget else None
        margin = style.pixelMetric(QStyle.PixelMetric.PM_FocusFrameHMargin, option, option.widget) + 1 if style else 3
        # one step puts a child's icon under its parent's text
        return level * (option.decorationSize.width() + 2 * margin)

    def paint(self, painter, option, index) -> None:
        shift = self._shift(option, index)
        if not shift:
            super().paint(painter, option, index)
            return
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        style = opt.widget.style() if opt.widget else None
        if style is None:
            super().paint(painter, option, index)
            return
        # background, selection, hover and focus over the whole row
        style.drawPrimitive(QStyle.PrimitiveElement.PE_PanelItemViewItem, opt, painter, opt.widget)
        # then icon and text in the shifted rect, without a second panel
        content = QStyleOptionViewItem(opt)
        content.rect = opt.rect.adjusted(shift, 0, 0, 0)
        if opt.state & QStyle.StateFlag.State_Selected:
            group = (QPalette.ColorGroup.Active if opt.state & QStyle.StateFlag.State_Active
                     else QPalette.ColorGroup.Inactive)
            content.palette.setColor(QPalette.ColorRole.Text, opt.palette.color(group, QPalette.ColorRole.HighlightedText))
        content.state &= ~(QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_MouseOver
                           | QStyle.StateFlag.State_HasFocus)
        content.backgroundBrush = Qt.BrushStyle.NoBrush
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, content, painter, opt.widget)

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setWidth(size.width() + self._shift(option, index))
        return size


def _history_id(text: str, mode: int) -> str:
    return f"search:{mode}:{text}"
