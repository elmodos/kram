#!/bin/bash
# The terminal front end's root path for real (docs/TUI_SPEC.md §11), a manual check, not part of pytest: in a Fedora
# container booted with systemd, with polkit and a user "user" in wheel (password "secret"), scripts/tui_root_pty.py
# runs `python3 -m kram.tui` from this source tree as that user in a pseudo-terminal, as SSH gives one, and presses
# f5: Administrator rights, Continue, polkit's prompt, the password, Kram comes back and the metadata refresh runs as
# root. Also a wrong password (Try again offered), Ctrl+C at the prompt (Kram survives), and a real transaction:
# the user searches a small package (tree), marks it, reviews and applies it, authenticates, and rpm says it is
# installed; then it is marked for removal and applied again, and rpm says it is gone.
# The refresh and the transaction download: the container has the network, and the dnf cache is a volume
# (kram-dnf-cache-<release>), so it is quick after the first run.
# Usage: scripts/tui_root_check.sh [release, default 44]   (44: Textual 4.0, 45: Textual 8.1)
set -euo pipefail
release=${1:-44}
src=$(cd "$(dirname "$0")/.." && pwd)
used=$(find /proc/*/fd -user "$(id -u)" -lname 'anon_inode:inotify' 2>/dev/null | wc -l || true)
limit=$(sysctl -n fs.inotify.max_user_instances)
if [ $((limit - used)) -lt 32 ]; then
    echo "fs.inotify.max_user_instances is $limit and $used are in use; raise it until the next boot with:"
    echo "  sudo sysctl fs.inotify.max_user_instances=1024"
    exit 2
fi
name=kram-tui-root-$release
trap 'podman rm -f $name >/dev/null 2>&1 || true' EXIT

podman build -q -t "kram-tui-root:$release" - >/dev/null 2>&1 <<EOF
FROM registry.fedoraproject.org/fedora:$release
RUN dnf5 -y install systemd dbus-broker polkit util-linux sudo procps-ng python3-textual python3-libdnf5 \
        python3-rpm && dnf5 clean all \
 && echo keepcache=True >> /etc/dnf/dnf.conf \
 && useradd -m -G wheel user && echo user:secret | chpasswd
CMD ["/sbin/init"]
EOF
podman run -d --name "$name" --systemd=always -v "$src:/src:ro,Z" \
    -v "kram-dnf-cache-$release:/var/cache/libdnf5:Z" "kram-tui-root:$release" >/dev/null

podman exec -i "$name" bash -euo pipefail <<'TEST'
# polkit.service cannot set up its systemd sandbox in a rootless container (spike T3): polkitd started by hand drops
# to its own user and takes its bus name; what it decides is the same
systemctl is-system-running --wait >/dev/null 2>&1 || true
for _ in $(seq 60); do [ -S /run/dbus/system_bus_socket ] && break; sleep 0.5; done  # the system bus is up
/usr/lib/polkit-1/polkitd >/tmp/polkitd.log 2>&1 &
for _ in $(seq 30); do busctl status org.freedesktop.PolicyKit1 >/dev/null 2>&1 && break; sleep 0.5; done
busctl status org.freedesktop.PolicyKit1 >/dev/null 2>&1 || { echo "polkitd did not start"; cat /tmp/polkitd.log; exit 1; }
echo "Fedora $(rpm -E %fedora), Textual $(python3 -c 'import textual; print(textual.__version__)'), polkit $(rpm -q --qf '%{VERSION}' polkit)"
# the catalog Kram loads as the user is the system's cache: have one before the first start
dnf5 -q makecache >/dev/null
python3 /src/scripts/tui_root_pty.py
TEST
