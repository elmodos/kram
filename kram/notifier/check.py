"""One update check, then exit (kram-update-check.service, started by its timer and path units).

Cheap when nothing changed: it compares the modification times of the cached repository metadata, the rpm
database and the repository configuration with the previous run, and only then loads libdnf5 to count. It never
touches the network: Fedora's dnf-makecache.timer (or Kram's Reload) refreshes the system cache, this only reads it.
Then it starts the tray service when there are upgrades and stops it when there are none.
"""
import glob
import os
import subprocess
import sys
import time

from . import TRAY_UNIT, read_state, write_state

SYSTEM_CACHEDIR = "/var/cache/libdnf5"  # libdnf5's system_cachedir; read from its config only when counting
WATCHED = [
    f"{SYSTEM_CACHEDIR}/*/repodata/repomd.xml",  # a repository refreshed (dnf-makecache.timer, Kram's Reload)
    "/var/lib/rpm/rpmdb.sqlite",                 # a transaction ran
    "/etc/yum.repos.d/*.repo",                   # a repository enabled, disabled, added or removed
    "/etc/dnf/dnf.conf",                         # excludes
    "/etc/dnf/versionlock.toml",
]


def fingerprint() -> list[list]:
    entries = []
    for pattern in WATCHED:
        for path in sorted(glob.glob(pattern)):
            try:
                entries.append([path, os.stat(path).st_mtime_ns])
            except OSError:
                pass
    return entries


def count() -> dict:
    from ..core.updates import open_system_base, summarize  # libdnf5: only when something changed

    t0 = time.monotonic()
    summary = summarize(open_system_base())
    return {"count": summary.count, "severity": summary.severity, "security": summary.security,
            "metadata_age": summary.metadata_age, "checked_at": int(time.time()),
            "seconds": round(time.monotonic() - t0, 2)}


def systemctl(verb: str) -> None:
    subprocess.run(["systemctl", "--user", "--no-block", verb, TRAY_UNIT], check=False)


def main() -> int:
    force = "--force" in sys.argv
    previous = read_state()
    current = fingerprint()
    if not force and previous.get("fingerprint") == current and "count" in previous:
        result = previous
        print(f"unchanged: {result['count']} upgrades")
    else:
        result = {**count(), "fingerprint": current}
        write_state(result)
        print(f"counted: {result['count']} upgrades ({result['severity']}) in {result['seconds']} s")
    systemctl("start" if result["count"] else "stop")
    return 0


if __name__ == "__main__":
    sys.exit(main())
