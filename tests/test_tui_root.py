"""How the terminal front end gets root (docs/TUI_SPEC.md §11, kram.tui.root), with a fake pkexec first on PATH and
a stand-in for `App.suspend`: nothing here runs as root or asks for a password. The real thing, with polkit in a
container and a pseudo-terminal, is scripts/tui_root_check.sh.

The fake pkexec takes its part from a plan file, one word per call: what pkexec would do (no agent, a wrong password,
Ctrl+C, a dismissed window, …) or, when authorized, the helper itself, which answers the ping and one request. Each
call notes whether it ran in a session of its own, whether its stdin was a terminal and whether it inherited an
ignored SIGINT.
"""
import asyncio
import json
import os
import signal
import subprocess
import sys
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

pytest.importorskip("textual")

from test_tui_window import WIDE, loaded, top, use_catalog  # noqa: E402

from kram.app.parity import Feature  # noqa: E402
from kram.ipc import client as ipc  # noqa: E402
from kram.tui import root  # noqa: E402
from kram.tui import window as window_module  # noqa: E402
from kram.tui.app import KramApp  # noqa: E402
from kram.tui.dialogs.progress import ProgressDialog  # noqa: E402
from kram.tui.dialogs.question import QuestionDialog  # noqa: E402

FAKE_PKEXEC = r'''#!{python}
import json, os, signal, sys, time
plan = os.environ["FAKE_PKEXEC_PLAN"]
with open(plan) as f:
    words = f.read().split()
mode = words[0] if words else "ok"
with open(plan, "w") as f:
    f.write("\n".join(words[1:]))
with open(os.environ["FAKE_PKEXEC_LOG"], "a") as f:
    f.write(json.dumps({"mode": mode, "new_session": os.getsid(0) == os.getpid(), "stdin_tty": os.isatty(0),
                        "sigint_ignored": signal.getsignal(signal.SIGINT) == signal.SIG_IGN}) + "\n")
if mode.startswith("slow-"):
    time.sleep(0.8)
    mode = mode[5:]
if mode == "hang":
    time.sleep(60)
if mode == "noagent":
    print("Error creating textual authentication agent: Error opening current controlling terminal for the process "
          "(`/dev/tty'): No such device or address", file=sys.stderr)
    sys.exit(127)
if mode == "notauth":
    print("Error executing command as another user: Not authorized\n\nThis incident has been reported.",
          file=sys.stderr)
    sys.exit(127)
if mode == "dismissed":
    sys.exit(126)
if mode == "sigint":
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    os.kill(os.getpid(), signal.SIGINT)
# authorized: from here on this process is the helper
for line in sys.stdin:
    req = json.loads(line)
    if req["op"] == "quit":
        break
    if req["op"] == "ping":
        print(json.dumps({"event": "done", "ok": True, "uid": 0}), flush=True)
        continue
    print(json.dumps({"event": "log", "text": "Refreshing repository metadata…", "key": "refreshing"}), flush=True)
    print(json.dumps({"event": "done", "ok": True}), flush=True)
'''


@pytest.fixture
def pkexec(tmp_path, monkeypatch):
    """The fake pkexec first on PATH; `plan(*words)` says what its next calls do, `calls()` what they saw."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "pkexec"
    script.write_text(FAKE_PKEXEC.replace("{python}", sys.executable))
    script.chmod(0o755)
    plan, log = tmp_path / "plan", tmp_path / "pkexec.log"
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '/usr/bin')}")
    monkeypatch.setenv("FAKE_PKEXEC_PLAN", str(plan))
    monkeypatch.setenv("FAKE_PKEXEC_LOG", str(log))
    monkeypatch.delenv("KRAM_HELPER_NO_PKEXEC", raising=False)
    monkeypatch.setattr(root, "is_root", lambda: False)  # the test container runs as root
    monkeypatch.setattr(window_module, "is_root", lambda: False)

    def calls() -> list[dict]:
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return SimpleNamespace(plan=lambda *words: plan.write_text("\n".join(words)), calls=calls, bin=bin_dir)


class Terminal:
    """`App.suspend` and subprocess.Popen as the root flow uses them: counts the suspends and notes Kram's SIGINT
    handler while pkexec is started inside one."""

    def __init__(self):
        self.suspended = 0
        self.inside = False
        self.handlers: list[object] = []

    @contextmanager
    def suspend(self):
        self.suspended += 1
        self.inside = True
        try:
            yield
        finally:
            self.inside = False

    def spawn(self, *args, **kw):
        if self.inside:
            self.handlers.append(signal.getsignal(signal.SIGINT))
        return subprocess.Popen(*args, **kw)


async def until(pilot, condition, seconds: float = 5) -> None:
    for _ in range(int(seconds / 0.02)):
        if condition():
            return
        await pilot.pause(0.02)
    assert condition()


def run(monkeypatch, test, loads: list | None = None):
    use_catalog(monkeypatch, load=_counting_load(loads) if loads is not None else None)
    app = KramApp()
    terminal = Terminal()

    async def go():
        async with app.run_test(size=WIDE) as pilot:
            app.main.root._suspend = terminal.suspend
            app.main.root._spawn = terminal.spawn
            await loaded(app, pilot)
            await test(app, pilot, terminal)
            app.main.browser.helper.stop()
    asyncio.run(go())


def _counting_load(loads: list):
    from test_tui_window import snapshot
    snap = snapshot()

    def load(*_a, **_k):
        loads.append(1)
        return snap
    return load


async def reload(app, pilot) -> None:
    """Reload (F5, Ctrl+R): metadata refreshed by the helper, which needs root."""
    app.action_run("reload")
    await pilot.pause()


async def answer(app, pilot, value) -> None:
    """The question on top answered: a button's id, or the Esc answer for None."""
    if value is None:
        app.screen.action_cancel()
    else:
        app.screen.dismiss(value)
    await pilot.pause()


def progress_dialog(app) -> ProgressDialog | None:
    return next((s for s in app.screen_stack if isinstance(s, ProgressDialog)), None)


async def reload_and_finish(app, pilot) -> ProgressDialog:
    """After the helper got the request: the progress dialog is up, done, and closed with Enter."""
    await until(pilot, lambda: (d := progress_dialog(app)) is not None and d.finished is not None)
    dialog = progress_dialog(app)
    assert dialog.finished is True and app.screen is dialog
    dialog.close()  # Enter
    await until(pilot, lambda: progress_dialog(app) is None)
    return dialog


# ---------------------------------------------------------------- as root (§11.2)

def test_as_root_the_helper_starts_without_pkexec_and_the_top_line_says_so(monkeypatch):
    monkeypatch.delenv("KRAM_HELPER_NO_PKEXEC", raising=False)
    monkeypatch.setattr(root, "is_root", lambda: True)
    monkeypatch.setattr(window_module, "is_root", lambda: True)
    access = SimpleNamespace(authenticate=lambda *a: pytest.fail("as root nothing is asked"))
    client = root.TuiHelperClient(lambda fn: None, access)
    assert client._command() == [sys.executable, "-I", str(ipc.HELPER)]  # no pkexec, no --allow-non-root
    assert client.pkexec_command()[0] == "pkexec" and not client.needs_authentication()

    async def test(app, pilot, _terminal):
        assert " ROOT   changes need no password" in top(app)
        await pilot.resize_terminal(44, 30)
        await pilot.pause()
        assert "ROOT" in top(app) and "changes need no password" not in top(app)  # the note goes before the badge
    run(monkeypatch, test)


def test_not_root_the_top_line_has_no_badge(monkeypatch, pkexec):
    async def test(app, pilot, _terminal):
        assert "ROOT" not in top(app)
    run(monkeypatch, test)


# ---------------------------------------------------------------- with a desktop's agent (§11.3.1)

@pytest.mark.feature(Feature.SYSTEM_POLKIT, front="tui")
def test_headless_pkexec_authenticates_once_for_the_session(monkeypatch, pkexec):
    pkexec.plan("ok")
    loads = []

    async def test(app, pilot, terminal):
        before = len(loads)
        await reload(app, pilot)
        dialog = await reload_and_finish(app, pilot)
        assert not dialog.waiting and dialog.stage.text == "Done."  # the answer came at once: no "Waiting…"
        assert "Refreshing repository metadata…" in "\n".join(dialog.lines)
        [call] = pkexec.calls()
        assert call["new_session"] and not call["stdin_tty"]  # no terminal for polkit's text agent to write to
        assert terminal.suspended == 0
        await until(pilot, lambda: len(loads) > before)  # Reload: refresh, then the catalog again
        # the helper lives for the session: the next request asks nothing
        await until(pilot, lambda: app.main.reload_enabled)
        await reload(app, pilot)
        await reload_and_finish(app, pilot)
        assert len(pkexec.calls()) == 1
    run(monkeypatch, test, loads)


def test_waiting_for_authentication_shows_after_a_moment(monkeypatch, pkexec):
    pkexec.plan("slow-ok")

    async def test(app, pilot, _terminal):
        await reload(app, pilot)
        await pilot.pause(0.15)
        assert progress_dialog(app) is None  # nothing that would flash up and away
        await until(pilot, lambda: progress_dialog(app) is not None)
        dialog = progress_dialog(app)
        assert dialog.waiting and dialog.stage.text == "Waiting for authentication…"
        assert app.main.browser.busy()
        await reload_and_finish(app, pilot)
        assert not dialog.waiting
    run(monkeypatch, test)


def test_esc_while_waiting_stops_the_request(monkeypatch, pkexec):
    pkexec.plan("hang")

    async def test(app, pilot, _terminal):
        await reload(app, pilot)
        await until(pilot, lambda: progress_dialog(app) is not None)
        progress_dialog(app).action_escape()
        await until(pilot, lambda: progress_dialog(app) is None)
        assert not app.main.browser.busy() and len(app.screen_stack) == 1
    run(monkeypatch, test)


def test_a_dismissed_desktop_window_cancels(monkeypatch, pkexec):
    pkexec.plan("dismissed")

    async def test(app, pilot, terminal):
        await reload(app, pilot)
        await until(pilot, lambda: (d := progress_dialog(app)) is not None and d.finished is not None)
        dialog = progress_dialog(app)
        assert dialog.finished is False and dialog.stage.detail == "Authorization was cancelled."
        assert terminal.suspended == 0 and not app.main.browser.busy()
    run(monkeypatch, test)


def test_no_pkexec(monkeypatch, pkexec, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))

    async def test(app, pilot, _terminal):
        await reload(app, pilot)
        await until(pilot, lambda: (d := progress_dialog(app)) is not None and d.finished is not None)
        assert progress_dialog(app).stage.detail == "Could not start pkexec. Is polkit installed?"
    run(monkeypatch, test)


# ---------------------------------------------------------------- without an agent (§11.3.2–§11.3.5)

async def administrator_rights(app, pilot) -> None:
    await until(pilot, lambda: isinstance(app.screen, QuestionDialog))
    assert app.screen.question.title == "Administrator rights"
    assert "“Refreshing metadata” needs administrator rights." in app.screen.question.text
    assert progress_dialog(app) is None  # pkexec failed at once: no waiting dialog came first


@pytest.mark.feature(Feature.SYSTEM_POLKIT, front="tui")
def test_no_agent_kram_steps_aside_and_polkit_asks_on_the_terminal(monkeypatch, pkexec):
    pkexec.plan("noagent", "ok")

    async def test(app, pilot, terminal):
        await reload(app, pilot)
        await administrator_rights(app, pilot)
        await answer(app, pilot, "continue")
        await reload_and_finish(app, pilot)
        headless, tty = pkexec.calls()
        assert headless["new_session"] and not tty["new_session"]  # on Kram's terminal, where polkit asks
        assert not tty["stdin_tty"] and not tty["sigint_ignored"]  # the pipes; SIGINT not ignored for pkexec
        assert terminal.suspended == 1 and terminal.handlers == [root._do_nothing]
        assert signal.getsignal(signal.SIGINT) is not root._do_nothing  # Kram's own handler is back
    run(monkeypatch, test)


def test_cancel_at_administrator_rights_shows_nothing_more(monkeypatch, pkexec):
    pkexec.plan("noagent")

    async def test(app, pilot, terminal):
        await reload(app, pilot)
        await administrator_rights(app, pilot)
        await answer(app, pilot, None)
        await until(pilot, lambda: not app.main.browser.busy())
        await pilot.pause()
        assert len(app.screen_stack) == 1 and terminal.suspended == 0
        assert app.main.reload_enabled
    run(monkeypatch, test)


def test_a_wrong_password_offers_to_try_again(monkeypatch, pkexec):
    pkexec.plan("noagent", "notauth", "ok")

    async def test(app, pilot, terminal):
        await reload(app, pilot)
        await administrator_rights(app, pilot)
        await answer(app, pilot, "continue")
        await until(pilot, lambda: isinstance(app.screen, QuestionDialog)
                    and app.screen.question.title == "Not authorized")
        assert [b.id for b in app.screen.question.buttons] == ["retry", "cancel"]
        await answer(app, pilot, "retry")
        await reload_and_finish(app, pilot)
        assert terminal.suspended == 2 and [c["mode"] for c in pkexec.calls()] == ["noagent", "notauth", "ok"]
    run(monkeypatch, test)


def test_a_wrong_password_and_cancel(monkeypatch, pkexec):
    pkexec.plan("noagent", "notauth")

    async def test(app, pilot, _terminal):
        await reload(app, pilot)
        await administrator_rights(app, pilot)
        await answer(app, pilot, "continue")
        await until(pilot, lambda: isinstance(app.screen, QuestionDialog)
                    and app.screen.question.title == "Not authorized")
        await answer(app, pilot, None)
        await until(pilot, lambda: not app.main.browser.busy())
        await pilot.pause()
        assert len(app.screen_stack) == 1
    run(monkeypatch, test)


def test_ctrl_c_at_the_prompt_cancels_and_kram_goes_on(monkeypatch, pkexec):
    pkexec.plan("noagent", "sigint", "ok")

    async def test(app, pilot, terminal):
        await reload(app, pilot)
        await administrator_rights(app, pilot)
        await answer(app, pilot, "continue")
        await until(pilot, lambda: (d := progress_dialog(app)) is not None and d.finished is not None)
        dialog = progress_dialog(app)
        assert dialog.finished is False and dialog.stage.detail == "Authorization was cancelled."
        assert app.is_running and not app.main.browser.busy()
        dialog.close()
        await until(pilot, lambda: progress_dialog(app) is None)
        # the next request starts again from the beginning: a new pkexec, a new password
        await until(pilot, lambda: app.main.reload_enabled)
        pkexec.plan("ok")
        await reload(app, pilot)
        await reload_and_finish(app, pilot)
        assert terminal.suspended == 1
    run(monkeypatch, test)


def test_a_dismissed_window_in_the_terminal_step_cancels(monkeypatch, pkexec):
    pkexec.plan("noagent", "dismissed")

    async def test(app, pilot, _terminal):
        await reload(app, pilot)
        await administrator_rights(app, pilot)
        await answer(app, pilot, "continue")
        await until(pilot, lambda: (d := progress_dialog(app)) is not None and d.finished is not None)
        assert progress_dialog(app).stage.detail == "Authorization was cancelled."
    run(monkeypatch, test)


def test_the_suspend_cannot_be_had(monkeypatch, pkexec):
    pkexec.plan("noagent")

    @contextmanager
    def no_terminal():
        raise RuntimeError("App.suspend is not supported in this environment.")
        yield

    async def test(app, pilot, _terminal):
        app.main.root._suspend = no_terminal
        await reload(app, pilot)
        await administrator_rights(app, pilot)
        await answer(app, pilot, "continue")
        await until(pilot, lambda: (d := progress_dialog(app)) is not None and d.finished is not None)
        assert "not supported" in progress_dialog(app).stage.detail
    run(monkeypatch, test)
