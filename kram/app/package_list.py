"""The package list's contents without a toolkit: the rows, which of them are shown in which order, and the marks,
blocked upgrades and optional names the cells show. A front end's list widget is a view over a `PackageList`.

Positions are ints: position p shows `rows[visible[p]]`. Sorting is done here, on the index list, rather than by the
toolkit: a sort proxy over 70k rows costs more than the sort itself.
"""
from ..core.mainloop import Signal
from ..core.marks import MarkSet
from ..core.model import PkgRow
from .columns import COL_NAME, CellContext, sorted_positions, version_ranks

# more changed rows than this: one change signal for the whole list
MANY_MARKS = 1000

Sort = tuple[int, bool]  # (column, descending)


class PackageList:
    """`visible` holds indices into `rows`, filtered and sorted. Two orderings: by a column, or "ranked": the order
    a search produced, kept as it is until the user sorts by a column.

    Signals, in the order a front end needs them:
    `about_to_reset()` / `reset()`: around a change of the whole list (new rows, another filter or search);
    `about_to_sort()` / `sorted(moved)`: around a re-sort of the shown rows, `moved[old_position]` = new position;
    `rows_changed(positions)`: those positions show something else (their marks, a blocked reason); None for all.
    """

    def __init__(self) -> None:
        self.rows: list[PkgRow] = []
        self.visible: list[int] = []
        self.ctx = CellContext()  # the marks, the blocked upgrades, the basearch and the optional names
        self._sort: Sort | None = (COL_NAME, False)
        self._positions_cache: dict[tuple[str, str], int] | None = None  # key -> position, see _positions
        self._ranks: dict[str, int] | None = None
        self.about_to_reset = Signal()
        self.reset = Signal()
        self.about_to_sort = Signal()
        self.sorted = Signal()
        self.rows_changed = Signal()

    # ---------------------------------------------------------------- what the cells show

    @property
    def marks(self) -> MarkSet:
        return self.ctx.marks

    @marks.setter
    def marks(self, marks: MarkSet) -> None:
        self.ctx.marks = marks

    @property
    def blocked(self) -> dict[tuple[str, str], str]:
        """Upgradable packages whose upgrade cannot be installed now -> the resolver's reason; see
        Catalog.blocked_upgrades. Filled after each load, so it may lag the rows by a moment. Always this one dict,
        changed in place: the sidebar's "Cannot be upgraded now" entry reads it."""
        return self.ctx.blocked

    @property
    def basearch(self) -> str:
        return self.ctx.basearch

    @property
    def optional(self) -> frozenset[str]:
        """The selected comps group's optional package names: in italics, as installing the group leaves them out."""
        return self.ctx.optional

    @optional.setter
    def optional(self, names: frozenset[str]) -> None:
        self.ctx.optional = names

    # ---------------------------------------------------------------- changes

    def set_rows(self, rows: list[PkgRow], basearch: str) -> None:
        self.about_to_reset.emit()
        self.rows = rows
        self.ctx.basearch = basearch
        self.blocked.clear()
        self.visible = list(range(len(rows)))
        self._positions_cache = None
        self._ranks = None
        self.reset.emit()

    def set_blocked(self, blocked: dict[tuple[str, str], str]) -> None:
        self.blocked.clear()
        self.blocked.update(blocked)
        if self.visible:
            self.rows_changed.emit(None)

    def set_blocked_reason(self, key: tuple[str, str], reason: str) -> None:
        """The reason of one blocked row, looked up for the selected row after the list was filled."""
        if key not in self.blocked:
            return
        self.blocked[key] = reason
        pos = self.position_of(key)
        if pos is not None:
            self.rows_changed.emit([pos])

    def set_visible(self, visible: list[int], ranked: bool = False) -> None:
        """`ranked`: keep the given order (search relevance) instead of the column sort."""
        self.about_to_reset.emit()
        self.visible = visible if ranked or self._sort is None else self._sorted(visible)
        self._positions_cache = None
        self.reset.emit()

    def marks_changed(self, keys=None) -> None:
        """The marks of `keys` changed (of any row if None): their rows show it."""
        if not self.visible:
            return
        if keys is None:
            self.rows_changed.emit(None)
            return
        keys = list(keys)
        if len(keys) > MANY_MARKS:
            # one signal for the whole list: a signal per row would make marking every row take minutes
            self.rows_changed.emit(None)
            return
        positions = self._positions()
        found = [pos for key in keys if (pos := positions.get(key)) is not None]
        if found:
            self.rows_changed.emit(found)

    # ---------------------------------------------------------------- sorting

    @property
    def sort_column(self) -> Sort | None:
        """The column sort, None while the order is ranked."""
        return self._sort

    def set_sort_column(self, sort: Sort | None) -> None:
        """Change the column sort without re-sorting now; the next `set_visible` applies it. None: ranked."""
        self._sort = sort

    def sort(self, column: int, descending: bool = False) -> None:
        """Re-sort the shown rows by `column`; a negative column keeps their order as it is and makes it the ranked
        one (a cleared sort indicator)."""
        if column < 0:
            self._sort = None
            return
        self._sort = (column, descending)
        self.about_to_sort.emit()
        old = self.visible
        self.visible = self._sorted(old)
        self._positions_cache = None
        new_pos = {i: pos for pos, i in enumerate(self.visible)}
        self.sorted.emit([new_pos[i] for i in old])

    def _sorted(self, visible: list[int]) -> list[int]:
        column, descending = self._sort
        return sorted_positions(self.rows, visible, column, descending, self._version_ranks)

    def _version_ranks(self) -> dict[str, int]:
        if self._ranks is None:
            self._ranks = version_ranks(self.rows)
        return self._ranks

    # ---------------------------------------------------------------- lookups

    def __len__(self) -> int:
        return len(self.visible)

    def row(self, pos: int) -> PkgRow:
        return self.rows[self.visible[pos]]

    def shown_rows(self) -> list[PkgRow]:
        """The shown rows, in the order shown."""
        return [self.rows[i] for i in self.visible]

    def position_of(self, key: tuple[str, str]) -> int | None:
        return self._positions().get(key)

    def _positions(self) -> dict[tuple[str, str], int]:
        """The position of each shown key, built once per change of the list: a linear scan per key made marking
        thousands of rows at once quadratic."""
        if self._positions_cache is None:
            self._positions_cache = {self.rows[i].key: pos for pos, i in enumerate(self.visible)}
        return self._positions_cache
