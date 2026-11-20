"""Loads the details of the package under the cursor for the detail tabs, once the cursor rests on it."""
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer

from ..core.catalog import Catalog
from ..core.model import PkgDetails, PkgRow
from ..core.worker import DnfWorker
from .details import DetailsTabs

# libdnf5 holds Python's lock while it looks the details up, so the window would stop for each row the cursor only
# passes (typing, holding an arrow key)
DETAILS_DELAY_MS = 120


class DetailsLoader(QObject):
    def __init__(self, tabs: DetailsTabs, catalog: Catalog, dnf: DnfWorker,
                 blocked: Callable[[tuple[str, str]], str | None],
                 set_reason: Callable[[tuple[str, str], str], None], parent: QObject):
        """`blocked`: why the upgrade of a package cannot be installed now, or None; "" when it is not known yet.
        `set_reason`: keeps a reason looked up for the cursor's row."""
        super().__init__(parent)
        self._tabs, self._catalog, self._dnf, self._blocked = tabs, catalog, dnf, blocked
        self._set_reason = set_reason
        # blocked keys whose reason was asked for since the blocked upgrades last arrived: the cursor's rests and
        # the arrival do not ask twice, nor again for one the resolver gives no reason for
        self._asked: set[tuple[str, str]] = set()
        self._row: PkgRow | None = None
        self._details: PkgDetails | None = None  # of `_row`, once loaded
        self.timer = QTimer(self, singleShot=True, interval=DETAILS_DELAY_MS)
        self.timer.timeout.connect(self.load)

    def follow(self, row: PkgRow) -> None:
        """The cursor is on `row`: its advisories at once (they come with the row), the rest once it rests there."""
        self._row = row
        self._details = None
        self._tabs.show_advisories(row)
        self._tabs.show_blocked(self._blocked(row.key))
        self.timer.start()

    def refresh_blocked(self) -> None:
        """The blocked upgrades arrived (they are resolved after the list is up)."""
        self._asked.clear()
        if self._row is not None:
            self._tabs.show_blocked(self._blocked(self._row.key))
            self._fetch_reason(self._row)

    def clear(self) -> None:
        """Nothing is listed."""
        self.timer.stop()
        self._row = self._details = None
        self._tabs.clear()

    def details_of(self, key: tuple[str, str]) -> PkgDetails | None:
        """The details of the package under the cursor, if that is `key` and they have arrived."""
        return self._details if self._row is not None and self._row.key == key else None

    def _is_current(self, row: PkgRow) -> bool:
        return self._row is not None and self._row.key == row.key

    def load(self) -> None:
        row = self._row
        if row is None:
            return
        # skipped on the dnf thread when the cursor moved on while it waited its turn
        self._dnf.submit(lambda: self._catalog.details(row.key) if self._is_current(row) else None,
                         lambda d: self._show(row, d))
        self._fetch_reason(row)

    def _fetch_reason(self, row: PkgRow) -> None:
        """A blocked upgrade whose reason the resolve of the whole upgrade did not give: asked for on its own."""
        if self._blocked(row.key) == "" and row.key not in self._asked:
            self._asked.add(row.key)
            self._dnf.submit(lambda: self._catalog.blocked_reason(row.key) if self._is_current(row) else None,
                             lambda reason: self._show_reason(row, reason))

    def _show_reason(self, row: PkgRow, reason: str | None) -> None:
        if reason is None:  # skipped on the dnf thread, the cursor had moved on: to be asked again
            self._asked.discard(row.key)
            return
        self._set_reason(row.key, reason)  # kept for the list's tooltip even when the cursor moved on
        if self._is_current(row):
            self._tabs.show_blocked(self._blocked(row.key))

    def _show(self, row: PkgRow, d: PkgDetails | None) -> None:
        if d is not None and self._is_current(row):  # ignore stale results when the cursor moved on
            self._details = d
            self._tabs.show_package(row, d)
