#!/bin/bash
# Do not run tui_check.sh and tui_root_check.sh at the same time: both mount the source tree with :Z, and the
# relabelling of one takes /src away from the other's container.
# Checks for the terminal front end (docs/TUI_SPEC.md §14.2), in containers, on both Textual versions Kram supports:
#   1. ruff over the repository and the whole test suite in the kram-test:44 image (Textual 4.0.0 added for the run,
#      the image itself is not changed) — the GUIs' tests included, so a change for the TUI cannot break them;
#   2. the TUI tests (tests/test_tui*.py) and the parity test in Fedora 45 (Textual 8.1).
# Usage: scripts/tui_check.sh [quick]    quick: only the TUI and parity tests, in both containers
set -euo pipefail
src=$(cd "$(dirname "$0")/.." && pwd)
mode=${1:-full}
tui_tests="tests/test_parity.py $(cd "$src" && find tests -maxdepth 1 -name "test_tui*.py" | sort | tr "\n" " ")"

echo "### Fedora 44, Textual 4.0"
podman run --rm -v "$src:/src:Z" -v kram-dnf-cache-44:/var/cache/libdnf5:Z -w /src localhost/kram-test:44 bash -c "
    dnf5 -q -y install python3-textual >/dev/null 2>&1 || { echo 'python3-textual: install failed'; exit 1; }
    python3 -c 'import textual; print(\"Textual\", textual.__version__)'
    ruff check .
    if [ '$mode' = quick ]; then python3 -m pytest -q -p no:cacheprovider $tui_tests; else python3 -m pytest -q -p no:cacheprovider; fi"

echo "### Fedora 45, Textual 8.1"
podman run --rm -v "$src:/src:Z" -v kram-dnf-cache-45:/var/cache/libdnf5:Z -w /src registry.fedoraproject.org/fedora:45 bash -c "
    echo keepcache=True >> /etc/dnf/dnf.conf
    dnf5 -q -y install python3-textual python3-pytest python3-libdnf5 python3-rpm >/dev/null 2>&1 \
        || { echo 'test dependencies: install failed'; exit 1; }
    python3 -c 'import textual; print(\"Textual\", textual.__version__)'
    python3 -m pytest -q -p no:cacheprovider $tui_tests"
