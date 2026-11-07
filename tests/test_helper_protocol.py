import json
import subprocess
import sys
from pathlib import Path

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
    )
    assert len(events) == 21
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
