"""Removing a group or an environment: packages that were there before it are flagged in the review, the running
desktop is warned about, and a hidden group cannot be removed on its own."""
from types import SimpleNamespace as NS

import pytest

from kram.core.model import PreviewGroup, PreviewItem, TransactionPreview

libdnf5 = pytest.importorskip("libdnf5")
T = libdnf5.transaction


def pkg(name, installed_at):
    return NS(get_name=lambda: name, get_arch=lambda: "x86_64", get_install_time=lambda: installed_at)


def comps(cid, name, packages=(), groups=()):
    return NS(get_groupid=lambda: cid, get_environmentid=lambda: cid, get_name=lambda: name,
              get_translated_name=lambda _lang: "", get_packages=lambda: [NS(get_name=lambda n=n: n) for n in packages],
              get_groups=lambda: list(groups), get_default_groups=list)


def removed(x, attr):
    return NS(get_action=lambda: T.TransactionItemAction_REMOVE, **{attr: lambda: x})


def item(name):
    return PreviewItem("remove", name, "x86_64", "1-1", "", "@System", 0, 1, "group")


def test_a_package_older_than_the_removed_group_is_flagged(monkeypatch):
    from kram.core import catalog as catalog_module
    from kram.core.catalog import Catalog

    # bolt came with the system (time 100); the environment and its group were installed at 500
    group = comps("sway-desktop", "Sway", packages=("bolt", "sway"))
    env = comps("sway-desktop-environment", "Sway Desktop", groups=("sway-desktop",))
    tr = NS(get_transaction_groups=lambda: [removed(group, "get_group")],
            get_transaction_environments=lambda: [removed(env, "get_environment")],
            get_transaction_packages=lambda: [
                NS(get_action=lambda: T.TransactionItemAction_REMOVE, get_package=lambda: pkg("bolt", 100)),
                NS(get_action=lambda: T.TransactionItemAction_REMOVE, get_package=lambda: pkg("sway", 600))])
    monkeypatch.setattr(catalog_module, "comps_install_times",
                        lambda _base: {"sway-desktop": 500, "env:sway-desktop-environment": 500})
    monkeypatch.setattr(catalog_module, "language", lambda: "")
    items = [item("bolt"), item("sway"), item("unrelated")]
    Catalog._mark_older_than_groups(NS(_base=None), tr, items)
    assert [(i.name, i.before) for i in items] == [("bolt", "Sway Desktop"), ("sway", ""), ("unrelated", "")]


def test_the_review_warns_about_older_packages_and_the_running_desktop():
    from kram.ui.apply_dialog import removal_warning

    older = PreviewItem("remove", "bolt", "x86_64", "1-1", "", "@System", 0, 1, "group", before="Sway Desktop")
    plasma = PreviewItem("remove", "plasma-workspace", "x86_64", "6-1", "", "@System", 0, 1, "group")
    preview = TransactionPreview([older, plasma], [], 0, -2, groups=[PreviewGroup("remove", "x", "X")])
    text = removal_warning(preview, ("KDE", frozenset({"plasma-workspace"})))
    assert "desktop you are using now (KDE: plasma-workspace)" in text
    assert "1 package was installed before the group that takes it" in text and "bolt" in text
    assert "desktop you are using" not in removal_warning(preview, ("GNOME", frozenset({"gnome-shell"})))


def test_session_packages_from_the_session_file_and_the_desktop(tmp_path, monkeypatch):
    from kram.core import session

    sessions = tmp_path / "wayland-sessions"
    sessions.mkdir()
    (sessions / "plasma.desktop").write_text("[Desktop Entry]\n")
    monkeypatch.setattr(session, "SESSION_DIRS", (str(sessions),))
    monkeypatch.setattr(session, "file_owners", lambda paths: {"plasma-workspace"} if paths else set())
    assert session.session_packages({"DESKTOP_SESSION": str(sessions / "plasma"), "XDG_CURRENT_DESKTOP": "KDE"}) == (
        "KDE", {"plasma-workspace"})
    assert session.session_packages({"DESKTOP_SESSION": "sway", "XDG_CURRENT_DESKTOP": "sway"}) == ("sway", {"sway"})
    assert session.session_packages({}) == ("", set())


def test_a_hidden_group_has_no_removal(monkeypatch):
    pytest.importorskip("PySide6.QtWidgets")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMenu
    QApplication.instance() or QApplication([])

    from kram.core.model import GroupInfo
    from kram.ui.marking import Marker

    core = GroupInfo("core", "Core", "", True, frozenset(), upgradable=True, visible=False)
    tools = GroupInfo("tools", "Tools", "", True, frozenset(), upgradable=True)
    texts = []
    for g in (core, tools):
        menu = QMenu()
        Marker.fill_group_menu(NS(), menu, g, busy=False, run=lambda *a: None)
        texts.append([a.text() for a in menu.actions()])
    assert texts == [["Upgrade Group…"], ["Upgrade Group…", "Remove Group…"]]
