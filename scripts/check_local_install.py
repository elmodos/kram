"""Run by scripts/rpm_check.sh as root inside the container: the installed helper's local_install.

Files belong to a normal user, as when the GUI asks pkexec; PKEXEC_UID is set the way pkexec sets it.
Usage: check_local_install.py <a .rpm file that is already installed> <a .rpm file of a package not installed>
"""
import hashlib
import json
import os
import pwd
import shutil
import subprocess
import sys

HELPER = "/usr/libexec/kram-helper"
USER = "kramtester"


def sha256(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def helper(**req) -> dict:
    env = {**os.environ, "PKEXEC_UID": str(pwd.getpwnam(USER).pw_uid)}
    line = json.dumps({"op": "local_install", **req}) + "\n"
    out = subprocess.run([HELPER], input=line, capture_output=True, text=True, env=env, timeout=600, check=False)
    events = [json.loads(x) for x in out.stdout.splitlines()]
    return events[-1] if events else {"stderr": out.stderr}


def expect(name: str, done: dict, ok: bool, error: str = "") -> None:
    good = done.get("ok") is ok and error in done.get("error", "")
    print(("ok   " if good else "FAIL ") + name + ("" if good else f": {done}"))
    if not good:
        sys.exit(1)


def main() -> None:
    installed = sys.argv[1]
    subprocess.run(["useradd", "-m", USER], check=True)
    home = pwd.getpwnam(USER).pw_dir
    own = os.path.join(home, "kram.rpm")
    shutil.copy(installed, own)
    shutil.chown(own, USER, USER)
    digest = sha256(own)

    expect("reinstall, test mode", helper(path=own, sha256=digest, action="reinstall", test=True), True)
    expect("the hash of another file", helper(path=own, sha256="0" * 64, action="reinstall", test=True),
           False, "changed after it was checked")
    secret = "/root/secret.rpm"
    shutil.copy(installed, secret)
    os.chmod(secret, 0o600)
    expect("a file only root can read", helper(path=secret, sha256=sha256(secret), action="reinstall", test=True),
           False, "Permission denied")
    link = os.path.join(home, "link.rpm")
    os.symlink(secret, link)
    expect("a symlink", helper(path=link, sha256=sha256(secret), action="reinstall", test=True),
           False, "Too many levels of symbolic links")
    fifo = os.path.join(home, "fifo.rpm")
    os.mkfifo(fifo)
    shutil.chown(fifo, USER, USER)
    expect("a FIFO", helper(path=fifo, sha256=digest, test=True), False, "not a regular file")
    os.makedirs("/srv", exist_ok=True)
    group_only = "/srv/group.rpm"
    shutil.copy(installed, group_only)
    os.chmod(group_only, 0o640)  # root:root, readable through root's group only
    expect("a file readable through root's group", helper(path=group_only, sha256=sha256(group_only), test=True),
           False, "Permission denied")
    not_rpm = os.path.join(home, "text.rpm")
    with open(not_rpm, "w") as f:
        f.write("not a package\n")
    shutil.chown(not_rpm, USER, USER)
    expect("not a package", helper(path=not_rpm, sha256=sha256(not_rpm), test=True), False)

    before = subprocess.run(["rpm", "-q", "--qf", "%{INSTALLTIME}", "kram"], capture_output=True, text=True).stdout
    expect("reinstall for real", helper(path=own, sha256=digest, action="reinstall"), True)
    after = subprocess.run(["rpm", "-q", "--qf", "%{INSTALLTIME}", "kram"], capture_output=True, text=True).stdout
    print(("ok   " if after >= before and after else "FAIL ") + "kram is still installed after the reinstall")
    leftovers = os.listdir("/var/cache/kram")
    mode = oct(os.stat("/var/cache/kram").st_mode & 0o777)
    good = not leftovers and mode == "0o700"
    print(("ok   " if good else "FAIL ") + f"/var/cache/kram is {mode} and empty: {leftovers}")
    if not good:
        sys.exit(1)

    fresh = os.path.join(home, os.path.basename(sys.argv[2]))
    shutil.copy(sys.argv[2], fresh)
    shutil.chown(fresh, USER, USER)
    name = subprocess.run(["rpm", "-qp", "--qf", "%{NAME}", fresh], capture_output=True, text=True).stdout
    expect(f"install {name} for real", helper(path=fresh, sha256=sha256(fresh)), True)
    record = subprocess.run(["dnf5", "-q", "repoquery", "--installed", "--qf", "%{reason} %{from_repo}\n", name],
                            capture_output=True, text=True).stdout.split()
    good = record == ["User", "@commandline"]
    print(("ok   " if good else "FAIL ") + f"{name} is recorded as installed by the user from @commandline: {record}")
    if not good:
        sys.exit(1)
    print("LOCAL INSTALL CHECKS PASSED")


if __name__ == "__main__":
    main()
