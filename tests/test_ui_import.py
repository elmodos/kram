"""Every UI module imports and the painted icons render, without a display (also run by the RPM's %check)."""
import importlib
import os
import pkgutil

import pytest

pytest.importorskip("PySide6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication

import kram.ui


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_ui_modules_import():
    for mod in pkgutil.iter_modules(kram.ui.__path__):
        importlib.import_module(f"kram.ui.{mod.name}")


def test_icons_render(app):
    from kram.core.marks import Action
    from kram.core.model import Origin, Status
    from kram.ui.icons import mark_icon, origin_icon, status_icon

    icons = [*map(status_icon, Status), *map(origin_icon, Origin), *map(mark_icon, Action)]
    for icon in icons:
        for scale in (1.0, 1.25, 2.0):
            pm = icon.pixmap(QSize(16, 16), scale)
            assert pm.width() == round(16 * scale)
            assert not pm.toImage().isNull()


def test_sidebar_history_removal(app):
    from kram.core.model import CatalogSnapshot
    from kram.ui.sidebar import Sidebar

    sb = Sidebar()
    sb.set_snapshot(CatalogSnapshot(rows=[], n_installed=0, n_upgradable=0, load_seconds=0))
    sb.history = [("fish", 0, 3), ("vim", 0, 5), ("vim", 1, 7)]
    sb.select("search", "search:0:vim")
    emitted = []
    sb.filterChanged.connect(emitted.append)

    sb.remove_search("fish", 0)  # not selected: the list keeps its selection and does not re-filter
    assert sb.history == [("vim", 0, 5), ("vim", 1, 7)]
    assert sb.current_entry_id == "search:0:vim" and not emitted

    sb.remove_search("vim", 0)  # the selected one: the next search takes over
    assert sb.current_entry_id == "search:1:vim"
    assert [e.query for e in emitted] == [("vim", 1)]

    sb.clear_history()
    assert sb.history == [] and sb.current_entry_id is None
    assert emitted[-1].id == "empty"


def test_apply_dialog_unchecks_a_recommendation(app):
    from PySide6.QtCore import Qt

    from kram.core.model import PreviewItem, Recommendation, TransactionPreview
    from kram.ui.apply_dialog import ApplyDialog

    def preview(excluded):
        items = [PreviewItem("install", "virt-manager", "noarch", "5.1-1", "", "fedora", 700, 2000, "user")]
        recs = [Recommendation("(kvm or qemu)", ["virt-manager"], True, [] if excluded else ["kvm"], ["kvm", "qemu"],
                               size=None if excluded else 9000, count=3, exact=True),
                Recommendation("langpack", [], False, ["langpack"], ["langpack"], size=10, count=1)]
        if not excluded:
            items.append(PreviewItem("install", "kvm", "x86_64", "1-1", "", "fedora", 50, 9000, "weak"))
        return TransactionPreview(items, [], 100, 11000 - 9000 * excluded, recs)

    asked = []
    dlg = ApplyDialog(preview(False), {"op": "transaction", "install": ["virt-manager.noarch"]},
                      resolve=lambda req, done, failed: (asked.append(req), done(preview(True))))
    assert dlg.recs.topLevelItemCount() == 2  # the direct one, then "Recommended by dependencies"
    item = dlg.recs.topLevelItem(0)
    assert item.text(0) == "kvm" and item.text(2) == "+8.8 kB, 3 packages"
    item.setCheckState(0, Qt.Unchecked)
    assert asked[-1]["exclude_weak"] == ["kvm", "qemu"]
    assert dlg.request["exclude_weak"] == ["kvm", "qemu"]
    item = dlg.recs.topLevelItem(0)
    assert item.checkState(0) == Qt.Unchecked and item.text(0) == "kvm or qemu"
    assert "exclude_from_weak=kvm,qemu" in dlg.cmd.toPlainText()
    item.setCheckState(0, Qt.Checked)
    assert "exclude_weak" not in asked[-1]

    # the equivalent command follows the checkbox, and survives a new resolve
    assert "--downloadonly" not in dlg.cmd.toPlainText()
    dlg.download_only.setChecked(True)
    assert "--downloadonly" in dlg.cmd.toPlainText()
    dlg.recs.topLevelItem(0).setCheckState(0, Qt.Unchecked)
    assert "--downloadonly" in dlg.cmd.toPlainText()
    assert "download_only" not in asked[-1]  # the preview still resolves the whole transaction
    dlg.download_only.setChecked(False)
    assert "--downloadonly" not in dlg.cmd.toPlainText()


def test_install_dialog(app, monkeypatch):
    import time

    from PySide6.QtCore import Qt

    from kram.core import local_rpm
    from kram.core.local_rpm import LocalRpm, Signature
    from kram.core.model import LocalTarget, PreviewItem, Recommendation, Requirement, TransactionPreview
    from kram.ui import install_dialog

    rpm = LocalRpm("/tmp/tool-2.0-1.x86_64.rpm", "ab" * 32, 1000, "tool", None, "2.0", "1", "x86_64", "A tool",
                   "Does things.", "", "MIT", "", "", 0, 5000, False, ["bash"], ["helper"], [], [], ["tool"], [], [],
                   ["/usr/bin/tool"], [], "", Signature("nokey", "dbfcf71c6d9f90a6"))
    monkeypatch.setattr(local_rpm, "read", lambda path: rpm)

    def preview(excluded):
        items = [PreviewItem("upgrade", "tool", "x86_64", "2.0-1", "1.0-1", "@commandline", 1000, 5000, "user")]
        rec = Recommendation("helper", ["tool"], True, [] if excluded else ["helper"], ["helper"], size=10, count=1)
        if not excluded:
            items.append(PreviewItem("install", "helper", "x86_64", "1-1", "", "fedora", 50, 10, "weak"))
        return TransactionPreview(items, [], 50, 4000, [rec])

    calls = []

    class Catalog:
        def open_local(self, path):
            calls.append(("open", path))
            return LocalTarget("upgrade", "1.0-1", "", "", {
                "requires": [Requirement("bash", ["bash"], ["bash"]), Requirement("libgone.so.1", [], [])],
                "recommends": [Requirement("helper", [], ["helper"])], "suggests": []})

        def resolve_local(self, path, action, exclude, sizes=True):
            calls.append(("resolve", action, exclude))
            return preview(bool(exclude))

        def forget_local(self):
            calls.append(("forget",))

    class Dnf:  # runs everything at once, like the dnf thread would, only synchronously
        def submit(self, fn, done, failed=None):
            done(fn())

    class Helper:
        busy = False

    requests = []

    class Progress:
        def __init__(self, helper, request, title, parent):
            requests.append(request)
            self.ok = True

        def exec(self):
            return 0
    monkeypatch.setattr(install_dialog, "ProgressDialog", Progress)

    dlg = install_dialog.InstallDialog(rpm.path, Catalog(), Dnf(), Helper(), marks=3)
    deadline = time.monotonic() + 10
    while dlg.rpm is None and time.monotonic() < deadline:  # the file is read on a thread of its own
        app.processEvents()
    assert dlg.install.text() == "Upgrade" and dlg.install.isEnabled()
    notes = dlg.notes_text()
    assert "1.0-1 to 2.0-1" in notes and "dbfcf71c6d9f90a6" in notes and "3 changes marked" in notes
    assert "Also changes 1 more package" in dlg.sizes.text()
    deps = dlg.deps.toPlainText()
    assert "bash — installed: bash" in deps and "libgone.so.1 — unavailable" in deps
    assert "helper — will be installed: helper" in deps

    dlg.recs.tree.topLevelItem(0).setCheckState(0, Qt.Unchecked)
    assert calls[-1] == ("resolve", "install", ["helper"])
    assert "helper — not installed" in dlg.deps.toPlainText()  # unchecked: no longer part of the transaction
    assert dlg.cmd.text() == "sudo dnf5 install --setopt=exclude_from_weak=helper /tmp/tool-2.0-1.x86_64.rpm"
    dlg.install.click()
    assert requests == [{"op": "local_install", "path": rpm.path, "sha256": rpm.sha256, "action": "install",
                         "exclude_weak": ["helper"]}]
    assert dlg.result() == install_dialog.QDialog.Accepted and dlg.changed_system and calls[-1] == ("forget",)


def test_progress_counts_packages_not_rpm_steps(app):
    """A reinstall is two rpm steps (install the copy, erase the old one): one package, and no "Removing"."""
    from PySide6.QtCore import QObject, Signal

    from kram.ui.progress_dialog import ProgressDialog

    class Client(QObject):
        event = Signal(dict)
        failed = Signal(str)

    client = Client()
    dlg = ProgressDialog(client, {"op": "local_install"}, "Installing tool")
    nevra = "tool-1.0-1.x86_64"
    for ev in [{"event": "resolved", "items": [{"action": "Reinstall", "nevra": nevra},
                                               {"action": "Replaced", "nevra": nevra}]},
               {"event": "rpm", "step": "element", "index": 0, "count": 2, "nevra": nevra},
               {"event": "rpm", "step": "install", "nevra": nevra, "done": 0, "total": 10},
               {"event": "rpm", "step": "element", "index": 1, "count": 2, "nevra": nevra},
               {"event": "rpm", "step": "remove", "nevra": nevra, "done": 0, "total": 10}]:
        client.event.emit(ev)
    log = dlg.log.toPlainText()
    assert "reinstall  tool-1.0-1" in log and "old copy  tool-1.0-1" in log and "Replaced" not in log
    assert "Installing tool-1.0-1.x86_64" in log and "Cleaning up the old copy of tool-1.0-1.x86_64" in log
    assert "Removing" not in log
    assert dlg.rpm_label.text() == "Package 1 of 1"
    client.event.emit({"event": "done", "ok": True})
    assert dlg.rpm_bar.value() == dlg.rpm_bar.maximum()


def test_whats_new_dialog(app):
    import kram
    from kram.core.releases import Release
    from kram.ui.whats_new import WhatsNewDialog

    dlg = WhatsNewDialog([Release(kram.__version__, "2026-11-10", ["Intro."], ["One", "Two"]),
                          Release("0.0.1", "2026-01-01", [], ["First"])])
    text = dlg.text.toPlainText()
    assert f"{kram.__version__} — 2026-11-10 (this version)" in text and "Two" in text and "0.0.1" in text
    empty = WhatsNewDialog([])
    assert "not available" in empty.text.toPlainText()
