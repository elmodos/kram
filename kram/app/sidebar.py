"""The sidebar's logic: which filter entries each view lists, which one is selected in each view, which are unfolded,
and the search history. The front end draws the entries it is given and reports what the user picks.

One list whose content the buttons below it choose, as in Synaptic. Nested entries (an origin's repositories, an
environment's groups) are children of the entry above them; only the views in COLLAPSIBLE fold.
"""
from dataclasses import dataclass

from ..core.filters import (
    FilterEntry,
    custom_filter_entries,
    environment_filters,
    group_filters,
    origin_filters,
    status_filters,
    visible_entries,
)
from ..core.mainloop import Signal
from ..core.model import CatalogSnapshot
from ..core.search import MODE_LABELS, Mode
from ..i18n import _
from .icons import STATUS_FILTER_ICONS, IconRef
from .scheduler import Scheduler

MAX_HISTORY = 30
COLLAPSIBLE = {"environments"}  # views whose parents fold; the others stay open

# (id, label, builder); "search" and "custom" are built from the sidebar's own history / custom filters
VIEWS = [
    ("status", _("Status"), status_filters),
    ("origin", _("Origin"), origin_filters),
    ("groups", _("Groups"), group_filters),
    ("environments", _("Environments"), environment_filters),
    ("search", _("Search results"), "history"),
    ("custom", _("Custom filters"), "custom"),
]
# the icon on each view's button: symbolic, so it reads as one monochrome glyph next to the label in any theme
VIEW_ICONS = {
    "status": "checkbox-checked-symbolic", "origin": "network-server-symbolic", "groups": "view-grid-symbolic",
    "environments": "computer-symbolic", "search": "edit-find-symbolic", "custom": "object-select-symbolic",
}


def history_id(text: str, mode: int) -> str:
    return f"search:{mode}:{text}"


def entry_text(e: FilterEntry) -> str:
    """What the list shows for an entry: its label and its count."""
    return e.label + (f"   ({e.count})" if e.count is not None else "")


def entry_icon(e: FilterEntry) -> IconRef | None:
    if e.origin is not None:
        return ("origin", e.origin)
    if e.group is not None:
        return ("group", e.group)
    return STATUS_FILTER_ICONS.get(e.id)


def entry_font(e: FilterEntry) -> tuple[bool, bool]:
    """(bold, italic): an "All …" entry heads the view, installed groups are bold; an environment's optional groups
    are in italics."""
    return e.bold or e.id.endswith(":all"), e.dim


@dataclass
class Listing:
    """What the list shows now. `parents[i]`: the index of entry i's parent, None for a top-level entry. `placeholder`:
    the text in place of entries when there are none."""
    view: str
    entries: list[FilterEntry]
    parents: list[int | None]
    current: str | None
    expanded: set[str]
    collapsible: bool
    placeholder: str


class SidebarModel:
    """`listed(listing)`: draw this (the front end keeps its own selection signals quiet meanwhile).
    `filter_changed(entry)`: filter the package list by `entry`. `entry_changed(index, entry)`: one entry's count
    changed, redraw it alone."""

    def __init__(self, scheduler: Scheduler):
        self._scheduler = scheduler
        self._snap: CatalogSnapshot | None = None
        self.entries: list[FilterEntry] = []
        self._view = "status"
        self._selected: dict[str, str] = {}  # view -> selected entry id
        self._current: str | None = None
        # the view of the entry the list is filtered by: the view shown unless the terminal front end steps through
        # the views without filtering (`browse`)
        self._filter_view = self._view
        self._expanded: set[str] = set()  # ids of the unfolded entries of the collapsible views
        self.history: list[tuple[str, int, int]] = []  # (text, mode, result count), newest first
        self.marked = None  # the MarkSet: marked keys for the "Marked" status entry
        self.blocked = None  # the upgrades that cannot be installed now, for "Cannot be upgraded now"
        self.custom: list = []  # kram.core.custom_filters.CustomFilter, in sidebar order
        self.listed = Signal()
        self.filter_changed = Signal()
        self.entry_changed = Signal()

    # ---------------------------------------------------------------- what is shown

    def set_snapshot(self, snap: CatalogSnapshot) -> None:
        self._snap = snap
        self._rebuild()

    def set_view(self, view_id: str) -> None:
        self._view = view_id
        self._rebuild()

    def browse(self, view_id: str) -> None:
        """Show `view_id`'s entries without filtering by one: the terminal front end steps through the views and
        filters only when an entry is picked (docs/TUI_SPEC.md §7.2.3). The filter, its view and entry stay."""
        self._view = view_id
        self._rebuild(emit=False)

    def select(self, view_id: str, entry_id: str) -> None:
        self._selected[view_id] = entry_id
        self.set_view(view_id)

    def refresh_counts(self) -> None:
        """Recount entries (e.g. after marking) without changing the selection or re-filtering."""
        self._rebuild(emit=False)

    def refresh_marked_count(self) -> None:
        """After marking: only the "Marked" entry's count changes. Recounting every status filter over the whole
        catalog on each mark made marking slow."""
        for i, e in enumerate(self.entries):
            if e.id == "status:marked":
                e.count = len(self.marked) if self.marked is not None else 0
                self.entry_changed.emit(i, e)
                return

    @property
    def current_view(self) -> str:
        return self._view

    @property
    def current_entry_id(self) -> str | None:
        """The entry the list is filtered by."""
        return self._current

    @property
    def filter_view(self) -> str:
        """The view `current_entry_id` is in: `current_view` but while `browse` shows another one."""
        return self._filter_view

    # ---------------------------------------------------------------- search history

    def add_search(self, text: str, mode: int, count: int) -> None:
        """Remember a search; when the search view is open, select it without re-emitting."""
        self.history = [(text, mode, count)] + [h for h in self.history if h[:2] != (text, mode)]
        del self.history[MAX_HISTORY:]
        self._selected["search"] = history_id(text, mode)
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
            kept = any(history_id(text, mode) == self._selected.get("search") for text, mode, _c in history)
            self._rebuild(emit=not kept)

    def _history_entries(self) -> list[FilterEntry]:
        return [FilterEntry(history_id(text, mode),
                            _("“{text}” — {mode}").format(text=text, mode=MODE_LABELS[Mode(mode)].lower()),
                            lambda _r: True, count, query=(text, mode))
                for text, mode, count in self.history]

    # ---------------------------------------------------------------- what the user does

    def chosen(self, index: int | None) -> None:
        """The user selected the entry at `index` (None: nothing selectable)."""
        e = self.entries[index] if index is not None and 0 <= index < len(self.entries) else None
        if e is not None:
            left = self._selected.get(self._view)
            self._selected[self._view] = e.id
            self._current = e.id
            self._filter_view = self._view
            self.filter_changed.emit(e)
            # an empty entry that stayed only because it was selected (a restored "Cannot be upgraded now"): gone once
            # the selection leaves it. After this signal, not in the middle of the list's own selection change
            if left != e.id and any(x.id == left and x.hide_empty and x.count == 0 for x in self.entries):
                self._scheduler.later(lambda: self._rebuild(emit=False))
        elif not self.entries:
            self._current = None
            self._filter_view = self._view
            self.filter_changed.emit(FilterEntry("empty", "", lambda _r: True))

    def folded(self, index: int, expanded: bool) -> None:
        if 0 <= index < len(self.entries):
            (self._expanded.add if expanded else self._expanded.discard)(self.entries[index].id)

    def entry(self, index: int | None) -> FilterEntry | None:
        return self.entries[index] if index is not None and 0 <= index < len(self.entries) else None

    # ---------------------------------------------------------------- building

    def _build(self) -> list[FilterEntry]:
        builder = next(b for vid, _l, b in VIEWS if vid == self._view)
        if builder == "history":
            return self._history_entries()
        if builder == "custom":
            return custom_filter_entries(self._snap, self.custom)
        if builder is status_filters:
            return visible_entries(status_filters(self._snap, self.marked, self.blocked),
                                   self._selected.get(self._view))
        return builder(self._snap)

    def _rebuild(self, emit: bool = True) -> None:
        if self._snap is None:
            return
        self.entries = entries = self._build()
        collapsible = self._view in COLLAPSIBLE
        parents: list[int | None] = []
        parent = None
        for i, e in enumerate(entries):
            if e.indent and parent is not None:
                parents.append(parent)
            else:
                parents.append(None)
                parent = i
        want = self._selected.get(self._view)
        current = next((i for i, e in enumerate(entries) if e.id == want), None)
        if collapsible and current is not None and parents[current] is not None:  # a selected child shows
            self._expanded.add(entries[parents[current]].id)
        if current is None and entries:
            current = 0
        current_id = entries[current].id if current is not None else None
        if self._view == self._filter_view:  # a view browsed to does not filter until an entry is picked
            self._current = current_id
        placeholder = (_("Search history is empty") if self._view == "search" else
                       _("No custom filters yet.\nRight-click to create one.")) if not entries else ""
        self.listed.emit(Listing(self._view, entries, parents, current_id, set(self._expanded), collapsible,
                                 placeholder))
        if emit:
            self.chosen(current)
