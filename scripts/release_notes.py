#!/usr/bin/env python3
"""Write GitHub release notes for tags from the %changelog section of packaging/kram.spec.

Usage:
  scripts/release_notes.py v0.11.2          print the notes for one tag
  scripts/release_notes.py --all DIR        write DIR/<tag>.md for every v* tag

The notes are the changelog items of that version (all package releases of it, oldest first), the tag
date and the COPR install commands. Publish one with:
  gh release create v0.11.2 --title "Kram 0.11.2" --notes-file DIR/v0.11.2.md
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "packaging" / "kram.spec"

INSTALL = """\
## Installing

```sh
sudo dnf copr enable elmodos/Kram
sudo dnf install kram
```

Already installed: `sudo dnf upgrade kram`.
"""


def changelog() -> dict[str, list[str]]:
    """Version → changelog items, oldest package release first."""
    text = SPEC.read_text(encoding="utf-8").split("%changelog", 1)[1]
    entries: dict[str, list[list[str]]] = {}
    version = None
    for line in text.splitlines():
        header = re.match(r"\* .* - ([^-\s]+)-\S+$", line)
        if header:
            version = header.group(1)
            entries.setdefault(version, []).append([])
        elif line.startswith("- ") and version:
            entries[version][-1].append(line[2:].strip().replace("%%", "%"))
        elif line[:1].isspace() and line.strip() and version and entries[version][-1]:
            # an item wrapped onto the next lines
            entries[version][-1][-1] += " " + line.strip().replace("%%", "%")
    # the spec lists the newest package release first
    return {v: [item for rel in reversed(rels) for item in rel] for v, rels in entries.items()}


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def notes(tag: str, items: list[str]) -> str:
    date = git("log", "-1", "--format=%ad", "--date=short", tag)
    body = "\n".join(f"- {item}" for item in items)
    return f"Released {date}.\n\n## What's new\n\n{body}\n\n{INSTALL}"


def main() -> int:
    log = changelog()
    if len(sys.argv) == 3 and sys.argv[1] == "--all":
        out = Path(sys.argv[2])
        out.mkdir(parents=True, exist_ok=True)
        tags = git("tag", "--list", "v*", "--sort=v:refname").split()
        missing = [t for t in tags if t[1:] not in log]
        for tag in tags:
            if tag[1:] in log:
                (out / f"{tag}.md").write_text(notes(tag, log[tag[1:]]), encoding="utf-8")
        print(f"{len(tags) - len(missing)} notes written to {out}")
        if missing:
            print("no changelog entry for: " + " ".join(missing), file=sys.stderr)
            return 1
        return 0
    if len(sys.argv) == 2 and not sys.argv[1].startswith("-"):
        tag = sys.argv[1]
        if tag[1:] not in log:
            print(f"no changelog entry for {tag}", file=sys.stderr)
            return 1
        print(notes(tag, log[tag[1:]]), end="")
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
