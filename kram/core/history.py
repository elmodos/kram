"""dnf's transaction history (`dnf5 history`), read through libdnf5, and the marks that would undo a transaction.
No Qt.

The history lives in /usr/lib/sysimage/libdnf5/transaction_history.sqlite, readable without root. Reading the
transactions alone takes milliseconds; their packages take ~5 ms per transaction (a thousand transactions: seconds),
so they are read in chunks, see `read_items`.

Undoing is not `dnf5 history undo`: it turns the transaction into ordinary marks, which the user sees in the list,
can change, and applies like any other (see `plan_undo`)."""
import pwd
from dataclasses import dataclass
from enum import Enum

from ..i18n import _
from .marks import Action
from .model import Reason


class Change(Enum):
    """What a transaction did to a package: one of the rows `history_rows` makes of its items."""
    INSTALL = "install"
    UPGRADE = "upgrade"
    DOWNGRADE = "downgrade"
    REINSTALL = "reinstall"
    REMOVE = "remove"
    OBSOLETED = "obsoleted"   # replaced by another package that obsoletes it
    REASON = "reason"         # only its install reason changed


@dataclass(frozen=True, slots=True)
class HistoryTransaction:
    id: int
    start: int            # seconds since the epoch
    user_id: int
    command: str          # dnf5's command line, "kram" for Kram's transactions, "" when not recorded
    comment: str
    ok: bool              # False: the transaction failed or never finished


@dataclass(frozen=True, slots=True)
class HistoryItem:
    """A package of a transaction, as dnf records it: an upgrade is two items, the new package (UPGRADE) and the
    one it replaced (REPLACED)."""
    name: str
    arch: str
    evr: str              # "1:2.3-4.fc44", the epoch only when not 0 (as libdnf5's Package.get_evr)
    action: str           # see ITEM_ACTIONS
    reason: Reason | None
    repo_id: str

    @property
    def key(self) -> tuple[str, str]:
        return self.name, self.arch


# libdnf5.transaction.TransactionItemAction_* -> HistoryItem.action
ITEM_ACTIONS = {1: "install", 2: "upgrade", 3: "downgrade", 4: "reinstall", 5: "remove", 6: "replaced", 7: "reason"}
# libdnf5.transaction.TransactionItemReason_* -> Reason (0 none, 3 clean: no reason to show)
ITEM_REASONS = {1: Reason.DEPENDENCY, 2: Reason.USER, 4: Reason.WEAK, 5: Reason.GROUP, 6: Reason.EXTERNAL}
STATE_OK = 2  # libdnf5.transaction.TransactionState_OK


@dataclass(frozen=True, slots=True)
class HistoryRow:
    """A line of a transaction as Kram shows it: an upgrade or downgrade in one line, from the old version to the
    new one."""
    change: Change
    name: str
    arch: str
    evr: str              # the version after the transaction; for a removal, the version removed
    old_evr: str          # upgrades and downgrades: the version before, else ""
    repo_id: str
    reason: Reason | None

    @property
    def key(self) -> tuple[str, str]:
        return self.name, self.arch


def _evr(p) -> str:
    epoch = p.get_epoch()
    return f"{epoch + ':' if epoch and epoch != '0' else ''}{p.get_version()}-{p.get_release()}"


def _history(base):
    import libdnf5
    return libdnf5.transaction.TransactionHistory(base)


def read_transactions(base) -> list[HistoryTransaction]:
    """Every transaction, the newest first, without their packages."""
    return sorted((HistoryTransaction(t.get_id(), t.get_dt_start(), t.get_user_id(), t.get_description() or "",
                                      t.get_comment() or "", t.get_state() == STATE_OK)
                   for t in _history(base).list_all_transactions()), key=lambda t: t.id, reverse=True)


def read_items(base, ids: list[int]) -> dict[int, tuple[HistoryItem, ...]]:
    """The packages of the transactions with these ids."""
    if not ids:
        return {}
    wanted = set(ids)
    found = {}
    # list_transactions(first, last) takes a range; the ids of a chunk are close together
    for t in _history(base).list_transactions(min(ids), max(ids)):
        if t.get_id() in wanted:
            found[t.get_id()] = tuple(
                HistoryItem(p.get_name(), p.get_arch(), _evr(p), ITEM_ACTIONS.get(p.get_action(), "other"),
                            ITEM_REASONS.get(p.get_reason()), p.get_repoid())
                for p in t.get_packages())
    return found


def user_name(uid: int) -> str:
    try:
        return pwd.getpwuid(uid).pw_name
    except (KeyError, OverflowError):
        return str(uid)


def command_label(command: str) -> str:
    return "Kram" if command == "kram" else command


def history_rows(items: tuple[HistoryItem, ...]) -> list[HistoryRow]:
    """The items of a transaction as Kram shows them: an upgrade or downgrade with the package it replaced in one
    row, a replaced package nothing of its name took the place of as obsoleted. Sorted by name."""
    replaced: dict[str, list[HistoryItem]] = {}
    for i in items:
        if i.action == "replaced":
            replaced.setdefault(i.name, []).append(i)
    rows = []
    for i in items:
        if i.action in ("upgrade", "downgrade", "reinstall"):
            olds = replaced.get(i.name, [])
            # the same arch first; an upgrade that changes the arch (noarch -> x86_64) replaced the other one
            old = next((o for o in olds if o.arch == i.arch), olds[0] if olds else None)
            if old is not None:
                olds.remove(old)
            change = {"upgrade": Change.UPGRADE, "downgrade": Change.DOWNGRADE, "reinstall": Change.REINSTALL}[i.action]
            rows.append(HistoryRow(change, i.name, i.arch, i.evr, old.evr if old and i.action != "reinstall" else "",
                                   i.repo_id, i.reason))
        elif i.action in ("install", "remove", "reason"):
            change = {"install": Change.INSTALL, "remove": Change.REMOVE, "reason": Change.REASON}[i.action]
            rows.append(HistoryRow(change, i.name, i.arch, i.evr, "", i.repo_id, i.reason))
    rows += [HistoryRow(Change.OBSOLETED, o.name, o.arch, o.evr, "", o.repo_id, o.reason)
             for olds in replaced.values() for o in olds]
    rows.sort(key=lambda r: (r.name, r.arch))
    return rows


def change_counts(rows: list[HistoryRow]) -> dict[Change, int]:
    counts: dict[Change, int] = {}
    for r in rows:
        counts[r.change] = counts.get(r.change, 0) + 1
    return counts


# ---------------------------------------------------------------- undo


@dataclass(frozen=True, slots=True)
class UndoStep:
    """A mark that undoes a row of the transaction. `instead_of`: the version the transaction removed, when another
    one is installed back because that one is no longer in the repositories."""
    key: tuple[str, str]
    action: Action
    evr: str = ""
    instead_of: str = ""


@dataclass(frozen=True, slots=True)
class UndoProblem:
    """A row of the transaction that cannot be undone, and why."""
    package: str          # name.arch
    why: str


@dataclass(frozen=True, slots=True)
class PackageState:
    """What the system has of a name.arch now: its installed versions (several for installonly packages such as the
    kernel), the versions in the enabled repositories, the newest of them, and the install reason."""
    installed: tuple[str, ...] = ()
    available: frozenset[str] = frozenset()
    candidate: str = ""
    reason: Reason | None = None


def plan_undo(rows: list[HistoryRow], state: dict[tuple[str, str], PackageState]) -> tuple[list[UndoStep],
                                                                                          list[UndoProblem]]:
    """The marks that take the system back to where it was before the transaction, as far as the repositories
    still allow, and the rows that cannot be undone. A package the transaction touched and something changed since
    is left alone: undoing it would undo the later change too."""
    steps: list[UndoStep] = []
    problems: list[UndoProblem] = []

    def problem(row: HistoryRow, why: str) -> None:
        problems.append(UndoProblem(f"{row.name}.{row.arch}", why))

    def changed_since(row: HistoryRow, now: PackageState) -> bool:
        if row.evr in now.installed:
            return False
        if now.installed:
            problem(row, _("changed since: {version} is installed now").format(version=", ".join(now.installed)))
        else:
            problem(row, _("removed since"))
        return True

    for row in rows:
        now = state.get(row.key, PackageState())
        if row.change is Change.REINSTALL:
            continue  # the same version before and after: nothing to undo
        if row.change is Change.INSTALL:
            if changed_since(row, now):
                continue
            if len(now.installed) > 1:
                # installonly (kernel): a removal mark takes name.arch, which would remove every version
                problem(row, _("several versions are installed; remove this one with dnf5 remove"))
            else:
                steps.append(UndoStep(row.key, Action.REMOVE))
        elif row.change in (Change.UPGRADE, Change.DOWNGRADE):
            if changed_since(row, now):
                continue
            if not row.old_evr:
                problem(row, _("the version it replaced is not recorded"))
            elif row.old_evr not in now.available:
                problem(row, _("version {version} is no longer in the repositories").format(version=row.old_evr))
            elif row.change is Change.UPGRADE:
                steps.append(UndoStep(row.key, Action.DOWNGRADE, row.old_evr))
            elif row.old_evr == now.candidate:
                steps.append(UndoStep(row.key, Action.UPGRADE))
            else:
                # Kram upgrades to the newest version only
                problem(row, _("version {version} is not the newest one in the repositories").format(
                    version=row.old_evr))
        elif row.change is Change.REMOVE:
            if now.installed:
                problem(row, _("installed again since"))
            elif row.evr in now.available:
                steps.append(UndoStep(row.key, Action.INSTALL, row.evr))
            elif now.candidate:
                steps.append(UndoStep(row.key, Action.INSTALL, now.candidate, instead_of=row.evr))
            else:
                problem(row, _("no longer in the repositories"))
        elif row.change is Change.OBSOLETED:
            problem(row, _("replaced by another package that obsoletes it"))
        elif row.change is Change.REASON:
            if not now.installed:
                problem(row, _("removed since"))
            elif now.reason is not row.reason:
                continue  # changed again since, or already back
            elif row.reason is Reason.USER:
                steps.append(UndoStep(row.key, Action.MARK_DEP))
            elif row.reason in (Reason.DEPENDENCY, Reason.WEAK):
                steps.append(UndoStep(row.key, Action.MARK_USER))
    return steps, problems
