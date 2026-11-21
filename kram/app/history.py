"""File → Transaction History: dnf's transactions (`dnf5 history`), their packages, the filter by package name and
whether the shown transaction can be undone. The front end draws what `History` tells its `HistoryView`.

The transactions load first, their packages after, in chunks on the dnf thread, so a long history shows at once and
other jobs get their turn in between; the current transaction's packages are asked for on their own when it is
chosen before its chunk came."""
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from ..core.catalog import Catalog
from ..core.history import (
    Change,
    HistoryRow,
    HistoryTransaction,
    change_counts,
    changes_comps,
    command_label,
    history_rows,
    user_name,
)
from ..core.marks import Action
from ..core.model import ENVIRONMENT_PREFIX, Reason
from ..core.worker import DnfWorker
from ..i18n import _, ngettext, pgettext
from .columns import REASON_LABEL
from .icons import IconRef
from .ports import view_ref
from .scheduler import Scheduler

CHUNK = 25  # transactions whose packages one worker job reads (~5 ms each): other jobs get their turn in between


def undo_tip() -> str:
    return _("Mark the changes that take the packages of this transaction back to where they were. Review them in "
             "the Marked list, then apply them.")


CHANGE_LABEL = {
    Change.INSTALL: pgettext("history", "Install"),
    Change.UPGRADE: pgettext("history", "Upgrade"),
    Change.DOWNGRADE: pgettext("history", "Downgrade"),
    Change.REINSTALL: pgettext("history", "Reinstall"),
    Change.REMOVE: pgettext("history", "Remove"),
    Change.OBSOLETED: pgettext("history", "Obsoleted"),
    Change.REASON: pgettext("history", "Reason change"),
}
# "3 installed, 12 upgraded": the counts of the Changes column. Each is a function of the count, so that its plural
# form is the language's (ngettext), which is not the same as the English one in every language
CHANGE_COUNT = {
    Change.INSTALL: lambda n: ngettext("{n} installed", "{n} installed", n),
    Change.UPGRADE: lambda n: ngettext("{n} upgraded", "{n} upgraded", n),
    Change.DOWNGRADE: lambda n: ngettext("{n} downgraded", "{n} downgraded", n),
    Change.REINSTALL: lambda n: ngettext("{n} reinstalled", "{n} reinstalled", n),
    Change.REMOVE: lambda n: ngettext("{n} removed", "{n} removed", n),
    Change.OBSOLETED: lambda n: ngettext("{n} obsoleted", "{n} obsoleted", n),
    Change.REASON: lambda n: ngettext("{n} reason changed", "{n} reasons changed", n),
}
CHANGE_ICON_ACTION = {
    Change.INSTALL: Action.INSTALL, Change.UPGRADE: Action.UPGRADE, Change.DOWNGRADE: Action.DOWNGRADE,
    Change.REINSTALL: Action.REINSTALL, Change.REMOVE: Action.REMOVE, Change.OBSOLETED: Action.REMOVE,
}


def counts_text(rows: list[HistoryRow]) -> str:
    """"1 environment, 16 groups; 1042 installed, 5 upgraded"."""
    counts = change_counts(rows)
    envs = sum(1 for r in rows if r.comps == "environment")
    groups = sum(1 for r in rows if r.comps == "group")
    comps = ", ".join(filter(None, (
        ngettext("{n} environment", "{n} environments", envs).format(n=envs) if envs else "",
        ngettext("{n} group", "{n} groups", groups).format(n=groups) if groups else "")))
    packages = ", ".join(CHANGE_COUNT[c](counts[c]).format(n=counts[c]) for c in Change if c in counts)
    if not packages:
        return comps or _("no package changes")
    return f"{comps}; {packages}" if comps else packages


def comps_key(row: HistoryRow) -> str:
    """The GroupInfo.key of a comps row, for its icon."""
    return ENVIRONMENT_PREFIX + row.arch if row.comps == "environment" else row.arch


def change_icon(row: HistoryRow) -> IconRef:
    if row.change is Change.REASON:
        return ("mark", Action.MARK_USER if row.reason is Reason.USER else Action.MARK_DEP)
    return ("mark", CHANGE_ICON_ACTION[row.change])


@dataclass(frozen=True)
class TransactionLine:
    id: int
    date: str
    changes: str
    user: str
    command: str
    tooltip: str        # the whole command line, and the comment
    failed: bool        # with an error icon and FAILED_TIP


def failed_tip() -> str:
    return _("The transaction failed or did not finish")


@dataclass(frozen=True)
class PackageLine:
    action: str
    package: str
    version: str = ""
    repo: str = ""
    reason: str = ""
    icon: IconRef | None = None     # on the action, or on the package for a group
    key: tuple[str, str] | None = None  # name, arch: a package the main window can show
    tooltip: str = ""               # on the package (a group's id)
    bold: bool = False              # its name matches the filter


@dataclass(frozen=True)
class UndoButton:
    enabled: bool
    text: str
    tooltip: str


class HistoryView(Protocol):
    def show_transactions(self, lines: list[TransactionLine]) -> None: ...

    def set_changes(self, tid: int, text: str) -> None: ...

    def set_current(self, tid: int | None) -> None:
        """Make it the current transaction; the view then calls `History.current_changed`."""
        ...

    def show_packages(self, lines: list[PackageLine]) -> None: ...

    def set_hidden(self, hidden: set[int]) -> None:
        """The transactions the filter hides; the others are shown."""
        ...

    def show_state(self, text: str) -> None: ...

    def show_undo(self, button: UndoButton) -> None: ...


class History:
    def __init__(self, dnf: DnfWorker, catalog: Catalog, scheduler: Scheduler, view: HistoryView,
                 user_name: Callable[[int], str] = user_name):
        self._dnf, self._catalog, self._scheduler, self._view = dnf, catalog, scheduler, view_ref(view)
        self._user_name = user_name
        self.transactions: list[HistoryTransaction] = []
        self._rows: dict[int, list[HistoryRow]] = {}   # transaction id -> its packages, as they load
        self._pending: list[int] = []                  # ids whose packages are still to load
        self._generation = 0                           # drops what a load started before a reload delivers
        self._busy = False                             # Kram is applying changes: no undo meanwhile
        self._can_mark = False                         # the main window has a catalog to mark in
        self.current: int | None = None
        self.filter = ""
        self._hidden: set[int] = set()

    # ---------------------------------------------------------------- loading

    def reload(self) -> None:
        """Read the transactions again (after a change was applied, or the first time)."""
        self._generation += 1
        gen = self._generation
        self._view.show_state(_("Loading…"))
        self._dnf.submit(self._catalog.history, lambda found: self._on_transactions(gen, found), self._on_error)

    def _on_error(self, error: BaseException) -> None:
        self._view.show_state(_("Could not read the history: {error}").format(error=error))

    def _on_transactions(self, gen: int, found: list[HistoryTransaction]) -> None:
        if gen != self._generation:
            return
        current = self.current
        self.transactions = found
        self._rows = {}
        self._hidden = set()
        users: dict[int, str] = {}
        lines = []
        for t in found:
            if t.user_id not in users:
                users[t.user_id] = self._user_name(t.user_id)
            lines.append(TransactionLine(t.id, datetime.fromtimestamp(t.start).strftime("%Y-%m-%d %H:%M"), "…",
                                         users[t.user_id], command_label(t.command),
                                         "\n\n".join(filter(None, (t.command, t.comment))), not t.ok))
        self.current = None
        self._view.show_transactions(lines)
        self._pending = [t.id for t in found]
        ids = [t.id for t in found]
        target = current if current in ids else (ids[0] if ids else None)
        if target is not None:
            self._view.set_current(target)
        self._load_next(gen)

    def _load_next(self, gen: int) -> None:
        """Read the packages of the next chunk of transactions, the newest first."""
        if gen != self._generation:
            return
        self._pending = [i for i in self._pending if i not in self._rows]
        if not self._pending:
            self._update_state()
            return
        chunk = self._pending[:CHUNK]
        self._update_state()
        self._dnf.submit(lambda: self._catalog.history_items(chunk), lambda items: self._on_items(gen, items, True),
                         self._on_error)

    def _on_items(self, gen: int, items: dict, chained: bool) -> None:
        if gen != self._generation:
            return
        for tid, found in items.items():
            rows = self._rows[tid] = history_rows(found)
            self._view.set_changes(tid, counts_text(rows))
        if self.current in items:
            self._show_packages()
        self._apply_filter()
        if chained:
            self._scheduler.later(lambda: self._load_next(gen))

    def _update_state(self) -> None:
        left = len([i for i in self._pending if i not in self._rows])
        total = len(self.transactions)
        if left:
            text = ngettext("Reading packages: {done} of {total} transaction",
                            "Reading packages: {done} of {total} transactions", total).format(done=total - left,
                                                                                              total=total)
        elif not self.transactions:
            text = _("No transactions recorded")
        elif self.filter.strip():
            text = ngettext("{shown} of {n} transaction", "{shown} of {n} transactions", total).format(
                shown=total - len(self._hidden), n=total)
        else:
            text = ngettext("{n} transaction", "{n} transactions", total).format(n=total)
        self._view.show_state(text)

    # ---------------------------------------------------------------- showing

    def current_changed(self, tid: int | None) -> None:
        self.current = tid
        if tid is not None and tid not in self._rows:
            gen = self._generation
            self._dnf.submit(lambda: self._catalog.history_items([tid]),
                             lambda items: self._on_items(gen, items, False), self._on_error)
        self._show_packages()

    def _show_packages(self) -> None:
        rows = self._rows.get(self.current, [])
        needle = self.filter.strip().lower()
        lines = []
        for r in sorted(rows, key=lambda r: (not r.comps, r.comps != "environment")):  # comps first
            if r.change is Change.UNREADABLE:
                lines.append(PackageLine("", _("The groups of this transaction could not be read")))
            elif r.comps:
                kind = _("environment") if r.comps == "environment" else _("group")
                lines.append(PackageLine(CHANGE_LABEL[r.change], f"{r.name} ({kind})",
                                         reason=REASON_LABEL.get(r.reason, ""), icon=("group", comps_key(r)),
                                         tooltip=r.arch))
            else:
                version = f"{r.old_evr} → {r.evr}" if r.old_evr else r.evr
                lines.append(PackageLine(CHANGE_LABEL[r.change], f"{r.name}.{r.arch}", version, r.repo_id,
                                         REASON_LABEL.get(r.reason, ""), change_icon(r), r.key,
                                         bold=bool(needle) and needle in r.name.lower()))
        self._view.show_packages(lines)
        self._update_undo()

    def set_filter(self, text: str) -> None:
        self.filter = text
        self._apply_filter()
        self._show_packages()  # in bold, the packages that match

    def _apply_filter(self) -> None:
        """Leave the transactions that changed a package whose name contains the text; while their packages are
        still loading, the ones not read yet are hidden."""
        needle = self.filter.strip().lower()
        self._hidden = set()
        if needle:
            for t in self.transactions:
                rows = self._rows.get(t.id)
                if rows is None or not any(needle in r.name.lower() for r in rows):
                    self._hidden.add(t.id)
        self._view.set_hidden(self._hidden)
        if self.current is not None and self.current in self._hidden:
            self._view.set_current(next((t.id for t in self.transactions if t.id not in self._hidden), None))
        self._update_state()

    def rows_of(self, tid: int) -> list[HistoryRow] | None:
        """The packages of a transaction, once read."""
        return self._rows.get(tid)

    # ---------------------------------------------------------------- undo

    def set_marking(self, can_mark: bool, busy: bool) -> None:
        """`can_mark`: the main window has a catalog; `busy`: it is applying changes."""
        self._can_mark, self._busy = can_mark, busy
        self._update_undo()

    def undo_button(self) -> UndoButton:
        tid = self.current
        t = next((t for t in self.transactions if t.id == tid), None)
        rows = self._rows.get(tid)
        enabled = bool(t and t.ok and rows) and self._can_mark and not self._busy
        if rows and changes_comps(rows):
            return UndoButton(enabled, _("Undo Transaction…"),
                              _("The transaction changed groups or environments: it is undone as “dnf5 history "
                                "undo” does, packages and groups together. Kram shows what that does before it "
                                "runs."))
        return UndoButton(enabled, _("Mark Changes to Undo"), undo_tip())

    def _update_undo(self) -> None:
        self._view.show_undo(self.undo_button())
