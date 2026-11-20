from kram.core.filters import (
    environment_filters,
    environment_id,
    group_filters,
    origin_filters,
    status_filters,
    visible_entries,
)
from kram.core.model import CatalogSnapshot, GroupInfo, Origin, PkgRow, Status


def row(name, status=Status.NOT_INSTALLED, repo="fedora", from_repo="", origin=Origin.FEDORA, user=False):
    inst = "" if status is Status.NOT_INSTALLED else "1-1"
    return PkgRow(name, "x86_64", "", inst, "1-1", repo, 1, origin, status, user, from_repo)


COPR = "copr:copr.fedorainfracloud.org:owner:proj"
ROWS = [
    row("a"),
    row("b", Status.INSTALLED, from_repo="updates", user=True),
    row("c", Status.UPGRADABLE, repo="updates", from_repo="fedora"),
    row("d", Status.ORPHAN, repo=COPR, from_repo=COPR, origin=Origin.COPR),
    # installed from COPR, but the candidate now comes from Fedora: still listed under the COPR project
    row("e", Status.INSTALLED, repo="fedora", from_repo=COPR, origin=Origin.COPR),
    row("f", repo="rpmfusion-free", origin=Origin.THIRD_PARTY),
]
SNAP = CatalogSnapshot(ROWS, 4, 1, 0.0)


def counts(entries):
    return {e.id: e.count for e in entries}


def test_unneeded_is_what_autoremove_removes_whatever_the_status():
    rows = [row("dep", Status.UNNEEDED), row("old-dep", Status.ORPHAN), row("app", Status.INSTALLED)]
    rows[0].unneeded = rows[1].unneeded = True
    c = counts(status_filters(CatalogSnapshot(rows, 3, 0, 0.0)))
    assert c["status:unneeded"] == 2 and c["status:orphan"] == 1


def test_upgrades_that_cannot_be_installed_have_an_entry_while_there_are_any():
    blocked = {ROWS[2].key: "nothing provides liboapv.so.11"}
    assert counts(status_filters(SNAP, blocked=blocked))["status:blocked"] == 1
    assert "status:blocked" not in counts(status_filters(SNAP))  # without the resolve, no entry at all
    blocked.clear()
    ids = [e.id for e in visible_entries(status_filters(SNAP, blocked=blocked))]
    assert "status:blocked" not in ids and "status:upgradable" in ids
    assert "status:blocked" in [e.id for e in visible_entries(status_filters(SNAP, blocked=blocked), "status:blocked")]

def test_status_counts():
    c = counts(status_filters(SNAP))
    assert c["status:all"] == 6
    assert c["status:installed"] == 4
    assert c["status:not-installed"] == 2
    assert c["status:upgradable"] == 1
    assert c["status:user"] == 1
    assert c["status:orphan"] == 1


def test_origin_subentries_add_up():
    entries = origin_filters(SNAP)
    c = counts(entries)
    assert c["origin:copr"] == 2
    assert c[f"repo:{COPR}"] == 2
    assert c["origin:third"] == c["repo:rpmfusion-free"] == 1
    assert c["origin:fedora"] == 3
    assert c["repo:fedora"] == 2 and c["repo:updates"] == 1  # each Fedora repository too, as in COPR
    assert "origin:local" not in c
    assert next(e for e in entries if e.id == f"repo:{COPR}").label == "owner/proj"


def test_group_filters():
    snap = CatalogSnapshot(ROWS, 4, 1, 0.0, groups=[
        GroupInfo("tools", "Tools", "Useful tools", True, frozenset({"a", "b", "not-in-catalog"})),
        GroupInfo("empty", "Empty", "", False, frozenset()),
    ])
    entries = group_filters(snap)
    assert counts(entries) == {"group:all": 6, "group:tools": 2, "group:empty": 0}
    assert entries[1].bold and entries[1].group == "tools" and entries[1].tip == "Useful tools"
    assert not entries[2].bold and entries[2].group == "empty"


def test_environments_are_a_tree_of_their_groups():
    """Each environment is followed by its groups (indent 1): those it installs, then its optional ones, dim.
    Groups hidden from the Groups view ("core") show here. No "All environments": it would only be all packages."""
    core = GroupInfo("core", "Core", "", True, frozenset({"a"}), visible=False)
    tools = GroupInfo("tools", "Tools", "", False, frozenset({"b", "c"}), optional=frozenset({"c"}))
    extra = GroupInfo("extra", "Extra", "", False, frozenset({"d"}))
    env = GroupInfo("work-environment", "Work", "For work", True, frozenset({"a", "b", "c"}),
                    optional=frozenset({"c"}), environment=True, groups=("tools", "core"),
                    optional_groups=("extra",))
    other = GroupInfo("play-environment", "Play", "", False, frozenset(), environment=True)
    snap = CatalogSnapshot(ROWS, 4, 1, 0.0, groups=[core, extra, tools], environments=[other, env])
    assert [e.id for e in group_filters(snap)] == ["group:all", "group:extra", "group:tools"]

    entries = environment_filters(snap)
    assert [(e.id, e.indent, e.dim) for e in entries] == [
        ("env:play-environment", 0, False), ("env:work-environment", 0, False),
        ("envgroup:work-environment:core", 1, False), ("envgroup:work-environment:tools", 1, False),
        ("envgroup:work-environment:extra", 1, True)]
    work = entries[1]
    assert work.group == "env:work-environment" and work.bold and work.optional == {"c"}
    # counted by name, as the predicates match
    assert [e.count for e in entries] == [sum(e.predicate(r) for r in ROWS) for e in entries]
    assert entries[3].group == "tools" and entries[3].optional == {"c"}
    assert "Optional" in entries[4].tip
    assert [environment_id(e.id) for e in entries[:3]] == ["play-environment", "work-environment",
                                                         "work-environment"]
