#!/bin/bash
# Run real transactions through the helper as root inside a throwaway Fedora container (rootless podman).
# The host system is never touched. Usage: scripts/container_check.sh [fedora release, default 44]
set -euo pipefail
release=${1:-44}
src=$(cd "$(dirname "$0")/.." && pwd)
exec podman run --rm -v "$src:/src:ro,Z" "registry.fedoraproject.org/fedora:$release" bash -euo pipefail -c '
    dnf5 -q -y install python3-libdnf5 python3-rpm >/dev/null
    # forget the imported Fedora keys so the helper has to ask for them
    rpm -e $(rpm -q gpg-pubkey) >/dev/null
    d="python3 /src/scripts/helper_driver.py --direct"
    echo "### install fish (key import question expected)"
    $d "{\"op\":\"transaction\",\"install\":[\"fish\"]}"
    rpm -q fish
    echo "### mark fish as dependency, then reinstall"
    $d "{\"op\":\"transaction\",\"mark_dep\":[\"fish\"]}" "{\"op\":\"transaction\",\"reinstall\":[\"fish\"]}"
    dnf5 -q repoquery --installed --qf "%{name} %{reason}\n" fish
    echo "### remove fish (ncurses-term should go too, unneeded)"
    $d "{\"op\":\"transaction\",\"remove\":[\"fish\"]}"
    ! rpm -q fish ncurses-term
    echo "### unsatisfiable request"
    ! $d "{\"op\":\"transaction\",\"install\":[\"no-such-package-kram\"]}"
    echo "### download only"
    $d "{\"op\":\"transaction\",\"install\":[\"fish\"],\"download_only\":true}"
    ! rpm -q fish
    echo "### refresh metadata"
    $d "{\"op\":\"refresh\"}"
    echo "ALL CHECKS PASSED"
'
