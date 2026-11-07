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
