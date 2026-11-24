"""The terminal front end's progress dialog (docs/TUI_SPEC.md §10.2, kram.tui.dialogs.progress) over a fake helper,
as tests/test_gtk.py tests the GTK one; and the window's requests that run through it (Reload, the version lock).
"""
import asyncio
import sys
from types import SimpleNamespace

import pytest

pytest.importorskip("textual")

from test_tui_window import WIDE, loaded, snapshot, use_catalog  # noqa: E402
from textual.widgets import Log, ProgressBar  # noqa: E402

from kram.app.parity import Feature  # noqa: E402
from kram.app.progress import BUSY  # noqa: E402
from kram.core.mainloop import Signal  # noqa: E402
from kram.core.settings import store as settings  # noqa: E402
from kram.tui import root  # noqa: E402
from kram.tui import window as window_module  # noqa: E402
from kram.tui.app import KramApp  # noqa: E402
from kram.tui.dialogs.progress import AUTO_CLOSE_KEY, LogDialog, LogTail, ProgressDialog  # noqa: E402
from kram.tui.dialogs.question import QuestionDialog  # noqa: E402
from kram.tui.widgets import Button, CheckBox  # noqa: E402


def fake_client(accepted: bool = True):
    answered = []
    return SimpleNamespace(event=Signal(), failed=Signal(), request=lambda _r: accepted, busy=False,
                           answer=lambda qid, yes: answered.append((qid, yes)), answered=answered)


def run(monkeypatch, test, load=None):
    use_catalog(monkeypatch, load=load)
    app = KramApp()

    async def go():
        async with app.run_test(size=WIDE) as pilot:
            await loaded(app, pilot)
            await test(app, pilot)
    asyncio.run(go())


async def until(pilot, condition, seconds: float = 5) -> None:
    for _ in range(int(seconds / 0.02)):
        if condition():
            return
        await pilot.pause(0.02)
    assert condition()


async def show(app, pilot, request: dict, title: str = "Applying changes", client=None):
    client = client or fake_client()
    finished = []
    dialog = ProgressDialog(client, request, title, lambda ok, result: finished.append((ok, result)), app.ui)
    assert dialog.start()
    dialog.show()
    await pilot.pause()
    return dialog, client, finished


def bar(dialog, name: str) -> ProgressBar:
    return dialog.query_one(f"#{name}-bar", ProgressBar)


def tail(dialog) -> str:
    return dialog.query_one(LogTail).render().plain


@pytest.mark.feature(Feature.DIALOG_PROGRESS, front="tui")
@pytest.mark.feature(Feature.DIALOG_PROGRESS_CLOSE_LOCK, front="tui")
def test_the_dialog_follows_the_helper_and_stays_until_it_is_done(monkeypatch):
    async def test(app, pilot):
        settings.set(AUTO_CLOSE_KEY, False)
        dialog, client, finished = await show(app, pilot, {"op": "transaction"})
        assert app.screen is dialog and dialog.stage.text == "Applying changes"
        assert not dialog.query_one("#close", Button).display  # no Close button until it is done
        assert bar(dialog, "download").total is None  # busy until a download says its size
        client.event.emit({"event": "resolved", "items": [{"action": "Install", "nevra": "a-1-1.noarch"},
                                                          {"action": "Upgrade", "nevra": "b-2-1.noarch"}]})
        assert dialog.stage.text == "The transaction has 2 packages. Downloading…"
        client.event.emit({"event": "download", "id": 1, "name": "a", "done": 50, "total": 100})
        assert bar(dialog, "download").progress == 500 and bar(dialog, "download").total == 1000
        assert dialog.download[1] == "Downloaded 50 B of 100 B"
        client.event.emit({"event": "rpm", "step": "install", "nevra": "a-1-1.noarch", "done": 0})
        assert dialog.stage.text == "Installing a-1-1.noarch"
        assert (bar(dialog, "rpm").progress, bar(dialog, "rpm").total) == (1, 2)
        assert dialog.rpm[1] == "Package 1 of 2"
        await pilot.pause()
        assert bar(dialog, "download").size.width > 60  # as wide as the dialog, not Textual's 32 cells
        assert "Installing a-1-1.noarch" in tail(dialog)
        # the transaction runs: Esc does nothing, and the hint says so
        assert "not while it runs" in str(dialog.query_one("#progress-box").border_subtitle)
        await pilot.press("escape")
        await pilot.pause()
        assert app.screen is dialog and not finished
        client.event.emit({"event": "done", "ok": True})
        await pilot.pause()
        assert dialog.stage == dialog.stage.__class__("Done.", "done", "") and dialog.finished is True
        close = dialog.query_one("#close", Button)
        assert close.display and close.has_focus
        assert (bar(dialog, "rpm").progress, bar(dialog, "rpm").total) == (2, 2)
        await pilot.press("enter")
        await until(pilot, lambda: finished)
        assert finished == [(True, {"event": "done", "ok": True})] and not client.event._slots
        assert len(app.screen_stack) == 1
    run(monkeypatch, test)


def test_a_refresh_has_no_package_bar_and_a_failure_stays(monkeypatch):
    async def test(app, pilot):
        settings.set(AUTO_CLOSE_KEY, True)
        dialog, client, finished = await show(app, pilot, {"op": "refresh"}, "Refreshing metadata")
        assert not dialog.query("#rpm-bar") and dialog.query("#download-bar")
        client.event.emit({"event": "log", "key": "refreshing", "text": "Refreshing repository metadata…"})
        assert dialog.stage.text == "Refreshing repository metadata…"
        client.failed.emit("pkexec died")
        await pilot.pause()
        assert dialog.stage.kind == "error" and dialog.stage.detail == "pkexec died"
        assert app.screen is dialog and not finished  # a failure stays on screen, auto-close or not
        await pilot.press("escape")  # done: Esc closes
        await until(pilot, lambda: finished)
        assert finished == [(False, {})]
    run(monkeypatch, test)


@pytest.mark.feature(Feature.DIALOG_PROGRESS_LOG, front="tui")
def test_the_log_under_the_bars_and_the_whole_log_with_its_times(monkeypatch):
    async def test(app, pilot):
        dialog, client, _finished = await show(app, pilot, {"op": "refresh"}, "Refreshing metadata")
        for i in range(8):
            client.event.emit({"event": "log", "text": f"line {i} " + "x" * 200})
        await pilot.pause()
        shown = tail(dialog).splitlines()
        assert len(shown) == 4 and shown[0].startswith(dialog.lines[4][:20]) and "line 7" in shown[-1]
        assert all(len(line) <= dialog.query_one(LogTail).size.width for line in shown)  # cut, not wrapped
        assert dialog.lines[0][2] == ":" and dialog.lines[0][10:].startswith("line 0")  # "12:00:05  line 0 …"
        await pilot.press("l")
        await pilot.pause()
        log_dialog = app.screen
        assert isinstance(log_dialog, LogDialog) and log_dialog.query_one(Log).line_count == 8
        client.event.emit({"event": "log", "text": "one more"})  # it follows while open
        await pilot.pause()
        assert log_dialog.query_one(Log).line_count == 9
        await pilot.press("escape")
        await pilot.pause()
        assert app.screen is dialog
    run(monkeypatch, test)


@pytest.mark.feature(Feature.DIALOG_PROGRESS_AUTO_CLOSE, front="tui")
def test_close_when_finished_successfully_is_remembered(monkeypatch):
    async def test(app, pilot):
        settings.set(AUTO_CLOSE_KEY, False)
        dialog, client, finished = await show(app, pilot, {"op": "refresh"}, "Refreshing metadata")
        box = dialog.query_one(CheckBox)
        assert not box.value
        box.focus()
        await pilot.press("space")
        assert box.value and settings.get(AUTO_CLOSE_KEY, False) is True  # saved on change
        client.event.emit({"event": "done", "ok": True})
        await until(pilot, lambda: finished)
        assert finished[0][0] is True and len(app.screen_stack) == 1
        dialog, client, finished = await show(app, pilot, {"op": "refresh"}, "Refreshing metadata")
        assert dialog.query_one(CheckBox).value  # the next one starts ticked
        # under the whole log it closes once the log is closed (a screen under another cannot be dismissed)
        await pilot.press("l")
        await pilot.pause()
        client.event.emit({"event": "done", "ok": True})
        await pilot.pause()
        assert isinstance(app.screen, LogDialog) and not finished
        await pilot.press("escape")
        await until(pilot, lambda: finished)
        assert len(app.screen_stack) == 1
    run(monkeypatch, test)


@pytest.mark.feature(Feature.DIALOG_PROGRESS_KEY_QUESTION, front="tui")
def test_the_key_question_is_asked_over_the_dialog(monkeypatch):
    async def test(app, pilot):
        dialog, client, _finished = await show(app, pilot, {"op": "transaction"})
        client.event.emit({"event": "question", "id": 4, "kind": "gpg_key", "key_id": "ABCD", "user_ids": ["Fedora"],
                           "fingerprint": "F1", "url": "file:///key", "timestamp": 0})
        await pilot.pause()
        question = app.screen
        assert isinstance(question, QuestionDialog) and question.question.title == "Import key"
        assert "Fingerprint: F1" in question.question.text and app.screen_stack[-2] is dialog
        await pilot.press("enter")  # Yes is focused
        await until(pilot, lambda: client.answered)
        assert client.answered == [(4, True)] and app.screen is dialog
        assert dialog.lines[-1].endswith("Key ABCD: importing")
    run(monkeypatch, test)


def test_a_busy_helper_says_so(monkeypatch):
    async def test(app, pilot):
        done = []
        monkeypatch.setattr(app.main.browser, "helper", fake_client(accepted=False))
        app.main.run_helper({"op": "refresh"}, "Refreshing metadata", done.append)
        await pilot.pause()
        assert done == [None] and isinstance(app.screen, QuestionDialog)
        assert app.screen.question.text == BUSY
    run(monkeypatch, test)


def test_quitting_is_refused_while_a_request_runs(monkeypatch):
    async def test(app, pilot):
        dialog, client, _finished = await show(app, pilot, {"op": "transaction"})
        app.main.browser.helper.busy = True  # what the real client says while the helper has the request
        app.request_quit()
        await pilot.pause()
        assert app.is_running and app.screen is dialog
        assert "Another operation is still running" in app.top_line.render().plain
        app.main.browser.helper.busy = False
    run(monkeypatch, test)


# ---------------------------------------------------------------- the window's requests

FAKE_HELPER = r'''
import json, sys
for line in sys.stdin:
    req = json.loads(line)
    if req["op"] == "quit":
        break
    with open(sys.argv[1], "a") as f:
        f.write(req["op"] + "\n")
    print(json.dumps({"event": "log", "text": "Refreshing repository metadata…", "key": "refreshing"}), flush=True)
    print(json.dumps({"event": "done", "ok": True}), flush=True)
'''


@pytest.fixture
def helper(tmp_path, monkeypatch):
    """The window's own client (kram.tui.root) over a fake helper that notes the requests it got."""
    script, seen = tmp_path / "helper.py", tmp_path / "requests"
    script.write_text(FAKE_HELPER)
    monkeypatch.setenv("KRAM_HELPER_NO_PKEXEC", "1")
    monkeypatch.setattr(root.TuiHelperClient, "_command", lambda self: [sys.executable, "-I", str(script), str(seen)])
    monkeypatch.setattr(window_module, "is_root", lambda: False)
    return lambda: seen.read_text().split() if seen.exists() else []


def counting(loads: list):
    snap = snapshot()

    def load(*_a, **_k):
        loads.append(1)
        return snap
    return load


async def finish(app, pilot) -> ProgressDialog:
    await until(pilot, lambda: isinstance(app.screen, ProgressDialog) and app.screen.finished is not None)
    dialog = app.screen
    await pilot.press("enter")
    await until(pilot, lambda: len(app.screen_stack) == 1)
    return dialog


def test_f5_refreshes_the_metadata_then_reloads(monkeypatch, helper):
    loads = []

    async def test(app, pilot):
        before = len(loads)
        assert app.main.action_enabled("reload")
        await pilot.press("f5")
        dialog = await finish(app, pilot)
        assert dialog.title_text == "Refreshing metadata" and dialog.finished is True
        assert helper() == ["refresh"]
        await until(pilot, lambda: len(loads) > before and app.main.reload_enabled)
        app.main.browser.helper.stop()
    run(monkeypatch, test, load=counting(loads))


@pytest.mark.feature(Feature.LIST_VERSION_LOCK, front="tui")
def test_the_version_lock_runs_with_its_progress_then_reloads(monkeypatch, helper):
    loads = []

    async def test(app, pilot):
        app.main.list.select(0)  # pkg0000 is installed
        await pilot.pause()
        assert app.main.action_enabled("lock")
        before = len(loads)
        await pilot.press("equals_sign")
        dialog = await finish(app, pilot)
        assert dialog.title_text == "Locking the version of 1 package"
        assert dialog.request == {"op": "versionlock", "action": "add", "names": ["pkg0000"]}
        assert helper() == ["versionlock"]
        await until(pilot, lambda: len(loads) > before)
        app.main.browser.helper.stop()
    run(monkeypatch, test, load=counting(loads))
