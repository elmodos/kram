"""The driver of scripts/tui_root_check.sh (runs in its container, as root): starts `python3 -m kram.tui` from the
source tree as the user "user" in a pseudo-terminal, as SSH would give one, and drives the root path of
docs/TUI_SPEC.md §11 where no polkit agent runs: f5 → pkexec without a terminal fails → Administrator rights →
Continue → Kram steps aside → polkit's text agent asks → the answer → Kram comes back.

Scenarios: the right password (the reload runs, the helper runs as root, a second f5 asks nothing), a wrong one
(Not authorized, Try again offered), Ctrl+C at the prompt (Kram survives and quits cleanly). Exit status 1 when one
did not go as §11 says.
"""
import fcntl
import os
import pty
import re
import select
import struct
import subprocess
import sys
import termios
import time

ANSI = re.compile(rb"\x1b\[[0-9;?<>=]*[ -/]*[@-~]|\x1b[()][0-9A-B]|\x1b[=>]|\x1b\][^\x07\x1b]*(\x07|\x1b\\)")
F5, ENTER, ESC, CTRL_C = b"\x1b[15~", b"\r", b"\x1b", b"\x03"
REFRESH_SECONDS = int(os.environ.get("KRAM_CHECK_REFRESH_SECONDS", "600"))  # a metadata refresh over the network


class Term:
    def __init__(self, argv: list[str], cols: int = 120, rows: int = 36):
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
        # Textual moves the cursor instead of writing spaces: a cursor move counts as a space, so words stay apart
        return ANSI.sub(b" ", self.raw[since:]).decode("utf-8", "replace")

    def seen(self, needle: str, since: int = 0) -> bool:
        return needle in re.sub(r"\s+", " ", self.text(since))

    def wait_for(self, needle: str, seconds: float, since: int = 0) -> bool:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if self.seen(needle, since):
                return True
            self.read(0.2)
        return self.seen(needle, since)

    def send(self, data: bytes, pause: float = 0.3) -> None:
        os.write(self.fd, data)
        self.read(pause)

    def finish(self, seconds: float = 20) -> int | None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.read(0.2)
            pid, status = os.waitpid(self.pid, os.WNOHANG)
            if pid:
                return os.waitstatus_to_exitcode(status)
        return None


def helper_users() -> list[str]:
    """The users the helper processes run as."""
    out = subprocess.run(["ps", "-eo", "user:20,args"], capture_output=True, text=True).stdout
    return [line.split()[0] for line in out.splitlines() if "kram_helper.py" in line and "pkexec" not in line]


def start() -> Term:
    env = "TERM=xterm-256color LANG=C.UTF-8"
    # --pty: a terminal of its own, as SSH gives; plain `su -c` runs the command without one
    return Term(["su", "-l", "user", "--pty", "-c", f"cd /src && {env} python3 -m kram.tui"])


def run(name: str, scenario) -> bool:
    t = start()
    ok = True

    def check(cond: bool, what: str) -> bool:
        nonlocal ok
        print(f"  {'ok  ' if cond else 'FAIL'} {what}", flush=True)
        ok &= cond
        return cond

    print(f"### {name}", flush=True)
    if not check(t.wait_for("Packages", 90), "the window is up"):
        print("  the terminal:", repr(t.text()[-800:]))
        return False
    # f5 does nothing until the catalog is loaded: press it until the dialog comes
    mark = len(t.raw)
    end = time.monotonic() + 180
    while time.monotonic() < end and not t.seen("Administrator rights", mark):
        t.send(F5, 2)
    check(t.seen("Administrator rights", mark), "f5: no agent, so Kram says why it steps aside")
    check(t.seen("needs administrator rights", mark), "…with what needs them")
    t.read(1)  # let the dialog take the focus before the key
    scenario(t, check)
    t.send(ESC, 0.6)
    t.send(b"q", 1)
    code = t.finish()
    check(code == 0, f"Kram quit cleanly (exit {code})")
    if not ok:
        print("  the terminal at the end:", repr(re.sub(r"\s+", " ", t.text())[-1500:]))
    return ok


def to_prompt(t: Term, check) -> int:
    """Continue: Kram steps aside and polkit's text agent asks. Returns the mark after the prompt."""
    mark = len(t.raw)
    t.send(ENTER, 0.5)
    check(t.wait_for("Password:", 20, mark), "Continue: Kram stepped aside, polkit's text agent asks")
    seen = t.raw[mark:]
    left = seen.find(b"\x1b[?1049l")
    check(left != -1 and left < seen.find(b"Password:"), "the alternate screen was left before the prompt")
    check(t.seen("Kram needs administrator rights. Kram comes back when you have answered.", mark),
          "Kram's one line of context is on the terminal")
    return len(t.raw)


def right_password(t: Term, check) -> None:
    to_prompt(t, check)
    mark = len(t.raw)
    t.send(b"secret\r", 0.5)
    check(t.wait_for("Refreshing metadata", 30, mark), "Kram came back with the progress of the reload")
    check(b"\x1b[?1049h" in t.raw[mark:], "the alternate screen was entered again")
    check(helper_users() == ["root"], f"the helper runs as root (ps: {helper_users()})")
    check(t.wait_for("Done.", REFRESH_SECONDS, mark), "the refresh ran to its end")
    t.send(ENTER, 2)  # Close; the catalog loads again
    # the helper lives for the session: the next f5 asks nothing
    mark = len(t.raw)
    end = time.monotonic() + 120
    while time.monotonic() < end and not t.seen("Refreshing metadata", mark):
        t.send(F5, 2)
    check(t.seen("Refreshing metadata", mark) and not t.seen("Administrator rights", mark),
          "a second f5 runs at once, without asking again")
    check(t.wait_for("Done.", REFRESH_SECONDS, mark), "…and ends")
    t.send(ENTER, 2)


def wrong_password(t: Term, check) -> None:
    to_prompt(t, check)
    mark = len(t.raw)
    t.send(b"wrong\r", 0.5)
    check(t.wait_for("Not authorized", 30, mark), "a wrong password: Kram came back and says Not authorized")
    check(t.seen("Try again", mark), "…and offers to try again")
    t.read(1)
    to_prompt(t, check)  # Try again is the default: polkit asks again
    mark = len(t.raw)
    t.send(b"wrong\r", 0.5)
    check(t.wait_for("Not authorized", 30, mark), "a second wrong password: Not authorized again")
    t.read(1)
    t.send(ESC, 1)  # Cancel
    check(helper_users() == [], "no helper runs")


def ctrl_c(t: Term, check) -> None:
    to_prompt(t, check)
    mark = len(t.raw)
    t.send(CTRL_C, 0.5)
    check(t.wait_for("Authorization was cancelled.", 30, mark), "Ctrl+C at the prompt: Kram came back, cancelled")
    check(helper_users() == [], "no helper runs")
    t.read(1)
    t.send(ENTER, 1)  # Close


def main() -> None:
    results = [run("right password", right_password), run("wrong password", wrong_password),
               run("Ctrl+C at the prompt", ctrl_c)]
    print("### result:", "all scenarios ok" if all(results) else "FAILED", flush=True)
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
