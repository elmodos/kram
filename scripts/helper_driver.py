#!/usr/bin/python3
"""Feed JSON requests to the helper and print its events; answers every question with --yes/--no.

    python3 scripts/helper_driver.py --direct '{"op":"transaction","install":["fish"]}' ...

--direct runs the helper without pkexec (use inside a container where you already are root).
Exit status is 0 only if every request ended with ok=true.
"""
import json
import subprocess
import sys
from pathlib import Path

HELPER = Path(__file__).resolve().parent.parent / "kram" / "helper" / "kram_helper.py"


def main() -> int:
    args = sys.argv[1:]
    direct = "--direct" in args
    answer = "--no" not in args
    requests = [json.loads(a) for a in args if not a.startswith("--")]
    cmd = [sys.executable, "-I", str(HELPER)]
    if not direct:
        cmd = ["pkexec", *cmd]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
    results = []
    for req in requests:
        proc.stdin.write(json.dumps(req) + "\n")
        proc.stdin.flush()
        for line in proc.stdout:
            ev = json.loads(line)
            kind = ev["event"]
            if kind == "question":
                print("QUESTION", ev)
                proc.stdin.write(json.dumps({"op": "answer", "id": ev["id"], "yes": answer}) + "\n")
                proc.stdin.flush()
            elif kind == "download" and not ev.get("end") and ev.get("done") not in (0, ev.get("total")):
                continue  # intermediate download progress is noise here
            elif kind == "rpm" and ev.get("step") in ("install", "remove") and ev.get("done") not in (0, ev.get("total")):
                continue
            else:
                print(kind.upper(), {k: v for k, v in ev.items() if k != "event"})
            if kind == "done":
                results.append(ev.get("ok"))
                break
    proc.stdin.write('{"op": "quit"}\n')
    proc.stdin.close()
    proc.wait()
    return 0 if results and all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
