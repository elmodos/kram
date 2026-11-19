"""File → Export List as CSV…"""
import csv
import io

from kram.core.csv_export import COLUMNS, write_csv
from kram.core.marks import Action, MarkSet
from kram.core.model import Advisory, Origin, PkgRow, Reason, Status

ROWS = [
    PkgRow("kram", "noarch", "Synaptic for dnf, with a \"quote\", and a comma", "0.9-1", "0.9.1-1", "copr:elmodos:Kram",
           2048, Origin.COPR, Status.UPGRADABLE, from_repo_id="copr:elmodos:Kram", reason=Reason.USER,
           advisories=(Advisory("FEDORA-1", "bugfix", "", "t", 0), Advisory("FEDORA-2", "enhancement", "", "t", 0))),
    PkgRow("vlc", "x86_64", "Media player\nsecond line", "", "3.0-1", "rpmfusion-free", 10, Origin.THIRD_PARTY,
           Status.NOT_INSTALLED),
]


def export(rows, marks=None):
    out = io.StringIO(newline="")
    n = write_csv(out, rows, marks or MarkSet())
    return n, list(csv.DictReader(io.StringIO(out.getvalue(), newline="")))


def test_columns_and_values_are_language_neutral():
    n, lines = export(ROWS)
    assert n == 2 and list(lines[0]) == list(COLUMNS)
    kram, vlc = lines
    assert kram == {
        "name": "kram", "arch": "noarch", "status": "upgradable", "installed_version": "0.9-1",
        "latest_version": "0.9.1-1", "latest_arch": "noarch", "repository": "copr:elmodos:Kram",
        "installed_from": "copr:elmodos:Kram", "origin": "copr", "reason": "user", "update_type": "bugfix",
        "advisories": "FEDORA-1 FEDORA-2", "size": "2048", "summary": ROWS[0].summary, "marked": ""}
    assert vlc["status"] == "none" and vlc["reason"] == "" and vlc["installed_version"] == ""
    assert vlc["summary"] == "Media player\nsecond line"  # quoted, read back whole


def test_marks_and_the_order_given():
    marks = MarkSet()
    marks.set(ROWS[1], Action.INSTALL)
    marks.set(ROWS[0], Action.DOWNGRADE, "0.8-1")
    _n, lines = export(list(reversed(ROWS)), marks)
    assert [(r["name"], r["marked"]) for r in lines] == [("vlc", "install"), ("kram", "downgrade 0.8-1")]


def test_nothing_listed_is_just_the_header():
    n, lines = export([])
    assert n == 0 and lines == []


def test_the_window_exports_what_it_lists(monkeypatch, tmp_path):
    import os

    import pytest
    pytest.importorskip("libdnf5")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication, QFileDialog
    QApplication.instance() or QApplication([])
    from kram.ui import main_window
    monkeypatch.setattr(main_window.MainWindow, "reload", lambda self: None)
    monkeypatch.setattr(QSettings, "setValue", lambda *_a: None)  # not into the user's settings
    win = main_window.MainWindow()
    try:
        assert not win.acts.export_csv.isEnabled()  # no catalog yet
        win.model.set_rows(ROWS, "x86_64")
        win.model.set_visible([1])  # what the filter and search left
        target = tmp_path / "list.csv"
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_a: (str(target), ""))
        win.export_csv()
        lines = target.read_text(encoding="utf-8").splitlines()
        assert lines[0] == ",".join(COLUMNS) and lines[1].startswith("vlc,x86_64,none,")
        assert "1 package exported" in win.statusBar().currentMessage()
    finally:
        win.dnf.shutdown()
