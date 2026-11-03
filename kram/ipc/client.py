"""Talks to the privileged helper over a pkexec'd QProcess, one request at a time.

The helper stays alive for the whole session, so the password is asked once, not per transaction.
"""
import json
import os
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, Signal

HELPER = Path(__file__).resolve().parent.parent / "helper" / "kram_helper.py"
# pkexec exit codes: the user dismissed the dialog / is not authorized
PKEXEC_CANCELLED = (126, 127)


class HelperClient(QObject):
    event = Signal(dict)        # every event line from the helper, including the final "done"
    failed = Signal(str)        # the helper could not be started or died; no "done" will follow

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc: QProcess | None = None
        self._buf = b""
        self.busy = False

    def _command(self) -> list[str]:
        cmd = [sys.executable, "-I", str(HELPER)]
        if os.environ.get("KRAM_HELPER_NO_PKEXEC") == "1":  # development/tests: run unprivileged
            return cmd + ["--allow-non-root"]
        return ["pkexec", *cmd]

    def _ensure_started(self) -> None:
        if self._proc is not None and self._proc.state() != QProcess.NotRunning:
            return
        self._buf = b""
        proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.SeparateChannels)
        proc.readyReadStandardOutput.connect(self._read)
        proc.readyReadStandardError.connect(lambda: self._forward_stderr(proc))
        proc.finished.connect(self._on_finished)
        proc.errorOccurred.connect(self._on_error)
        cmd = self._command()
        proc.start(cmd[0], cmd[1:])
        self._proc = proc

    def request(self, req: dict) -> None:
        """Send one request; events arrive via `event` until one with event == "done"."""
        if self.busy:
            raise RuntimeError("helper is busy")
        self._ensure_started()
        self.busy = True
        self._write(req)

    def answer(self, question_id: int, yes: bool) -> None:
        self._write({"op": "answer", "id": question_id, "yes": yes})

    def stop(self) -> None:
        if self._proc is not None and self._proc.state() != QProcess.NotRunning:
            self._write({"op": "quit"})
            self._proc.closeWriteChannel()
            if not self._proc.waitForFinished(3000):
                self._proc.kill()

    def _write(self, obj: dict) -> None:
        self._proc.write((json.dumps(obj) + "\n").encode())

    def _read(self) -> None:
        self._buf += bytes(self._proc.readAllStandardOutput())
        *lines, self._buf = self._buf.split(b"\n")
        for line in lines:
            if not line.strip():
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                ev = {"event": "log", "text": line.decode(errors="replace")}
            if ev.get("event") == "done":
                self.busy = False
            self.event.emit(ev)

    def _forward_stderr(self, proc: QProcess) -> None:
        # rpm scriptlet output and libdnf5 messages land here (the helper moves fd 1 to stderr)
        text = bytes(proc.readAllStandardError()).decode(errors="replace").rstrip()
        if text:
            self.event.emit({"event": "log", "text": text, "stderr": True})

    def _on_finished(self, code: int, _status) -> None:
        if self.busy:
            self.busy = False
            if code in PKEXEC_CANCELLED:
                self.failed.emit("Автентифікацію скасовано або доступ заборонено.")
            else:
                self.failed.emit(f"Привілейований процес несподівано завершився (код {code}).")

    def _on_error(self, error) -> None:
        if error == QProcess.FailedToStart and self.busy:
            self.busy = False
            self.failed.emit("Не вдалося запустити pkexec. Чи встановлено polkit?")
