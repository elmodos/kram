"""How the helper gets root in a terminal (docs/TUI_SPEC.md §11): the `HelperClient` the window gives to Browser.

The GUIs start the helper with pkexec and let the desktop's polkit agent ask for the password. In a terminal pkexec
has a problem: with no agent registered for the session it falls back to polkit's text agent on the controlling
terminal, which would write its prompt over Textual's screen. So, before the first request (spike T3,
docs/TUI_FRONTEND.md §8):

1. The helper is started with pkexec in a new session, without a controlling terminal (its stdio are the pipes of
   the protocol, which are no terminal either), and asked a `ping`, which needs root and does nothing. A desktop's
   agent asks in its own window; the progress dialog says "Waiting for authentication…" once 0.3 s have passed
   without an answer, so that the no-agent case (an answer within 0.02–0.07 s) shows nothing that flashes.
2. Without an agent pkexec ends with exit 127 and a message naming the "authentication agent". Kram says why it steps
   aside (Administrator rights), then on Continue suspends itself (`App.suspend`: the terminal is the shell's again),
   prints one line, and starts the helper again with pkexec, this time in Kram's session, so that polkit's text
   agent asks on /dev/tty while the protocol keeps to the pipes. Kram waits inside the suspend for the helper's
   answer to the ping, or for pkexec's end, with a SIGINT handler that does nothing: Ctrl+C at the prompt ends
   pkexec, not Kram (a handler, not SIG_IGN, which pkexec would inherit across exec). Then Kram resumes.
3. polkit's text agent takes one password: a wrong one ends pkexec with 127 "Not authorized", and Kram offers to try
   again.

Once the ping is answered, the authenticated helper is the client's for the rest of the session (one password), and
the request that needed it is sent. Every dialog that follows another starts from the first one's dismissal callback:
pushing one right after `dismiss()` lost the focus or froze the screen now and then on Textual 8 (spike T3).

As root (euid 0, `sudo kram-tui`) the helper starts without pkexec and nothing is asked.
"""
import json
import os
import signal
import subprocess
import sys
import threading
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path

from .. import INSTALLED_HELPER
from ..app.ports import CANCEL, Button, Question
from ..app.progress import helper_text
from ..core.mainloop import Post
from ..i18n import N_, _
from ..ipc.client import HELPER, HelperClient, _installed

WAIT_DELAY = 0.3  # seconds without pkexec's answer before "Waiting for authentication…" shows (§11.3.1)
PING = b'{"op": "ping"}\n'
# what pkexec says when no agent can ask: polkit 127 "Error creating textual authentication agent: …", older ones
# "No authentication agent found" (spike T3)
NO_AGENT = "authentication agent"
NO_PKEXEC = N_("Could not start pkexec. Is polkit installed?")  # the GUIs' text (kram.ipc.client)
CANCELLED = N_("Authorization was cancelled.")
NOT_AUTHORIZED = N_("Authentication was cancelled or not authorized.")  # the GUIs' text (kram.ipc.client)
UNEXPECTED = N_("The privileged helper exited unexpectedly (code {code}).")  # the GUIs' text
STEP_ASIDE = N_("Kram needs administrator rights. Kram comes back when you have answered.")


def is_root() -> bool:
    return os.geteuid() == 0


def no_pkexec() -> bool:
    """Development and tests: the helper runs unprivileged, as kram.ipc.client allows."""
    return os.environ.get("KRAM_HELPER_NO_PKEXEC") == "1"


def _do_nothing(_signum, _frame) -> None:
    """Kram's SIGINT handler while pkexec asks on the terminal (the module's docstring)."""


@dataclass
class Answer:
    """How a pkexec'd helper answered the ping: `proc` is the running, authenticated helper; else pkexec's exit
    `code` (negative: killed by that signal) and what it wrote to stderr, or the helper's own `error`."""
    proc: subprocess.Popen | None = None
    code: int | None = None
    err: str = ""
    error: str = ""


def wait_for_ping(proc: subprocess.Popen) -> Answer:
    """Send the ping and wait for its "done", or for pkexec's end. Blocking: on a thread, or inside the suspend.
    The helper's lines after the ping stay in `proc.stdout`'s buffer for the client's reader."""
    try:
        proc.stdin.write(PING)
        proc.stdin.flush()
    except OSError:  # pkexec ended before it read anything: its exit code says why
        pass
    for line in proc.stdout:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if isinstance(ev, dict) and ev.get("event") == "done":
            if ev.get("ok"):
                return Answer(proc)
            _close(proc)
            return Answer(code=proc.wait(), error=helper_text(ev, "error"))
    code = proc.wait()
    err = proc.stderr.read().decode(errors="replace").strip()
    _close(proc)
    return Answer(code=code, err=err)


def _close(proc: subprocess.Popen) -> None:
    for pipe in (proc.stdin, proc.stdout, proc.stderr):
        try:
            pipe.close()
        except OSError:
            pass


class TuiHelperClient(HelperClient):
    """The GUIs' client, but the first request that needs pkexec goes through `access` first (the module's
    docstring); as root the helper starts without pkexec."""

    def __init__(self, post: Post, access: "RootAccess"):
        super().__init__(post)
        self.access = access
        self._pending: dict | None = None

    def _command(self) -> list[str]:
        if is_root() and not no_pkexec():
            # the helper itself, which runs as root without pkexec: the installed one, or the checkout's
            if _installed() and Path(INSTALLED_HELPER).exists():
                return [INSTALLED_HELPER]
            return [sys.executable, "-I", str(HELPER)]
        return super()._command()

    def pkexec_command(self) -> list[str]:
        return super()._command()

    def needs_authentication(self) -> bool:
        return not self._running() and not is_root() and not no_pkexec()

    def request(self, req: dict) -> bool:
        if self.busy:
            return False
        if not self.needs_authentication():
            return super().request(req)
        self.busy = True
        self._pending = req
        self.access.authenticate(self, self._authorized, self._refused)
        return True

    def _authorized(self, proc: subprocess.Popen, send: bool) -> None:
        """The helper answered the ping: it is the session's. `send` False: the user stopped the request meanwhile;
        the helper stays for the next one."""
        self._attach(proc)
        req, self._pending = self._pending, None
        if send and req is not None:
            self._write(req)
        else:
            self._fail(_(CANCELLED))

    def _refused(self, message: str) -> None:
        self._pending = None
        self._fail(message)


class RootAccess:
    """The dialogs and the terminal of the authentication (the module's docstring), for `TuiHelperClient`.

    The progress dialog of the request (kram.tui.dialogs.progress) is handed over by `present` right after the
    request was accepted: while the authentication runs it shows only once it has something to say (the 0.3 s, an
    outcome), and a cancel by the user shows nothing at all. `suspend` and `spawn` are the app's `suspend` and
    subprocess.Popen, replaceable in tests."""

    def __init__(self, app, ui, suspend: Callable[[], AbstractContextManager] | None = None,
                 spawn: Callable[..., subprocess.Popen] = subprocess.Popen):
        self.app, self.ui = app, ui
        self._suspend = suspend or app.suspend
        self._spawn = spawn
        self.active = False       # an authentication runs
        self.dialog = None        # the request's progress dialog, once presented
        self.shown = False        # ...and on the screen
        self.stopped = False      # the user stopped it (Esc in the waiting dialog)
        self._client: TuiHelperClient | None = None
        self._authorized: Callable[[subprocess.Popen, bool], None] | None = None
        self._refused: Callable[[str], None] | None = None
        self._pkexec: subprocess.Popen | None = None
        self._timer = None

    # ---------------------------------------------------------------- the progress dialog

    def present(self, dialog) -> None:
        """Show the request's progress dialog: at once, or when the authentication has something to say."""
        if not self.active:
            dialog.show()
            return
        self.dialog, self.shown = dialog, False

    def _show_dialog(self, waiting: bool = False) -> None:
        if self.dialog is not None and not self.shown:
            self.shown = True
            self.dialog.set_waiting(waiting)
            self.dialog.show()

    def _waited(self) -> None:
        """0.3 s and no answer yet: a desktop's agent is asking in its own window."""
        self._timer = None
        if self.active:
            self._show_dialog(waiting=True)

    def stop(self) -> None:
        """Esc in the waiting dialog. pkexec is still the user's own process until it has authenticated, so it can
        be ended; if it had just authenticated, the helper stays for the next request and this one is not sent."""
        if not self.active:
            return
        self.stopped = True
        if self._pkexec is not None:
            try:
                self._pkexec.kill()
            except (PermissionError, ProcessLookupError):
                pass

    # ---------------------------------------------------------------- the flow

    def authenticate(self, client: TuiHelperClient, authorized: Callable[[subprocess.Popen, bool], None],
                     refused: Callable[[str], None]) -> None:
        """Step 1: pkexec without a terminal, the ping on a thread. One of the callbacks follows, on the app's
        thread, never from inside this call."""
        self.active, self.stopped, self.dialog, self.shown = True, False, None, False
        self._client, self._authorized, self._refused = client, authorized, refused
        self._timer = self.app.set_timer(WAIT_DELAY, self._waited)
        proc = self._start(new_session=True)
        if proc is None:
            self.app.call_later(self._refuse, _(NO_PKEXEC), True)
            return

        def wait() -> None:
            answer = wait_for_ping(proc)
            client._post(lambda: self._headless_answered(answer))
        threading.Thread(target=wait, name="kram-pkexec", daemon=True).start()

    def _start(self, new_session: bool) -> subprocess.Popen | None:
        """The helper through pkexec, its stdio the protocol's pipes. `new_session`: without a controlling terminal,
        so that only a desktop's agent can ask; else in Kram's session, so that polkit's text agent asks on it."""
        try:
            proc = self._spawn(self._client.pkexec_command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, start_new_session=new_session)
        except OSError:
            return None
        self._pkexec = proc
        return proc

    def _headless_answered(self, answer: Answer) -> None:
        self._pkexec = None
        if answer.proc is not None:
            self._authorize(answer.proc)
        elif self.stopped:
            self._refuse(_(CANCELLED), False)
        elif answer.code == 127 and NO_AGENT in answer.err:
            self._no_agent()
        else:
            self._refuse(self._failure(answer), True)

    def _no_agent(self) -> None:
        """Step 2: say why Kram steps aside, and do it on Continue."""
        self._stop_timer()
        if self.shown:  # over the waiting dialog, which no desktop window answers now
            self.dialog.set_waiting(False)
        title = self.dialog.title_text if self.dialog is not None else _("Administrator rights")
        question = Question(
            _("Administrator rights"),
            _("“{what}” needs administrator rights.").format(what=title) + "\n\n" +
            _("There is no password window here (no desktop, or no polkit agent in it), so Kram steps aside for a "
              "moment: polkit asks for your password in this terminal, and Kram comes back when you have "
              "answered. It asks once for the whole session."),
            buttons=(Button("continue", _("Continue"), "accept"), CANCEL), default="continue",
            informative=_("Started as root (sudo kram-tui), Kram asks no password at all."))
        self.ui.ask(question, lambda answer: self._step_aside() if answer == "continue"
                    else self._refuse(_(CANCELLED), False))

    def _step_aside(self) -> None:
        """Step 3, from the dismissal of the dialog before it: polkit asks on the terminal while Kram is suspended.
        It blocks until pkexec has answered: nothing of Kram's can run meanwhile anyway."""
        answer: Answer | None = None
        try:
            with self._suspend():
                print("\n" + _(STEP_ASIDE) + "\n", flush=True)
                old = signal.signal(signal.SIGINT, _do_nothing)
                try:
                    proc = self._start(new_session=False)
                    answer = wait_for_ping(proc) if proc is not None else None
                finally:
                    signal.signal(signal.SIGINT, old)
                    self._pkexec = None
        except Exception as e:  # noqa: BLE001 - no terminal to give back (Textual's SuspendNotSupported, …)
            self._refuse(str(e) or type(e).__name__, True)
            return
        if answer is None:
            self._refuse(_(NO_PKEXEC), True)
        elif answer.proc is not None:
            self._authorize(answer.proc)
        elif answer.code == 127 and not answer.error and NO_AGENT not in answer.err:
            self._not_authorized()
        elif answer.code is not None and answer.code < 0:  # Ctrl+C at the prompt: pkexec died of SIGINT
            self._refuse(_(CANCELLED), True)
        else:
            self._refuse(self._failure(answer), True)

    def _not_authorized(self) -> None:
        """Step 5: polkit's text agent took one wrong password."""
        question = Question(_("Not authorized"),
                            _("The password was not accepted, or this user may not change the system."),
                            buttons=(Button("retry", _("Try again"), "accept"), CANCEL), default="retry")
        self.ui.ask(question, lambda answer: self._step_aside() if answer == "retry"
                    else self._refuse(_(CANCELLED), False))

    @staticmethod
    def _failure(answer: Answer) -> str:
        if answer.error:
            return answer.error
        if answer.code == 126:  # dismissed in the desktop's window
            return _(CANCELLED)
        if answer.code == 127:
            return _(NOT_AUTHORIZED)
        return _(UNEXPECTED).format(code=answer.code)

    # ---------------------------------------------------------------- the outcome

    def _stop_timer(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    def _end(self):
        self._stop_timer()
        self.active = False
        dialog, self.dialog = self.dialog, None
        return dialog

    def _authorize(self, proc: subprocess.Popen) -> None:
        stopped = self.stopped
        shown = self.shown
        dialog = self._end()
        self._authorized(proc, not stopped)
        if dialog is not None:
            dialog.set_waiting(False)
            if not shown:  # (Esc, which stops, needs the dialog on the screen)
                dialog.show()

    def _refuse(self, message: str, show: bool) -> None:
        """The request does not run. `show`: the progress dialog says why, if it is not up already; else (the user
        cancelled) a dialog not shown yet stays away."""
        shown = self.shown
        dialog = self._end()
        if dialog is not None:
            dialog.set_waiting(False)
        self._refused(message)
        if dialog is not None and not shown:
            if show:
                dialog.show()
            else:
                dialog.discard()
