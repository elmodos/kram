"""Marking: what the user marks for the next transaction, in the package list's marks. Comps groups are not marked:
their menu runs the change at once.

The window decides what is selected and repaints; this decides what a mark means: which upgrades "Mark All Upgrades"
takes, the packages that must go with a removal, the marks a reload leaves without a package."""
from collections.abc import Callable

from ..core.catalog import Catalog
from ..core.filters import upgrades_by_kind
from ..core.history import UndoStep
from ..core.mainloop import Signal
from ..core.marks import Action, Mark, allowed_actions, allowed_group_actions
from ..core.model import CatalogSnapshot, GroupInfo, PkgRow, Status
from ..core.worker import DnfWorker
from ..i18n import N_, _, ngettext
from .actions import DynamicItem
from .markings import read_markings
from .package_list import PackageList
from .ports import CANCEL, Button, Question, Ui

# sidebar menu of a comps group: (text, theme icon); None stands for an install with optional packages. Each runs
# at once, after the review: groups are not marked
GROUP_MENU = {
    Action.INSTALL: (N_("Install Group…"), "list-add"),
    None: (N_("Install Group with Optional Packages…"), "list-add"),
    Action.UPGRADE: (N_("Upgrade Group…"), "go-up"),
    Action.REMOVE: (N_("Remove Group…"), "list-remove"),
}
ENVIRONMENT_MENU = {
    Action.INSTALL: (N_("Install Environment…"), "list-add"),
    None: (N_("Install Environment with Optional Groups…"), "list-add"),
    Action.UPGRADE: (N_("Upgrade Environment…"), "go-up"),
    Action.REMOVE: (N_("Remove Environment…"), "list-remove"),
}
MESSAGE_MS = 8000  # how long a status bar message about a bulk marking stays


class Marker:
    """`changed(keys)`: the marks of these package keys changed (None: of any number of packages). `groups_changed()`:
    the check for group upgrades is done. `message(text, ms)`: a status bar message and its timeout. `failed(error)`:
    a background check failed."""

    def __init__(self, packages: PackageList, catalog: Catalog, dnf: DnfWorker, ui: Ui):
        self.packages, self._catalog, self._dnf, self._ui = packages, catalog, dnf, ui
        self.marks = packages.marks
        self.changed = Signal()
        self.groups_changed = Signal()
        self.message = Signal()
        self.failed = Signal()
        self.snapshot: CatalogSnapshot | None = None
        self._upgrades_of_kind: dict[str, list[PkgRow]] = {}  # see upgrades_by_kind
        self.unneeded: list[PkgRow] = []  # what dnf autoremove would remove

    # ---------------------------------------------------------------- catalog

    def set_snapshot(self, snap: CatalogSnapshot) -> None:
        """A (re)loaded catalog: drop the marks that no longer apply, find which groups can be upgraded."""
        self.snapshot = snap
        self._upgrades_of_kind = upgrades_by_kind(snap.rows)
        self.unneeded = [r for r in snap.rows if r.unneeded]
        self.revalidate()
        self._check_group_upgrades(snap)

    def upgrades_of(self, kind: str) -> list[PkgRow]:
        """UPGRADES_SECURITY, UPGRADES_SECURITY_HIGH or UPGRADES_FIXES."""
        return self._upgrades_of_kind.get(kind, [])

    def group(self, key: str) -> GroupInfo | None:
        """A comps group or environment by GroupInfo.key."""
        if self.snapshot is None:
            return None
        return next((g for g in (*self.snapshot.groups, *self.snapshot.environments) if g.key == key), None)

    def revalidate(self) -> None:
        """After a reload, drop marks that no longer apply (package gone, already installed, ...). Says nothing: the
        reloaded list is drawn afresh anyway."""
        rows = {r.key: r for r in self.snapshot.rows}
        for key, mark in list(self.marks.items()):
            row = rows.get(key)
            if row is None or not (mark.action is Action.DOWNGRADE and row.installed
                                   or mark.action in allowed_actions(row)):
                self.marks.unmark(key)

    def _check_group_upgrades(self, snap: CatalogSnapshot) -> None:
        """Find which installed groups `dnf5 group upgrade` would change, after the list is shown (a dry-run
        resolve each, ~0.1 s); until then their Upgrade item is disabled."""
        installed = [g.key for g in (*snap.groups, *snap.environments) if g.installed]
        if not installed:
            return

        def done(found: set[str]) -> None:
            if self.snapshot is not snap:
                return  # reloaded meanwhile: that load runs its own check
            for g in (*snap.groups, *snap.environments):
                if g.installed:
                    g.upgradable = g.key in found
            self.groups_changed.emit()
        self._dnf.submit(lambda: self._catalog.upgradable_groups(installed), done, self.failed.emit)

    # ---------------------------------------------------------------- packages

    def mark(self, rows: list[PkgRow], action: Action, evr: str = "") -> None:
        before = {r.key: self.marks.get(r.key) for r in rows}
        changed = [r.key for r in rows if self.marks.set(r, action, evr)]
        if changed:
            self.changed.emit(changed)
            if action is Action.REMOVE:
                self._check_removal_dependents(changed, {k: before[k] for k in changed})

    def _check_removal_dependents(self, keys: list, before: dict[tuple[str, str], Mark | None]) -> None:
        """Like Synaptic: packages that depend on the ones just marked for removal must go too; offer to mark them."""
        rows = {r.key: r for r in self.snapshot.rows}
        remove = self.marks.request(rows).get("remove", [])

        def done(dependents):
            marks = self.marks
            if any((m := marks.get(k)) is None or m.action is not Action.REMOVE for k in keys):
                return  # the marks changed meanwhile
            extra = [rows[k] for k in dependents if k not in marks and k in rows]
            if not extra:
                return
            question = Question(
                "Kram", ngettext("{n} installed package depends on the packages marked for removal and has to be "
                                 "removed as well:",
                                 "{n} installed packages depend on the packages marked for removal and have to be "
                                 "removed as well:", len(extra)).format(n=len(extra)),
                (CANCEL, Button("mark", _("Mark"), "accept")), informative=", ".join(sorted(r.name for r in extra)),
                default="mark")
            self._ui.ask(question, lambda answer: self._answer_dependents(answer, extra, before))
        self._dnf.submit(lambda: self._catalog.removal_dependents(remove), done, self.failed.emit)

    def _answer_dependents(self, answer: str | None, extra: list[PkgRow],
                           before: dict[tuple[str, str], Mark | None]) -> None:
        marks = self.marks
        if answer == "mark":
            for r in extra:
                marks.set(r, Action.REMOVE)
            self.changed.emit([r.key for r in extra])
        else:  # as in Synaptic, cancelling takes back the removal that needed them
            for k, m in before.items():
                marks.restore(k, m)
            self.changed.emit(list(before))

    def unmark(self, rows: list[PkgRow]) -> None:
        keys = [r.key for r in rows if r.key in self.marks]
        for k in keys:
            self.marks.unmark(k)
        self.changed.emit(keys)

    def unmark_all(self) -> None:
        self.marks.clear()
        self.changed.emit(None)

    def toggle_likely(self, row: PkgRow) -> bool:
        """Unmark the row, or mark it for the one change it obviously wants: install or upgrade.
        False, and nothing changes, when there is none (an installed package without an upgrade)."""
        if row.key in self.marks:
            self.marks.unmark(row.key)
        else:
            allowed = allowed_actions(row)
            action = next((a for a in (Action.INSTALL, Action.UPGRADE) if a in allowed), None)
            if action is None:
                return False
            self.marks.set(row, action)
        self.changed.emit([row.key])
        return True

    def mark_all_upgrades(self) -> None:
        if self.snapshot:
            self._mark_for_upgrade([r for r in self.snapshot.rows if r.status is Status.UPGRADABLE])

    def mark_upgrades(self, kind: str) -> None:
        """Mark the upgrades of one kind: UPGRADES_SECURITY, UPGRADES_SECURITY_HIGH or UPGRADES_FIXES."""
        self._mark_for_upgrade(self.upgrades_of(kind))

    def _mark_for_upgrade(self, rows: list[PkgRow]) -> None:
        """Upgrades that cannot be installed now are left out (see PackageList.blocked): marked one by one, the Apply
        dialog says why they cannot be carried out."""
        blocked = self.packages.blocked
        left_out = sum(1 for r in rows if r.key in blocked)
        changed = [r.key for r in rows if r.key not in blocked and self.marks.set(r, Action.UPGRADE)]
        self.changed.emit(None)
        text = ngettext("{n} package marked for upgrade", "{n} packages marked for upgrade", len(changed)).format(
            n=len(changed))
        if left_out:
            text += "; " + ngettext("{n} upgrade left out: it cannot be installed now",
                                    "{n} upgrades left out: they cannot be installed now", left_out).format(n=left_out)
            text += ". " + _("Status → Cannot be upgraded now lists them with the reason.")
        self.message.emit(text, MESSAGE_MS)

    def mark_unneeded(self) -> None:
        """Autoremove: mark every unneeded dependency for removal. The Apply dialog then shows what goes, including
        what becomes unneeded only once these are gone."""
        changed = [r.key for r in self.unneeded if self.marks.set(r, Action.REMOVE)]
        self.changed.emit(None)
        self.message.emit(ngettext("{n} unneeded dependency marked for removal",
                                   "{n} unneeded dependencies marked for removal",
                                   len(changed)).format(n=len(changed)), MESSAGE_MS)

    def read_file(self, path: str) -> None:
        """Add the marks from a markings file to the current ones; report what could not be marked."""
        def marked(n: int) -> None:
            self.changed.emit(None)
            self.message.emit(ngettext("{n} package marked", "{n} packages marked", n).format(n=n), 5000)
        read_markings(self._ui, path, self.marks, {r.key: r for r in self.snapshot.rows}, marked)

    def mark_undo(self, steps: list[UndoStep]) -> list[UndoStep]:
        """Add the marks that undo a transaction (see plan_undo) to the current ones; the steps that could not be
        marked come back. Removals go together, so the packages that must go with them are asked about once."""
        rows = {r.key: r for r in self.snapshot.rows}
        failed, removals = [], []
        for step in steps:
            row = rows.get(step.key)
            if row is not None and step.action is Action.REMOVE and row.installed:
                removals.append(row)
            elif row is None or not self.marks.set(row, step.action, step.evr):
                failed.append(step)
        self.changed.emit(None)
        if removals:
            self.mark(removals, Action.REMOVE)
        return failed


def group_menu(group: GroupInfo, busy: bool, run: Callable[[GroupInfo, Action, bool], None]) -> list[DynamicItem]:
    """`dnf5 group install / upgrade / remove` for a comps group or environment in the sidebar; each item calls
    `run(group, action, with optional packages)`. Nothing to run while `busy`."""
    allowed = allowed_group_actions(group)
    labels = ENVIRONMENT_MENU if group.environment else GROUP_MENU
    # a hidden group ("core", "standard", under an environment) is the base of the system: no removal of its own
    removable = group.visible or group.environment
    installed = [Action.UPGRADE, Action.REMOVE] if removable else [Action.UPGRADE]
    items = []
    for action in installed if group.installed else [Action.INSTALL, None]:
        text, icon = labels[action]
        optional = action is None
        act = Action.INSTALL if optional else action
        # upgrade only once the check after loading has found something to upgrade
        known = action is not Action.UPGRADE or group.upgradable is True
        has_optional = bool(group.optional_groups or group.optional) if optional else True
        tip = ""
        if action is Action.UPGRADE and group.upgradable is not True:
            tip = (_("Checking for upgrades…") if group.upgradable is None else
                   _("Nothing to upgrade: its packages are up to date and match the group"))
        elif optional and not has_optional:
            tip = _("It has no optional packages")
        items.append(DynamicItem(_(text), lambda act=act, optional=optional: run(group, act, optional), icon,
                                 act in allowed and known and has_optional and not busy, tip))
    return items
