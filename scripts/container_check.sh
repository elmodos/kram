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
    echo "### simulate an upgrade to the next release: as a normal user, nothing changes, the metadata is deleted"
    before=$(rpm -qa | sort | sha256sum)
    runuser -u kramuser -- env HOME=/home/kramuser PYTHONPATH=/src python3 -c "
from kram.core.upgrade_audit import cache_dir, simulate
import os
r = simulate(str($(rpm -E %fedora) + 1))
print(\"resolved\", r.resolved, \"upgrades\", r.upgrades, \"download\", r.download, \"blockers\", len(r.blockers))
assert r.resolved and r.upgrades > 0 and r.download > 0 and r.free > 0
assert not os.path.exists(cache_dir())"
    test "$before" = "$(rpm -qa | sort | sha256sum)"
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
    echo "### version lock: a package installed from the release repository while updates has a newer one"
    lockpkg=""
    for n in tmux jq nano htop strace wget2 less vim-minimal; do
        old=$(dnf5 -q repoquery --repo fedora --latest-limit 1 --qf "%{evr}" "$n.x86_64" 2>/dev/null)
        new=$(dnf5 -q repoquery --repo updates --latest-limit 1 --qf "%{evr}" "$n.x86_64" 2>/dev/null)
        if [ -n "$old" ] && [ -n "$new" ] && [ "$old" != "$new" ]; then lockpkg=$n; break; fi
    done
    test -n "$lockpkg"
    dnf5 -q -y install --repo fedora "$lockpkg" >/dev/null
    echo "### a package that is not installed cannot be locked"
    ! $d "{\"op\":\"versionlock\",\"action\":\"add\",\"names\":[\"fish\"]}"
    test ! -s /etc/dnf/versionlock.toml || ! grep -q fish /etc/dnf/versionlock.toml
    echo "### lock $lockpkg $old: the catalog shows it locked, without an upgrade, holding back $new"
    $d "{\"op\":\"versionlock\",\"action\":\"add\",\"names\":[\"$lockpkg\"]}"
    grep -q "$old" /etc/dnf/versionlock.toml
    PYTHONPATH=/src python3 -c "
from kram.core.catalog import Catalog
from kram.core.model import Status
c = Catalog()
rows = {r.name: r for r in c.load().rows}
r = rows[\"$lockpkg\"]
print(r.status, r.locks, r.candidate_evr, r.held_evr, [a.id for a in r.held_advisories])
assert r.locked and r.status is Status.INSTALLED and r.candidate_evr == \"$old\" and r.held_evr == \"$new\"
assert r.locks[0].conditions == \"evr = $old\" and \"versionlock add\" in r.locks[0].comment
assert not r.advisories
v = c.details(r.key).versions
print([(x.evr, x.installed, x.candidate, x.locked_out) for x in v])
assert any(x.evr == \"$new\" and x.locked_out for x in v)
p = c.resolve({\"upgrade\": [\"$lockpkg-$new.x86_64\"]})
print(p.problems, p.versionlock)
assert not p.ok and p.versionlock"
    echo "### unlock: the upgrade is back"
    $d "{\"op\":\"versionlock\",\"action\":\"delete\",\"names\":[\"$lockpkg\"]}"
    ! grep -q "$lockpkg" /etc/dnf/versionlock.toml
    PYTHONPATH=/src python3 -c "
from kram.core.catalog import Catalog
from kram.core.model import Status
r = {r.name: r for r in Catalog().load().rows}[\"$lockpkg\"]
assert not r.locked and r.status is Status.UPGRADABLE and not r.held_evr"
    echo "### environment: install one through the helper; the catalog shows it installed, with its groups"
    # as on a real system: the protected packages the environment would bring are there already, else undoing it
    # would have to remove them and dnf refuses
    dnf5 -q -y install systemd systemd-udev selinux-policy-targeted >/dev/null
    rpm -qa | sort > /tmp/before_env
    $d "{\"op\":\"transaction\",\"environment_install\":[\"custom-environment\"]}"
    dnf5 -q environment list --installed | grep -q custom-environment
    PYTHONPATH=/src python3 -c "
from kram.core.catalog import Catalog
c = Catalog()
snap = c.load()
env = next(e for e in snap.environments if e.id == \"custom-environment\")
print(env.key, env.installed, env.groups, env.optional_groups)
assert env.installed and env.groups and env.packages
print(\"upgradable\", c.upgradable_groups([env.key]))  # the image is older than updates: its packages may be
removal = c.resolve({\"environment_remove\": [env.id]})
assert (\"remove\", env.key) in [(g.action, g.id) for g in removal.groups]"
    echo "### undo the environment install: the history shows its groups; reverting takes packages and records back"
    envtid=$(PYTHONPATH=/src python3 -c "
from kram.core.catalog import Catalog
from kram.core.history import changes_comps, history_rows
c = Catalog()
c.load()
tid = c.history()[0].id
rows = history_rows(c.history_items([tid])[tid])
print([(r.comps, r.arch) for r in rows if r.comps][:3], file=__import__(\"sys\").stderr)
assert changes_comps(rows) and any(r.comps == \"environment\" and r.arch == \"custom-environment\" for r in rows)
p = c.resolve({\"revert\": [tid]})
assert p.ok and (\"remove\", \"env:custom-environment\") in [(g.action, g.id) for g in p.groups], p.problems
print(tid)")
    $d "{\"op\":\"transaction\",\"revert\":[$envtid]}"
    ! dnf5 -q environment list --installed | grep -q custom-environment
    ! dnf5 -q group list --installed | grep -qw core
    diff <(rpm -qa | sort) /tmp/before_env
    echo "### group with its optional packages: the smallest group that has some"
    optgroup=$(PYTHONPATH=/src python3 -c "
from kram.core.catalog import Catalog
snap = Catalog().load()
installed = {r.name for r in snap.rows if r.installed}
g = min((g for g in snap.groups if g.visible and not g.installed and g.optional and len(g.packages) < 15),
        key=lambda g: len(g.packages))
print(g.id, *sorted(g.optional - installed))")
    set -- $optgroup
    gid=$1; shift
    $d "{\"op\":\"transaction\",\"group_install_optional\":[\"$gid\"]}"
    dnf5 -q group list --installed | grep -q "$gid"
    rpm -q "$@"
    echo "ALL CHECKS PASSED"
'
