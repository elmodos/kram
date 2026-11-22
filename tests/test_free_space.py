"""The free space check before a transaction: in the review (Apply stays off) and in the helper (before it downloads
gigabytes rpm would refuse to install)."""
import os
from types import SimpleNamespace

import pytest

from kram.app.parity import Feature  # noqa: E402  (the feature marks of the parity tests)
from kram.core.model import PreviewItem, TransactionPreview
from kram.helper import kram_helper
from kram.helper.kram_helper import human_size, mount_point, space_shortfall

GB = 1 << 30


@pytest.fixture
def disks(monkeypatch):
    """Two filesystems: / with 5 GB free, /var/cache with 2 GB free (when `split`); else one."""
    state = {"split": False}

    def fake_mount(path):
        return "/var/cache" if state["split"] and path.startswith("/var/cache") else "/"

    def fake_stat(path):
        return SimpleNamespace(st_dev=2 if path == "/var/cache" else 1)

    def fake_statvfs(path):
        free = 2 * GB if path == "/var/cache" else 5 * GB
        return SimpleNamespace(f_bavail=free // 4096, f_frsize=4096)
    monkeypatch.setattr(kram_helper, "mount_point", fake_mount)
    monkeypatch.setattr(kram_helper.os, "stat", fake_stat)
    monkeypatch.setattr(kram_helper.os, "statvfs", fake_statvfs)
    return state


def test_one_filesystem_needs_the_download_and_the_install_together(disks):
    """The packages stay in the cache until the transaction is done."""
    assert space_shortfall(2 * GB, 2 * GB, "/var/cache/libdnf5") == []
    assert space_shortfall(3 * GB, 3 * GB, "/var/cache/libdnf5") == [("/", GB)]
    assert space_shortfall(3 * GB, -10 * GB, "/var/cache/libdnf5") == []  # removals free space: only the download


def test_a_separate_cache_filesystem_counts_on_its_own(disks):
    disks["split"] = True
    assert space_shortfall(3 * GB, 4 * GB, "/var/cache/libdnf5") == [("/var/cache", GB)]
    assert space_shortfall(GB, 6 * GB, "/var/cache/libdnf5") == [("/", GB)]


def test_mount_point_of_a_path_that_does_not_exist_yet(tmp_path):
    assert mount_point(str(tmp_path / "no" / "such" / "dir")) == mount_point(str(tmp_path))
    assert os.path.ismount(mount_point(str(tmp_path)))


def test_sizes_read_as_in_the_gui():
    from kram.qt.package_model import human_size as gui_size
    for n in (0, 900, 2048, 7378 << 20, 3 * GB + 123):
        assert human_size(n) == gui_size(n)


@pytest.mark.feature(Feature.APPLY_REVIEW, front="qt")
def test_review_keeps_apply_off_without_space_but_allows_a_download_that_fits(disks):
    pytest.importorskip("PySide6.QtWidgets")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from kram.qt.apply_dialog import ApplyDialog

    item = PreviewItem("install", "fonts", "noarch", "1-1", "", "fedora", 3 * GB, 7 * GB, "group")
    preview = TransactionPreview([item], [], 3 * GB, 7 * GB, to_download=3 * GB, cache_dir="/var/cache/libdnf5")
    dlg = ApplyDialog(preview, {"op": "transaction", "group_install": ["fonts"]})
    assert not dlg.ok.isEnabled() and not dlg.space.isHidden()
    assert "5.0 GB more is needed" in dlg.space.text() and "Download packages only" in dlg.space.text()
    dlg.download_only.setChecked(True)  # 3 GB fit in 5
    assert dlg.ok.isEnabled() and dlg.space.isHidden()
    dlg.download_only.setChecked(False)
    assert not dlg.ok.isEnabled()

    cached = TransactionPreview([item], [], 3 * GB, 4 * GB, to_download=0, cache_dir="/var/cache/libdnf5")
    assert ApplyDialog(cached, {"op": "transaction"}).ok.isEnabled()  # downloaded already: 4 GB fit
