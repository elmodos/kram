"""kram.app.marking without a toolkit: the question about the packages a removal takes along, both answers."""
from kram.app.marking import Marker
from kram.app.package_list import PackageList
from kram.app.ports import RecordingUi
from kram.core.marks import Action
from kram.core.model import CatalogSnapshot, Origin, PkgRow, Status


def row(name):
    return PkgRow(name, "x86_64", "", "1-1", "1-1", "fedora", 1, Origin.FEDORA, Status.INSTALLED, True)


ROWS = [row("lib"), row("app"), row("other")]


class Catalog:
    def removal_dependents(self, remove):
        return [("app", "x86_64")] if "lib.x86_64" in remove else []


class Dnf:  # runs at once, as the dnf thread would, only synchronously
    def submit(self, fn, done, failed=None):
        done(fn())


def marker(answers):
    packages = PackageList()
    packages.set_rows(ROWS, "x86_64")
    ui = RecordingUi(answers)
    m = Marker(packages, Catalog(), Dnf(), ui)
    m.set_snapshot(CatalogSnapshot(ROWS, 3, 0, 0.0))
    changes = []
    m.changed.connect(changes.append)
    return m, ui, changes


def test_marking_the_dependents_too():
    m, ui, changes = marker(["mark"])
    m.mark([ROWS[0]], Action.REMOVE)
    question = ui.calls[0][1]
    assert "1 installed package depends" in question.text and question.informative == "app"
    assert {k for k, _mark in m.marks.items()} == {("lib", "x86_64"), ("app", "x86_64")}
    assert changes == [[("lib", "x86_64")], [("app", "x86_64")]]


def test_cancelling_takes_back_the_removal():
    m, ui, changes = marker(["cancel"])
    m.marks.set(ROWS[2], Action.REMOVE)
    m.mark([ROWS[0]], Action.REMOVE)
    assert {k for k, _mark in m.marks.items()} == {("other", "x86_64")}  # marked before: stays
    m2, _ui, _changes = marker([None])  # closed without an answer: the same as cancel
    m2.mark([ROWS[0]], Action.REMOVE)
    assert len(m2.marks) == 0


def test_no_question_without_dependents():
    m, ui, _changes = marker([])
    m.mark([ROWS[2]], Action.REMOVE)
    assert ui.calls == [] and len(m.marks) == 1
