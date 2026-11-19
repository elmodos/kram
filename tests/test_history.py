from kram.core.history import (
    Change,
    HistoryItem,
    HistoryRow,
    PackageState,
    UndoStep,
    change_counts,
    command_label,
    history_rows,
    plan_undo,
)
from kram.core.marks import Action
from kram.core.model import Reason


def item(name, evr, action, arch="x86_64", reason=Reason.USER, repo="fedora"):
    return HistoryItem(name, arch, evr, action, reason, repo)


def hrow(change, name, evr, old="", reason=Reason.USER):
    return HistoryRow(change, name, "x86_64", evr, old, "fedora", reason)


def test_upgrade_and_replaced_make_one_row():
    rows = history_rows((item("vim", "9.1-2", "upgrade"), item("vim", "9.1-1", "replaced", repo="@System"),
                         item("bash", "5.3-1", "install")))
    assert [(r.change, r.name, r.evr, r.old_evr) for r in rows] == [
        (Change.INSTALL, "bash", "5.3-1", ""), (Change.UPGRADE, "vim", "9.1-2", "9.1-1")]


def test_arch_change_and_obsoleted():
    rows = history_rows((item("foo", "2-1", "upgrade"), item("foo", "1-1", "replaced", arch="noarch"),
                         item("new", "1-1", "install"), item("old", "3-1", "replaced")))
    assert [(r.change, r.name, r.arch, r.old_evr) for r in rows] == [
        (Change.UPGRADE, "foo", "x86_64", "1-1"), (Change.INSTALL, "new", "x86_64", ""),
        (Change.OBSOLETED, "old", "x86_64", "")]


def test_reinstall_has_no_old_version():
    rows = history_rows((item("vim", "9.1-1", "reinstall"), item("vim", "9.1-1", "replaced")))
    assert [(r.change, r.old_evr) for r in rows] == [(Change.REINSTALL, "")]


def test_counts_and_labels():
    rows = [hrow(Change.INSTALL, "a", "1"), hrow(Change.INSTALL, "b", "1"), hrow(Change.REMOVE, "c", "1")]
    assert change_counts(rows) == {Change.INSTALL: 2, Change.REMOVE: 1}
    assert command_label("kram") == "Kram"
    assert command_label("dnf5 upgrade") == "dnf5 upgrade"


def undo(rows, **state):
    steps, problems = plan_undo(rows, {(name, "x86_64"): s for name, s in state.items()})
    return steps, [(p.package, p.why) for p in problems]


def test_undo_install_removes():
    steps, problems = undo([hrow(Change.INSTALL, "fish", "4-1")], fish=PackageState(("4-1",)))
    assert steps == [UndoStep(("fish", "x86_64"), Action.REMOVE)] and not problems


def test_undo_install_changed_or_removed_since():
    rows = [hrow(Change.INSTALL, "fish", "4-1"), hrow(Change.INSTALL, "zsh", "5-1")]
    steps, problems = undo(rows, fish=PackageState(("4-2",)))
    assert not steps
    assert problems == [("fish.x86_64", "changed since: 4-2 is installed now"), ("zsh.x86_64", "removed since")]


def test_undo_install_of_an_installonly_package():
    steps, problems = undo([hrow(Change.INSTALL, "kernel", "6.2-1")], kernel=PackageState(("6.1-1", "6.2-1")))
    assert not steps and problems[0][0] == "kernel.x86_64"


def test_undo_upgrade_downgrades_when_the_old_version_is_there():
    rows = [hrow(Change.UPGRADE, "vim", "9.1-2", old="9.1-1"), hrow(Change.UPGRADE, "git", "3-1", old="2-1")]
    steps, problems = undo(rows, vim=PackageState(("9.1-2",), frozenset({"9.1-1", "9.1-2"}), "9.1-2"),
                           git=PackageState(("3-1",), frozenset({"3-1"}), ""))
    assert steps == [UndoStep(("vim", "x86_64"), Action.DOWNGRADE, "9.1-1")]
    assert problems == [("git.x86_64", "version 2-1 is no longer in the repositories")]


def test_undo_downgrade_upgrades_to_the_newest_only():
    rows = [hrow(Change.DOWNGRADE, "vim", "1-1", old="3-1"), hrow(Change.DOWNGRADE, "git", "1-1", old="2-1")]
    steps, problems = undo(rows, vim=PackageState(("1-1",), frozenset({"1-1", "3-1"}), "3-1"),
                           git=PackageState(("1-1",), frozenset({"2-1", "3-1"}), "3-1"))
    assert steps == [UndoStep(("vim", "x86_64"), Action.UPGRADE)]
    assert problems == [("git.x86_64", "version 2-1 is not the newest one in the repositories")]


def test_undo_remove_installs_that_version_or_the_newest():
    rows = [hrow(Change.REMOVE, "a", "1-1"), hrow(Change.REMOVE, "b", "1-1"), hrow(Change.REMOVE, "c", "1-1"),
            hrow(Change.REMOVE, "d", "1-1")]
    steps, problems = undo(rows, a=PackageState((), frozenset({"1-1", "2-1"}), "2-1"),
                           b=PackageState((), frozenset({"2-1"}), "2-1"), d=PackageState(("1-1",)))
    assert steps == [UndoStep(("a", "x86_64"), Action.INSTALL, "1-1"),
                     UndoStep(("b", "x86_64"), Action.INSTALL, "2-1", instead_of="1-1")]
    assert problems == [("c.x86_64", "no longer in the repositories"), ("d.x86_64", "installed again since")]


def test_undo_reason_change():
    rows = [hrow(Change.REASON, "a", "1", reason=Reason.USER), hrow(Change.REASON, "b", "1", reason=Reason.DEPENDENCY),
            hrow(Change.REASON, "c", "1", reason=Reason.USER)]
    steps, problems = undo(rows, a=PackageState(("1",), reason=Reason.USER),
                           b=PackageState(("1",), reason=Reason.DEPENDENCY),
                           c=PackageState(("1",), reason=Reason.DEPENDENCY))  # changed back since: nothing to do
    assert steps == [UndoStep(("a", "x86_64"), Action.MARK_DEP), UndoStep(("b", "x86_64"), Action.MARK_USER)]
    assert not problems


def test_undo_skips_reinstall_and_reports_obsoleted():
    steps, problems = undo([hrow(Change.REINSTALL, "a", "1"), hrow(Change.OBSOLETED, "b", "1")])
    assert not steps and problems == [("b.x86_64", "replaced by another package that obsoletes it")]
