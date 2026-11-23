import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HELPER = Path(__file__).resolve().parent.parent / "kram" / "helper" / "kram_helper.py"


def talk(*lines: str) -> list[dict]:
    out = subprocess.run([sys.executable, "-I", str(HELPER), "--allow-non-root"],
                         input="".join(line + "\n" for line in lines), capture_output=True, text=True, timeout=30, check=False)
    return [json.loads(line) for line in out.stdout.splitlines()]


def test_ping():
    [ev] = talk('{"op": "ping"}')
    assert ev["ok"] is True


def test_rejects_bad_input():
    events = talk(
        '{"op": "transaction", "install": ["../etc/passwd"]}',
        '{"op": "transaction", "install": ["/usr/bin/foo"]}',
        '{"op": "transaction", "install": "fish"}',
        '{"op": "transaction"}',
        '{"op": "rm -rf"}',
        "not json",
        "[]",
        '{"op": "transaction", "downgrade": ["bash-5.0;rm"]}',
        '{"op": "transaction", "mark_user": [42]}',
        '{"op": "repo_set_enabled", "repos": {}}',
        '{"op": "repo_set_enabled", "repos": {"fedora; rm -rf /": true}}',
        '{"op": "repo_set_enabled", "repos": {"fedora": "yes"}}',
        '{"op": "copr", "action": "enable", "project": "owner/proj --hub=evil"}',
        '{"op": "copr", "action": "build", "project": "owner/proj"}',
        '{"op": "copr", "action": "enable", "project": "owner/proj", "hub": "evil.example/x"}',
        '{"op": "copr", "action": "enable", "project": "-y/x"}',
        '{"op": "copr", "action": "enable", "project": "owner/-x"}',
        '{"op": "copr", "action": "enable", "project": "owner/x", "hub": "-evil"}',
        '{"op": "repo_set_enabled", "repos": {"-fedora": true}}',
        '{"op": "transaction", "install": ["fish"], "exclude_weak": ["../etc/passwd"]}',
        '{"op": "transaction", "exclude_weak": ["qemu-kvm-core"]}',
        '{"op": "transaction", "install": ["fish"], "upgrade_all": "false"}',
        '{"op": "transaction", "install": ["fish"], "test": 1}',
        '{"op": "transaction", "install": ["fish"], "download_only": "yes"}',
        '{"op": "local_install", "path": "fish.rpm", "sha256": "' + "0" * 64 + '"}',
        '{"op": "local_install", "path": "/etc/shadow", "sha256": "' + "0" * 64 + '"}',
        '{"op": "local_install", "path": "/tmp/fish.rpm", "sha256": "' + "A" * 64 + '"}',
        '{"op": "local_install", "path": "/tmp/fish.rpm", "sha256": "' + "0" * 64 + '", "action": "remove"}',
        '{"op": "local_install", "path": "/tmp/fish.rpm", "sha256": "' + "0" * 64 + '", "exclude_weak": ["a/b"]}',
        '{"op": "clean_cache"}',
        '{"op": "clean_cache", "target": "/var/cache"}',
        '{"op": "clean_cache", "target": ["packagekit"]}',
        '{"op": "transaction", "group_install": ["-y"]}',
        '{"op": "transaction", "group_install": ["kde apps"]}',
        '{"op": "transaction", "group_remove": "kde-apps"}',
        '{"op": "transaction", "group_upgrade": ["@kde-apps"]}',
        '{"op": "transaction", "environment_install": ["env:kde-desktop-environment"]}',
        '{"op": "transaction", "environment_install_optional": ["--with-optional"]}',
        '{"op": "transaction", "group_install_optional": "kde-apps"}',
        '{"op": "transaction", "revert": [7, 8]}',
        '{"op": "transaction", "revert": ["7"]}',
        '{"op": "transaction", "revert": [true]}',
        '{"op": "transaction", "revert": [0]}',
        '{"op": "transaction", "revert": [7], "install": ["fish"]}',
        '{"op": "transaction", "revert": [7], "skip_unavailable": "yes"}',
        '{"op": "repo_remove"}',
        '{"op": "repo_remove", "repos": []}',
        '{"op": "repo_remove", "repos": "code"}',
        '{"op": "repo_remove", "repos": ["../../etc/passwd"]}',
        '{"op": "repo_remove", "repos": ["-code"]}',
        '{"op": "repo_remove", "repos": [7]}',
        '{"op": "remove_leftovers"}',
        '{"op": "remove_leftovers", "paths": []}',
        '{"op": "remove_leftovers", "paths": ["/etc/passwd"]}',
        '{"op": "remove_leftovers", "paths": ["/etc/x/../shadow.rpmsave"]}',
        '{"op": "remove_leftovers", "paths": ["/var/x.rpmsave"]}',
        '{"op": "mirrors"}',
        '{"op": "mirrors", "fastestmirror": "yes"}',
        '{"op": "mirrors", "pin": "updates"}',
        '{"op": "mirrors", "pin": {"repo": "-updates", "baseurl": null}}',
        '{"op": "mirrors", "pin": {"repo": "updates; rm", "baseurl": null}}',
        '{"op": "mirrors", "pin": {"baseurl": "https://mirror.example/fedora/"}}',
        '{"op": "mirrors", "pin": {"repo": "updates", "baseurl": "https://mirror.example/fedora"}}',
        '{"op": "mirrors", "pin": {"repo": "updates", "baseurl": "ftp://mirror.example/fedora/"}}',
        '{"op": "mirrors", "pin": {"repo": "updates", "baseurl": "file:///etc/"}}',
        '{"op": "mirrors", "pin": {"repo": "updates", "baseurl": "https://user:pw@mirror.example/fedora/"}}',
        '{"op": "mirrors", "pin": {"repo": "updates", "baseurl": "https://mirror.example/f/$releasever/"}}',
        '{"op": "mirrors", "pin": {"repo": "updates", "baseurl": "https://mirror.example/a b/"}}',
        '{"op": "mirrors", "pin": {"repo": "updates", "baseurl": "https://mirror.example/f/?x=1/"}}',
        '{"op": "mirrors", "pin": {"repo": "updates", "baseurl": 7}}',
        '{"op": "mirrors", "pin": {"repo": "no-such-repo-anywhere", "baseurl": null}}',
        '{"op": "refresh", "repos": []}',
        '{"op": "refresh", "repos": "fedora"}',
        '{"op": "refresh", "repos": ["-fedora"]}',
        '{"op": "refresh", "repos": ["fedora; rm -rf /"]}',
        '{"op": "refresh", "repos": [7]}',
    )
    assert len(events) == 76
    assert all(ev["event"] == "done" and ev["ok"] is False and ev["stage"] == "protocol" for ev in events)


def test_refuses_non_root_without_flag():
    out = subprocess.run([sys.executable, "-I", str(HELPER)], input="", capture_output=True, text=True, timeout=30, check=False)
    if out.returncode == 0:  # running the suite as root
        return
    assert json.loads(out.stdout)["stage"] == "startup"


def test_question_waits_for_answer():
    """ask() must consume exactly one reply line and treat anything but a matching yes as no."""
    import importlib.util
    import io

    spec = importlib.util.spec_from_file_location("kram_helper_under_test", HELPER)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    helper._proto = io.StringIO()
    for reply, expected in [('{"op": "answer", "id": 1, "yes": true}', True),
                            ('{"op": "answer", "id": 2, "yes": true}', False),   # wrong id
                            ('{"op": "answer", "id": 1, "yes": "true"}', False),  # not a bool
                            ("garbage", False), ("", False)]:
        sys.stdin, old = io.StringIO(reply + "\n" if reply else ""), sys.stdin
        try:
            assert helper.ask(1, kind="gpg_key") is expected
        finally:
            sys.stdin = old
    assert '"question"' in helper._proto.getvalue()


@pytest.mark.skipif(os.geteuid() == 0, reason="root passes the check")
def test_own_failures_carry_a_key_for_the_gui_to_translate():
    out = subprocess.run([sys.executable, "-I", str(HELPER)], input="", capture_output=True, text=True, timeout=30,
                         check=False, env={"LANG": "de_DE.UTF-8"})  # a locale that may not be installed: no crash
    [ev] = [json.loads(line) for line in out.stdout.splitlines()]
    assert ev == {"event": "done", "ok": False, "stage": "startup", "key": "not_root", "params": {},
                  "error": "The helper must run as root"}


def _load_helper():
    import importlib.util
    spec = importlib.util.spec_from_file_location("kram_helper_under_test", HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _ClosedPipe:
    def write(self, _text):
        raise BrokenPipeError(32, "Broken pipe")

    def flush(self):
        pass

    def close(self):  # closing flushes what is buffered: that fails too
        raise BrokenPipeError(32, "Broken pipe")


def test_emit_survives_a_closed_gui(monkeypatch):
    """rpm's callbacks call emit(): a write to a pipe the GUI closed must not raise into libdnf5, or the helper
    aborts in the middle of a transaction."""
    helper = _load_helper()
    monkeypatch.setattr(helper, "_proto", _ClosedPipe())
    monkeypatch.setattr(helper.os, "dup2", lambda *_args: None)  # the test runner's own fds stay as they are
    helper.emit("rpm", step="install")  # no exception
    assert helper._gui_gone
    helper.emit("done", ok=True)  # later events are dropped quietly


def test_guarded_callback_returns_its_default_with_a_closed_gui(monkeypatch):
    helper = _load_helper()
    monkeypatch.setattr(helper, "_proto", _ClosedPipe())
    monkeypatch.setattr(helper.os, "dup2", lambda *_args: None)

    @helper._guarded(7)
    def callback(*_args):
        raise ValueError("boom")

    assert callback(1) == 7


def test_helper_exits_cleanly_when_the_gui_closes_its_end():
    proc = subprocess.Popen([sys.executable, "-I", str(HELPER), "--allow-non-root"], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    proc.stdin.write('{"op": "ping"}\n')
    proc.stdin.flush()
    assert json.loads(proc.stdout.readline())["ok"] is True
    proc.stdout.close()  # the GUI is gone; the next reply has nowhere to go
    proc.stdin.write('{"op": "ping"}\n')
    proc.stdin.close()
    assert proc.wait(30) == 0
