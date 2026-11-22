#!/bin/bash
# Spike S10 (docs/GTK_FRONTEND.md §10, D9): does the package split work for existing users?
#   1. builds the last single-package kram (tag v0.11.3) and the split packages of the working tree (as 0.12.0);
#   2. in a Fedora container booted with systemd and a logged-in user (linger), installs the old kram, enables the
#      tray checker for the user, runs `dnf upgrade`: kram must become kram-qt + kram-common (never kram-gtk), and the
#      user units must stay enabled; three times from scratch, and once with `dnf distro-sync`;
#   3. `dnf swap kram-qt kram-gtk` and back; kram-gtk pulls in no Qt, kram-qt no GTK 4;
#   4. /usr/bin/kram is the alternatives link to the installed front end after each of these;
#   5. on a clean system `dnf install kram` installs kram-qt + kram-common, `dnf install kram-gtk` kram-gtk + kram-common.
# Usage: scripts/spikes/s10_split.sh [release, default 44]
set -euo pipefail
release=${1:-44}
src=$(cd "$(dirname "$0")/../.." && pwd)
# systemd, dbus-broker and the user manager in the rootless container each need an inotify instance, counted
# against the host user's limit, which a desktop session alone can use up (128 by default)
used=$(find /proc/*/fd -user "$(id -u)" -lname 'anon_inode:inotify' 2>/dev/null | wc -l || true)
limit=$(sysctl -n fs.inotify.max_user_instances)
if [ $((limit - used)) -lt 32 ]; then
    echo "fs.inotify.max_user_instances is $limit and $used are in use; raise it until the next boot with:"
    echo "  sudo sysctl fs.inotify.max_user_instances=1024"
    exit 2
fi
work=$(mktemp -d)
trap 'podman rm -f kram-s10 >/dev/null 2>&1 || true; rm -rf "$work"' EXIT
mkdir -p "$work/rpms"

echo "### build the old (v0.11.3) and the split (0.12.0) packages"
podman run --rm -v "$src:/src:ro,Z" -v "$work/rpms:/out:Z" -v "kram-dnf-cache-$release:/var/cache/libdnf5:Z" \
        "registry.fedoraproject.org/fedora:$release" bash -euo pipefail -c '
    echo keepcache=True >> /etc/dnf/dnf.conf
    dnf5 -q -y install rpm-build git-core "dnf5-command(builddep)" python3-devel >/dev/null 2>&1
    git config --global --add safe.directory "*"
    git config --global user.email check@localhost && git config --global user.name check
    cp -a /src /build && cd /build
    if [ -n "$(git status --porcelain)" ]; then git add -A && git commit -qm "uncommitted changes"; fi
    build() {  # $1 = git ref, $2 = version, $3 = output directory
        local dir=/tmp/srpm-$2
        mkdir -p "$dir"
        git archive --format=tar.gz --prefix="kram-$2/" -o "$dir/kram-$2.tar.gz" "$1"
        git show "$1:packaging/kram.spec" | sed "s/^%global base_version .*/%global base_version $2/" > "$dir/kram.spec"
        rpmbuild -bs "$dir/kram.spec" --define "_sourcedir $dir" --define "_srcrpmdir $dir" >/dev/null
        dnf5 -q -y builddep "$dir"/kram-*.src.rpm >/dev/null 2>&1
        rpmbuild -rr --nocheck "$dir"/kram-*.src.rpm --define "_srcrpmdir $dir/br" >/dev/null 2>&1 || true
        # written only when something is missing
        if ls "$dir"/br/*.buildreqs.nosrc.rpm >/dev/null 2>&1; then
            dnf5 -q -y builddep "$dir"/br/*.buildreqs.nosrc.rpm >/dev/null 2>&1
        fi
        if ! rpmbuild --rebuild --nocheck "$dir"/kram-*.src.rpm --define "_rpmdir $3" >/tmp/build.log 2>&1; then
            tail -40 /tmp/build.log; exit 1
        fi
    }
    build v0.11.3 0.11.3 /out/old
    build HEAD 0.12.0 /out/new
    find /out -name "*.rpm" -printf "%P\n"
'

echo "### a Fedora $release container with systemd and a user session"
podman build -q -t kram-s10:"$release" - >/dev/null <<EOF
FROM registry.fedoraproject.org/fedora:$release
RUN dnf5 -y install systemd dbus-broker util-linux createrepo_c procps-ng && dnf5 clean all \
 && useradd -m -u 1000 user && mkdir -p /var/lib/systemd/linger && touch /var/lib/systemd/linger/user
CMD ["/sbin/init"]
EOF
podman run -d --name kram-s10 --systemd=always -v "$work/rpms:/rpms:ro,Z" \
    -v "kram-dnf-cache-$release:/var/cache/libdnf5:Z" kram-s10:"$release" >/dev/null

podman exec -i kram-s10 bash -euo pipefail <<'TEST'
echo keepcache=True >> /etc/dnf/dnf.conf
rm -f /etc/rpm/macros.image-language-conf
mkdir -p /repo
printf '[kram-local]\nname=kram local\nbaseurl=file:///repo\ngpgcheck=0\nmetadata_expire=0\n' > /etc/yum.repos.d/kram-local.repo
for _ in $(seq 60); do systemctl is-active --quiet user@1000.service && break; sleep 1; done
systemctl is-active user@1000.service
units="kram-update-check.timer kram-update-check.path"
u() { SYSTEMD_BUS_TIMEOUT=15s systemctl --user -M user@ "$@"; }
repo() {  # $@ = directories of /rpms to publish
    rm -f /repo/*.rpm; for d in "$@"; do cp /rpms/$d/noarch/*.rpm /repo/; done
    createrepo_c -q /repo
}
fail() { echo "FAIL: $*"; exit 1; }
installed() { rpm -qa --qf '%{NAME}\n' 'kram*' | sort | tr '\n' ' '; }
launcher() {  # $1 = what was run, $2 = qt or gtk: /usr/bin/kram is the alternatives link to that front end
    local target
    target=$(readlink -f /usr/bin/kram) || fail "$1: no /usr/bin/kram"
    [ -L /usr/bin/kram ] && [ "$target" = /usr/libexec/kram/kram-$2 ] || fail "$1: /usr/bin/kram is $(ls -l /usr/bin/kram) → $target"
    [ "$(rpm -qf --qf '%{NAME}' /usr/bin/kram)" = "kram-$2" ] || fail "$1: /usr/bin/kram owned by $(rpm -qf /usr/bin/kram)"
    python3 -c "import ast, sys; ast.parse(open(sys.argv[1]).read())" "$target" || fail "$1: launcher"
    grep -q "^from kram.$2" "$target" || fail "$1: $target does not start kram.$2"
    echo "  /usr/bin/kram → $target"
}
enabled() { for unit in $units; do echo "$unit: $(u is-enabled $unit 2>&1)"; done; }
fresh_old() {
    dnf5 -q -y remove 'kram*' >/dev/null 2>&1 || true
    rm -rf /home/user/.config/systemd
    repo old
    dnf5 -q -y --refresh install kram >/dev/null 2>&1 || fail "install of the old kram"
    u daemon-reload
    u enable --now $units 2>/dev/null
    [ "$(installed)" = "kram " ] || fail "old: $(installed)"
    enabled | grep -qv ': enabled$' && fail "old units: $(enabled)"
    repo old new
}
check_split() {  # $1 = what was run
    [ "$(installed)" = "kram-common kram-qt " ] || fail "$1: installed $(installed)"
    echo "$1: installed $(installed)"
    enabled | sed "s/^/  /"
    enabled | grep -qv ': enabled$' && fail "$1: units not enabled"
    u is-active --quiet kram-update-check.timer || fail "$1: timer not running"
    echo "  timer and path active: $(u is-active $units | tr '\n' ' ')"
}

echo "### dnf upgrade, three times from scratch"
for run in 1 2 3; do
    fresh_old
    dnf5 -y --refresh upgrade > /tmp/upgrade.log 2>&1 || { cat /tmp/upgrade.log; fail "upgrade"; }
    if [ $run = 1 ]; then
        grep -E "^ *(Installing|Upgrading|Removing|Replacing)|kram" /tmp/upgrade.log | head -20
        echo "  scriptlet output of the old kram's %preun (the units it disabled):"
        grep -E "Removed" /tmp/upgrade.log | sed "s/^/    /" || echo "    (none)"
    fi
    check_split "upgrade $run"
    launcher "upgrade $run" qt
done

echo "### dnf distro-sync"
fresh_old
dnf5 -q -y --refresh distro-sync >/dev/null 2>&1 || fail "distro-sync"
check_split "distro-sync"
launcher distro-sync qt

echo "### kram-gtk over the old kram: the solver refuses (not rpm), dnf swap kram kram-gtk works"
fresh_old
if dnf5 -y --refresh install kram-gtk > /tmp/gtk-over-old.log 2>&1; then cat /tmp/gtk-over-old.log; fail "kram-gtk installed next to the old kram"; fi
grep -qi "conflict" /tmp/gtk-over-old.log || { cat /tmp/gtk-over-old.log; fail "kram-gtk over the old kram: not a solver conflict"; }
grep -i "rpm transaction failed\|file .* conflicts" /tmp/gtk-over-old.log && fail "kram-gtk over the old kram: failed in rpm"
[ "$(installed)" = "kram " ] || fail "after the refused install: $(installed)"
echo "install kram-gtk over the old kram: refused by the solver ($(grep -m1 -io "conflicts with [^ ]*" /tmp/gtk-over-old.log))"
dnf5 -q -y swap kram kram-gtk >/dev/null 2>&1 || fail "swap kram kram-gtk"
[ "$(installed)" = "kram-common kram-gtk " ] || fail "swap kram kram-gtk: $(installed)"
enabled | grep -qv ': enabled$' && fail "swap kram kram-gtk: units $(enabled)"
echo "swap kram kram-gtk: installed $(installed); units enabled"
launcher "swap kram kram-gtk" gtk
dnf5 -q -y swap kram-gtk kram-qt >/dev/null 2>&1 || fail "back to qt"

echo "### dnf swap kram-qt kram-gtk, and back"
dnf5 -q -y swap kram-qt kram-gtk >/dev/null 2>&1 || fail "swap to gtk"
[ "$(installed)" = "kram-common kram-gtk " ] || fail "swap to gtk: $(installed)"
enabled | grep -qv ': enabled$' && fail "swap to gtk: units $(enabled)"
echo "swap to gtk: installed $(installed); units enabled"
launcher "swap to gtk" gtk
dnf5 -q -y swap kram-gtk kram-qt >/dev/null 2>&1 || fail "swap to qt"
[ "$(installed)" = "kram-common kram-qt " ] || fail "swap to qt: $(installed)"
enabled | grep -qv ': enabled$' && fail "swap to qt: units $(enabled)"
echo "swap to qt: installed $(installed); units enabled"
launcher "swap to qt" qt

echo "### what each front end pulls in"
deps() { dnf5 -q repoquery --requires --resolve --recursive "$1" 2>/dev/null; }
deps kram-gtk | grep -iE "pyside|qt6-qtbase" && fail "kram-gtk pulls in Qt"
echo "kram-gtk: no Qt"
deps kram-qt | grep -E "^(gtk4|libadwaita)-[0-9]" && fail "kram-qt pulls in GTK 4"
echo "kram-qt: no GTK 4 / libadwaita"

echo "### dnf install kram on a clean system"
dnf5 -q -y remove 'kram*' >/dev/null 2>&1
repo new
dnf5 -q -y --refresh install kram >/dev/null 2>&1 || fail "install kram"
[ "$(installed)" = "kram-common kram-qt " ] || fail "install kram: $(installed)"
echo "install kram: $(installed)"
launcher "install kram" qt
dnf5 -q -y remove 'kram*' >/dev/null 2>&1
dnf5 -q -y install kram-gtk >/dev/null 2>&1 || fail "install kram-gtk"
[ "$(installed)" = "kram-common kram-gtk " ] || fail "install kram-gtk: $(installed)"
echo "install kram-gtk: $(installed)"
launcher "install kram-gtk" gtk
dnf5 -q -y remove 'kram*' >/dev/null 2>&1
[ -e /usr/bin/kram ] || [ -L /usr/bin/kram ] && fail "remove: /usr/bin/kram left behind"
[ -e /etc/alternatives/kram ] && fail "remove: /etc/alternatives/kram left behind"
echo "remove: no /usr/bin/kram, no alternative left"
echo "S10 PASSED"
TEST
