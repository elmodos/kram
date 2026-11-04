import pytest

from kram.core.custom_filters import (
    STATUS_ANY_INSTALLED,
    Condition,
    CustomFilter,
    Field,
    Op,
    conditions_for_view,
    load_filters,
    ops_for,
)
from kram.core.filters import custom_filter_entries
from kram.core.model import CatalogSnapshot, GroupInfo, Origin, PkgRow, Status

COPR = "copr:copr.fedorainfracloud.org:owner:proj"
MB = 1024 * 1024


def row(name, status=Status.NOT_INSTALLED, summary="", repo="fedora", from_repo="", origin=Origin.FEDORA,
        user=False, size=1, arch="x86_64"):
    inst = "" if status is Status.NOT_INSTALLED else "1-1"
    return PkgRow(name, arch, summary, inst, "1-1", repo, size, origin, status, user, from_repo)


ROWS = [
    row("python3-requests", Status.UNNEEDED, "HTTP library", from_repo="fedora", arch="noarch"),
    row("python3-foo", Status.INSTALLED, "Foo", from_repo="updates", user=True),
    row("wezterm", Status.INSTALLED, "Terminal emulator", repo=COPR, from_repo=COPR, origin=Origin.COPR,
        user=True, size=200 * MB),
    row("kernel", Status.UPGRADABLE, "The Linux kernel", repo="updates", from_repo="fedora", size=150 * MB),
    row("kernel-devel", summary="Development package for the kernel"),
    row("kitty", summary="Fast terminal", size=15 * MB),
]
SNAP = CatalogSnapshot(ROWS, 4, 1, 0.0, descriptions=["requests", "foo", "GPU-accelerated", "Linux", "headers", "GPU"],
                       groups=[GroupInfo("term", "Terminals", "", False, frozenset({"kitty", "wezterm"}))])


def names(f: CustomFilter) -> list[str]:
    pred = f.compile(SNAP)
    return [r.name for r in ROWS if pred(r)]


@pytest.mark.parametrize(("cond", "expected"), [
    (Condition(Field.NAME, Op.CONTAINS, "PYTHON"), ["python3-requests", "python3-foo"]),
    (Condition(Field.NAME, Op.MATCHES, "kernel*"), ["kernel", "kernel-devel"]),
    (Condition(Field.NAME, Op.IS, "kernel"), ["kernel"]),
    (Condition(Field.NAME_SUMMARY, Op.CONTAINS, "terminal"), ["wezterm", "kitty"]),
    (Condition(Field.NAME_SUMMARY, Op.NOT_CONTAINS, "kernel"), ["python3-requests", "python3-foo", "wezterm", "kitty"]),
    (Condition(Field.DESCRIPTION, Op.CONTAINS, "gpu"), ["wezterm", "kitty"]),
    (Condition(Field.STATUS, Op.IS, STATUS_ANY_INSTALLED), ["python3-requests", "python3-foo", "wezterm", "kernel"]),
    (Condition(Field.STATUS, Op.IS, "upgradable"), ["kernel"]),
    (Condition(Field.STATUS, Op.IS_NOT, "none"), ["python3-requests", "python3-foo", "wezterm", "kernel"]),
    (Condition(Field.ORIGIN, Op.IS, "copr"), ["wezterm"]),
    (Condition(Field.REPO, Op.IS, "updates"), ["python3-foo", "kernel"]),  # origin repo or candidate repo
    (Condition(Field.GROUP, Op.IS, "term"), ["wezterm", "kitty"]),
    (Condition(Field.GROUP, Op.IS, "no-such-group"), []),
    (Condition(Field.REASON, Op.IS, "user"), ["python3-foo", "wezterm"]),
    (Condition(Field.REASON, Op.IS, "dependency"), ["python3-requests", "kernel"]),
    (Condition(Field.ARCH, Op.IS, "noarch"), ["python3-requests"]),
    (Condition(Field.SIZE, Op.GREATER, "100"), ["wezterm", "kernel"]),
    (Condition(Field.SIZE, Op.LESS, "0,5"), ["python3-requests", "python3-foo", "kernel-devel"]),
    (Condition(Field.SIZE, Op.GREATER, "lots"), []),
])
def test_conditions(cond, expected):
    assert names(CustomFilter("t", [cond])) == expected


def test_all_any_and_empty():
    conds = [Condition(Field.NAME, Op.MATCHES, "kernel*"), Condition(Field.NAME, Op.NOT_CONTAINS, "devel")]
    assert names(CustomFilter("t", conds)) == ["kernel"]
    assert names(CustomFilter("t", conds, match_all=False)) == [r.name for r in ROWS]
    assert names(CustomFilter("t", [])) == [r.name for r in ROWS]


def test_entries_count():
    filters = [CustomFilter("Big", [Condition(Field.SIZE, Op.GREATER, "100")]),
               CustomFilter("COPR", [Condition(Field.ORIGIN, Op.IS, "copr")])]
    entries = custom_filter_entries(SNAP, filters)
    assert [(e.id, e.label, e.count) for e in entries] == [("custom:Big", "Big", 2), ("custom:COPR", "COPR", 1)]


def test_roundtrip_and_bad_data():
    f = CustomFilter("Mine", [Condition(Field.REASON, Op.IS, "user"), Condition(Field.SIZE, Op.LESS, "5")], False)
    data = [f.to_dict(), {"name": "broken"}, {"name": "x", "conditions": [{"field": "nope", "op": "is"}]},
            {"name": "y", "conditions": [{"field": "size", "op": "contains", "value": "1"}]}, "garbage"]
    assert load_filters(data) == [f, CustomFilter("broken")]
    assert load_filters("not a list") == []


def test_ops_for_fields():
    assert Op.GREATER in ops_for(Field.SIZE) and Op.IS not in ops_for(Field.SIZE)
    assert ops_for(Field.ORIGIN) == [Op.IS, Op.IS_NOT]
    assert Op.MATCHES in ops_for(Field.NAME)


def test_conditions_for_view():
    assert conditions_for_view("status:all", "", None) == []
    assert conditions_for_view("status:user", "", None) == [Condition(Field.REASON, Op.IS, "user")]
    assert conditions_for_view("repo:" + COPR, "term", Field.NAME_SUMMARY) == [
        Condition(Field.REPO, Op.IS, COPR), Condition(Field.NAME_SUMMARY, Op.CONTAINS, "term")]
    assert conditions_for_view("origin:all", "x", Field.NAME) == [Condition(Field.NAME, Op.CONTAINS, "x")]
    assert conditions_for_view("group:term", "", None) == [Condition(Field.GROUP, Op.IS, "term")]
