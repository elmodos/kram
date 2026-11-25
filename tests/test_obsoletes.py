"""Upgrades to a package of another name that obsoletes the installed one: kram 0.11 -> kram-qt (Obsoletes: kram <
0.12.0). libdnf5's filter_upgradable does not see them, `dnf5 upgrade` does."""
import os

import rpm

from kram.app.columns import CellContext, cell_text
from kram.core.marks import Action, MarkSet, allowed_actions
from kram.core.model import Origin, PkgRow, Status

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _Reldep:
    """`name < version`, as an Obsoletes entry."""

    def __init__(self, name, below=None):
        self.name, self.below = name, below

    def get_name(self):
        return self.name

    def matches(self, p):
        return p.name == self.name and (self.below is None or rpm.labelCompare(("0", p.version, "1"),
                                                                                ("0", self.below, "0")) < 0)


class _Pkg:
    def __init__(self, name, version, installed, obsoletes=(), arch="noarch"):
        self.name, self.version, self.installed, self.obsoletes, self.arch = name, version, installed, obsoletes, arch

    def get_name(self):
        return self.name

    def get_arch(self):
        return self.arch

    def get_epoch(self):
        return "0"

    def get_version(self):
        return self.version

    def get_release(self):
        return "1"

    def get_obsoletes(self):
        return list(self.obsoletes)


def _fake_dnf(monkeypatch, packages, obsoletes=True):
    import libdnf5

    class Query:
        def __init__(self, base_or_query):
            self.pkgs = list(base_or_query.pkgs) if isinstance(base_or_query, Query) else list(packages)

        def __iter__(self):
            return iter(self.pkgs)

        def filter_installed(self):
            self.pkgs = [p for p in self.pkgs if p.installed]

        def filter_available(self):
            self.pkgs = [p for p in self.pkgs if not p.installed]

        def filter_upgradable(self):
            self.pkgs = []  # the same name has nothing newer in these cases

        def filter_latest_evr(self):
            newest = {}
            for p in self.pkgs:
                old = newest.get(p.name)
                if old is None or rpm.labelCompare(("0", p.version, "1"), ("0", old.version, "1")) > 0:
                    newest[p.name] = p
            self.pkgs = list(newest.values())

        def filter_obsoletes(self, query):
            self.pkgs = [p for p in self.pkgs if any(r.matches(old) for r in p.obsoletes for old in query)]

        def filter_name(self, names):
            self.pkgs = [p for p in self.pkgs if p.name in names]

        def filter_provides(self, reldep):
            self.pkgs = [p for p in self.pkgs if reldep.matches(p)]

    class Option:
        def get_value(self):
            return obsoletes

    class Config:
        def get_obsoletes_option(self):
            return Option()

    class Base:
        def get_config(self):
            return Config()

    monkeypatch.setattr(libdnf5.rpm, "PackageQuery", Query)
    return Base()


KRAM_QT = [_Pkg("kram-qt", v, False, [_Reldep("kram", "0.12.0")]) for v in ("0.12.0", "0.14.1")]


def test_an_obsoleting_package_of_another_name_is_an_upgrade(monkeypatch):
    from kram.core.updates import replacements, upgradable_keys
    base = _fake_dnf(monkeypatch, [_Pkg("kram", "0.11.3", True), _Pkg("kram", "0.11.3", False), *KRAM_QT])
    found = replacements(base)
    assert list(found) == [("kram", "noarch")]
    assert found["kram", "noarch"].get_version() == "0.14.1"  # the newest of the obsoleting package
    assert upgradable_keys(base) == {("kram", "noarch")}


def test_no_replacement_when_the_version_is_not_obsoleted_or_obsoletes_are_off(monkeypatch):
    from kram.core.updates import replacements
    # kram 0.12 (never built, but the Obsoletes says < 0.12.0) is not replaced
    assert replacements(_fake_dnf(monkeypatch, [_Pkg("kram", "0.12.0", True), *KRAM_QT])) == {}
    assert replacements(_fake_dnf(monkeypatch, [_Pkg("kram", "0.11.3", True), *KRAM_QT], obsoletes=False)) == {}


def test_an_installed_obsoleter_is_upgraded_not_a_replacement(monkeypatch):
    from kram.core.updates import replacements
    packages = [_Pkg("kram", "0.11.3", True), _Pkg("kram-qt", "0.12.0", True), *KRAM_QT]
    assert replacements(_fake_dnf(monkeypatch, packages)) == {}


KRAM = PkgRow("kram", "noarch", "", "0.11.3-1.fc44", "0.14.1-1.fc44", "copr:copr.fedorainfracloud.org:elmodos:Kram",
              1, Origin.COPR, Status.UPGRADABLE, replaced_by="kram-qt")


def test_the_upgrade_of_a_replaced_package_is_dnf5_upgrade_of_its_name():
    # `dnf5 upgrade kram` installs kram-qt in its place; kram.noarch finds nothing to upgrade
    assert allowed_actions(KRAM) == [Action.UPGRADE, Action.REMOVE, Action.MARK_USER]
    m = MarkSet()
    assert m.set(KRAM, Action.UPGRADE)
    assert m.request({KRAM.key: KRAM}) == {"upgrade": ["kram"]}


def test_the_latest_version_names_the_replacement():
    assert cell_text(KRAM, 5, CellContext(basearch="x86_64")) == "kram-qt 0.14.1-1.fc44"
