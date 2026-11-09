"""Counting the package caches and cleaning PackageKit's, on a fake tree."""
import io
import json
import os

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

    report = cache.CacheReport(cache.Usage(), cache.Usage(5, 2), None, cache.Usage(2048, 2), "offline")
    monkeypatch.setattr(cache_dialog, "measure", lambda: report)
    dlg = cache_dialog.CacheDialog(Inline(), lambda _target: None)
    rows = dlg.rows
    assert not rows["dnf_packages"].button.isEnabled()  # empty
    assert rows["dnf_metadata"].button.isEnabled()      # usable even when empty, here not
    assert rows["user"].button.isHidden()               # this system has no such cache
    assert not rows["packagekit"].button.isEnabled()    # an offline update is prepared
    assert rows["packagekit"].files.text() == "2 files"
    assert not dlg.note.isHidden()
