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


DISCOVER = UpgradeProgram("Discover", ("plasma-discover", "--mode", "Update"))
GNOME = UpgradeProgram("GNOME Software", ("gnome-software", "--mode=updates"))


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
                         downgrades=["a 2 → 1"], orphaned=["b"], empty_repos=["gone"], download=2048, needed=4096,
                         free=1)
    monkeypatch.setattr(upgrade_dialog.upgrade_audit, "simulate", lambda v, _cancel: asked.append(v) or result)
    dialog.start_check()
    assert asked == ["45"] and not dialog.running_check and dialog.check.isEnabled()
    wanted = ["Problems that stop the upgrade: 1", "Would be removed: 1", "Installed, with no version in Fedora 45: 1",
              "Would be downgraded: 1", "Repositories with nothing for Fedora 45: 1"]
    assert titles(dialog) == ["No COPR projects are enabled.", *wanted]
    assert "only if packages are removed" in dialog.status.text() and "Not enough free" in dialog.status.text()
    dialog.start_check()  # a second check replaces the first one's lines
    assert titles(dialog) == ["No COPR projects are enabled.", *wanted]


def test_dialog_reports_a_failed_simulation(dialog, monkeypatch):
    from kram.ui import upgrade_dialog

    def fail(_version, _cancel):
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
    assert not dlg.close_button.isEnabled() and not dlg.check.isEnabled()
    assert dlg.cancel_button.isVisible() and dlg.cancel_button.isEnabled() and dlg.busy.isVisible()
    dlg.reject()  # Esc, and the window's own close button
    assert dlg.isVisible() and dlg.running_check
    dnf.jobs[0][1](AuditResult("45", True))
    assert not dlg.running_check and dlg.close_button.isEnabled() and dlg.cancel_button.isHidden()
    assert dlg.busy.isHidden()
    dlg.reject()
    assert not dlg.isVisible()


def test_cancel_stops_the_check_and_returns_to_the_start(queued):
    from kram.core.upgrade_audit import Cancelled

    dlg, dnf = queued
    intro = dlg.status.text()
    dlg.start_check()
    dlg.cancel_check()
    assert dlg._cancel.is_set() and not dlg.cancel_button.isEnabled() and dlg.status.text() == "Cancelling…"
    assert dlg.running_check  # until the transfers have really stopped
    dnf.jobs[0][2](Cancelled())
    assert dlg.status.text() == intro and not dlg.running_check and dlg.check.isEnabled()
    assert dlg.close_button.isEnabled()
    dlg.start_check()  # and it can be started again, not cancelled from the start
    assert not dlg._cancel.is_set()


def test_simulate_raises_cancelled_and_leaves_no_cache(monkeypatch, tmp_path):
    pytest.importorskip("libdnf5")
    import threading

    from kram.core import upgrade_audit

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    cancel = threading.Event()

    def interrupted(_target, cache, event):
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
