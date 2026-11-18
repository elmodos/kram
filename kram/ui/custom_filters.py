"""The user's own sidebar filters: kept in the settings, edited in the Custom Filters dialog, made from the current view.

Filters that ask what packages provide need libdnf5 for that: its answers are kept in the catalog snapshot, asked for
on the dnf thread when a filter needs one the snapshot does not have yet."""
import json
from collections.abc import Callable

from PySide6.QtCore import QObject, QSettings
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMenu, QMessageBox, QWidget

from ..core.catalog import Catalog
from ..core.custom_filters import CustomFilter, Field, conditions_for_view, load_filters, provides_queries
from ..core.filters import FilterEntry
from ..core.model import CatalogSnapshot
from ..core.search import Mode
from ..core.worker import DnfWorker
from ..i18n import _
from .filters_dialog import FiltersDialog
from .sidebar import Sidebar

SETTINGS_KEY = "filters/custom"
PREFIX = "custom:"  # sidebar entry ids of custom filters: "custom:<name>"
# the search modes a filter condition can reproduce
SEARCH_FIELDS = {Mode.NAME: Field.NAME, Mode.NAME_SUMMARY: Field.NAME_SUMMARY, Mode.DESCRIPTION: Field.DESCRIPTION,
                 Mode.PROVIDES: Field.PROVIDES}


class CustomFilters(QObject):
    """The filters themselves live in `sidebar.custom`, which shows them; this loads, edits and saves them."""

    def __init__(self, sidebar: Sidebar, catalog: Catalog, dnf: DnfWorker,
                 snapshot: Callable[[], CatalogSnapshot | None], parent: QWidget):
        super().__init__(parent)
        self._window = parent  # for the dialogs
        self._sidebar, self._catalog, self._dnf, self._snapshot = sidebar, catalog, dnf, snapshot
        sidebar.entryActivated.connect(lambda e: e.id.startswith(PREFIX) and self.edit(select=e.id.removeprefix(PREFIX)))

    def restore(self) -> None:
        try:
            self._sidebar.custom = load_filters(json.loads(QSettings().value(SETTINGS_KEY, "[]")))
        except (TypeError, ValueError):
            self._sidebar.custom = []

    def _save(self) -> None:
        QSettings().setValue(SETTINGS_KEY, json.dumps([f.to_dict() for f in self._sidebar.custom], ensure_ascii=False))

    def queries(self) -> set[tuple[str, bool]]:
        """What the filters ask about provides: for the catalog to answer while it loads."""
        return provides_queries(self._sidebar.custom)

    def resolve_missing(self, done: Callable[[], None]) -> bool:
        """Ask for the provides answers the snapshot does not have (a filter edited while it loaded, or closed
        before its count came back), then call `done`. False, and `done` is not called, when nothing is missing."""
        missing = self.queries() - self._snapshot().provides.keys()
        if missing:
            self._resolve(missing, done)
        return bool(missing)

    def _resolve(self, queries: set[tuple[str, bool]], done: Callable[[], None]) -> None:
        """Ask libdnf5 on its own thread; the filters themselves run on this one, from the snapshot's answers."""
        snap = self._snapshot()

        def store(found):
            snap.provides.update(found)
            done()
        self._dnf.submit(lambda: {q: self._catalog.provides_keys(*q) for q in queries}, store)

    def edit(self, select: str | None = None, new: CustomFilter | None = None) -> None:
        """Settings → Custom Filters…, at the filter `select` or with the filter `new` added."""
        snap = self._snapshot()
        if snap is None:
            return
        sidebar = self._sidebar
        d = FiltersDialog(sidebar.custom, snap, self._window, select=select, new=new, resolve_provides=self._resolve)
        if not d.exec():
            return
        sidebar.custom = d.filters()
        self._save()
        name = d.current_name()

        def show():
            if name is not None:
                sidebar.select("custom", PREFIX + name)
            elif sidebar.current_view == "custom":
                sidebar.set_view("custom")
        if not self.resolve_missing(show):
            show()

    def new_from_view(self, entry: FilterEntry | None, text: str, mode: Mode) -> None:
        """A new filter with the conditions of the sidebar entry and the search shown now."""
        entry_id = self._sidebar.current_entry_id or ""
        search_field = SEARCH_FIELDS.get(mode)
        conditions = conditions_for_view(entry_id, text, search_field)
        if entry_id.startswith(PREFIX):
            base = next((f for f in self._sidebar.custom if PREFIX + f.name == entry_id), None)
            if base is not None:
                conditions = list(base.conditions) + conditions
        # named after what it reproduces: "Upgradable", "COPR “term”", …; "All" adds nothing to the name
        from_view = bool(conditions_for_view(entry_id, "", None)) or entry_id.startswith(PREFIX)
        parts = [entry.label if entry and from_view else "", f"“{text}”" if text and search_field else ""]
        self.edit(new=CustomFilter(" ".join(p for p in parts if p) or _("New filter"), conditions))

    def delete(self, name: str) -> None:
        if QMessageBox.question(self._window, _("Custom Filters"), _("Delete the filter “{name}”?").format(name=name)) \
                != QMessageBox.StandardButton.Yes:
            return
        self._sidebar.custom = [f for f in self._sidebar.custom if f.name != name]
        self._save()
        self._sidebar.set_view(self._sidebar.current_view)

    def fill_menu(self, m: QMenu, entry: FilterEntry | None) -> None:
        """Edit and Delete in the sidebar menu of a custom filter's entry."""
        if entry is None or not entry.id.startswith(PREFIX):
            return
        name = entry.id.removeprefix(PREFIX)
        m.addAction(QIcon.fromTheme("document-edit"), _("Edit Filter…"), lambda: self.edit(select=name))
        m.addAction(QIcon.fromTheme("edit-delete"), _("Delete Filter"), lambda: self.delete(name))
        m.addSeparator()
