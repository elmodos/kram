"""Running other programs without a toolkit, without blocking the main loop.

`run` waits for a program on a thread of its own and hands its exit code and output to the main loop through `post`
(kram.core.mainloop's contract). Kram uses it for `rpm -V` (the package file dialog checks what a reinstall would
repair) and `systemctl enable --now` (which waits while the desktop's polkit dialog asks for the password).
`spawn_detached` starts a program that outlives Kram: the desktop's software centre, from the Fedora N dialog.
"""
import os
import subprocess
import threading
from collections.abc import Callable, Mapping, Sequence

FAILED_TO_START = 127  # the shell's code for a program that is not there


class Process:
    """A running program. `kill` ends it, and its `done` is not called any more."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._popen: subprocess.Popen | None = None
        self._killed = False
        self.finished = False

    def kill(self) -> None:
        with self._lock:
            self._killed = True
            if self._popen is not None and self._popen.poll() is None:
                try:
                    self._popen.kill()
                except OSError:
                    pass

    @property
    def killed(self) -> bool:
        return self._killed

    @property
    def running(self) -> bool:
        return not self.finished and not self._killed


def run(argv: Sequence[str], *, post: Callable[[Callable[[], None]], None],
        done: Callable[[int, str, str], None], env: Mapping[str, str] | None = None) -> Process:
    """Run `argv` and call `done(code, stdout, stderr)` on the main thread. `env` is added to Kram's own
    environment. A program that cannot be started finishes with code `FAILED_TO_START` and the reason as its
    stderr. Output is decoded as UTF-8, bad bytes replaced."""
    process = Process()
    environment = {**os.environ, **env} if env else None

    def wait() -> None:
        try:
            with process._lock:
                if process._killed:
                    return
                popen = process._popen = subprocess.Popen(
                    list(argv), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    env=environment)
            out, err = popen.communicate()
            code = popen.returncode
            stdout, stderr = out.decode(errors="replace"), err.decode(errors="replace")
        except OSError as e:
            code, stdout, stderr = FAILED_TO_START, "", e.strerror or str(e)

        def deliver() -> None:
            process.finished = True
            if not process._killed:
                done(code, stdout, stderr)
        if not process._killed:
            post(deliver)

    threading.Thread(target=wait, name="kram-proc", daemon=True).start()
    return process


def spawn_detached(argv: Sequence[str]) -> bool:
    """Start `argv` in a session of its own, its output nowhere, and do not wait for it: it stays when Kram quits.
    False if it could not be started."""
    try:
        popen = subprocess.Popen(list(argv), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        return False
    threading.Thread(target=popen.wait, name="kram-reap", daemon=True).start()  # no zombie while Kram runs
    return True
