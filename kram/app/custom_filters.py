"""The user's own sidebar filters: kept in the settings, edited in the Custom Filters dialog, made from the current view.

Filters that ask what packages provide need libdnf5 for that: its answers are kept in the catalog snapshot, asked for
on the dnf thread when a filter needs one the snapshot does not have yet."""
import json
from collections.abc import Callable
from typing import Protocol

from ..core.catalog import Catalog
from ..core.custom_filters import CustomFilter, Field, conditions_for_view, load_filters, provides_queries
from ..core.filters import FilterEntry
from ..core.model import CatalogSnapshot
from ..core.search import Mode
from ..core.settings import store as settings
from ..core.worker import DnfWorker
from ..i18n import _
from .actions import DynamicItem
from .ports import Question, Ui
from .sidebar import SidebarModel

SETTINGS_KEY = "filters/custom"
PREFIX = "custom:"  # sidebar entry ids of custom filters: "custom:<name>"
# the search modes a filter condition can reproduce
SEARCH_FIELDS = {Mode.NAME: Field.NAME, Mode.NAME_SUMMARY: Field.NAME_SUMMARY, Mode.DESCRIPTION: Field.DESCRIPTION,
                 Mode.PROVIDES: Field.PROVIDES}


Resolve = Callable[[set[tuple[str, bool]], Callable[[], None], Callable[[], None] | None], None]


class EditDialog(Protocol):
    def __call__(self, filters: list[CustomFilter], snap: CatalogSnapshot, select: str | None,
                 new: CustomFilter | None, resolve_provides: Resolve,
                 done: Callable[[tuple[list[CustomFilter], str | None] | None], None]) -> None:
        """The front end's Custom Filters dialog: `done((filters, current name))` on OK, `done(None)` on Cancel."""
        ...


class CustomFilters:
    """The filters themselves live in `sidebar.custom`, which shows them; this loads, edits and saves them."""

    def __init__(self, sidebar: SidebarModel, catalog: Catalog, dnf: DnfWorker,
                 snapshot: Callable[[], CatalogSnapshot | None], ui: Ui, edit_dialog: EditDialog):
        self._sidebar, self._catalog, self._dnf, self._snapshot = sidebar, catalog, dnf, snapshot
        self._ui, self._edit_dialog = ui, edit_dialog

    def activated(self, entry: FilterEntry) -> None:
        """A sidebar entry was double-clicked: a custom filter opens in the dialog."""
        if entry.id.startswith(PREFIX):
            self.edit(select=entry.id.removeprefix(PREFIX))

    def restore(self) -> None:
        try:
            self._sidebar.custom = load_filters(json.loads(settings.get(SETTINGS_KEY, "[]")))
        except (TypeError, ValueError):
            self._sidebar.custom = []

    def _save(self) -> None:
        settings.set(SETTINGS_KEY, json.dumps([f.to_dict() for f in self._sidebar.custom], ensure_ascii=False))

    def queries(self) -> set[tuple[str, bool]]:
        """What the filters ask about provides: for the catalog to answer while it loads."""
        return provides_queries(self._sidebar.custom)

    def resolve_missing(self, done: Callable[[], None], failed: Callable[[], None] | None = None) -> bool:
        """Ask for the provides answers the snapshot does not have (a filter edited while it loaded, or closed
        before its count came back), then call `done`. False, and `done` is not called, when nothing is missing."""
        missing = self.queries() - self._snapshot().provides.keys()
        if missing:
            self._resolve(missing, done, failed)
        return bool(missing)

    def _resolve(self, queries: set[tuple[str, bool]], done: Callable[[], None],
                 failed: Callable[[], None] | None = None) -> None:
        """Ask libdnf5 on its own thread; the filters themselves run on this one, from the snapshot's answers."""
        snap = self._snapshot()

        def store(found):
            snap.provides.update(found)
            done()
        def store_failed(_error):  # the caller shows that the count is not there
            if failed is not None:
                failed()
        self._dnf.submit(lambda: {q: self._catalog.provides_keys(*q) for q in queries}, store, store_failed)

    def edit(self, select: str | None = None, new: CustomFilter | None = None) -> None:
        """Settings → Custom Filters…, at the filter `select` or with the filter `new` added."""
        snap = self._snapshot()
        if snap is None:
            return
        self._edit_dialog(self._sidebar.custom, snap, select, new, self._resolve, self._edited)

    def _edited(self, result: tuple[list[CustomFilter], str | None] | None) -> None:
        if result is None:
            return
        sidebar = self._sidebar
        sidebar.custom, name = result
        self._save()

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
        def answered(answer: str | None) -> None:
            if answer != "yes":
                return
            self._sidebar.custom = [f for f in self._sidebar.custom if f.name != name]
            self._save()
            self._sidebar.set_view(self._sidebar.current_view)
        self._ui.ask(Question(_("Custom Filters"), _("Delete the filter “{name}”?").format(name=name)), answered)

    def menu_items(self, entry: FilterEntry | None) -> list[DynamicItem]:
        """Edit and Delete in the sidebar menu of a custom filter's entry."""
        if entry is None or not entry.id.startswith(PREFIX):
            return []
        name = entry.id.removeprefix(PREFIX)
        return [DynamicItem(_("Edit Filter…"), lambda: self.edit(select=name), "document-edit"),
                DynamicItem(_("Delete Filter"), lambda: self.delete(name), "edit-delete")]
