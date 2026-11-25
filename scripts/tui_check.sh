#!/bin/bash
# Checks for the terminal front end (docs/TUI_SPEC.md §14.2), in containers, on both Textual versions Kram supports:
#   44: ruff over the repository and the whole test suite in the kram-test:44 image (Textual 4.0.0 added for the
#       run, the image itself is not changed) — the GUIs' tests included, so a change for the TUI cannot break them;
#   45: the TUI tests (tests/test_tui*.py) and the parity test in Fedora 45 (Textual 8.1).
# Both containers run at the same time, each with pytest-xdist (added for the run like Textual) on its share of the
# processors: with every processor in each, timing-sensitive tests failed under the load. Their output comes after
# both are done, 44 first. The source tree is mounted with the shared label (:z), so that the
# two, and scripts/tui_root_check.sh, can use it at once.
#
# Usage: scripts/tui_check.sh [quick] [44|45]
#   quick   only the TUI and parity tests, in both containers (ruff still runs in 44)
#   44, 45  only that container
# KRAM_UPDATE_SNAPSHOTS=1 in the environment rewrites the TUI's snapshot files (tests/snapshots/tui/), each
# container its own Textual's set.
# While working: `scripts/tui_check.sh quick 45` (the newest Textual, about a minute). Before a merge into main:
# `scripts/tui_check.sh`, both versions and the whole suite.
set -euo pipefail
src=$(cd "$(dirname "$0")/.." && pwd)
mode=full
only=""
for arg in "$@"; do
    case $arg in
        quick) mode=quick ;;
        44|45) only=$arg ;;
        *) echo "usage: $0 [quick] [44|45]" >&2; exit 2 ;;
    esac
done
containers=2
[ -n "$only" ] && containers=1
workers=$(( $(nproc) / containers ))
[ "$workers" -ge 1 ] || workers=1
tui_tests="tests/test_parity.py $(cd "$src" && find tests -maxdepth 1 -name "test_tui*.py" | sort | tr "\n" " ")"
pytest="python3 -m pytest -q -p no:cacheprovider -rf -n $workers"

check_44() {
    podman run --rm -e KRAM_UPDATE_SNAPSHOTS -v "$src:/src:z" -v kram-dnf-cache-44:/var/cache/libdnf5:Z -w /src localhost/kram-test:44 bash -c "
        dnf5 -q -y install python3-textual python3-pytest-xdist >/dev/null 2>&1 \
            || { echo 'python3-textual, python3-pytest-xdist: install failed'; exit 1; }
        python3 -c 'import textual; print(\"Textual\", textual.__version__)'
        ruff check .
        if [ '$mode' = quick ]; then $pytest $tui_tests; else $pytest; fi"
}

check_45() {
    podman run --rm -e KRAM_UPDATE_SNAPSHOTS -v "$src:/src:z" -v kram-dnf-cache-45:/var/cache/libdnf5:Z -w /src registry.fedoraproject.org/fedora:45 bash -c "
        echo keepcache=True >> /etc/dnf/dnf.conf
        dnf5 -q -y install python3-textual python3-pytest python3-pytest-xdist python3-libdnf5 python3-rpm >/dev/null 2>&1 \
            || { echo 'test dependencies: install failed'; exit 1; }
        python3 -c 'import textual; print(\"Textual\", textual.__version__)'
        $pytest $tui_tests"
}

logs=$(mktemp -d)
trap 'rm -rf "$logs"' EXIT
declare -A pids
for release in 44 45; do
    if [ -z "$only" ] || [ "$only" = "$release" ]; then
        "check_$release" >"$logs/$release" 2>&1 &
        pids[$release]=$!
    fi
done
failed=0
for release in 44 45; do
    [ -n "${pids[$release]:-}" ] || continue
    title="Fedora 44, Textual 4.0"
    [ "$release" = 45 ] && title="Fedora 45, Textual 8.1"
    status=0
    wait "${pids[$release]}" || status=$?
    echo "### $title"
    cat "$logs/$release"
    if [ "$status" -ne 0 ]; then
        echo "### $title: FAILED (exit $status)"
        failed=1
    fi
done
exit $failed
