"""The main window's actions and menus as data (kram.app.actions, kram.app.preferences), and the Qt menus built from
them: the same menus as before the data existed, and every setting of the registry in its toolkit's menu."""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from kram.app import preferences
from kram.app.actions import (
    MARK_ACTIONS,
    action_defs,
    action_state,
    downgrade_items,
    mark_id,
    menu_bar,
    walk,
)
from kram.app.parity import Feature  # noqa: E402  (the feature marks of the parity tests)
from kram.core.marks import Action, MarkSet
from kram.core.model import Origin, PkgRow, Status

ROWS = {
    "new": PkgRow("new", "x86_64", "", "", "1-1", "fedora", 1, Origin.FEDORA, Status.NOT_INSTALLED, False),
    "old": PkgRow("old", "x86_64", "", "1-1", "1-2", "fedora", 1, Origin.FEDORA, Status.UPGRADABLE, True),
    "same": PkgRow("same", "x86_64", "", "1-1", "1-1", "fedora", 1, Origin.FEDORA, Status.INSTALLED, True),
}


def state(rows=(), *, catalog=True, n_upgradable=0, marks=None, blocked=None, busy=False, kinds=None, unneeded=False,
          can_open_file=True):
    return action_state(list(rows), catalog=catalog, n_upgradable=n_upgradable, marks=marks or MarkSet(),
                        blocked=blocked or {}, busy=busy, upgrades_of_kind=kinds or {}, unneeded=unneeded,
                        can_open_file=can_open_file)


def test_every_action_has_a_unique_id_and_every_menu_entry_exists():
    ids = [d.id for d in action_defs()]
    assert len(ids) == len(set(ids))
    used = {item.action for menu in menu_bar() for item in walk(menu.items) if item.action}
    assert used <= set(ids)


@pytest.mark.feature(Feature.MARK_INSTALL_REMOVE, front="qt")
def test_marks_follow_the_selection_and_stop_while_busy():
    enabled = state([ROWS["new"]]).enabled
    assert enabled[mark_id(Action.INSTALL)] and not enabled[mark_id(Action.REMOVE)]
    enabled = state([ROWS["new"]], busy=True).enabled
    assert not any(enabled[mark_id(a)] for a in MARK_ACTIONS)


def test_downgrade_needs_one_installed_package():
    assert state([ROWS["old"]]).enabled["downgrade"]
    assert not state([ROWS["new"]]).enabled["downgrade"]
    assert not state([ROWS["old"], ROWS["same"]]).enabled["downgrade"]
    assert not state([ROWS["old"]], busy=True).enabled["downgrade"]


@pytest.mark.feature(Feature.MARK_UNMARK_ALL, front="qt")
def test_unmark_apply_and_save_need_marks():
    marks = MarkSet()
    marks.set(ROWS["new"], Action.INSTALL)
    on = state([ROWS["new"]], marks=marks).enabled
    assert on["unmark"] and on["apply"] and on["unmark_all"] and on["save_marks"]
    assert not state([ROWS["old"]], marks=marks).enabled["unmark"]  # the selection is not marked
    busy = state([ROWS["new"]], marks=marks, busy=True).enabled
    assert not busy["apply"] and not busy["unmark"] and busy["unmark_all"]
    off = state([ROWS["new"]]).enabled
    assert not off["apply"] and not off["unmark_all"] and not off["save_marks"]


def test_lock_and_unlock():
    locked = PkgRow("lk", "x86_64", "", "1-1", "1-1", "fedora", 1, Origin.FEDORA, Status.INSTALLED, True,
                    locks=(SimpleNamespace(conditions="evr = 1-1"),))
    assert state([ROWS["same"]]).enabled["lock"] and not state([ROWS["same"]]).enabled["unlock"]
    assert state([locked]).enabled["unlock"] and not state([locked]).enabled["lock"]
    assert not state([ROWS["new"]]).enabled["lock"]
    assert not state([locked], busy=True).enabled["unlock"]


def test_catalog_actions_wait_for_the_catalog():
    names = ("read_marks", "export_csv", "history", "repos", "copr", "cache", "filters", "new_filter", "upgrade")
    assert all(state().enabled[n] for n in names)
    assert not any(state(catalog=False).enabled[n] for n in names)
    assert state([ROWS["same"]]).enabled["show_in_history"]
    assert not state([ROWS["same"], ROWS["old"]]).enabled["show_in_history"]


def test_upgrades_and_unneeded():
    assert not state().enabled["mark_upgrades"] and state(n_upgradable=2).enabled["mark_upgrades"]
    assert not state(catalog=False, n_upgradable=2).enabled["mark_upgrades_menu"]
    kinds = state(kinds={"security": True, "fixes": False}).enabled
    assert kinds["mark_upgrades.security"] and not kinds["mark_upgrades.fixes"]
    assert not kinds["mark_upgrades.security_high"]
    assert state(unneeded=True).enabled["mark_unneeded"] and not state().enabled["mark_unneeded"]
    assert not state(can_open_file=False).enabled["open_file"]


def test_why_blocked_shows_only_for_one_blocked_row():
    blocked = {ROWS["old"].key: "reason"}
    assert state([ROWS["old"]], blocked=blocked).visible["why_blocked"]
    assert not state([ROWS["same"]], blocked=blocked).visible["why_blocked"]
    assert not state([ROWS["old"], ROWS["same"]], blocked=blocked).visible["why_blocked"]


@pytest.mark.feature(Feature.MENU_DOWNGRADE_SUBMENU, front="qt")
def test_downgrade_items():
    version = lambda evr, installed=False: SimpleNamespace(evr=evr, installed=installed, locked_out=False,  # noqa: E731
                                                           repo_id="fedora")
    chosen = []
    assert downgrade_items(ROWS["old"], None, chosen.append)[0].label == "(loading…)"
    details = SimpleNamespace(versions=[version("1-2"), version("1-1", True), version("0.9-1")])
    items = downgrade_items(ROWS["old"], details, chosen.append)
    assert [i.label for i in items] == ["0.9-1  (fedora)"]
    items[0].run()
    assert chosen == ["0.9-1"]
    assert not downgrade_items(ROWS["old"], SimpleNamespace(versions=[]), chosen.append)[0].enabled
    # a package that is not installed: GTK builds the submenu with every context menu, and an empty EVR broke it
    assert not downgrade_items(ROWS["new"], details, chosen.append)[0].enabled


def test_preferences_round_trip_and_announce_changes():
    seen = []
    preferences.changed.connect(seen.append)
    try:
        assert preferences.value(preferences.STATUS_CLICK) is False
        preferences.set_value(preferences.STATUS_CLICK, True)
        assert preferences.value(preferences.STATUS_CLICK) is True and seen == [preferences.STATUS_CLICK]
        preferences.set_value(preferences.TOOLBAR_STYLE, "nonsense")
        assert preferences.value(preferences.TOOLBAR_STYLE) == "system"  # not one of the choices
        preferences.set_value(preferences.STALE_DAYS, 1000)
        assert preferences.value(preferences.STALE_DAYS) == 365
    finally:
        preferences.changed.disconnect(seen.append)


@pytest.mark.feature(Feature.SETTINGS_REGISTRY, front="qt")
@pytest.mark.feature(Feature.SETTINGS_TOOLBAR_STYLE, front="qt")
def test_each_toolkit_has_its_own_settings():
    qt = {p.key for p in preferences.prefs_for("qt")}
    gtk = {p.key for p in preferences.prefs_for("gtk")}
    assert preferences.TOOLBAR_STYLE in qt - gtk and preferences.MENU_BAR in gtk - qt
    assert {preferences.STATUS_CLICK, preferences.WATCH_RELEASES} <= qt & gtk


# ---------------------------------------------------------------- the Qt menus

def dump_menu(menu) -> list:
    out = []
    for a in menu.actions():
        if a.isSeparator():
            out.append("-")
            continue
        entry = [a.text(), [s.toString() for s in a.shortcuts()], a.isCheckable(), a.isEnabled(), a.isVisible(),
                 a.toolTip() if a.toolTip() != a.text().replace("&", "") else ""]
        if a.menu():
            entry.append(dump_menu(a.menu()))
        out.append(entry)
    return out


@pytest.fixture
def window():
    pytest.importorskip("libdnf5")
    pytest.importorskip("PySide6.QtWidgets")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from kram.core import distro
    from kram.qt import main_window
    if distro.running_release() is None:
        pytest.skip("the recorded menus are those of a Fedora system")
    original = main_window.MainWindow.reload
    main_window.MainWindow.reload = lambda self: None
    try:
        win = main_window.MainWindow()
    finally:
        main_window.MainWindow.reload = original
    yield win
    win.dnf.shutdown()


def test_the_qt_menus_are_those_of_0_11_3(window):
    """Recorded from the window of 0.11.3, before the menus were data: menu bar, context menu, the shortcuts of
    the table and of the window."""
    from PySide6.QtGui import QKeySequence
    from PySide6.QtWidgets import QMenu

    from kram.qt.actions import STANDARD_KEYS
    recorded = [json.loads(line) for line in
                (Path(__file__).with_name("data") / "qt_menus_0.11.3.json").read_text().splitlines()]
    # Find and Quit take the platform's keys, which change with the Qt version (Qt 6.10, Fedora 43, gives Quit the
    # Exit key, later ones nothing offscreen): expect what this Qt gives, as 0.11.3 did
    platform = {d.label: [k for k in [QKeySequence(STANDARD_KEYS[d.id]).toString()] if k]
                for d in action_defs() if d.id in STANDARD_KEYS}

    def with_platform_keys(entries):
        for entry in entries:
            if isinstance(entry, list):
                if entry[0] in platform:
                    entry[1] = platform[entry[0]]
                if len(entry) > 6:
                    with_platform_keys(entry[6])
        return entries
    for i, part in enumerate(recorded):
        recorded[i] = with_platform_keys(part)
    assert dump_menu(window.menuBar()) == recorded[0]
    context = QMenu()
    window.acts.fill_package_menu(context)
    context.addSeparator()
    context.addActions([window.acts.copy_name, window.acts.copy_nevra])
    assert dump_menu(context) == recorded[1]
    assert [[a.text(), [s.toString() for s in a.shortcuts()]] for a in window.table.actions()] == recorded[2]
    assert [[a.text(), [s.toString() for s in a.shortcuts()]] for a in window.actions()] == recorded[3]


@pytest.mark.feature(Feature.MENU_BAR, front="qt")
def test_the_qt_menu_bar_is_the_data(window):
    from kram.qt.actions import TOOLKIT
    defs = {d.id: d for d in action_defs()}
    bar = window.menuBar().actions()
    assert [a.text() for a in bar] == [m.title for m in menu_bar()]
    for qmenu, menu in zip((a.menu() for a in bar), menu_bar(), strict=True):
        texts = [a.text() for a in qmenu.actions() if not a.isSeparator()]
        expected = []
        for item in menu.items:
            if item.action:
                expected.append(defs[item.action].label)
            elif item.submenu:
                expected.append(item.submenu.title)
            elif item.prefs:
                expected += [p.label for p in preferences.prefs_for(TOOLKIT, item.prefs)]
        assert texts == expected
    settings = next(a.menu() for a in bar if a.text() == "&Settings")
    labels = {a.text() for a in settings.actions()}
    for pref in preferences.PREFS:
        assert (pref.label in labels) == (TOOLKIT in pref.toolkits and pref.section == "settings"), pref.key
