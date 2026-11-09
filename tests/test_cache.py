"""Counting the package caches and cleaning PackageKit's, on a fake tree."""
import io
import json
import os
import shutil

import pytest

pytest.importorskip("libdnf5")

from kram.core import cache
from kram.helper import kram_helper as helper


def write(path, size):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


@pytest.fixture
def packagekit(tmp_path, monkeypatch):
    root = tmp_path / "PackageKit"
    write(root / "44/metadata/fedora-1/packages/a.rpm", 100)
    write(root / "44/metadata/fedora-1/packages/b.rpm", 20)
    write(root / "44/metadata/fedora-1/repodata/primary.xml.zst", 7)
    write(root / "43/metadata/updates-2/packages/old.rpm", 3)
    (root / "44/metadata/fedora-1/packages/link.rpm").symlink_to(tmp_path / "outside.rpm")
    write(tmp_path / "outside.rpm", 5)
    monkeypatch.setattr(helper, "PACKAGEKIT_CACHE", str(root))
    monkeypatch.setattr(helper, "OFFLINE_MARKERS", (str(tmp_path / "system-update"),))
    monkeypatch.setattr(helper, "_bus_call", lambda *_args: None)
    monkeypatch.setattr(helper, "_proto", io.StringIO())
    return root


def events():
    return [json.loads(line) for line in helper._proto.getvalue().splitlines()]


def test_scan_dnf_separates_packages_from_metadata(tmp_path):
    write(tmp_path / "fedora-1/packages/a.rpm", 10)
    write(tmp_path / "fedora-1/repodata/primary.xml.zst", 4)
    write(tmp_path / "fedora-1/solv/fedora.solv", 2)
    write(tmp_path / "temporary_files.toml", 1)
    assert cache.scan_dnf(str(tmp_path)) == (cache.Usage(10, 1), cache.Usage(7, 3))


def test_a_missing_cache_is_not_an_empty_one(tmp_path):
    assert cache.scan_dnf(str(tmp_path / "none")) == (None, None)
    assert cache.scan_tree(str(tmp_path / "none")) is None
    assert cache.scan_tree(str(tmp_path)) == cache.Usage()


def test_packagekit_counts_only_what_cleaning_removes(packagekit):
    assert cache.scan_packagekit() == cache.Usage(123, 3)


def test_packagekit_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(helper, "PACKAGEKIT_CACHE", str(tmp_path / "none"))
    assert cache.scan_packagekit() is None


def test_clean_keeps_metadata_and_symlinks(packagekit, tmp_path):
    helper.clean_packagekit()
    assert helper.packagekit_rpms() == []
    assert (packagekit / "44/metadata/fedora-1/repodata/primary.xml.zst").exists()
    assert (packagekit / "44/metadata/fedora-1/packages/link.rpm").is_symlink()
    assert (tmp_path / "outside.rpm").exists()
    assert events()[-1] == {"event": "done", "ok": True}
    assert events()[0]["params"] == {"count": 3}


def test_prepared_offline_update_blocks_cleaning(packagekit, tmp_path):
    (tmp_path / "system-update").symlink_to("/nonexistent")  # a dangling link still means "prepared"
    assert helper.packagekit_blocker() == "offline"
    helper.clean_packagekit()
    assert len(helper.packagekit_rpms()) == 3
    assert events() == [{"event": "done", "ok": False, "stage": "packagekit", "reason": "offline",
                         "error": "PackageKit's cache is in use: offline"}]


@pytest.mark.parametrize(("owned", "transactions", "expected"), [
    (None, None, None),                      # no system bus
    ("b false", None, None),                 # the daemon is not running: it must not be started by asking
    ("b true", "ao 0", None),
    ("b true", 'ao 1 "/1_abc"', "transaction"),
    ("b true", None, "transaction"),         # running, but it does not answer: assume it is busy
])
def test_packagekit_transaction(packagekit, monkeypatch, owned, transactions, expected):
    calls = []

    def bus(*args):
        calls.append(args)
        return owned if args[3] == "NameHasOwner" else transactions
    monkeypatch.setattr(helper, "_bus_call", bus)
    assert helper.packagekit_blocker() == expected
    assert len(calls) == (2 if owned == "b true" else 1)


def test_dialog_shows_the_report(monkeypatch):
    pytest.importorskip("PySide6.QtWidgets")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from kram.ui import cache_dialog

    QApplication.instance() or QApplication([])

    class Inline:
        def submit(self, fn, on_done, on_error=None):
            on_done(fn())

    report = cache.CacheReport(cache.Usage(), cache.Usage(5, 2), None, cache.Usage(2048, 2), "offline",
                               "/var/cache/libdnf5", "/home/u/.cache/libdnf5")
    monkeypatch.setattr(cache_dialog, "measure", lambda: report)
    dlg = cache_dialog.CacheDialog(Inline(), lambda _target: None)
    rows = dlg.rows
    assert not rows["dnf_packages"].button.isEnabled()  # empty
    assert rows["dnf_metadata"].button.isEnabled()      # usable even when empty, here not
    assert rows["user"].frame.isHidden()                # this system has no such cache
    assert rows["user"].separator.isHidden()
    assert rows["dnf_packages"].separator.isHidden()    # no line above the first row
    assert not rows["packagekit"].separator.isHidden()
    assert not rows["packagekit"].button.isEnabled()    # an offline update is prepared
    assert rows["packagekit"].files.text() == "2 files"
    assert not dlg.note.isHidden()
    # the path says where the files are, the link opens a folder that exists
    assert "/var/cache/libdnf5/*/packages</a>" in rows["dnf_packages"].path.text()
    assert "href='file:///var/cache/libdnf5'" in rows["dnf_packages"].path.text()
    assert rows["dnf_packages"].path.openExternalLinks()


def test_dialog_shrinks_with_wrapped_text_and_scrolls(monkeypatch):
    pytest.importorskip("PySide6.QtWidgets")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QLabel

    from kram.ui import cache_dialog

    app = QApplication.instance() or QApplication([])

    class Later:  # as the real thread does: the numbers arrive after the window has appeared
        pending = None

        def submit(self, fn, on_done, on_error=None):
            self.pending = lambda: on_done(fn())

    def settle():
        for _ in range(5):
            app.processEvents()

    usage = cache.Usage(3 << 30, 467)
    report = cache.CacheReport(usage, usage, usage, usage, None, "/var/cache/libdnf5", "/home/someone/.cache/libdnf5")
    monkeypatch.setattr(cache_dialog, "measure", lambda: report)
    dnf = Later()
    dlg = cache_dialog.CacheDialog(dnf, lambda _target: None)
    dlg.show()
    settle()
    dnf.pending()
    settle()

    assert dlg.scroll.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    narrowest = dlg.minimumSizeHint().width()
    assert narrowest < 600
    dlg.resize(narrowest, 180)
    settle()
    content = dlg.scroll.widget()
    assert content.width() <= dlg.scroll.viewport().width()     # nothing is cut off on the right
    assert dlg.scroll.verticalScrollBar().maximum() > 0         # the rest scrolls
    for label in content.findChildren(QLabel):
        if label.wordWrap() and label.text():
            assert label.height() >= label.heightForWidth(label.width()), label.text()


def test_locations_open_real_folders(monkeypatch):
    monkeypatch.setattr(helper, "PACKAGEKIT_CACHE", "/var/cache/PackageKit")
    report = cache.CacheReport(None, None, None, None, None, "/var/cache/libdnf5", "/home/u/.cache/libdnf5")
    locations = report.locations()
    assert locations["user"] == ("/home/u/.cache/libdnf5", "/home/u/.cache/libdnf5")
    assert locations["packagekit"] == ("/var/cache/PackageKit/*/metadata/*/packages", "/var/cache/PackageKit")
    assert not any("*" in folder for _shown, folder in locations.values())


def test_a_single_packagekit_release_is_named_in_the_path(packagekit):
    assert cache.packagekit_release() == ""  # the fixture has 43 and 44
    shutil.rmtree(packagekit / "43")
    assert cache.packagekit_release() == "44"
    report = cache.CacheReport(None, None, None, None, None, "/d", "/u", "44")
    metadata = str(packagekit / "44/metadata")
    assert report.locations()["packagekit"] == (f"{metadata}/*/packages", metadata)


def test_packagekit_release_without_the_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(helper, "PACKAGEKIT_CACHE", str(tmp_path / "none"))
    assert cache.packagekit_release() == ""
