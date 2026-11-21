"""Settings → Custom Filters: editing a copy of the user's filters (Synaptic's filter editor). `FiltersEdit` holds
the copy, which one is being edited, how many packages it matches (asking libdnf5 for what provides a capability,
once), and whether the result can be saved; the front end's dialog holds the editor's widgets and gives back what
they contain (`FiltersView.editor_contents`)."""
import copy
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from ..core.custom_filters import Condition, CustomFilter, Field, choices, provides_queries
from ..core.model import CatalogSnapshot
from ..i18n import _, ngettext
from .ports import view_ref
from .scheduler import Scheduler

EDITABLE_CHOICES = (Field.REPO, Field.ARCH)  # values may not be in the current catalog (disabled repo, i686)
RECOUNT_MS = 200
# (queries, done, failed): adds the answers to snap.provides in the background, then calls done, or failed
ResolveProvides = Callable[[set[tuple[str, bool]], Callable[[], None], Callable[[], None]], None]


@dataclass(frozen=True)
class ValueEditor:
    """What a condition's value is edited with: free text, or a choice of values (which may be typed over)."""
    options: list[tuple[str, str]] | None  # (value, label); None: free text
    editable: bool = False
    placeholder: str = ""
    numeric: bool = False                   # megabytes


def value_editor(field: Field, snap: CatalogSnapshot | None) -> ValueEditor:
    options = choices(field, snap)
    if options is not None:
        return ValueEditor(options, field in EDITABLE_CHOICES)
    if field is Field.SIZE:
        return ValueEditor(None, placeholder=_("megabytes"), numeric=True)
    if field is Field.PROVIDES:
        return ValueEditor(None, placeholder=_("capability, e.g. application()"))
    return ValueEditor(None, placeholder=_("text"))


class FiltersView(Protocol):
    def editor_contents(self) -> tuple[str, bool, list[Condition]]:
        """The editor's name, "match all", and conditions."""
        ...

    def show_count(self, text: str) -> None: ...


class FiltersEdit:
    def __init__(self, filters: list[CustomFilter], snap: CatalogSnapshot | None, view: FiltersView,
                 scheduler: Scheduler, resolve_provides: ResolveProvides | None = None):
        self.filters = copy.deepcopy(filters)
        self.current = -1
        self._snap, self._view, self._resolve_provides = snap, view_ref(view), resolve_provides
        self._asked: set[tuple[str, bool]] = set()
        self._recount = scheduler.timer(RECOUNT_MS, self.update_count)

    def current_name(self) -> str | None:
        return self.filters[self.current].name if 0 <= self.current < len(self.filters) else None

    def unique(self, base: str) -> str:
        names = {f.name for f in self.filters}
        name, n = base, 2
        while name in names:
            name, n = f"{base} {n}", n + 1
        return name

    def store(self) -> None:
        """Write the editor's contents back into the current filter."""
        if not 0 <= self.current < len(self.filters):
            return
        f = self.filters[self.current]
        name, match_all, conditions = self._view.editor_contents()
        f.name, f.match_all, f.conditions = name.strip(), match_all, conditions

    def select(self, row: int) -> CustomFilter | None:
        """The editor moves to another filter: the one to show in it."""
        self.store()
        self.current = row
        return self.filters[row] if 0 <= row < len(self.filters) else None

    def add(self, f: CustomFilter) -> int:
        self.store()
        self.filters.append(f)
        return len(self.filters) - 1

    def delete(self) -> int | None:
        """Delete the current filter; its index, None if there was none."""
        i = self.current
        if not 0 <= i < len(self.filters):
            return None
        self.current = -1  # nothing to store back
        del self.filters[i]
        return i

    def changed(self) -> None:
        """Something in the editor changed: count again once it settles."""
        self._recount.start()

    def update_count(self) -> None:
        self.store()
        if self._snap is None or not 0 <= self.current < len(self.filters):
            self._view.show_count("")
            return
        current = self.filters[self.current]
        if missing := provides_queries([current]) - self._snap.provides.keys():
            self._view.show_count(_("Counting…"))
            if self._resolve_provides is not None and (new := missing - self._asked):
                self._asked |= new
                self._resolve_provides(new, self.update_count, lambda: self._count_failed(new))
            return
        pred = current.compile(self._snap)
        n = sum(1 for r in self._snap.rows if pred(r))
        self._view.show_count(ngettext("{n} package matches", "{n} packages match", n).format(n=n))

    def _count_failed(self, queries: set) -> None:
        """libdnf5 could not count them: say so, and ask again the next time the filter is shown."""
        self._asked -= queries
        self._view.show_count(_("Could not count"))

    def problem(self) -> str | None:
        """Why the filters cannot be saved as they are; None if they can."""
        self.store()
        names = [f.name for f in self.filters]
        if any(not n for n in names):
            return _("Every filter needs a name.")
        if len(set(names)) != len(names):
            return _("Two filters have the same name.")
        return None
