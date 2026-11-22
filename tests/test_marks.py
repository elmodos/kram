from dataclasses import replace

import pytest

from kram.app.parity import Feature  # noqa: E402  (the feature marks of the parity tests)
from kram.core.marks import (
    Action,
    MarkSet,
    allowed_actions,
    allowed_group_actions,
    dnf5_command,
    dump_marks,
    group_request,
    parse_marks,
)
from kram.core.model import GroupInfo, Origin, PkgRow, Status


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
    # one transaction: one `dnf5 do`, as separate commands could fail where the whole does not
    assert dnf5_command(req) == ("sudo dnf5 do --action=install fish.x86_64 --action=upgrade firefox.x86_64 "
                                 "--action=downgrade bash-5-1.x86_64 --action=remove veyon.x86_64")


def test_remark_replaces_and_unmark():
    m = MarkSet()
    m.set(CUR, Action.REINSTALL)
    m.set(CUR, Action.REMOVE)
    assert m.get(CUR.key).action is Action.REMOVE
    m.unmark(CUR.key)
    assert CUR.key not in m


@pytest.mark.feature(Feature.MARKINGS_FILE, front="qt")
def test_markings_file_roundtrip():
    m = MarkSet()
    m.set(NEW, Action.INSTALL)
    m.set(OLD, Action.DOWNGRADE, "1:0.9-1.fc44")
    m.set(CUR, Action.REMOVE)
    text = dump_marks(m)
    assert text.splitlines()[1:] == ["remove bash.x86_64", "downgrade firefox.x86_64 1:0.9-1.fc44",
                                     "install fish.x86_64"]
    marks, bad = parse_marks(text)
    assert bad == []
    assert dict(marks) == dict(m.items())


def test_markings_file_bad_lines():
    lines = [
        "# comment", "", "install fish.x86_64",
        "frobnicate fish.x86_64",       # 4: unknown action
        "install fish",                 # 5: no arch
        "downgrade fish.x86_64",        # 6: downgrade without a version
        "remove fish.x86_64 1-1 extra",  # 7: too many fields
        "install",                      # 8: no package
        "  mark_dep  python3-foo.noarch  ",
    ]
    marks, bad = parse_marks("\n".join(lines))
    assert bad == [4, 5, 6, 7, 8]
    assert [k for k, _m in marks] == [("fish", "x86_64"), ("python3-foo", "noarch")]


def test_restore_takes_back_a_mark():
    """Cancelling the dependents dialog restores what each package was marked with before."""
    m = MarkSet()
    m.set(OLD, Action.UPGRADE)
    before = {OLD.key: m.get(OLD.key), CUR.key: m.get(CUR.key)}
    m.set(OLD, Action.REMOVE)
    m.set(CUR, Action.REMOVE)
    for key, mark in before.items():
        m.restore(key, mark)
    assert m.get(OLD.key).action is Action.UPGRADE
    assert CUR.key not in m


def test_command_shows_unchecked_recommendations():
    req = {"install": ["virt-manager.noarch"], "remove": ["fish.x86_64"],
           "exclude_weak": ["libvirt-daemon-kvm", "libvirt-daemon-qemu"]}
    assert dnf5_command(req) == ("sudo dnf5 do --setopt=exclude_from_weak=libvirt-daemon-kvm,libvirt-daemon-qemu "
                                 "--action=install virt-manager.noarch --action=remove fish.x86_64")


def test_command_for_download_only():
    req = {"install": ["fish.x86_64"], "remove": ["veyon.x86_64"], "mark_dep": ["bash.x86_64"],
           "exclude_weak": ["kvm"], "download_only": True}
    assert dnf5_command(req) == "sudo dnf5 install --downloadonly --setopt=exclude_from_weak=kvm fish.x86_64"
    assert dnf5_command({"remove": ["veyon.x86_64"], "download_only": True}) == ""
    assert dnf5_command({"upgrade": ["a.x86_64"], "download_only": False}) == "sudo dnf5 upgrade a.x86_64"


def test_command_for_a_package_file():
    req = {"op": "local_install", "path": "/home/me/My Downloads/tool.rpm", "sha256": "0" * 64, "action": "reinstall"}
    assert dnf5_command(req) == "sudo dnf5 reinstall '/home/me/My Downloads/tool.rpm'"


def test_upgrade_that_changes_the_arch_names_the_new_package():
    # python3-wcwidth 0.7.0 was noarch, 0.9.2 is x86_64: name.arch would only find the old noarch build, and
    # libdnf5 refuses name-evr.x86_64 for it
    wcwidth = PkgRow("python3-wcwidth", "noarch", "", "0.7.0-6.fc45", "0.9.2-1.fc45", "updates", 1, Origin.FEDORA,
                     Status.UPGRADABLE, candidate_arch="x86_64")
    assert allowed_actions(wcwidth) == [Action.UPGRADE, Action.REMOVE, Action.MARK_USER]
    m = MarkSet()
    assert m.set(wcwidth, Action.UPGRADE)
    assert m.request({wcwidth.key: wcwidth}) == {"upgrade": ["python3-wcwidth"]}
    same = PkgRow("python3-wcwidth", "noarch", "", "0.7.0-6.fc45", "0.7.0-6.fc45", "fedora", 1, Origin.FEDORA,
                  Status.INSTALLED, candidate_arch="x86_64")
    assert Action.REINSTALL not in allowed_actions(same)  # the same version of another arch is no reinstall


KDE_APPS = GroupInfo("kde-apps", "KDE Applications", "", False, frozenset({"dolphin"}))
KDE_ENV = GroupInfo("kde-desktop-environment", "KDE Plasma Workspaces", "", False, frozenset({"plasma-desktop"}),
                    environment=True, groups=("kde-desktop",), optional_groups=("kde-education",))
DEV_TOOLS = GroupInfo("development-tools", "Development Tools", "", True, frozenset({"gcc", "make"}))


def test_command_for_one_transaction():
    """A swap (kram-qt for kram-gtk, as the conflict offer marks it) runs as one transaction: `dnf5 do`."""
    swap = {"install": ["kram-gtk.noarch"], "remove": ["kram-qt.noarch"]}
    assert dnf5_command(swap) == "sudo dnf5 do --action=install kram-gtk.noarch --action=remove kram-qt.noarch"
    # one action stays the plain command; reason changes stay apart, they do not change what resolves
    assert dnf5_command({"install": ["a.x86_64", "b.x86_64"], "mark_user": ["c.x86_64"]}).splitlines() == [
        "sudo dnf5 install a.x86_64 b.x86_64", "sudo dnf5 mark user c.x86_64"]
    assert dnf5_command({**swap, "mark_dep": ["c.x86_64"]}).splitlines() == [
        "sudo dnf5 do --action=install kram-gtk.noarch --action=remove kram-qt.noarch",
        "sudo dnf5 mark dependency c.x86_64"]
    # groups and environments are @ids, with the packages of the same action
    req = {"install": ["fish.x86_64"], "group_install": ["kde-apps"], "environment_remove": ["xfce-desktop"]}
    assert dnf5_command(req) == "sudo dnf5 do --action=install fish.x86_64 @kde-apps --action=remove @xfce-desktop"
    # a download-only run removes nothing: what is left may be one action again
    assert dnf5_command({**swap, "download_only": True}) == "sudo dnf5 install --downloadonly kram-gtk.noarch"
    # `dnf5 do` has no --with-optional: such an install keeps its own command
    req = {"remove": ["fish.x86_64"], "group_install_optional": ["kde-apps"]}
    assert dnf5_command(req).splitlines() == ["sudo dnf5 remove fish.x86_64",
                                              "sudo dnf5 group install --with-optional kde-apps"]


def test_group_actions():
    """Groups are not marked: their menu runs one change at once. What it may run, and the request it sends."""
    assert allowed_group_actions(KDE_APPS) == [Action.INSTALL]
    assert allowed_group_actions(DEV_TOOLS) == [Action.UPGRADE, Action.REMOVE]  # not checked yet
    assert allowed_group_actions(replace(DEV_TOOLS, upgradable=False)) == [Action.REMOVE]
    assert group_request(KDE_APPS, Action.INSTALL) == {"group_install": ["kde-apps"]}
    assert group_request(DEV_TOOLS, Action.REMOVE) == {"group_remove": ["development-tools"]}
    req = group_request(KDE_ENV, Action.INSTALL, optional=True)
    assert req == {"environment_install_optional": ["kde-desktop-environment"]}
    assert dnf5_command(req) == "sudo dnf5 group install --with-optional kde-desktop-environment"
    # a download-only run fetches the packages of a group being installed or upgraded, removes nothing
    assert dnf5_command({"group_install": ["kde-apps"], "download_only": True}) == (
        "sudo dnf5 group install --downloadonly kde-apps")
    assert dnf5_command({"group_remove": ["kde-apps"], "download_only": True}) == ""


def test_markings_files_no_longer_take_groups():
    """Kram 0.9 and 0.10 wrote group marks ("install @kde-apps"); reading such a file says those lines are not
    valid markings."""
    m = MarkSet()
    m.set(NEW, Action.INSTALL)
    text = dump_marks(m)
    assert text.splitlines()[1:] == ["install fish.x86_64"]
    marks, bad = parse_marks(text + "install @kde-apps\nupgrade @kde.apps\n")
    assert [k for k, _m in marks] == [("fish", "x86_64")] and bad == [3, 4]


def test_revert_command():
    assert dnf5_command({"op": "transaction", "revert": [7]}) == "sudo dnf5 history undo 7"
    assert dnf5_command({"revert": [7], "skip_unavailable": True}) == "sudo dnf5 history undo --skip-unavailable 7"
