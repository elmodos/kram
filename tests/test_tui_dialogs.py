"""The terminal front end's dialogs of step 3.4 over a made-up catalog (docs/TUI_SPEC.md §10.10–§10.15, §10.18): Custom
Filters, Update Notifications, Fedora N and its notice on the top line, the markings and the CSV export through the
path line, Columns, and the panels' sizes kept between runs.

Run with Textual's headless driver (`App.run_test`, `Pilot`), as tests/test_tui_window.py. Skipped without Textual.
"""
import csv
import json
import subprocess
import threading
from contextlib import contextmanager

import pytest

pytest.importorskip("textual")

from test_tui_window import run, top, use_catalog, window_module  # noqa: E402
from textual.widgets import Input  # noqa: E402

from kram.app import notifier as app_notifier  # noqa: E402
from kram.app import preferences, release_watch  # noqa: E402
from kram.app.columns import COL_CANDIDATE, COL_INSTALLED, COL_NAME, COL_REPO  # noqa: E402
from kram.app.parity import Feature  # noqa: E402
from kram.app.ports import FakeBus  # noqa: E402
from kram.core import distro, net, upgrade_audit  # noqa: E402
from kram.core.custom_filters import STATUS_ANY_INSTALLED, Condition, CustomFilter, Field, Op  # noqa: E402
from kram.core.marks import Action  # noqa: E402
from kram.core.settings import store as settings  # noqa: E402
from kram.notifier import control  # noqa: E402
from kram.tui.dialogs import notifier as notifier_dialog  # noqa: E402
from kram.tui.dialogs.columns import ColumnsDialog  # noqa: E402
from kram.tui.dialogs.filters import ConditionRow, FiltersDialog  # noqa: E402
from kram.tui.dialogs.notifier import NotifierDialog  # noqa: E402
from kram.tui.dialogs.path import PathDialog  # noqa: E402
from kram.tui.dialogs.question import QuestionDialog  # noqa: E402
from kram.tui.dialogs.upgrade import UpgradeDialog, upgrade_commands  # noqa: E402
from kram.tui.package_list import Columns  # noqa: E402
from kram.tui.widgets import Button, CheckBox, Choice, Radio  # noqa: E402

VIM = CustomFilter("Vim", [Condition(Field.NAME, Op.CONTAINS, "pkg000")])
BIG = CustomFilter("Big", [Condition(Field.SIZE, Op.GREATER, "0.2")])


def keep_filters(*filters: CustomFilter) -> None:
    settings.set("filters/custom", json.dumps([f.to_dict() for f in filters]))


def saved_filters() -> list[CustomFilter]:
    return [CustomFilter.from_dict(d) for d in json.loads(settings.get("filters/custom", "[]"))]


async def filters_dialog(app, pilot, action: str = "filters") -> FiltersDialog:
    app.main.run_action(action)
    await pilot.pause()
    assert isinstance(app.screen, FiltersDialog)
    return app.screen


def table_names(dialog: FiltersDialog) -> list[str]:
    table = dialog.filter_table
    return [dialog._filter_cell(key, "name").plain for key in table.keys]


async def count(dialog: FiltersDialog, pilot) -> str:
    """The count once it has settled: the recount timer goes off on the test's clock."""
    await pilot.pause()
    dialog.app.main.scheduler.fire()
    await pilot.pause()
    return dialog.count


# ---------------------------------------------------------------- Custom Filters (§10.10)

def test_the_keys_of_the_dialogs():
    """The keys the tests below stand in for with the actions they are bound to. Ctrl+S takes priority: OK from a
    text field too."""
    def keys(screen):
        return {key: (b.action, b.priority) for b in screen.BINDINGS for key in b.key.split(",")}
    filters, columns, upgrade = keys(FiltersDialog), keys(ColumnsDialog), keys(UpgradeDialog)
    assert filters["ctrl+s"] == ("accept", True) and filters["escape"][0] == "cancel"
    assert {k: columns[k][0] for k in ("space", "alt+up", "alt+down", "less_than_sign", "greater_than_sign")} == {
        "space": "toggle", "alt+up": "move(-1)", "alt+down": "move(1)", "less_than_sign": "width(-1)",
        "greater_than_sign": "width(1)"}
    assert upgrade["y"][0] == "copy_command" and upgrade["escape"][0] == "close"


@pytest.mark.feature(Feature.DIALOG_CUSTOM_FILTERS, front="tui")
def test_the_filters_dialog_edits_a_copy_that_ok_saves(monkeypatch):
    use_catalog(monkeypatch, clock=True)
    keep_filters(VIM, BIG)

    async def test(app, pilot):
        b = app.main.browser
        dialog = await filters_dialog(app, pilot)
        assert table_names(dialog) == ["Vim", "Big"] and dialog.edit.current_name() == "Vim"
        assert dialog.query_one("#name", Input).value == "Vim"
        assert [r.condition() for r in dialog.rows] == VIM.conditions
        dialog.query_one("#name", Input).value = "Editors"
        await pilot.pause()
        assert table_names(dialog) == ["Editors", "Big"]  # the list follows the name as it is typed
        dialog.action_cancel()  # Esc: Cancel drops it all
        await pilot.pause()
        assert len(app.screen_stack) == 1 and [f.name for f in b.sidebar.custom] == ["Vim", "Big"]

        dialog = await filters_dialog(app, pilot)
        dialog.query_one("#name", Input).value = "Editors"
        dialog.query_one("#add-condition", Button).action_press()
        await pilot.pause()
        row = dialog.rows[-1]
        assert isinstance(row, ConditionRow) and dialog.focused is row.query_one("#text", Input)
        # another field: its operators and its kind of value
        row.query_one("#field", Choice).set_value(Field.STATUS, tell=True)
        await pilot.pause()
        assert row.query_one("#op", Choice).options[0][0] is Op.IS
        assert row.query_one("#values", Choice).value == STATUS_ANY_INSTALLED
        assert row.condition() == Condition(Field.STATUS, Op.IS, STATUS_ANY_INSTALLED)
        # a field whose values may be typed over: a text line and the list of them
        row.query_one("#field", Choice).set_value(Field.ARCH, tell=True)
        await pilot.pause()
        row.query_one("#pick", Button).action_press()
        await pilot.pause()
        app.screen.dismiss("x86_64")  # the catalog's only one
        await pilot.pause()
        assert row.condition() == Condition(Field.ARCH, Op.IS, "x86_64")
        dialog.action_accept()  # ctrl+s: OK
        await pilot.pause()
        assert len(app.screen_stack) == 1
        editors = CustomFilter("Editors", [*VIM.conditions, Condition(Field.ARCH, Op.IS, "x86_64")])
        assert saved_filters() == b.sidebar.custom == [editors, BIG]
        assert b.sidebar.current_view == "custom" and b.sidebar.current_entry_id == "custom:Editors"

        # New and Delete; two filters of one name cannot be saved
        dialog = await filters_dialog(app, pilot)
        dialog.query_one("#new", Button).action_press()
        await pilot.pause()
        assert table_names(dialog) == ["Editors", "Big", "New filter"] and dialog.focused.id == "name"
        dialog.query_one("#name", Input).value = "Big"
        await pilot.pause()
        dialog.action_accept()
        await pilot.pause()
        assert isinstance(app.screen, QuestionDialog) and app.screen.question.text == "Two filters have the same name."
        app.screen.focused.action_press()  # Enter: OK
        await pilot.pause()
        assert app.screen is dialog
        dialog.query_one("#delete", Button).action_press()
        await pilot.pause()
        assert table_names(dialog) == ["Editors", "Big"] and dialog.edit.current_name() == "Big"
        dialog.query_one("#delete", Button).action_press()
        dialog.query_one("#delete", Button).action_press()
        await pilot.pause()
        assert table_names(dialog) == [] and not dialog.query_one("#editor").display
        assert "No filters yet" in str(dialog.query_one("#no-filters").render())
        dialog.action_accept()
        await pilot.pause()
        assert saved_filters() == b.sidebar.custom == []
    run(test)


@pytest.mark.feature(Feature.DIALOG_CUSTOM_FILTERS_COUNT, front="tui")
@pytest.mark.feature(Feature.DIALOG_CUSTOM_FILTERS_MATCH, front="tui")
def test_the_count_follows_the_conditions_and_all_or_any(monkeypatch):
    use_catalog(monkeypatch, clock=True)
    keep_filters(VIM)

    async def test(app, pilot):
        b = app.main.browser
        dialog = await filters_dialog(app, pilot)
        assert await count(dialog, pilot) == "10 packages match"  # pkg0000 … pkg0009
        dialog.rows[0].query_one("#text", Input).value = "pkg00"
        assert await count(dialog, pilot) == "100 packages match"
        dialog.rows[0].query_one("#text", Input).value = "pkg000"
        dialog.query_one("#add-condition", Button).action_press()
        await pilot.pause()
        dialog.rows[-1].query_one("#field", Choice).set_value(Field.STATUS, tell=True)  # installed (any): 100
        assert await count(dialog, pilot) == "4 packages match"  # all: 0, 3, 6 and 9
        match = dialog.query_one("#match", Radio)
        dot = app.glyphs.item  # `*` where the terminal is not UTF-8
        assert f"({dot}) all conditions  ( ) any condition" in match.render().plain
        match.action_step(1)  # right
        assert f"( ) all conditions  ({dot}) any condition" in match.render().plain
        assert await count(dialog, pilot) == "106 packages match"  # any: 10 + 100 - 4
        dialog.rows[0].query_one("#remove", Button).action_press()
        await pilot.pause()
        assert len(dialog.rows) == 1 and await count(dialog, pilot) == "100 packages match"
        dialog.action_accept()
        await pilot.pause()
        [vim] = b.sidebar.custom
        assert vim.match_all is False and vim.conditions == [Condition(Field.STATUS, Op.IS, STATUS_ANY_INSTALLED)]
    run(test)


@pytest.mark.feature(Feature.DIALOG_CUSTOM_FILTERS_NEW_FROM_VIEW, front="tui")
def test_a_new_filter_from_the_view_is_filled_in(monkeypatch):
    use_catalog(monkeypatch, clock=True)
    keep_filters(VIM)

    async def test(app, pilot):
        b = app.main.browser
        b.sidebar.select("status", "status:installed")
        await pilot.pause()
        label = b.filter.label
        dialog = await filters_dialog(app, pilot, "new_filter")
        assert table_names(dialog) == ["Vim", label] and dialog.edit.current_name() == label
        assert dialog.focused.id == "name"
        assert [r.condition() for r in dialog.rows] == [Condition(Field.STATUS, Op.IS, STATUS_ANY_INSTALLED)]
        assert await count(dialog, pilot) == "100 packages match"
        dialog.action_accept()
        await pilot.pause()
        assert [f.name for f in b.sidebar.custom] == ["Vim", label]
        assert b.sidebar.current_entry_id == f"custom:{label}"
    run(test)


@pytest.mark.feature(Feature.SIDEBAR_CUSTOM_FILTER_EDIT, front="tui")
def test_e_on_a_custom_filter_edits_it(monkeypatch):
    use_catalog(monkeypatch, clock=True)
    keep_filters(VIM, BIG)

    async def test(app, pilot):
        sidebar = app.main.sidebar
        sidebar.browse("custom")
        sidebar.entries.go(1)
        sidebar.action_edit()  # e
        await pilot.pause()
        dialog = app.screen
        assert isinstance(dialog, FiltersDialog) and dialog.edit.current_name() == "Big"
        assert dialog.filter_table.current == 1
        dialog.action_cancel()
        await pilot.pause()
        sidebar.browse("status")  # not on an entry of another view
        assert sidebar.check_action("edit", ()) is False
    run(test)


def test_the_filters_dialog_fits_a_narrow_terminal(monkeypatch):
    use_catalog(monkeypatch, clock=True)
    keep_filters(CustomFilter("Vim", [Condition(Field.UPDATE, Op.IS_NOT, "bugfix")]))

    async def test(app, pilot):
        dialog = await filters_dialog(app, pilot)
        await pilot.pause()
        box = dialog.query_one("#filters-box")
        assert box.has_class("-narrow")
        row = dialog.rows[0]
        widths = [w.size.width for w in (row.query_one("#field"), row.query_one("#op"), row.query_one(".value"),
                                          row.query_one("#remove"))]
        assert widths[:2] == [15, 13] and widths[2] >= 10 and sum(widths) + 3 <= box.content_region.width
        assert dialog.query_one("#match").region.y > dialog.query_one("#match-line").region.y  # under its label
    run(test, size=(64, 22))


# ---------------------------------------------------------------- Update notifications (§10.11)

def notifier_setup(monkeypatch, tmp_path, timer: list[str]):
    system = tmp_path / "xdg-autostart"
    system.mkdir()
    (system / "org.kde.discover.notifier.desktop").write_text("[Desktop Entry]\nExec=DiscoverNotifier\n")
    monkeypatch.setattr(control, "SYSTEM_AUTOSTART", system)
    calls = []
    monkeypatch.setattr(control, "checker_enabled", lambda: bool(calls) and calls[-1])
    monkeypatch.setattr(control, "set_checker_enabled", lambda on: calls.append(on) or "")
    monkeypatch.setattr(control, "fedora_timer_state", lambda: timer[0])
    monkeypatch.setattr(notifier_dialog, "BusctlBus", FakeBus)
    monkeypatch.setattr(notifier_dialog, "is_root", lambda: False)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    return calls


@pytest.mark.feature(Feature.DIALOG_NOTIFICATIONS, front="tui")
@pytest.mark.feature(Feature.DIALOG_NOTIFICATIONS_STALE_DAYS, front="tui")
def test_the_notifier_dialog_turns_things_on_and_off(monkeypatch, tmp_path):
    use_catalog(monkeypatch)
    calls = notifier_setup(monkeypatch, tmp_path, ["enabled"])

    async def test(app, pilot):
        app.action_menu()  # m
        await pilot.pause()
        app.screen.dismiss(app.main.open_notifications)  # Settings → Update Notifications…
        await pilot.pause()
        dialog = app.screen
        assert isinstance(dialog, NotifierDialog)
        tray, days = dialog.query_one("#tray", CheckBox), dialog.query_one("#stale-days", Input)
        assert dialog.focused is tray and not tray.value and not days.can_focus and days.has_class("-off")
        assert "no system tray" in str(dialog.query_one("#no-tray").render())  # FakeBus: no tray host
        assert not dialog.query_one("#timer-line").display  # the timer is on
        tray.action_toggle()  # space
        await pilot.pause()
        assert calls == [True] and tray.value and days.can_focus
        assert days.value == "7"
        days.value = "14"
        await pilot.pause()
        assert preferences.value(preferences.STALE_DAYS) == 14
        assert str(dialog.query_one("#days").render()).strip() == "days"
        days.focus()
        days.value = "999"  # out of the range: not kept, and put back when left
        await pilot.pause()
        dialog.focus_next()  # tab
        await pilot.pause()
        assert preferences.value(preferences.STALE_DAYS) == 14 and days.value == "14"
        # Discover's notifier, off for this user and back on; its file copied without a desktop
        toggle = dialog.query_one("#toggle-0", Button)
        toggle.action_press()
        await pilot.pause()
        assert dialog.notifications.notifiers[0].turned_off() and toggle.label == "Turn Back On"
        toggle.action_press()
        await pilot.pause()
        assert not dialog.notifications.notifiers[0].turned_off() and toggle.label == "Turn Off"
        dialog.query_one("#show-0", Button).action_press()
        await pilot.pause()
        assert app.clipboard.endswith("org.kde.discover.notifier.desktop")
        dialog.action_close()  # Esc
        await pilot.pause()
        assert len(app.screen_stack) == 1
    run(test)


@pytest.mark.feature(Feature.DIALOG_NOTIFICATIONS_FEDORA_TIMER, front="tui")
def test_fedora_s_timer_is_turned_on_in_the_terminal_without_a_desktop(monkeypatch, tmp_path):
    use_catalog(monkeypatch)
    timer = ["disabled"]
    notifier_setup(monkeypatch, tmp_path, timer)
    suspended, ran = [], []

    @contextmanager
    def suspend():
        suspended.append(True)
        yield

    def run_systemctl(argv, **kw):
        ran.append(argv)
        if len(ran) == 1:
            return subprocess.CompletedProcess(argv, 1, "", "Access denied")
        timer[0] = "enabled"
        return subprocess.CompletedProcess(argv, 0, "", "")

    async def test(app, pilot):
        dialog = NotifierDialog(app.ui, FakeBus(), suspend=suspend, run=run_systemctl)
        app.push_screen(dialog)
        await pilot.pause()
        state = str(dialog.query_one("#timer").render())
        assert state.startswith(f"{app.glyphs.warning} Off: dnf-makecache.timer is disabled")
        assert dialog.query_one("#timer-line").display
        dialog.query_one("#timer-on", Button).action_press()
        await pilot.pause()
        assert suspended == [True] and ran == [["systemctl", "enable", "--now", "dnf-makecache.timer"]]
        assert isinstance(app.screen, QuestionDialog) and app.screen.question.text == "Access denied"
        app.screen.focused.action_press()  # Enter: OK
        await pilot.pause()
        dialog.query_one("#timer-on", Button).action_press()
        await pilot.pause()
        assert len(ran) == 2 and app.screen is dialog
        assert str(dialog.query_one("#timer").render()).startswith(f"{app.glyphs.yes} On: dnf-makecache.timer")
        assert not dialog.query_one("#timer-line").display
    run(test)


def test_with_a_desktop_its_polkit_window_asks_for_fedora_s_timer(monkeypatch, tmp_path):
    use_catalog(monkeypatch)
    timer = ["disabled"]
    notifier_setup(monkeypatch, tmp_path, timer)
    monkeypatch.setattr(notifier_dialog, "has_desktop", lambda: True)
    started = []
    monkeypatch.setattr(app_notifier.proc, "run", lambda argv, post, done: started.append((argv, done)) or
                        type("P", (), {"kill": lambda self: None})())

    async def test(app, pilot):
        dialog = NotifierDialog(app.ui, FakeBus(), suspend=lambda: pytest.fail("no stepping aside"))
        app.push_screen(dialog)
        await pilot.pause()
        button = dialog.query_one("#timer-on", Button)
        button.action_press()
        await pilot.pause()
        assert [argv for argv, _done in started] == [["systemctl", "enable", "--now", "dnf-makecache.timer"]]
        assert not button.enabled  # while the desktop asks
        timer[0] = "enabled"
        started[0][1](0, "", "")
        await pilot.pause()
        assert not dialog.query_one("#timer-line").display
    run(test)


def test_the_bus_is_asked_with_busctl():
    from kram.tui.ui_port import BusctlBus
    asked = []

    def fake(argv, **kw):
        asked.append(argv[-3:])
        out = {"NameHasOwner": "b true", "GetConnectionUnixProcessID": "u 4242"}[argv[-3]]
        return subprocess.CompletedProcess(argv, 0, out + "\n", "")
    bus = BusctlBus(fake)
    assert bus.has_owner("org.kde.StatusNotifierWatcher") and bus.owner_pid("org.kde.discover.notifier") == 4242
    assert asked[0] == ["NameHasOwner", "s", "org.kde.StatusNotifierWatcher"]
    gone = BusctlBus(lambda argv, **kw: subprocess.CompletedProcess(argv, 1, "", "no bus"))
    assert not gone.has_owner("x") and gone.owner_pid("x") is None


# ---------------------------------------------------------------- Fedora N (§5.4, §10.12)

BODHI = {"releases": [{"version": "44", "state": "current", "id_prefix": "FEDORA", "eol": "2027-06-02"},
                      {"version": "45", "state": "current", "id_prefix": "FEDORA", "eol": "2027-12-08"},
                      {"version": "46", "state": "current", "id_prefix": "FEDORA", "eol": "2028-06-01"}]}


CHECK = release_watch.ReleaseWatcher.check  # use_catalog turns it off


def on_fedora_44(monkeypatch, target: int = 45) -> list:
    monkeypatch.setattr(release_watch.ReleaseWatcher, "check", CHECK)
    monkeypatch.setattr(release_watch.distro, "running_release", lambda: 44)
    settings.set("distro/target", target)
    settings.set("distro/running_eol", "2027-06-02")
    asked = []
    monkeypatch.setattr(net, "fetch_json", lambda url, *, done, failed, **kw: asked.append(url) or done(BODHI))
    return asked


@pytest.mark.feature(Feature.RELEASE_BUTTON, front="tui")
@pytest.mark.feature(Feature.RELEASE_WATCH, front="tui")
@pytest.mark.feature(Feature.SETTINGS_WATCH_RELEASES, front="tui")
def test_the_top_line_says_a_new_release_is_out_while_watching(monkeypatch):
    use_catalog(monkeypatch)
    monkeypatch.setattr(window_module, "is_root", lambda: False)  # the test container runs as root: no badge
    asked = on_fedora_44(monkeypatch)

    async def test(app, pilot):
        b = app.main.browser
        assert "Fedora 45 is out: r" in top(app) and app.check_action("release", ()) is True
        preferences.set_value(preferences.WATCH_RELEASES, False)
        assert "Fedora" not in top(app) and app.check_action("release", ()) is False
        b.refreshed.emit()  # Reload: not asked while not watching
        assert asked == []
        preferences.set_value(preferences.WATCH_RELEASES, True)
        b.refreshed.emit()
        await pilot.pause()
        assert asked == [distro.BODHI_RELEASES_URL] and "Fedora 46 is out: r" in top(app)  # Bodhi's answer
        await pilot.resize_terminal(50, 24)
        await pilot.pause()
        assert top(app).rstrip().endswith("Fedora 46 is out: r")  # the catalog's age goes first
        app.action_release()  # r
        await pilot.pause()
        assert isinstance(app.screen, UpgradeDialog) and app.screen.state.target == 46
    run(test)


@pytest.mark.feature(Feature.RELEASE_DIALOG, front="tui")
def test_the_release_dialog_checks_and_cannot_close_meanwhile(monkeypatch):
    use_catalog(monkeypatch, threaded=True)  # the check waits for its cancel
    on_fedora_44(monkeypatch)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    started, cancelled = threading.Event(), []

    def simulate(target, cancel, report):
        report("resolving", {})
        started.set()
        cancel.wait(5)
        cancelled.append(target)
        raise upgrade_audit.Cancelled()
    monkeypatch.setattr(upgrade_audit, "simulate", simulate)

    async def test(app, pilot):
        app.action_release()  # r
        await pilot.pause()
        dialog = app.screen
        assert isinstance(dialog, UpgradeDialog)
        findings = str(dialog.query_one("#findings").render())
        assert findings == "i No COPR projects are enabled."
        assert str(dialog.query_one("#have").render()).startswith("You have Fedora 44, supported until 2027-06-02.")
        assert dialog.query_one("#notes").url == distro.RELEASE_NOTES_URL.format(version=45)
        assert dialog.query_one("#guide").url == distro.UPGRADE_GUIDE_URL
        assert str(dialog.query_one("#command").render()) == "\n".join(upgrade_commands(45))
        dialog.action_copy_command()  # y
        assert app.clipboard == "\n".join(upgrade_commands(45))
        assert not dialog.query("#program")  # no desktop: no software centre to open

        dialog.query_one("#check", Button).action_press()
        for _ in range(100):
            if started.is_set() and dialog.state.log:
                break
            await pilot.pause(0.02)
        await pilot.pause()
        assert dialog.state.running and not dialog.query_one("#check").display
        assert dialog.query_one("#cancel").display and not dialog.query_one("#close", Button).enabled
        assert "Working out the upgrade…" in str(dialog.query_one("#log").render())
        dialog.action_close()  # Esc: neither the dialog nor Kram closes meanwhile
        await pilot.press("q")
        await pilot.pause()
        assert app.screen is dialog and app.return_code is None
        assert "not while it runs" in str(dialog.query_one("#upgrade-box").border_subtitle)
        dialog.query_one("#cancel", Button).action_press()
        for _ in range(100):
            if not dialog.state.running:
                break
            await pilot.pause(0.02)
        await pilot.pause()
        assert cancelled == ["45"] and dialog.query_one("#check").display
        assert dialog.state.log[-1].endswith("Cancelling…")
        dialog.action_close()
        await pilot.pause()
        assert len(app.screen_stack) == 1
        app.action_release()  # the check made for this release is kept for the session
        await pilot.pause()
        assert app.screen.state is dialog.state and "Cancelling…" in str(app.screen.query_one("#log").render())
    run(test)


# ---------------------------------------------------------------- markings and CSV (§10.15)

@pytest.mark.feature(Feature.MARKINGS_FILE, front="tui")
def test_markings_are_saved_and_read_back_through_the_path_line(monkeypatch, tmp_path):
    use_catalog(monkeypatch)
    settings.set("markings/dir", str(tmp_path))
    path = tmp_path / "kram-markings.txt"

    async def test(app, pilot):
        b = app.main.browser
        b.packages.marks.set(b.snapshot.rows[1], Action.INSTALL)
        b.packages.marks.set(b.snapshot.rows[3], Action.REMOVE)
        b.update_actions()
        app.action_run("save_marks")  # ctrl+s
        await pilot.pause()
        dialog = app.screen
        assert isinstance(dialog, PathDialog) and dialog.query_one(Input).value == str(path)
        dialog.accept()  # Enter
        await pilot.pause()
        assert len(app.screen_stack) == 1 and path.exists()
        assert "2 markings saved to" in top(app)
        app.action_run("save_marks")  # once more: it exists now, so it asks first
        await pilot.pause()
        app.screen.accept()
        await pilot.pause()
        assert isinstance(app.screen, QuestionDialog) and "already exists" in app.screen.question.text
        app.screen.dismiss("replace")
        await pilot.pause()
        assert len(app.screen_stack) == 1
        app.main.run_action("unmark_all")
        await pilot.pause()
        assert not b.packages.marks
        app.action_run("read_marks")  # ctrl+o
        await pilot.pause()
        field = app.screen.query_one(Input)
        assert isinstance(app.screen, PathDialog) and field.value == f"{tmp_path}/"
        app.screen.action_complete()  # Tab: the only matching file
        app.screen.accept()
        await pilot.pause()
        assert len(app.screen_stack) == 1
        assert {k: m.action for k, m in b.packages.marks.items()} == {
            b.snapshot.rows[1].key: Action.INSTALL, b.snapshot.rows[3].key: Action.REMOVE}
    run(test)


@pytest.mark.feature(Feature.MARKINGS_CSV_EXPORT, front="tui")
def test_the_list_is_exported_as_csv_through_the_path_line(monkeypatch, tmp_path):
    use_catalog(monkeypatch)
    settings.set("export/dir", str(tmp_path))

    async def test(app, pilot):
        app.main.run_action("export_csv")
        await pilot.pause()
        dialog = app.screen
        assert isinstance(dialog, PathDialog) and dialog.query_one(Input).value == str(tmp_path / "kram-packages.csv")
        dialog.query_one(Input).value = str(tmp_path / "list.csv")
        dialog.accept()
        await pilot.pause()
        assert len(app.screen_stack) == 1 and "300 packages exported to" in top(app)
        with open(tmp_path / "list.csv", newline="") as f:
            found = list(csv.reader(f))
        assert len(found) == 301 and found[0][0] == "name" and found[1][0] == "pkg0000"
        app.main.run_action("export_csv")
        await pilot.pause()
        app.screen.query_one(Input).value = str(tmp_path / "list.csv")
        app.screen.accept()
        await pilot.pause()
        assert isinstance(app.screen, QuestionDialog)  # the overwrite question
        app.screen.action_cancel()  # Esc: Cancel, the path line stays
        await pilot.pause()
        assert isinstance(app.screen, PathDialog)
    run(test)


# ---------------------------------------------------------------- Columns (§10.18) and the panels

def header(app) -> list[str]:
    return [c for c, _w in app.main.list.columns]


@pytest.mark.feature(Feature.LIST_COLUMNS, front="tui")
def test_columns_are_hidden_moved_and_resized_and_kept(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        main = app.main
        app.action_menu()
        await pilot.pause()
        app.screen.dismiss(main.open_columns)  # Settings → Columns…
        await pilot.pause()
        dialog = app.screen
        assert isinstance(dialog, ColumnsDialog)
        table = dialog.query_one("#column-list")
        assert table.keys[:3] == [COL_NAME, COL_INSTALLED, *table.keys[2:3]] and dialog.focused is table
        dialog.action_toggle()  # space: Package is always shown
        assert COL_NAME in header(app)
        table.action_move(1)
        dialog.action_toggle()  # Installed hidden
        await pilot.pause()
        assert COL_INSTALLED not in header(app)
        assert dialog._cell(COL_INSTALLED, "on").plain == "[ ]"
        table.select_key(COL_REPO)
        dialog.action_move(-1)  # alt+up
        dialog.action_move(-1)  # before the latest version
        await pilot.pause()
        assert header(app).index(COL_REPO) < header(app).index(COL_CANDIDATE) and table.current == COL_REPO
        for d in (1, 1, 1, -1):  # > > > <
            dialog.action_width(d)
        await pilot.pause()
        assert dict(main.list.columns)[COL_REPO] == 14
        table.select_key(COL_NAME)
        name = dict(main.list.columns)[COL_NAME]
        dialog.action_width(-1)  # from the width it had
        await pilot.pause()
        assert dict(main.list.columns)[COL_NAME] == name - 1 and dialog._cell(COL_NAME, "width").plain == str(name - 1)
        dialog.action_close()
        await pilot.pause()
        saved = json.loads(preferences.value(preferences.TUI_COLUMNS))
        assert saved["hidden"] == sorted({*Columns().hidden, COL_INSTALLED})
        assert saved["widths"] == {str(COL_NAME): name - 1, str(COL_REPO): 14}
        return main.list.columns_state
    kept = []

    async def first(app, pilot):
        kept.append(await test(app, pilot))
    run(first)

    async def again(app, pilot):
        assert app.main.list.columns_state == kept[0]
        assert COL_INSTALLED not in header(app) and dict(app.main.list.columns)[COL_REPO] == 14
    run(again)


def test_columns_of_another_version_fall_back_to_the_defaults():
    assert Columns.from_dict({"order": [1, 2], "hidden": [99], "widths": {"0": 9, "6": 1000, "x": 3}}) == Columns()
    assert Columns.from_dict("nonsense") == Columns()
    columns = Columns(hidden={COL_INSTALLED}, widths={COL_REPO: 20})
    assert Columns.from_dict(json.loads(json.dumps(columns.to_dict()))) == columns


@pytest.mark.feature(Feature.WINDOW_PANES_SAVED, front="tui")
def test_the_panels_sizes_and_pins_are_kept(monkeypatch):
    use_catalog(monkeypatch)

    async def first(app, pilot):
        app.action_toggle_panel("sidebar")  # g
        await pilot.pause()
        app.action_resize_panel("sidebar", 2)  # >
        app.action_resize_panel("sidebar", 2)
        await pilot.pause()
        assert app.panel("sidebar").outer_size.width == 32
        app.action_toggle_panel("details")  # d
        await pilot.pause()
        app.action_resize_panel("details", -1)  # <
        await pilot.pause()
        assert app.panel("details").outer_size.height == 11
        app.action_toggle_panel("details")  # hidden, and no longer pinned
        await pilot.pause()
        assert app.shown_panels() == ["sidebar"]
    run(first)
    assert (preferences.value(preferences.TUI_SIDEBAR_WIDTH), preferences.value(preferences.TUI_DETAILS_HEIGHT),
            preferences.value(preferences.TUI_PINNED)) == (32, 11, "sidebar")

    async def again(app, pilot):
        assert app.shown_panels() == ["sidebar"] and app.panel("sidebar").outer_size.width == 32
        app.action_toggle_panel("details")
        await pilot.pause()
        assert app.panel("details").outer_size.height == 11
        await pilot.resize_terminal(80, 24)  # a slide-over keeps its own size, and `<` `>` do nothing there
        await pilot.pause()
        app.action_toggle_panel("sidebar")
        await pilot.pause()
        app.action_resize_panel("sidebar", 2)
        await pilot.pause()
        assert app.panel("sidebar").outer_size.width == 30 and preferences.value(preferences.TUI_SIDEBAR_WIDTH) == 32
    run(again)

