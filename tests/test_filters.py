from kram.core.filters import origin_filters, status_filters
from kram.core.model import CatalogSnapshot, Origin, PkgRow, Status


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
    assert "origin:local" not in c
    assert next(e for e in entries if e.id == f"repo:{COPR}").label == "owner/proj"
