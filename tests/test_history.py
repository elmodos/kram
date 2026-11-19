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


def test_comps_rows_are_not_packages():
    """An environment install records the environment and its groups next to the packages: they show as rows of
    their own, are not counted as packages, and the marks to undo leave them out (the transaction is reverted
    instead, see changes_comps)."""
    from kram.core.history import changes_comps

    items = (item("sway", "1.10-1", "install"),
             HistoryItem("Sway Desktop", "sway-desktop-environment", "", "install", Reason.USER, "",
                         comps="environment"),
             HistoryItem("Fonts", "fonts", "", "install", Reason.DEPENDENCY, "", comps="group"))
    rows = history_rows(items)
    assert {(r.comps, r.name) for r in rows if r.comps} == {("environment", "Sway Desktop"), ("group", "Fonts")}
    assert change_counts(rows) == {Change.INSTALL: 1} and changes_comps(rows)
    assert not changes_comps(history_rows(items[:1]))
    steps, problems = plan_undo(rows, {("sway", "x86_64"): PackageState(("1.10-1",))})
    assert steps == [UndoStep(("sway", "x86_64"), Action.REMOVE)] and problems == []


def test_reading_comps_from_the_history_database(tmp_path):
    """libdnf5's Python bindings cannot list a transaction's groups: they are read from its database."""
    import sqlite3
    from types import SimpleNamespace

    from kram.core.history import read_comps

    db = sqlite3.connect(tmp_path / "transaction_history.sqlite")
    db.executescript("""
        CREATE TABLE trans_item (id INTEGER PRIMARY KEY, trans_id INTEGER, item_id INTEGER, repo_id INTEGER,
                                 action_id INTEGER, reason_id INTEGER, state_id INTEGER);
        CREATE TABLE comps_group (item_id INTEGER, groupid TEXT, name TEXT, translated_name TEXT, pkg_types INTEGER);
        CREATE TABLE comps_environment (item_id INTEGER, environmentid TEXT, name TEXT, translated_name TEXT,
                                        pkg_types INTEGER);
        INSERT INTO trans_item VALUES (1, 7, 10, 0, 1, 2, 1), (2, 7, 11, 0, 1, 1, 1), (3, 9, 10, 0, 5, 2, 1);
        INSERT INTO comps_environment VALUES (10, 'sway-desktop-environment', 'Sway Desktop', 'Sway', 0);
        INSERT INTO comps_group VALUES (11, 'fonts', 'Fonts', 'Шрифти', 0);
    """)
    db.commit()
    db.close()
    base = SimpleNamespace(get_config=lambda: SimpleNamespace(transaction_history_dir=str(tmp_path)))
    found = read_comps(base, [7, 9])
    assert sorted((i.comps, i.arch, i.name, i.action) for i in found[7]) == [
        ("environment", "sway-desktop-environment", "Sway", "install"), ("group", "fonts", "Шрифти", "install")]
    assert [(i.arch, i.action) for i in found[9]] == [("sway-desktop-environment", "remove")]
    missing = SimpleNamespace(get_config=lambda: SimpleNamespace(transaction_history_dir=str(tmp_path / "none")))
    assert read_comps(missing, [7]) == {}
