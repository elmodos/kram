#!/bin/bash
# Spike T3 (docs/TUI_SPEC.md §11.5): how kram-tui gets root where no polkit agent runs (SSH, a virtual console).
# In a Fedora container booted with systemd, polkit and a user "user" (wheel, password "secret"):
#   A. pkexec with no controlling terminal and no agent: does it fail at once, and with which code and message?
#   B. spike T2 in a pseudo-terminal, driven by t3_pty.py: the whole path with the right password, a wrong one three
#      times, and Ctrl+C at the prompt;
#   C. what sudo leaves of the user's environment (HOME, SUDO_USER): where kram-tui run with sudo reads settings.
# The desktop-agent path needs a desktop: it is checked on the author's system by hand (§11 of TUI_FRONTEND.md).
# Usage: scripts/spikes/t3_root.sh [release, default 44]   (44: Textual 4.0, 45: Textual 8.1)
# Needs KRAM_SPIKE_SNAPSHOT-style pickle at $T3_SNAPSHOT (a CatalogSnapshot, see t1_tui.py).
set -euo pipefail
release=${1:-44}
src=$(cd "$(dirname "$0")/../.." && pwd)
snapshot=${T3_SNAPSHOT:?set T3_SNAPSHOT to a pickled CatalogSnapshot}
used=$(find /proc/*/fd -user "$(id -u)" -lname 'anon_inode:inotify' 2>/dev/null | wc -l || true)
limit=$(sysctl -n fs.inotify.max_user_instances)
if [ $((limit - used)) -lt 32 ]; then
    echo "fs.inotify.max_user_instances is $limit and $used are in use; raise it until the next boot with:"
    echo "  sudo sysctl fs.inotify.max_user_instances=1024"
    exit 2
fi
name=kram-t3-$release
trap 'podman rm -f $name >/dev/null 2>&1 || true' EXIT

podman build -q -t "kram-t3:$release" - >/dev/null <<EOF
FROM registry.fedoraproject.org/fedora:$release
RUN dnf5 -y install systemd dbus-broker polkit util-linux sudo procps-ng python3-textual python3-libdnf5 \
        python3-rpm && dnf5 clean all \
 && useradd -m -G wheel user && echo user:secret | chpasswd
CMD ["/sbin/init"]
EOF
podman run -d --name "$name" --systemd=always -v "$src:/src:ro,Z" -v "$(dirname "$snapshot"):/out:ro,Z" \
    "kram-t3:$release" >/dev/null
podman exec "$name" bash -c 'ln -sf "/out/'"$(basename "$snapshot")"'" /out/snapshot44.pickle 2>/dev/null || true'

podman exec -i "$name" bash -euo pipefail <<'TEST'
# polkit.service cannot set up its systemd sandbox in a rootless container ("Failed to keep CAP_SYS_ADMIN", then
# exit 1); polkitd started by hand drops to its own user and takes its bus name: what it decides is the same
systemctl is-system-running --wait >/dev/null 2>&1 || true  # the system bus is up
/usr/lib/polkit-1/polkitd >/tmp/polkitd.log 2>&1 &
for _ in $(seq 30); do busctl status org.freedesktop.PolicyKit1 >/dev/null 2>&1 && break; sleep 0.5; done
busctl status org.freedesktop.PolicyKit1 >/dev/null 2>&1 || { echo "polkitd did not start"; cat /tmp/polkitd.log; exit 1; }
echo "Textual $(python3 -c 'import textual; print(textual.__version__)'), polkit $(rpm -q --qf '%{VERSION}' polkit)"

echo "### A. pkexec, no terminal, no agent (as user, in a login session)"
runuser -l user -c 'start=$(date +%s.%N); setsid -w pkexec /usr/bin/true </dev/null >/tmp/a.out 2>&1; code=$?;
    end=$(date +%s.%N); echo "  exit $code after $(echo "$end - $start" | bc 2>/dev/null || python3 -c "print(round($end-$start,2))") s"; sed "s/^/  /" /tmp/a.out'

echo "### B. the whole path in a terminal"
python3 /src/scripts/spikes/t3_pty.py

echo "### C. sudo and the user's environment"
runuser -l user -c 'echo secret | sudo -S -p "" env' | grep -E '^(HOME|USER|SUDO_USER|XDG_CONFIG_HOME)=' | sed 's/^/  sudo:    /'
runuser -l user -c 'echo secret | sudo -S -p "" -i env' | grep -E '^(HOME|USER|SUDO_USER|XDG_CONFIG_HOME)=' | sed 's/^/  sudo -i: /'
TEST
