"""The driver of scripts/tui_root_check.sh (runs in its container, as root): starts `python3 -m kram.tui` from the
source tree as the user "user" in a pseudo-terminal, as SSH would give one, and drives the root path of
docs/TUI_SPEC.md §11 where no polkit agent runs: f5 → pkexec without a terminal fails → Administrator rights →
Continue → Kram steps aside → polkit's text agent asks → the answer → Kram comes back.

Scenarios: the right password (the reload runs, the helper runs as root, a second f5 asks nothing), a wrong one
(Not authorized, Try again offered), Ctrl+C at the prompt (Kram survives and quits cleanly), and a real transaction
(§7.5, §10.1): search a small package that is not installed, mark it with +, review it with a, apply with ctrl+a,
authenticate, and check with rpm that it is installed; then mark it with - and apply again (no password the second
time), and check that it is gone. Exit status 1 when one did not go as the spec says.
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
F5, ENTER, ESC, CTRL_C, CTRL_A = b"\x1b[15~", b"\r", b"\x1b", b"\x03", b"\x01"
DOWN, RIGHT, TAB, SHIFT_TAB = b"\x1b[B", b"\x1b[C", b"\t", b"\x1b[Z"
PACKAGE = os.environ.get("KRAM_CHECK_PACKAGE", "tree")  # small, no dependencies beyond glibc, not in the image
REPO = os.environ.get("KRAM_CHECK_REPO", "updates-testing")  # a repository of the image's own files
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


def run(name: str, scenario, reload: bool = True) -> bool:
    """`reload`: the scenario starts at the Administrator rights of f5; else at the loaded window."""
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
    if reload:
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


def installed(name: str) -> bool:
    return subprocess.run(["rpm", "-q", name], capture_output=True).returncode == 0


def apply_marked(t: Term, check, what: str, authenticate: bool) -> None:
    """`a`, the review, ctrl+a, the password when asked, the transaction to its end, Close."""
    mark = len(t.raw)
    t.send(b"a", 0.5)
    check(t.wait_for("Apply changes", 120, mark), f"a: the Apply changes dialog reviews {what}")
    check(t.seen(f"{what} (1)", mark) and t.seen(PACKAGE, mark), f"…{what}: {PACKAGE}")
    check(t.seen("sudo dnf5", mark), "…with the dnf5 command")
    t.read(1)
    mark = len(t.raw)
    t.send(CTRL_A, 1)
    if authenticate:
        check(t.wait_for("Administrator rights", 30, mark), "ctrl+a: the transaction needs administrator rights")
        t.read(1)
        to_prompt(t, check)
        t.send(b"secret\r", 0.5)
    else:
        check(not t.wait_for("Administrator rights", 3, mark), "ctrl+a: no password asked again")
    check(t.wait_for("Applying changes", 60, mark), "the progress dialog shows the transaction")
    end = time.monotonic() + REFRESH_SECONDS
    while time.monotonic() < end and not t.seen("Done.", mark) and not t.seen("Error:", mark):
        if t.seen("Import key", mark):  # a repository's key, the first time (§10.2): Yes is focused
            t.send(ENTER, 1)
            mark = len(t.raw)
        t.read(1)
    check(t.seen("Done.", mark), "the transaction ran to its end")
    mark = len(t.raw)
    t.send(ENTER, 2)  # Close; the catalog loads again
    check(t.wait_for("Metadata:", 120, mark), "…and Kram reloaded the catalog")


def transaction(t: Term, check) -> None:
    check(not installed(PACKAGE), f"{PACKAGE} is not installed before")
    check(t.wait_for("Metadata:", 120), "the catalog is loaded")
    t.read(1)
    mark = len(t.raw)
    t.send(b"/", 1)
    t.send(PACKAGE.encode(), 1.5)
    t.send(ENTER, 1)
    check(t.wait_for(f"“{PACKAGE}” in All", 20, mark), f"the search for {PACKAGE} filters the list")
    mark = len(t.raw)
    t.send(b"+", 1)
    check(t.wait_for("1 change marked", 10, mark), "+: marked for installation, the top line counts it")
    apply_marked(t, check, "To be installed", authenticate=True)
    check(installed(PACKAGE), f"rpm -q {PACKAGE}: installed")
    mark = len(t.raw)
    t.send(b"-", 2)
    check(t.wait_for("1 change marked", 10, mark), "-: marked for removal")
    apply_marked(t, check, "To be removed", authenticate=False)
    check(not installed(PACKAGE), f"rpm -q {PACKAGE}: removed")


def repo_enabled(repo: str) -> bool:
    out = subprocess.run(["dnf5", "repolist", "--enabled"], capture_output=True, text=True).stdout
    return any(line.split()[:1] == [repo] for line in out.splitlines())


def switch_repo(t: Term, check, on: bool, authenticate: bool) -> None:
    """Settings → Repositories, the filter, `space` on the repository, ctrl+a, the password when asked, the
    request to its end, Close; then dnf5 says whether it is on."""
    mark = len(t.raw)
    t.send(b"m", 1)
    for _ in range(3):  # File, Edit, Package, Settings
        t.send(DOWN, 0.3)
    t.send(RIGHT, 0.5)
    t.send(ENTER, 1)  # Repositories: the first entry of Settings
    check(t.wait_for("Show debuginfo and source repositories", 60, mark), "Settings → Repositories: the dialog")
    t.read(1)
    t.send(SHIFT_TAB, 0.5)  # from the table to the filter line
    t.send(REPO.encode(), 1)
    t.send(TAB, 0.5)  # back to the table: the repository is the only row
    mark = len(t.raw)
    t.send(b" ", 1)
    word = "on" if on else "off"
    check(t.wait_for(f"turn {word} {REPO}", 10, mark), f"space: {REPO} to be turned {word}, said under the table")
    mark = len(t.raw)
    t.send(CTRL_A, 1)
    if authenticate:
        check(t.wait_for("Administrator rights", 30, mark), "ctrl+a: changing repositories needs administrator rights")
        t.read(1)
        to_prompt(t, check)
        t.send(b"secret\r", 0.5)
    else:
        check(not t.wait_for("Administrator rights", 3, mark), "ctrl+a: no password asked again")
    check(t.wait_for("Changing repositories", 60, mark), "the progress dialog shows the request")
    check(t.wait_for("Done.", 120, mark), "…which ran to its end")
    mark = len(t.raw)
    t.send(ENTER, 2)  # Close; the catalog loads again
    check(t.wait_for("Metadata:", 300, mark), "…and Kram reloaded the catalog")
    check(repo_enabled(REPO) == on, f"dnf5 repolist: {REPO} is {word}")


def repositories(t: Term, check) -> None:
    before = repo_enabled(REPO)
    check(t.wait_for("Metadata:", 120), "the catalog is loaded")
    t.read(1)
    switch_repo(t, check, not before, authenticate=True)
    switch_repo(t, check, before, authenticate=False)


def main() -> None:
    results = [run("right password", right_password), run("wrong password", wrong_password),
               run("Ctrl+C at the prompt", ctrl_c), run("a transaction: install, then remove", transaction, False),
               run(f"repositories: {REPO} on and off", repositories, False)]
    print("### result:", "all scenarios ok" if all(results) else "FAILED", flush=True)
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
