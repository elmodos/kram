#!/usr/bin/python3
"""M0 check: start the helper through pkexec and run a *test* transaction (rpm --test, nothing is installed).

    python3 scripts/m0_helper_check.py fish
    python3 scripts/m0_helper_check.py --no-pkexec fish   # unprivileged: resolves, then fails at download
"""
import json
import subprocess
import sys
from pathlib import Path

HELPER = Path(__file__).resolve().parent.parent / "dnf_gui" / "helper" / "dnf_gui_helper.py"


def main() -> int:
    args = sys.argv[1:]
    no_pkexec = "--no-pkexec" in args
    pkgs = [a for a in args if not a.startswith("--")] or ["fish"]
    cmd = [sys.executable, "-I", str(HELPER)]
    cmd = cmd + ["--allow-non-root"] if no_pkexec else ["pkexec"] + cmd
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    requests = [{"op": "ping"}, {"op": "transaction", "install": pkgs, "test": True}, {"op": "quit"}]
    proc.stdin.write("".join(json.dumps(r) + "\n" for r in requests))
    proc.stdin.close()
    last_download = {}
    for line in proc.stdout:
        ev = json.loads(line)
        if ev["event"] == "download" and not ev.get("end"):
            # print each download at most every 25%
            pct = int(100 * ev["done"] / ev["total"]) if ev.get("total") else 0
            if pct // 25 == last_download.get(ev["id"], -1):
                continue
            last_download[ev["id"]] = pct // 25
        print(ev)
    return proc.wait()


if __name__ == "__main__":
    sys.exit(main())
