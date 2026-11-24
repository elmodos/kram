"""Talks to the privileged helper over a pkexec'd subprocess, one request at a time.

The helper stays alive for the whole session, so the password is asked once, not per transaction. Two daemon
threads read its stdout (the JSON event lines) and stderr; everything they read reaches the GUI thread through
`post` (kram.core.mainloop), where `busy` changes and the signals are emitted.
"""
import functools
import json
import os
import site
import subprocess
import sys
import threading
from pathlib import Path

from .. import INSTALLED_HELPER
from ..core.mainloop import Post, Signal
from ..i18n import _

HELPER = Path(__file__).resolve().parent.parent / "helper" / "kram_helper.py"
# pkexec exit codes: the user dismissed the dialog / is not authorized
PKEXEC_CANCELLED = (126, 127)
STOP_TIMEOUT = 3  # seconds for the helper to quit before it is killed


class HelperClient:
    def __init__(self, post: Post):
        self.event = Signal()   # (dict) every event line from the helper, including the final "done"
        self.failed = Signal()  # (str) the helper could not be started or died; no "done" will follow
        self._post = post
        self._proc: subprocess.Popen | None = None
        self.busy = False

    def _command(self) -> list[str]:
        cmd = [sys.executable, "-I", str(HELPER)]
        if os.environ.get("KRAM_HELPER_NO_PKEXEC") == "1":  # development/tests: run unprivileged
            return cmd + ["--allow-non-root"]
        if _installed() and Path(INSTALLED_HELPER).exists():
            # matches the polkit policy's exec.path, so the dialog shows Kram's own message
            return ["pkexec", INSTALLED_HELPER]
        return ["pkexec", *cmd]  # source checkout: run the checkout's helper (generic pkexec prompt)

    def _running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _start(self) -> bool:
        try:
            proc = subprocess.Popen(self._command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE)
        except OSError:
            self._proc = None
            return False
        self._attach(proc)
        return True

    def _attach(self, proc: subprocess.Popen) -> None:
        """`proc` is the helper from now on: its output is read and reported. Called by `_start`, and by a front end
        that starts and authenticates the helper its own way before the first request (kram.tui.root)."""
        self._proc = proc
        threading.Thread(target=self._read_stdout, args=(proc,), name="kram-helper-stdout", daemon=True).start()
        threading.Thread(target=self._read_stderr, args=(proc,), name="kram-helper-stderr", daemon=True).start()

    def request(self, req: dict) -> bool:
        """Send one request; events arrive via `event` until one with event == "done" (or `failed` fires).

        Returns False, and sends nothing, while another request is running: the caller decides what to show."""
        if self.busy:
            return False
        self.busy = True
        if not self._running() and not self._start():
            # reported from the main loop, like every other outcome: never from inside request()
            self._post(functools.partial(self._fail, _("Could not start pkexec. Is polkit installed?")))
            return True
        self._write(req)
        return True

    def answer(self, question_id: int, yes: bool) -> None:
        self._write({"op": "answer", "id": question_id, "yes": yes})

    def stop(self) -> None:
        if not self._running():
            return
        proc = self._proc
        self._write({"op": "quit"})
        try:
            proc.stdin.close()
        except OSError:
            pass
        try:
            proc.wait(STOP_TIMEOUT)
        except subprocess.TimeoutExpired:
            # after authentication the helper runs as root, and this process cannot signal it
            try:
                proc.kill()
            except (PermissionError, ProcessLookupError):
                pass

    def _write(self, obj: dict) -> None:
        try:
            self._proc.stdin.write((json.dumps(obj) + "\n").encode())
            self._proc.stdin.flush()
        except (OSError, ValueError, AttributeError):
            pass  # the helper is gone: its end is reported by _on_finished

    # --- reader threads: they only parse and post ---

    def _read_stdout(self, proc: subprocess.Popen) -> None:
        for line in proc.stdout:
            if not line.strip():
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                ev = None
            if not isinstance(ev, dict):  # not JSON, or JSON that is not an object: show it as a log line
                ev = {"event": "log", "text": line.decode(errors="replace").rstrip("\n")}
            self._post(functools.partial(self._on_event, proc, ev))
        code = proc.wait()
        self._post(functools.partial(self._on_finished, proc, code))

    def _read_stderr(self, proc: subprocess.Popen) -> None:
        # rpm scriptlet output and libdnf5 messages land here (the helper moves fd 1 to stderr)
        while chunk := proc.stderr.read1(65536):
            text = chunk.decode(errors="replace").rstrip()
            if text:
                self._post(functools.partial(self._on_event, proc, {"event": "log", "text": text, "stderr": True}))

    # --- GUI thread ---

    def _on_event(self, proc: subprocess.Popen, ev: dict) -> None:
        if proc is not self._proc:  # a helper from before a restart
            return
        if ev.get("event") == "done":
            self.busy = False
        self.event.emit(ev)

    def _on_finished(self, proc: subprocess.Popen, code: int) -> None:
        if proc is not self._proc or not self.busy:
            return
        if code in PKEXEC_CANCELLED:
            self._fail(_("Authentication was cancelled or not authorized."))
        else:
            self._fail(_("The privileged helper exited unexpectedly (code {code}).").format(code=code))

    def _fail(self, message: str) -> None:
        self.busy = False
        self.failed.emit(message)


def _installed() -> bool:
    """Kram runs from the system site-packages (a package), not from a source checkout."""
    return any(HELPER.is_relative_to(d) for d in site.getsitepackages())
