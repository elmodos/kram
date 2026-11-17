"""Update advisories: what kind of fix an upgrade is, in the package list, the sidebar and the ways to mark upgrades."""
import os

import pytest

from kram.core.custom_filters import UPDATE_SECURITY_HIGH, Condition, CustomFilter, Field, Op, conditions_for_view
from kram.core.filters import (
    UPGRADES_FIXES,
    UPGRADES_SECURITY,
    UPGRADES_SECURITY_HIGH,
    status_filters,
    upgrades_by_kind,
)
from kram.core.model import Advisory, CatalogSnapshot, Origin, PkgRow, Status

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def advisory(id, type, severity="", issued=0):
    return Advisory(id, type, severity, f"{id} title", issued)


CRITICAL = advisory("FEDORA-2026-1", "security", "critical")
MODERATE = advisory("FEDORA-2026-2", "security", "moderate")
UNRATED = advisory("FEDORA-2026-3", "security")
BUGFIX = advisory("FEDORA-2026-4", "bugfix")
ENHANCEMENT = advisory("FEDORA-2026-5", "enhancement")
NEWPACKAGE = advisory("RHSA-2026:6", "newpackage")


def row(name, *advisories, status=Status.UPGRADABLE):
    return PkgRow(name, "x86_64", "", "1-1", "2-1", "updates", 1, Origin.FEDORA, status, advisories=advisories)


ROWS = [
    row("firefox", CRITICAL),
    row("openssl", MODERATE, BUGFIX),
    row("assimp", UNRATED),
    row("kernel", BUGFIX),
    row("plasma", ENHANCEMENT),
    row("ibus", NEWPACKAGE),
    row("chrome"),  # a third-party repository: no advisories
    row("bash", status=Status.INSTALLED),
]
SNAP = CatalogSnapshot(ROWS, len(ROWS), 7, 0.0)


@pytest.mark.parametrize(("a", "level"), [
    (CRITICAL, "critical"), (MODERATE, "moderate"), (UNRATED, "security"), (BUGFIX, "bugfix"),
    (ENHANCEMENT, "enhancement"), (NEWPACKAGE, "other"), (advisory("X", "security", "urgent"), "security"),
])
def test_level(a, level):
    assert a.level == level


def test_rank_puts_security_first():
    ranked = sorted([NEWPACKAGE, ENHANCEMENT, BUGFIX, UNRATED, MODERATE, CRITICAL], key=lambda a: a.rank)
    assert ranked == [CRITICAL, MODERATE, UNRATED, BUGFIX, ENHANCEMENT, NEWPACKAGE]


def test_url_only_for_fedora():
    assert CRITICAL.url == "https://bodhi.fedoraproject.org/updates/FEDORA-2026-1"
    assert NEWPACKAGE.url == ""


def test_row_advisory_is_the_first():
    assert ROWS[1].advisory is MODERATE
    assert ROWS[6].advisory is None


def test_upgrades_by_kind():
    kinds = {kind: [r.name for r in rows] for kind, rows in upgrades_by_kind(ROWS).items()}
    assert kinds == {
        UPGRADES_SECURITY: ["firefox", "openssl", "assimp"],
        UPGRADES_SECURITY_HIGH: ["firefox"],
        UPGRADES_FIXES: ["firefox", "openssl", "assimp", "kernel"],
    }


def test_sidebar_counts():
    counts = {e.id: e.count for e in status_filters(SNAP)}
    assert counts["status:security"] == 3
    assert counts["status:bugfix"] == 2  # openssl has a bug fix advisory too


@pytest.mark.parametrize(("value", "expected"), [
    ("security", ["firefox", "openssl", "assimp"]),
    (UPDATE_SECURITY_HIGH, ["firefox"]),
    ("bugfix", ["openssl", "kernel"]),
    ("enhancement", ["plasma"]),
])
def test_custom_filter(value, expected):
    pred = CustomFilter("t", [Condition(Field.UPDATE, Op.IS, value)]).compile(SNAP)
    assert [r.name for r in ROWS if pred(r)] == expected


def test_custom_filter_from_view():
    assert conditions_for_view("status:security", "", None) == [Condition(Field.UPDATE, Op.IS, "security")]
    assert conditions_for_view("status:bugfix", "", None) == [Condition(Field.UPDATE, Op.IS, "bugfix")]


@pytest.fixture(scope="module")
def model():
    from PySide6.QtWidgets import QApplication

    from kram.ui.package_model import PackageTableModel
    _app = QApplication.instance() or QApplication([])
    m = PackageTableModel()
    m.set_rows(ROWS, "x86_64")
    yield m


def shown(model):
    return [model.rows[i].name for i in model.visible]


def test_sort_by_update_type(model):
    from PySide6.QtCore import Qt

    from kram.ui.package_model import COL_ADVISORY
    model.sort(COL_ADVISORY, Qt.AscendingOrder)
    assert shown(model) == ["firefox", "openssl", "assimp", "kernel", "plasma", "ibus", "bash", "chrome"]
    model.sort(COL_ADVISORY, Qt.DescendingOrder)  # the rows without advisories stay at the end
    assert shown(model)[:6] == ["ibus", "plasma", "kernel", "assimp", "openssl", "firefox"]
    assert set(shown(model)[6:]) == {"bash", "chrome"}


def test_column_and_tooltip(model):
    from PySide6.QtCore import Qt

    from kram.ui.package_model import COL_ADVISORY, COL_CANDIDATE
    model.set_visible(list(range(len(ROWS))), ranked=True)
    assert model.data(model.index(0, COL_ADVISORY)) == "Security: critical"
    assert model.data(model.index(6, COL_ADVISORY)) == ""
    assert model.data(model.index(1, COL_CANDIDATE), Qt.ToolTipRole) == (
        "Security: moderate — FEDORA-2026-2 — FEDORA-2026-2 title\nBug fix — FEDORA-2026-4 — FEDORA-2026-4 title")
    assert model.data(model.index(6, COL_CANDIDATE), Qt.ToolTipRole) is None
    # every row has an icon next to its version (a blank one without an advisory), so that the versions line up
    assert not model.data(model.index(6, COL_CANDIDATE), Qt.DecorationRole).isNull()


def test_details_tab_comes_and_goes(model):
    from kram.ui.details import DetailsTabs
    tabs = DetailsTabs()
    index = tabs.indexOf(tabs.advisories)
    assert not tabs.isTabVisible(index)
    tabs.select_name("dependencies")
    tabs.show_advisories(ROWS[0])
    assert tabs.isTabVisible(index)
    assert not tabs.tabIcon(index).isNull()
    assert "FEDORA-2026-1" in tabs.advisories.toPlainText()
    assert tabs.current_name() == "dependencies"  # showing up does not take the user away from their tab
    tabs.setCurrentIndex(index)  # the user picks it
    tabs.show_advisories(ROWS[6])  # a package without advisories: back to the tab the user had before
    assert not tabs.isTabVisible(index)
    assert tabs.current_name() == "advisories"  # still what the user wants, and what the settings keep
    assert tabs.currentWidget() is tabs.deps
    tabs.show_advisories(ROWS[3])  # the next package with advisories: there again
    assert tabs.currentIndex() == index
    tabs.select_name("files")
    tabs.show_advisories(ROWS[1])
    assert tabs.current_name() == "files"


class _Pkg:
    def __init__(self, name, arch="x86_64"):
        self.name, self.arch = name, arch

    def get_name(self):
        return self.name

    def get_arch(self):
        return self.arch


class _Item:
    def __init__(self, action, package, replaces=()):
        self.action, self.package, self.replaces = action, package, list(replaces)

    def get_action(self):
        return self.action

    def get_package(self):
        return self.package

    def get_replaces(self):
        return self.replaces


def _resolver(monkeypatch, items, problems=None):
    import libdnf5

    class Transaction:
        def get_problems(self):
            return libdnf5.base.GoalProblem_NO_PROBLEM if problems is None else problems

        def get_transaction_packages(self):
            return items

    class Goal:
        def __init__(self, base):
            pass

        def add_rpm_upgrade(self):
            pass

        def resolve(self):
            return Transaction()
    monkeypatch.setattr(libdnf5.base, "Goal", Goal)


def test_installable_upgrades_leave_out_what_the_resolver_skips(monkeypatch):
    import libdnf5

    from kram.core.updates import installable_upgrades
    T = libdnf5.transaction
    upgradable = {("gjs", "x86_64"), ("ffmpeg", "x86_64"), ("old-tool", "noarch")}
    # ffmpeg's new build needs a missing library: best=False drops it without a problem
    _resolver(monkeypatch, [
        _Item(T.TransactionItemAction_UPGRADE, _Pkg("gjs")),
        _Item(T.TransactionItemAction_REPLACED, _Pkg("gjs")),
        _Item(T.TransactionItemAction_INSTALL, _Pkg("new-tool", "noarch"), [_Pkg("old-tool", "noarch")]),  # obsoletes
    ])
    assert installable_upgrades(None, upgradable) == {("gjs", "x86_64"), ("old-tool", "noarch")}
    assert installable_upgrades(None, set()) == set()


def test_installable_upgrades_keep_all_when_the_resolve_fails(monkeypatch):
    import libdnf5

    from kram.core.updates import installable_upgrades
    _resolver(monkeypatch, [], problems=libdnf5.base.GoalProblem_SOLVER_ERROR)
    assert installable_upgrades(None, {("gjs", "x86_64")}) == {("gjs", "x86_64")}
