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
    )
    assert len(events) == 7
    assert all(ev["event"] == "done" and ev["ok"] is False and ev["stage"] == "protocol" for ev in events)


def test_refuses_non_root_without_flag():
    out = subprocess.run([sys.executable, "-I", str(HELPER)], input="", capture_output=True, text=True, timeout=30, check=False)
    if out.returncode == 0:  # running the suite as root
        return
    assert json.loads(out.stdout)["stage"] == "startup"
