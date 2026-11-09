#!/bin/bash
# Run real transactions through the helper as root inside a throwaway Fedora container (rootless podman).
# The host system is never touched. Usage: scripts/container_check.sh [fedora release, default 44]
set -euo pipefail
release=${1:-44}
src=$(cd "$(dirname "$0")/.." && pwd)
exec podman run --rm -v "$src:/src:ro,Z" "registry.fedoraproject.org/fedora:$release" bash -euo pipefail -c '
    dnf5 -q -y install python3-libdnf5 python3-rpm dnf5-plugins util-linux shadow-utils >/dev/null
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
    echo "### clean downloaded packages (fish from the download-only step)"
    find /var/cache/libdnf5 -name "*.rpm" | grep -q .
    $d "{\"op\":\"clean_cache\",\"target\":\"dnf_packages\"}"
    ! find /var/cache/libdnf5 -name "*.rpm" | grep -q .
    echo "### delete and download the metadata again"
    $d "{\"op\":\"clean_cache\",\"target\":\"dnf_metadata\"}"
    dnf5 -q --cacheonly repoquery fish | grep -q fish
    echo "### clean PackageKit: only rpms, not while an offline update is prepared"
    pk=/var/cache/PackageKit/44/metadata/fedora-abc
    mkdir -p "$pk/packages" "$pk/repodata"
    touch "$pk/packages/a.rpm" "$pk/repodata/primary.xml.zst" /root/outside.rpm
    ln -s /root/outside.rpm "$pk/packages/link.rpm"
    ln -s /var/cache /system-update
    ! $d "{\"op\":\"clean_cache\",\"target\":\"packagekit\"}"
    test -e "$pk/packages/a.rpm"
    rm /system-update
    $d "{\"op\":\"clean_cache\",\"target\":\"packagekit\"}"
    test ! -e "$pk/packages/a.rpm" -a -e "$pk/repodata/primary.xml.zst" -a -L "$pk/packages/link.rpm" -a -e /root/outside.rpm
    echo "### the cache of a normal user is cleaned without root and leaves the system cache alone"
    useradd kramuser
    runuser -u kramuser -- dnf5 -q makecache
    test -n "$(find /home/kramuser/.cache/libdnf5 -type f | head -1)"
    runuser -u kramuser -- dnf5 clean all
    test -z "$(find /home/kramuser/.cache/libdnf5 -type f | head -1)"
    dnf5 -q --cacheonly repoquery fish | grep -q fish
    echo "### refresh metadata"
    $d "{\"op\":\"refresh\"}"
    echo "### disable and re-enable a repository (dnf5 config-manager setopt)"
    $d "{\"op\":\"repo_set_enabled\",\"repos\":{\"fedora-cisco-openh264\":false}}"
    dnf5 -q repo list --disabled | grep -q fedora-cisco-openh264
    $d "{\"op\":\"repo_set_enabled\",\"repos\":{\"fedora-cisco-openh264\":true}}"
    dnf5 -q repo list --enabled | grep -q fedora-cisco-openh264
    echo "### unknown repository is rejected"
    ! $d "{\"op\":\"repo_set_enabled\",\"repos\":{\"no-such-repo\":true}}"
    copr_id=copr:copr.fedorainfracloud.org:wezfurlong:wezterm-nightly
    echo "### COPR enable"
    $d "{\"op\":\"copr\",\"action\":\"enable\",\"project\":\"wezfurlong/wezterm-nightly\"}"
    dnf5 -q repo list --enabled | grep -q "$copr_id"
    echo "### COPR repo id with dots and colons through setopt"
    $d "{\"op\":\"repo_set_enabled\",\"repos\":{\"$copr_id\":false}}"
    dnf5 -q repo list --disabled | grep -q "$copr_id"
    echo "### COPR enable again, disable, remove"
    $d "{\"op\":\"copr\",\"action\":\"enable\",\"project\":\"wezfurlong/wezterm-nightly\"}"
    $d "{\"op\":\"copr\",\"action\":\"disable\",\"project\":\"wezfurlong/wezterm-nightly\"}"
    dnf5 -q repo list --disabled | grep -q "$copr_id"
    $d "{\"op\":\"copr\",\"action\":\"remove\",\"project\":\"wezfurlong/wezterm-nightly\"}"
    ! dnf5 -q repo list --all | grep -q "$copr_id"
    echo "### COPR project that does not exist"
    ! $d "{\"op\":\"copr\",\"action\":\"enable\",\"project\":\"nobody-kram/no-such-project\"}"
    echo "ALL CHECKS PASSED"
'
