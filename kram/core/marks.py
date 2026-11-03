"""Marked changes (Synaptic's "mark for installation/removal/..."). Pure data, no libdnf5, no Qt."""
from dataclasses import dataclass
from enum import Enum

from ..i18n import _
from .model import PkgRow, Status


class Action(Enum):
    INSTALL = "install"
    REMOVE = "remove"
    UPGRADE = "upgrade"
    REINSTALL = "reinstall"
    DOWNGRADE = "downgrade"      # to Mark.evr
    MARK_USER = "mark_user"      # change install reason only, nothing is (un)installed
    MARK_DEP = "mark_dep"


ACTION_LABELS = {
    Action.INSTALL: _("install"),
    Action.REMOVE: _("remove"),
    Action.UPGRADE: _("upgrade"),
    Action.REINSTALL: _("reinstall"),
    Action.DOWNGRADE: _("downgrade"),
    Action.MARK_USER: _("mark as installed by user"),
    Action.MARK_DEP: _("mark as dependency"),
}

INSTALL_LIKE = (Action.INSTALL, Action.UPGRADE, Action.REINSTALL, Action.DOWNGRADE)


@dataclass(frozen=True, slots=True)
class Mark:
    action: Action
    evr: str = ""   # target version for DOWNGRADE (and an explicit version for INSTALL)


def allowed_actions(row: PkgRow) -> list[Action]:
    """What can be marked for this row, in menu order."""
    if not row.installed:
        return [Action.INSTALL] if row.candidate_evr else []
    actions = []
    if row.status is Status.UPGRADABLE:
        actions.append(Action.UPGRADE)
    if row.candidate_evr == row.installed_evr:
        actions.append(Action.REINSTALL)  # needs the exact installed version in a repo
    actions.append(Action.REMOVE)
    actions.append(Action.MARK_DEP if row.user_installed else Action.MARK_USER)
    return actions


def spec(row: PkgRow, mark: Mark) -> str:
    """Package spec for libdnf5's Goal: name.arch, or a full NEVRA when a version is pinned."""
    if mark.evr:
        return f"{row.name}-{mark.evr}.{row.arch}"
    return f"{row.name}.{row.arch}"


class MarkSet:
    def __init__(self) -> None:
        self._marks: dict[tuple[str, str], Mark] = {}

    def __len__(self) -> int:
        return len(self._marks)

    def __contains__(self, key: tuple[str, str]) -> bool:
        return key in self._marks

    def get(self, key: tuple[str, str]) -> Mark | None:
        return self._marks.get(key)

    def items(self):
        return self._marks.items()

    def set(self, row: PkgRow, action: Action, evr: str = "") -> bool:
        """Mark a row; returns False (and changes nothing) if the action does not apply to it."""
        if action is Action.DOWNGRADE:
            if not (row.installed and evr):
                return False
        elif action not in allowed_actions(row):
            return False
        self._marks[row.key] = Mark(action, evr)
        return True

    def unmark(self, key: tuple[str, str]) -> None:
        self._marks.pop(key, None)

    def clear(self) -> None:
        self._marks.clear()

    def counts(self) -> tuple[int, int]:
        """(to install/upgrade/reinstall/downgrade, to remove)"""
        inst = sum(1 for m in self._marks.values() if m.action in INSTALL_LIKE)
        rm = sum(1 for m in self._marks.values() if m.action is Action.REMOVE)
        return inst, rm

    def request(self, rows_by_key: dict[tuple[str, str], PkgRow]) -> dict[str, list[str]]:
        """Group marks into the helper's transaction request fields."""
        req: dict[str, list[str]] = {a.value: [] for a in Action}
        for key, mark in sorted(self._marks.items()):
            req[mark.action.value].append(spec(rows_by_key[key], mark))
        return {k: v for k, v in req.items() if v}


def dnf5_command(request: dict[str, list[str]]) -> str:
    """The equivalent dnf5 command lines, for the preview dialog."""
    verbs = [("install", "install"), ("upgrade", "upgrade"), ("reinstall", "reinstall"),
             ("downgrade", "downgrade"), ("remove", "remove"),
             ("mark_user", "mark user"), ("mark_dep", "mark dependency")]
    return "\n".join(f"sudo dnf5 {verb} {' '.join(request[k])}" for k, verb in verbs if request.get(k))


MARKINGS_HEADER = "# Kram markings: <action> <name>.<arch> [<version>]"


def dump_marks(marks: MarkSet) -> str:
    """Plain-text markings file (File → Save Markings), one mark per line."""
    lines = [MARKINGS_HEADER]
    for (name, arch), mark in sorted(marks.items()):
        lines.append(" ".join(filter(None, (mark.action.value, f"{name}.{arch}", mark.evr))))
    return "\n".join(lines) + "\n"


def parse_marks(text: str) -> tuple[list[tuple[tuple[str, str], Mark]], list[int]]:
    """Read a markings file: ([(key, mark)], numbers of the lines that are not valid markings)."""
    marks, bad = [], []
    actions = {a.value: a for a in Action}
    for n, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        action = actions.get(fields[0])
        name, _dot, arch = fields[1].rpartition(".") if len(fields) > 1 else ("", "", "")
        evr = fields[2] if len(fields) == 3 else ""
        if action is None or not name or not arch or len(fields) > 3 or (action is Action.DOWNGRADE) != bool(evr):
            bad.append(n)
            continue
        marks.append(((name, arch), Mark(action, evr)))
    return marks, bad
