"""Which Fedora runs here, what Bodhi says, and the dialog about it. No network."""
import json
import os

import pytest

from kram.core import distro
from kram.core.copr import parse_chroots
from kram.core.distro import FedoraRelease, UpgradeProgram


def bodhi(*items):
    return {"releases": [dict(zip(("name", "version", "state", "id_prefix", "eol"), i, strict=True)) for i in items]}


PAYLOAD = bodhi(("ELN", "eln", "pending", "FEDORA", None),
                ("EPEL-10.4", "10.4", "current", "FEDORA-EPEL", None),
                ("F43", "43", "current", "FEDORA", "2026-12-02"),
                ("F43C", "43", "current", "FEDORA-CONTAINER", "2026-12-02"),
                ("F44", "44", "current", "FEDORA", "2027-06-02"),
                ("F45", "45", "current", "FEDORA", "2027-12-08"),
                ("F45F", "45", "current", "FEDORA-FLATPAK", "2027-11-24"),
                ("F46", "46", "pending", "FEDORA", "2028-05-24"))


def test_parse_releases_keeps_shipped_fedora_only():
    assert distro.parse_releases(PAYLOAD) == [FedoraRelease(43, "2026-12-02"), FedoraRelease(44, "2027-06-02"),
                                              FedoraRelease(45, "2027-12-08")]


@pytest.mark.parametrize("payload", [None, [], "x", {}, {"releases": "x"}, {"releases": [1, {"state": "current"}]}])
def test_parse_releases_survives_nonsense(payload):
    assert distro.parse_releases(payload) == []


@pytest.mark.parametrize(("running", "expected"), [(45, None), (44, 45), (43, 45), (42, 44), (41, 43), (40, None)])
def test_choose_target_is_at_most_two_releases_ahead(running, expected):
    target = distro.choose_target(running, distro.parse_releases(PAYLOAD))
    assert (target.version if target else None) == expected


@pytest.mark.parametrize(("text", "expected"), [
    ('ID=fedora\nVERSION_ID=44\nVARIANT_ID=kde\nREDHAT_SUPPORT_PRODUCT_VERSION=44\n', 44),
    ('ID="fedora"\nVERSION_ID="44"\n', 44),
    ('ID=fedora\nVERSION_ID=46\nREDHAT_SUPPORT_PRODUCT_VERSION=rawhide\n', None),
    ('ID=fedora\nVERSION_ID=eln\nVARIANT_ID=eln\n', None),
    ('ID=fedora\nVERSION_ID=11\nVARIANT_ID=eln\n', None),
    ('ID=nobara\nVERSION_ID=44\nID_LIKE=fedora\n', None),
    ('ID=fedora\n', None),
    ('', None),
])
def test_fedora_version(text, expected):
    assert distro.fedora_version(distro.parse_os_release(text)) == expected


DISCOVER = UpgradeProgram("Discover", ("plasma-discover", "--mode", "Update"), "plasmadiscover")
GNOME = UpgradeProgram("GNOME Software", ("gnome-software", "--mode=updates"), "org.gnome.Software")


@pytest.mark.parametrize(("desktop", "installed", "expected"), [
    ("KDE", {"plasma-discover", "gnome-software"}, DISCOVER),
    ("GNOME", {"plasma-discover", "gnome-software"}, GNOME),
    ("ubuntu:GNOME", {"plasma-discover", "gnome-software"}, GNOME),
    ("GNOME", {"plasma-discover"}, DISCOVER),
    ("KDE", {"gnome-software"}, GNOME),
    ("", {"gnome-software"}, GNOME),
    ("KDE", set(), None),
])
def test_upgrade_program(desktop, installed, expected):
    assert distro.upgrade_program(desktop, lambda name: name if name in installed else None) == expected


def test_parse_chroots():
    assert parse_chroots({"chroot_repos": {"fedora-45-x86_64": "url"}}) == {"fedora-45-x86_64"}
    with pytest.raises(ValueError):
        parse_chroots({"error": "no such project"})


class FakeReply:
    def __init__(self, payload=None, failed=False):
        self.body, self.failed = json.dumps(payload).encode(), failed

    def deleteLater(self):
        pass

    def errorString(self):
        return "failed"

    def error(self):
        from PySide6.QtNetwork import QNetworkReply
        return QNetworkReply.TimeoutError if self.failed else QNetworkReply.NoError

    def readAll(self):
        return self.body


@pytest.fixture
def dialog():
    pytest.importorskip("libdnf5")
    pytest.importorskip("PySide6.QtWidgets")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from kram.core.model import CatalogSnapshot
    from kram.ui.upgrade_dialog import UpgradeDialog

    QApplication.instance() or QApplication([])

    class Inline:
        def submit(self, fn, on_done, on_error=None):
            try:
                result = fn()
            except Exception as e:  # noqa: BLE001
                on_error(e)
            else:
                on_done(result)

    return UpgradeDialog(45, 44, "2027-06-02", CatalogSnapshot([], 0, 0, 0.0), Inline())


def titles(dlg):
    return [dlg.tree.topLevelItem(i).text(0) for i in range(dlg.tree.topLevelItemCount())]


def test_dialog_without_copr_projects(dialog):
    assert titles(dialog) == ["No COPR projects are enabled."]
    assert "changes nothing" in dialog.status.text()


def test_dialog_lists_copr_projects_without_a_build(dialog):
    dialog._waiting, dialog._copr_total = 3, 3
    dialog._on_copr(FakeReply({"chroot_repos": {"fedora-45-x86_64": "u"}}), "fedora-45-x86_64", "a/ok")
    dialog._on_copr(FakeReply({"chroot_repos": {"fedora-44-x86_64": "u"}}), "fedora-45-x86_64", "a/old")
    dialog._on_copr(FakeReply(failed=True), "fedora-45-x86_64", "a/down")
    assert titles(dialog) == ["COPR projects without a build for Fedora 45: 1",
                              "COPR projects that could not be checked: 1"]
    assert dialog.copr_item.child(0).text(0) == "a/old"


def test_dialog_shows_the_simulation(dialog, monkeypatch):
    from kram.core.upgrade_audit import AuditResult
    from kram.ui import upgrade_dialog

    asked = []
    result = AuditResult("45", True, blockers=["needs libvpx"], upgrades=10, installs=2, removed=["vbox"],
                         downgrades=["a 2 → 1"], orphaned=["b"], replaced=["c → d"], empty_repos=["gone"],
                         download=2048,
                         needed=4096, free=1)
    monkeypatch.setattr(upgrade_dialog.upgrade_audit, "simulate", lambda v, _cancel, _report: asked.append(v) or result)
    dialog.start_check()
    assert asked == ["45"] and not dialog.running_check and not dialog.check.isHidden()
    wanted = ["Problems that stop the upgrade: 1", "Would be removed: 1",
              "Stay as they are, with no updates from Fedora 45: 1", "Replaced by other packages: 1",
              "Would be downgraded: 1", "Repositories with nothing for Fedora 45: 1"]
    assert titles(dialog) == ["No COPR projects are enabled.", *wanted]
    assert "only if packages are removed" in dialog.status.text() and "Not enough free" in dialog.status.text()
    dialog.start_check()  # a second check replaces the first one's lines
    assert titles(dialog) == ["No COPR projects are enabled.", *wanted]


def test_dialog_reports_a_failed_simulation(dialog, monkeypatch):
    from kram.ui import upgrade_dialog

    def fail(_version, _cancel, _report):
        raise RuntimeError("no network")
    monkeypatch.setattr(upgrade_dialog.upgrade_audit, "simulate", fail)
    dialog.start_check()
    assert dialog.status.text() == "Could not check: no network" and dialog.busy.isHidden()


class Queue:
    """Runs nothing until told to, as the real thread does while a download takes its time."""

    def __init__(self):
        self.jobs = []

    def submit(self, fn, on_done, on_error=None):
        self.jobs.append((fn, on_done, on_error))


@pytest.fixture
def queued():
    pytest.importorskip("libdnf5")
    pytest.importorskip("PySide6.QtWidgets")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from kram.core.model import CatalogSnapshot
    from kram.ui.upgrade_dialog import UpgradeDialog

    QApplication.instance() or QApplication([])
    dnf = Queue()
    dlg = UpgradeDialog(45, 44, "", CatalogSnapshot([], 0, 0, 0.0), dnf)
    dlg.show()
    return dlg, dnf


def test_the_dialog_stays_open_during_a_check(queued):
    from kram.core.upgrade_audit import AuditResult

    dlg, dnf = queued
    dlg.start_check()
    dlg.start_check()
    assert len(dnf.jobs) == 1  # not started twice
    assert not dlg.close_button.isEnabled() and dlg.check.isHidden()
    assert dlg.cancel_button.isVisible() and dlg.cancel_button.isEnabled() and dlg.busy.isVisible()
    dlg.reject()  # Esc, and the window's own close button
    assert dlg.isVisible() and dlg.running_check
    dnf.jobs[0][1](AuditResult("45", True))
    assert not dlg.running_check and dlg.close_button.isEnabled() and dlg.cancel_button.isHidden()
    assert dlg.busy.isHidden()
    dlg.reject()
    assert not dlg.isVisible()


def test_cancel_takes_the_place_of_check(queued):
    from PySide6.QtWidgets import QApplication

    dlg, _dnf = queued
    QApplication.processEvents()
    assert dlg.check.isVisible() and dlg.cancel_button.isHidden()
    place = dlg.check.geometry()
    dlg.start_check()
    QApplication.processEvents()
    assert dlg.check.isHidden() and dlg.cancel_button.isVisible()
    # same spot and size; the height of the panel follows the text beside it
    assert (dlg.cancel_button.x(), dlg.cancel_button.size()) == (place.x(), place.size())


def test_cancel_stops_the_check_and_returns_to_the_start(queued):
    from kram.core.upgrade_audit import Cancelled

    dlg, dnf = queued
    intro = dlg.status.text()
    dlg.start_check()
    dlg.cancel_check()
    assert dlg._cancel.is_set() and not dlg.cancel_button.isEnabled() and dlg.status.text() == "Cancelling…"
    assert dlg.running_check  # until the transfers have really stopped
    dnf.jobs[0][2](Cancelled())
    assert dlg.status.text() == intro and not dlg.running_check and dlg.check.isVisible()
    assert dlg.close_button.isEnabled()
    dlg.start_check()  # and it can be started again, not cancelled from the start
    assert not dlg._cancel.is_set()


def test_simulate_raises_cancelled_and_leaves_no_cache(monkeypatch, tmp_path):
    pytest.importorskip("libdnf5")
    import threading

    from kram.core import upgrade_audit

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    cancel = threading.Event()

    def interrupted(_target, cache, event, _report):
        assert os.path.isdir(cache)
        event.set()
        raise RuntimeError("Download aborted")
    monkeypatch.setattr(upgrade_audit, "_simulate", interrupted)
    with pytest.raises(upgrade_audit.Cancelled):
        upgrade_audit.simulate("45", cancel)
    assert not os.path.exists(upgrade_audit.cache_dir())


def test_a_failure_that_is_not_a_cancel_is_reported(monkeypatch, tmp_path):
    pytest.importorskip("libdnf5")
    from kram.core import upgrade_audit

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr(upgrade_audit, "_simulate", lambda *_a: (_ for _ in ()).throw(RuntimeError("no network")))
    with pytest.raises(RuntimeError, match="no network"):
        upgrade_audit.simulate("45")


def test_the_log_follows_the_check(queued):
    from kram.core.upgrade_audit import AuditResult

    dlg, dnf = queued
    assert dlg.log.isHidden()  # nothing to show before the first check
    dlg.start_check()
    assert dlg.log.isVisible() and dlg.log.toPlainText() == ""
    dlg._on_report("downloading", {"name": "Fedora 45"})
    dlg._on_report("downloaded", {"name": "Fedora 45", "size": 2048})
    dlg._on_report("mirror_failure", {"url": "http://m", "error": "timeout"})
    dlg._on_report("resolving", {})
    dnf.jobs[0][1](AuditResult("45", True))
    lines = [line.split("  ", 1)[1] for line in dlg.log.toPlainText().splitlines()]
    assert lines == ["Downloading Fedora 45", "Downloaded Fedora 45 (2.0 kB)", "Mirror unavailable: http://m: timeout",
                     "Working out the upgrade…", "Done."]
    dlg.start_check()  # a new check starts a new log
    assert dlg.log.toPlainText() == ""


def test_every_report_has_a_message():
    pytest.importorskip("libdnf5")
    pytest.importorskip("PySide6.QtWidgets")
    import re
    from pathlib import Path

    from kram.ui.upgrade_dialog import AUDIT_MESSAGES

    source = (Path(__file__).parent.parent / "kram/core/upgrade_audit.py").read_text()
    keys = set(re.findall(r'report\("(\w+)"', source)) | set(re.findall(r'_say\("(\w+)"', source))
    assert keys - {"progress", "still_downloading"} == set(AUDIT_MESSAGES)  # those two are handled on their own


def test_a_failing_report_cannot_escape_into_libdnf5():
    pytest.importorskip("libdnf5")
    import threading

    from kram.core import upgrade_audit

    def broken(_key, _params):
        raise RuntimeError("the dialog is gone")
    downloads = upgrade_audit._Downloads(threading.Event(), broken)
    assert downloads.add_new_download(None, "Fedora", 0) == 1
    assert downloads.end(1, downloads.TransferStatus_SUCCESSFUL, "") == downloads.OK


def test_rows_carry_the_state_marks(dialog, monkeypatch):
    from PySide6.QtGui import QIcon

    from kram.core.upgrade_audit import AuditResult
    from kram.ui import upgrade_dialog as ui

    kinds = []
    monkeypatch.setattr(ui, "_state_icon", lambda kind: kinds.append(kind) or QIcon())
    monkeypatch.setattr(ui.upgrade_audit, "simulate", lambda *_a: AuditResult(
        "45", True, blockers=["b"], removed=["r"], orphaned=["o"], replaced=["p"], downgrades=["d"],
        empty_repos=["e"]))
    dialog.start_check()
    assert kinds == [ui.ERROR, ui.WARN, ui.WARN, ui.INFO, ui.INFO, ui.WARN]
    assert set(ui.ICONS) >= {ui.OK, ui.WARN, ui.ERROR, ui.INFO}


def test_copr_row_mark_follows_the_answer(dialog, monkeypatch):
    from PySide6.QtGui import QIcon

    from kram.ui import upgrade_dialog as ui

    kinds = []
    monkeypatch.setattr(ui, "_state_icon", lambda kind: kinds.append(kind) or QIcon())
    dialog._copr_total = 1
    dialog._show_copr()
    dialog._copr_missing = ["a/b"]
    dialog._show_copr()
    assert kinds == [ui.OK, ui.WARN]


def test_sort_out_tells_replaced_from_staying():
    pytest.importorskip("libdnf5")
    from kram.core.upgrade_audit import sort_out

    without_target = {"libgit2": "libgit2", "claude-desktop": "claude-desktop (@commandline)",
                      "VirtualBox-7.2": "VirtualBox-7.2", "libcollection": "libcollection"}
    replaced, staying = sort_out(without_target, ["VirtualBox-7.2"],
                                 {"libgit2": {"libgit2_1.9"}, "libcollection": {"libini_config"}})
    assert replaced == ["libcollection → libini_config", "libgit2 → libgit2_1.9"]
    assert staying == ["claude-desktop (@commandline)"]  # the removed one is reported as removed, not here too


class Pkg:
    def __init__(self, name, arch="x86_64", repo="updates"):
        self.name, self.arch, self.repo = name, arch, repo

    def get_name(self):
        return self.name

    def get_arch(self):
        return self.arch

    def get_from_repo_id(self):
        return self.repo


def test_without_target_goes_by_name_and_hides_the_running_releases_repo():
    pytest.importorskip("libdnf5")
    from kram.core.upgrade_audit import _without_target

    installed = [Pkg("libreoffice-help-en", "noarch"), Pkg("libgit2"), Pkg("tool", repo="@commandline"),
                 Pkg("gpg-pubkey")]
    available = [Pkg("libreoffice-help-en", "x86_64")]
    assert _without_target(installed, available) == {"libgit2": "libgit2", "tool": "tool (@commandline)"}


def test_the_three_links_sit_at_the_bottom_left(monkeypatch):
    pytest.importorskip("libdnf5")
    pytest.importorskip("PySide6.QtWidgets")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QApplication

    from kram.core.model import CatalogSnapshot
    from kram.ui import upgrade_dialog as ui

    QApplication.instance() or QApplication([])
    monkeypatch.setattr(ui.distro, "upgrade_program", lambda _desktop: DISCOVER)
    opened = []
    monkeypatch.setattr(ui.QDesktopServices, "openUrl", lambda url: opened.append(url.toString()))
    dlg = ui.UpgradeDialog(45, 44, "", CatalogSnapshot([], 0, 0, 0.0), Queue())
    dlg.resize(760, 600)
    dlg.show()
    QApplication.processEvents()
    row = [dlg.notes_button, dlg.guide_button, dlg.open_program, dlg.close_button]
    xs = [b.mapTo(dlg, QPoint(0, 0)).x() for b in row]  # Close lives inside its button box
    assert xs == sorted(xs)
    assert len({b.y() for b in (dlg.notes_button, dlg.guide_button, dlg.open_program)}) == 1
    assert dlg.check.y() < dlg.tree.y() < dlg.notes_button.y()
    assert dlg.check.x() + dlg.check.width() <= dlg.status.x()  # what Check does, right beside it
    assert dlg.check.geometry().center().y() == dlg.status.geometry().center().y()
    assert dlg.open_program.text() == "Open Discover"
    dlg.notes_button.click()
    dlg.guide_button.click()
    assert opened == [ui.distro.RELEASE_NOTES_URL.format(version=45), ui.distro.UPGRADE_GUIDE_URL]
    monkeypatch.setattr(ui.distro, "upgrade_program", lambda _desktop: None)
    assert ui.UpgradeDialog(45, 44, "", CatalogSnapshot([], 0, 0, 0.0), Queue()).open_program is None


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def downloads(monkeypatch):
    pytest.importorskip("libdnf5")
    import threading

    from kram.core import upgrade_audit

    clock = Clock()
    monkeypatch.setattr(upgrade_audit.time, "monotonic", clock)
    said = []
    return upgrade_audit._Downloads(threading.Event(), lambda key, params: said.append((key, params))), clock, said


def test_a_quiet_log_says_what_is_still_being_waited_for(downloads):
    d, clock, said = downloads
    handle = d.add_new_download(None, "Fedora 45", 0)
    d.progress(handle, 39, 12)
    clock.now += 4
    d.progress(handle, 39, 12)
    assert not [s for s in said if s[0] == "still_downloading"]
    clock.now += 1.5
    d.progress(handle, 39, 12)  # a stalled server: the same numbers, and the line still comes
    assert said[-1] == ("still_downloading", {"items": [("Fedora 45", 12, 39)]})
    d.progress(handle, 39, 12)
    assert len([s for s in said if s[0] == "still_downloading"]) == 1  # and not with every call
    d.end(handle, d.TransferStatus_SUCCESSFUL, "")
    clock.now += 60
    d.progress(handle, 39, 39)
    assert len([s for s in said if s[0] == "still_downloading"]) == 1  # nothing is left to wait for


def test_it_names_the_largest_downloads_only(downloads):
    d, clock, said = downloads
    for i, size in enumerate((1, 50, 9, 30), 1):
        assert d.add_new_download(None, f"r{i}", 0) == i
        d.progress(i, size, 0)
    clock.now += 6
    d.progress(1, 1, 0)
    assert [item[0] for item in said[-1][1]["items"]] == ["r2", "r4", "r3"]


def test_progress_sums_every_transfer_and_is_throttled(downloads):
    d, clock, said = downloads
    d.add_new_download(None, "a", 0)
    d.add_new_download(None, "b", 0)
    d.progress(1, 100, 40)
    d.progress(2, 100, 10)
    clock.now += 0.3
    d.progress(2, 100, 20)
    assert [p for k, p in said if k == "progress"] == [{"done": 40, "total": 100}, {"done": 60, "total": 200}]


def test_dialog_shows_progress_and_still_downloading(queued):
    dlg, _dnf = queued
    dlg.start_check()
    assert dlg.busy.maximum() == 0
    dlg._on_report("progress", {"done": 5, "total": 10})
    assert dlg.busy.maximum() == 1000 and dlg.busy.value() == 500
    dlg._on_report("progress", {"done": 10, "total": 10})
    assert dlg.busy.maximum() == 0  # all known bytes are in, the rest is still to come
    dlg._on_report("still_downloading", {"items": [("Fedora 45", 1024, 2048), ("Slow", 0, 0)]})
    assert dlg.log.toPlainText().split("  ", 1)[1] == "Still downloading: Fedora 45: 1.0 kB of 2.0 kB; Slow"


def test_removed_packages_say_what_they_need(dialog):
    from kram.core.upgrade_audit import AuditResult

    needs = {"simpleaudio": ["python(abi) = 3.14"], "vbox": ["a", "b", "c", "d"]}
    result = AuditResult("45", True, removed=["simpleaudio", "vbox", "plain"], removal_needs=needs)
    assert dialog._removal_line("simpleaudio", result) == "simpleaudio — needs python(abi) = 3.14"
    assert dialog._removal_line("vbox", result) == "vbox — needs a, b, c, …"
    assert dialog._removal_line("plain", result) == "plain"  # removed for another reason: nothing to claim
