"""Waiting while another package manager (akmods after a kernel upgrade, dnf) holds the system repo lock."""
import pytest

from kram.core.updates import is_lock_error, waiting_for_lock

LOCKED = 'Failed to acquire system repo lock for reading, lock located at "/var/lib/dnf/system-repo.lock"'


class Error(Exception):  # stands in for libdnf5.exception.Error, which has no public constructor
    pass


def flaky(failures: int, error: str = LOCKED):
    calls = []

    def load():
        calls.append(1)
        if len(calls) <= failures:
            raise Error(error)
        return "base"
    return load, calls


def test_lock_error_is_recognised():
    assert is_lock_error(Error(LOCKED))
    assert not is_lock_error(Error("Failed to load repo fedora"))


def test_waits_until_the_lock_is_released():
    load, calls = flaky(3)
    waits, sleeps = [], []
    assert waiting_for_lock(load, lambda: waits.append(1), sleep=sleeps.append) == "base"
    assert len(calls) == 4
    assert waits == [1]  # told once, not on every retry
    assert len(sleeps) == 3


def test_no_wait_when_the_lock_is_free():
    load, _calls = flaky(0)
    waits = []
    assert waiting_for_lock(load, lambda: waits.append(1), sleep=lambda s: pytest.fail("slept")) == "base"
    assert waits == []


def test_other_errors_are_not_retried():
    load, calls = flaky(1, "Failed to load repo fedora")
    with pytest.raises(Error, match="fedora"):
        waiting_for_lock(load, sleep=lambda s: pytest.fail("slept"))
    assert len(calls) == 1


def test_gives_up_after_the_timeout():
    load, calls = flaky(1000)
    with pytest.raises(Error, match="repo lock"):
        waiting_for_lock(load, timeout=5, poll=1, sleep=lambda s: None)
    assert len(calls) == 6  # the first try and five more, one a second


def test_update_check_skips_a_locked_count(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    from kram import notifier
    from kram.notifier import check

    notifier.write_state({"count": 3, "severity": "low", "fingerprint": []})
    monkeypatch.setattr(check, "fingerprint", lambda: [["/var/lib/rpm/rpmdb.sqlite", 1]])

    def locked():
        raise Error(LOCKED)
    monkeypatch.setattr(check, "count", locked)
    monkeypatch.setattr(check, "systemctl", lambda verb: pytest.fail("touched the tray"))
    assert check.main() == 0
    assert notifier.read_state()["count"] == 3  # the previous state stays, so the next run counts again
    assert "skipped" in capsys.readouterr().out
