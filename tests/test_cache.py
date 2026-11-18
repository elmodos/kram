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

    assert dlg.scroll.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
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


# ---------------------------------------------------------------- leftover configuration files

from kram.core import leftovers  # noqa: E402


@pytest.fixture
def etc(tmp_path):
    (tmp_path / "ssh").mkdir()
    (tmp_path / "ssh" / "sshd_config").write_text("Port 22\n")
    (tmp_path / "ssh" / "sshd_config.rpmnew").write_text("Port 22\nUsePAM yes\n")
    (tmp_path / "yum.repos.d").mkdir()
    (tmp_path / "yum.repos.d" / "fedora.repo.rpmsave").write_text("[fedora]\n")
    (tmp_path / "app.conf").write_text("b\n")
    (tmp_path / "app.conf.rpmsave").write_text("a\n")
    (tmp_path / "linked.rpmsave").symlink_to(tmp_path / "app.conf")
    (tmp_path / "closed").mkdir()
    (tmp_path / "closed" / "x.rpmnew").write_text("")
    (tmp_path / "plain.conf").write_text("")
    return tmp_path


def test_the_search_finds_rpms_copies_and_counts_what_it_cannot_read(etc, monkeypatch):
    scandir = os.scandir

    def closed(path):  # what a folder of mode 0750 is for a normal user (the tests may run as root)
        if str(path).endswith("closed"):
            raise PermissionError(13, "Permission denied", str(path))
        return scandir(path)
    monkeypatch.setattr(os, "scandir", closed)
    files, unreadable = helper.find_leftover_files(str(etc))
    assert [(os.path.relpath(f["path"], etc), f["current"]) for f in files] == [
        ("app.conf.rpmsave", True), ("ssh/sshd_config.rpmnew", True), ("yum.repos.d/fedora.repo.rpmsave", False)]
    assert unreadable == 1


def test_leftovers_are_told_apart(etc, monkeypatch):
    (etc / "closed" / "x.rpmnew").unlink()
    monkeypatch.setattr(leftovers, "file_owners", lambda paths: {p: "openssh-server" for p in paths if "ssh" in p})
    report = leftovers.scan(str(etc))
    kinds = {os.path.relpath(f.path, etc): (f.kind, f.package) for f in report.files}
    assert kinds == {"app.conf.rpmsave": (leftovers.Kind.SAVED, ""),
                     "ssh/sshd_config.rpmnew": (leftovers.Kind.NEW, "openssh-server"),
                     "yum.repos.d/fedora.repo.rpmsave": (leftovers.Kind.ORPHAN, "")}
    new = next(f for f in report.files if f.kind is leftovers.Kind.NEW)
    assert new.current == str(etc / "ssh" / "sshd_config") and new.comparable
    assert "+UsePAM yes" in leftovers.diff(new).splitlines()
    assert not next(f for f in report.files if f.kind is leftovers.Kind.ORPHAN).comparable


def test_the_helper_deletes_only_unowned_leftovers_in_etc(etc):
    root = str(etc)
    ok = str(etc / "app.conf.rpmsave")
    assert helper.check_leftover(ok, lambda _p: None, root) == ok
    for bad, error in ((str(etc / "app.conf"), "not a leftover"), ("/tmp/x.rpmsave", "not a leftover"),
                       (f"{root}/ssh/../app.conf.rpmsave", "not a plain path"),
                       (str(etc / "linked.rpmsave"), "not a plain path"),
                       (str(etc / "gone.rpmsave"), "gone.rpmsave"), (42, "not a leftover")):
        with pytest.raises(helper.ProtocolError, match=error):
            helper.check_leftover(bad, lambda _p: None, root)
    with pytest.raises(helper.ProtocolError, match="belongs to the package rpm"):
        helper.check_leftover(ok, lambda _p: "rpm", root)


def leftover_dialog(monkeypatch, report, helper_fn):
    pytest.importorskip("PySide6.QtWidgets")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from kram.ui import cache_dialog

    QApplication.instance() or QApplication([])

    class Inline:
        def submit(self, fn, on_done, on_error=None):
            on_done(fn())

    monkeypatch.setattr(cache_dialog, "measure", lambda: cache.CacheReport(None, None, None, None, None))
    monkeypatch.setattr(cache_dialog, "scan_leftovers", lambda: report)
    return cache_dialog, cache_dialog.CacheDialog(Inline(), lambda _target: None, helper=helper_fn)


K = leftovers.Kind
REPORT = leftovers.LeftoverReport([
    leftovers.Leftover("/etc/ssh/sshd_config.rpmnew", 10, 0, K.NEW, "openssh-server"),
    leftovers.Leftover("/etc/yum.repos.d/fedora.repo.rpmsave", 10, 0, K.ORPHAN),
    leftovers.Leftover("/etc/yum.repos.d/chrome.repo.rpmsave", 10, 0, K.ORPHAN),
], 3)


def test_dialog_lists_the_leftovers(monkeypatch):
    _module, dlg = leftover_dialog(monkeypatch, REPORT, lambda _r, _t: None)
    assert "3 files found. 3 folders only root can read were not searched." == dlg.leftovers_status.text()
    assert not dlg.search_root_btn.isHidden() and dlg.delete_unused_btn.isEnabled()
    assert dlg._leftover_column.count() == 3
    assert "openssh-server" in dlg.describe(REPORT.files[0])


def test_dialog_without_leftovers(monkeypatch):
    _module, dlg = leftover_dialog(monkeypatch, leftovers.LeftoverReport([], 0), lambda _r, _t: None)
    assert dlg.leftovers_status.text() == "Nothing found."
    assert dlg.search_root_btn.isHidden() and not dlg.delete_unused_btn.isEnabled()


def test_delete_unused_asks_then_runs_the_helper(monkeypatch):
    requests = []
    module, dlg = leftover_dialog(monkeypatch, REPORT, lambda r, _t: requests.append(r) or {"ok": True})

    class Box:
        Icon, ButtonRole, StandardButton = module.QMessageBox.Icon, module.QMessageBox.ButtonRole, \
            module.QMessageBox.StandardButton

        def __init__(self, *_args, **_kwargs):
            self.delete = object()

        def setInformativeText(self, text):
            Box.info = text

        def addButton(self, text, _role=None):
            return self.delete if text == "Delete" else object()

        def exec(self):
            pass

        def clickedButton(self):
            return self.delete
    monkeypatch.setattr(module, "QMessageBox", Box)
    dlg.delete_unused_btn.click()
    assert requests == [{"op": "remove_leftovers", "paths": ["/etc/yum.repos.d/fedora.repo.rpmsave",
                                                             "/etc/yum.repos.d/chrome.repo.rpmsave"]}]
    assert [f.path for f in dlg.leftovers.files] == ["/etc/ssh/sshd_config.rpmnew"]
    assert not dlg.delete_unused_btn.isEnabled()


def test_search_as_root_replaces_the_list(monkeypatch):
    found = [{"path": "/etc/firewalld/firewalld.conf.rpmnew", "size": 1, "mtime": 0, "current": True}]
    module, dlg = leftover_dialog(monkeypatch, REPORT, lambda r, _t: {"ok": True, "files": found, "unreadable": 0})
    monkeypatch.setattr(leftovers, "file_owners", lambda paths: {p: "firewalld" for p in paths})
    dlg.search_root_btn.click()
    assert [(f.path, f.kind, f.package) for f in dlg.leftovers.files] == [
        ("/etc/firewalld/firewalld.conf.rpmnew", K.NEW, "firewalld")]
    assert dlg.search_root_btn.isHidden()
