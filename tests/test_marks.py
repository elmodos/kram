from kram.core.marks import Action, MarkSet, allowed_actions, dnf5_command
from kram.core.model import Origin, PkgRow, Status


def row(name, status, inst="", cand="1-1", user=False):
    return PkgRow(name, "x86_64", "", inst, cand, "fedora", 1, Origin.FEDORA, status, user)


NEW = row("fish", Status.NOT_INSTALLED)
OLD = row("firefox", Status.UPGRADABLE, inst="1-1", cand="2-1", user=True)
CUR = row("bash", Status.INSTALLED, inst="5-3", cand="5-3")
ORPHAN = row("veyon", Status.ORPHAN, inst="4-1", cand="")
ROWS = {r.key: r for r in (NEW, OLD, CUR, ORPHAN)}


def test_allowed_actions():
    assert allowed_actions(NEW) == [Action.INSTALL]
    assert allowed_actions(OLD) == [Action.UPGRADE, Action.REMOVE, Action.MARK_DEP]
    assert allowed_actions(CUR) == [Action.REINSTALL, Action.REMOVE, Action.MARK_USER]
    assert allowed_actions(ORPHAN) == [Action.REMOVE, Action.MARK_USER]  # no repo copy to reinstall from


def test_invalid_marks_are_rejected():
    m = MarkSet()
    assert not m.set(NEW, Action.REMOVE)
    assert not m.set(CUR, Action.UPGRADE)
    assert not m.set(NEW, Action.DOWNGRADE, "0.9-1")
    assert len(m) == 0


def test_request_and_command():
    m = MarkSet()
    assert m.set(NEW, Action.INSTALL)
    assert m.set(OLD, Action.UPGRADE)
    assert m.set(CUR, Action.DOWNGRADE, "5-1")
    assert m.set(ORPHAN, Action.REMOVE)
    assert m.counts() == (3, 1)
    req = m.request(ROWS)
    assert req == {"install": ["fish.x86_64"], "upgrade": ["firefox.x86_64"],
                   "downgrade": ["bash-5-1.x86_64"], "remove": ["veyon.x86_64"]}
    assert dnf5_command(req).splitlines() == [
        "sudo dnf5 install fish.x86_64", "sudo dnf5 upgrade firefox.x86_64",
        "sudo dnf5 downgrade bash-5-1.x86_64", "sudo dnf5 remove veyon.x86_64"]


def test_remark_replaces_and_unmark():
    m = MarkSet()
    m.set(CUR, Action.REINSTALL)
    m.set(CUR, Action.REMOVE)
    assert m.get(CUR.key).action is Action.REMOVE
    m.unmark(CUR.key)
    assert CUR.key not in m
