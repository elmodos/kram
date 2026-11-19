"""dnf's version lock: what the catalog makes of it, the list, the filters and the helper's request.

The real lock (dnf5 versionlock as root, libdnf5 hiding the locked-out versions) is checked in a container by
scripts/container_check.sh."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from kram.core.custom_filters import STATUS_LOCKED, Condition, CustomFilter, Field, Op, conditions_for_view
from kram.core.filters import status_filters
from kram.core.model import Advisory, CatalogSnapshot, Origin, PkgRow, Status, VersionLock
from kram.core.versionlock import NAME_RE, held_back, locks_for

HELPER = Path(__file__).resolve().parent.parent / "kram" / "helper" / "kram_helper.py"
LOCK = VersionLock("evr = 3.6a-1.fc44", "Added by 'versionlock add' command on 2026-11-19 10:53:53")
SECURITY = Advisory("FEDORA-2026-1", "security", "important", "tmux fix", 0)


def row(name="tmux", installed="3.6a-1.fc44", candidate="3.6a-1.fc44", status=Status.INSTALLED, **kw):
    return PkgRow(name, "x86_64", "", installed, candidate, "fedora", 1, Origin.FEDORA, status, **kw)


class Pkg:
    def __init__(self, evr):
        self.version, _dash, self.release = evr.rpartition("-")

    def get_epoch(self):
        return "0"

    def get_version(self):
        return self.version

    def get_release(self):
        return self.release


def test_locks_apply_by_name_and_by_glob():
    kernel = VersionLock("evr = 6.17.4-300.fc45")
    locks = {"tmux": (LOCK,), "kernel*": (kernel,)}
    assert locks_for(locks, "tmux") == (LOCK,)
    assert locks_for(locks, "kernel-core") == (kernel,)
    assert locks_for(locks, "tmux-plugins") == ()


def test_held_back_is_the_newest_excluded_version_newer_than_what_is_there():
    newest = {("tmux", "x86_64"): Pkg("3.8-2.fc44")}
    key = ("tmux", "x86_64")
    assert held_back(newest, key, Pkg("3.6a-1.fc44"), Pkg("3.6a-1.fc44")).release == "2.fc44"
    assert held_back(newest, key, None, Pkg("3.6a-1.fc44")) is not None   # a lock left without the package
    assert held_back(newest, key, Pkg("3.9-1.fc44"), None) is None         # nothing newer is held back
    assert held_back(newest, ("less", "x86_64"), Pkg("1-1"), None) is None


def test_lock_names_never_read_as_options():
    assert all(NAME_RE.match(n) for n in ("tmux", "kernel-core", "389-ds-base", "libstdc++", "python3.14"))
    assert not any(NAME_RE.match(n) for n in ("-y", "--setopt=x", "a b", "a/b", "", "../x", "tmux;rm"))


def test_held_advisories_do_not_count_as_upgrades():
    """A security fix the lock holds back is shown, but Security updates and the ways to mark upgrades leave it out:
    there is nothing to install."""
    locked = row(locks=(LOCK,), held_evr="3.8-2.fc44", held_advisories=(SECURITY,))
    snap = CatalogSnapshot([locked, row("less")], 2, 0, 0.0)
    counts = {e.id: e.count for e in status_filters(snap)}
    assert counts["status:locked"] == 1
    assert counts["status:security"] == 0 and counts["status:upgradable"] == 0


def test_the_locked_entry_stays_while_nothing_is_locked():
    """So that the user sees that packages can be locked at all."""
    entry = next(e for e in status_filters(CatalogSnapshot([row()], 1, 0, 0.0)) if e.id == "status:locked")
    assert not entry.hide_empty and entry.count == 0


def test_custom_filter_on_locked_versions():
    snap = CatalogSnapshot([row(locks=(LOCK,)), row("less")], 2, 0, 0.0)
    f = CustomFilter("Locked", [Condition(Field.STATUS, Op.IS, STATUS_LOCKED)])
    assert [r.name for r in snap.rows if f.compile(snap)(r)] == ["tmux"]
    assert conditions_for_view("status:locked", "", None) == [Condition(Field.STATUS, Op.IS, STATUS_LOCKED)]


def talk(*lines: str) -> list[dict]:
    out = subprocess.run([sys.executable, "-I", str(HELPER), "--allow-non-root"], check=False, timeout=30,
                         input="".join(line + "\n" for line in lines), capture_output=True, text=True)
    return [json.loads(line) for line in out.stdout.splitlines()]


def test_helper_rejects_bad_versionlock_requests():
    events = talk(*(json.dumps({"op": "versionlock", **req}) for req in (
        {"action": "add"},
        {"action": "add", "names": []},
        {"action": "add", "names": "tmux"},
        {"action": "add", "names": ["-y"]},
        {"action": "add", "names": ["--setopt=versionlock=0"]},
        {"action": "add", "names": ["tmux; rm -rf /"]},
        {"action": "add", "names": [7]},
        {"action": "exclude", "names": ["tmux"]},
        {"action": "clear", "names": ["tmux"]},
    )))
    assert len(events) == 9
    assert all(ev["event"] == "done" and ev["ok"] is False and ev["stage"] == "protocol" for ev in events)


@pytest.mark.skipif(os.geteuid() == 0, reason="as root it would really lock")
def test_helper_locks_installed_packages_only(tmp_path):
    """Without root the rpm check still runs: a name that is not installed is refused before dnf5 is started."""
    [ev] = talk(json.dumps({"op": "versionlock", "action": "add", "names": ["no-such-package-kram"]}))
    assert ev["ok"] is False and ev["key"] == "lock_not_installed"
    assert ev["params"] == {"names": "no-such-package-kram"}
