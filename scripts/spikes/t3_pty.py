"""Spike T3, the driver (runs in the container of t3_root.sh, as root): starts spike T2 as the user "user" in a
pseudo-terminal, as a person at a terminal would, and drives the root path of docs/TUI_SPEC.md §11 with no polkit
agent: F5 → pkexec without a terminal fails → the explanation → Continue → Kram steps aside → polkit's text agent
asks → the answer → Kram comes back. Scenarios: the right password, a wrong one until polkit gives up, Ctrl+C at the prompt.

Prints what it saw and the pkexec results T2 wrote; exit status 1 when a scenario did not go as §11 says.
"""
import fcntl
import os
import pty
import re
import select
import struct
import sys
import termios
import time

ANSI = re.compile(rb"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[()][0-9A-B]|\x1b[=>]")
F5, ENTER, ESC, CTRL_C, WRONG = b"\x1b[15~", b"\r", b"\x1b", b"\x03", b"wrong\r"
LOG = "/tmp/t3.log"


class Term:
    def __init__(self, argv: list[str], cols: int = 120, rows: int = 32):
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.execvp(argv[0], argv)
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        self.raw = b""

    def read(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while (left := end - time.monotonic()) > 0:
            r, _, _ = select.select([self.fd], [], [], left)
            if not r:
                return
            try:
                chunk = os.read(self.fd, 65536)
            except OSError:
                return
            if not chunk:
                return
            self.raw += chunk

    def text(self, since: int = 0) -> str:
        return ANSI.sub(b"", self.raw[since:]).decode("utf-8", "replace")

    def wait_for(self, needle: str, seconds: float, since: int = 0) -> bool:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if needle in self.text(since):
                return True
            self.read(0.2)
        return needle in self.text(since)

    def send(self, data: bytes, pause: float = 0.3) -> None:
        os.write(self.fd, data)
        self.read(pause)

    def finish(self, seconds: float = 10) -> int | None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.read(0.2)
            pid, status = os.waitpid(self.pid, os.WNOHANG)
            if pid:
                return os.waitstatus_to_exitcode(status)
        return None


def run(name: str, answer: list[bytes], expect_after: str) -> bool:
    if os.path.exists(LOG):
        os.remove(LOG)
    env = (f"KRAM_SPIKE_SNAPSHOT=/out/snapshot44.pickle KRAM_SPIKE_PKEXEC=1 KRAM_SPIKE_ROOT=0 "
           f"KRAM_SPIKE_LOG={LOG} TERM=xterm-256color LANG=C.UTF-8")
    # --pty: a terminal of its own, as SSH gives; plain `su -c` runs the command in a new session without one
    t = Term(["su", "-l", "user", "--pty", "-c", f"cd /src && {env} python3 scripts/spikes/t2_dialogs.py"])
    ok = True

    def check(cond: bool, what: str) -> None:
        nonlocal ok
        print(f"  {'ok  ' if cond else 'FAIL'} {what}")
        ok &= cond

    print(f"### {name}")
    check(t.wait_for("Packages", 60), "the window is up")
    t.send(F5, 1)
    check(t.wait_for("Administrator rights", 15), "no agent: the explanation is shown")
    t.read(3)  # let the dialog take the focus before the key
    mark = len(t.raw)
    t.send(ENTER, 0.5)
    check(t.wait_for("Password:", 15, mark), "Kram stepped aside, polkit's text agent asks")
    seen = t.raw[mark:]
    left = seen.find(b"\x1b[?1049l")
    check(left != -1 and left < seen.find(b"Password:"), "the alternate screen was left before the prompt")
    check("Kram needs administrator rights" in t.text(mark), "Kram's one line of context is on the terminal")
    if answer == [WRONG]:  # wrong until polkit gives up: how many tries does it give?
        tries = 0
        while tries < 6:
            mark = len(t.raw)
            t.send(WRONG, 0.2)
            tries += 1
            end = time.monotonic() + 30
            while time.monotonic() < end and "Password:" not in t.text(mark) and "Not authorized" not in t.text(mark):
                t.read(0.2)
            if "Not authorized" in t.text(mark) or "Password:" not in t.text(mark):
                break
        print(f"  polkit took {tries} wrong passwords, then: "
              f"{' / '.join(x.strip() for x in t.text(mark).splitlines() if 'auth' in x.lower())[:200]}")
    else:
        for a in answer:
            mark = len(t.raw)  # before the answer: Kram may be back within the send's pause
            t.send(a, 0.5)
    check(t.wait_for(expect_after, 40, mark), f"Kram came back and shows “{expect_after}”")
    if expect_after not in t.text(mark):  # why not: the processes and the end of what the terminal got
        os.system("ps -eo pid,pgid,tpgid,stat,wchan:20,cmd | grep -E 'python3|pkexec|polkit-agent' | grep -v grep")
        print("  the terminal since the last answer:", repr(t.text(mark)[-600:]))
    back = t.raw[mark:]
    check(b"\x1b[?1049h" in back, "the alternate screen was entered again")
    t.send(ESC, 0.6)
    t.send(ESC, 0.6)
    t.send(b"q", 0.5)
    code = t.finish()
    check(code == 0, f"Kram quit cleanly (exit {code})")
    print("  pkexec, as T2 recorded it:")
    for line in open(LOG).read().splitlines() if os.path.exists(LOG) else ["(no log)"]:
        print("   ", line)
    return ok


def main() -> None:
    results = [
        run("right password", [b"secret\r"], "Refreshing repository metadata"),
        run("wrong password until polkit gives up", [WRONG], "Not authorized (pkexec"),
        run("Ctrl+C at the prompt", [CTRL_C], "cancelled"),
    ]
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
